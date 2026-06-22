import os
import json
import time
import sqlite3
import smtplib
import threading
import urllib.request
from datetime import datetime
from functools import wraps
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from flask import Flask, request, jsonify, render_template_string, redirect, url_for, session
from flask_cors import CORS

app = Flask(__name__)

# Security layer parameters pulled from Render Environment variables
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "temporary-dev-key-placeholder")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "temporary-password-placeholder")
API_KEY = os.environ.get("X_API_KEY", "bels-magic-hands-2026")

# Enforced cross-origin script authorization 
CORS(app, resources={r"/api/*": {"origins": ["https://icosahedron-pug-dad8.squarespace.com"]}})

ONLINE_USERS = {}
ONLINE_TIMEOUT = 60
APP_START_TIME = time.time()
LAST_INCIDENT = None
STATUS_HISTORY = []
MAX_HISTORY = 60

DB_PATH = os.path.join(os.path.dirname(__file__), "database.db")

SERVICES = {
    "Swedish Massage": {"duration": "60 min", "price": 100},
    "Deep Tissue Restoration": {"duration": "90 min", "price": 140},
    "Sports Recovery Session": {"duration": "75 min", "price": 135},
    "Hot-stone Massage": {"duration": "60 min", "price": 150},
}

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587
SMTP_USER = os.environ.get("SMTP_USER", "bels_massage@belsmagichandsmassage.com")
SMTP_PASS = os.environ.get("SMTP_PASS", "")


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                dob TEXT,
                address TEXT,
                phone TEXT,
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS game_scores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                player_name TEXT NOT NULL,
                score INTEGER NOT NULL,
                level TEXT,
                game_mode TEXT,
                record_id INTEGER,
                played_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (record_id) REFERENCES records(id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS appointments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT,
                phone TEXT,
                message_type TEXT NOT NULL,
                date TEXT NOT NULL,
                time TEXT NOT NULL,
                notes TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                price REAL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        try:
            conn.execute("ALTER TABLE appointments ADD COLUMN price REAL DEFAULT 0")
        except sqlite3.OperationalError:
            pass
    print("Database connection structural mappings validated.")


# --- Session Control Utilities ---
def require_admin_session(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("admin_login"))
        return f(*args, **kwargs)
    return decorated


def require_api_key(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if request.headers.get("X-API-Key") != API_KEY:
            return jsonify({"error": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated


def send_confirmation_email(data):
    if not data.get("email") or not SMTP_PASS:
        return False
    try:
        html = f"""
        <div style="font-family:sans-serif;max-width:500px;margin:0 auto;background:#faf6f4;padding:32px;border-radius:12px;">
            <h2>Appointment Confirmed — Bel's Magic Hands</h2>
            <p>Hi <strong>{data['name']}</strong>, your session registration is complete.</p>
            <p><strong>Service:</strong> {data.get('message_type','')}<br><strong>Time:</strong> {data.get('date','')} @ {data.get('time','')}</p>
        </div>
        """
        msg = MIMEMultipart("alternative")
        msg["Subject"] = "Appointment Confirmed"
        msg["From"] = f"Bel's Magic Hands <{SMTP_USER}>"
        msg["To"] = data["email"]
        msg.attach(MIMEText(html, "html"))

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(SMTP_USER, data["email"], msg.as_string())
        return True
    except:
        return False


def send_invoice_email_worker(appt):
    if not appt.get("email") or not SMTP_PASS:
        return False
    try:
        price = appt.get("price", 0)
        html = f"""
        <div style="font-family:sans-serif;max-width:500px;margin:0 auto;background:#ffffff;padding:40px;border:1px solid #eee;border-radius:12px;color:#333;">
            <div style="text-align:center;margin-bottom:30px;">
                <h2 style="margin:0;color:#ff6b8b;">INVOICE</h2>
                <p style="margin:4px 0 0;font-size:14px;color:#777;">Bel's Magic Hands Massage Therapy</p>
            </div>
            <hr style="border:none;border-top:1px solid #eee;margin:20px 0;">
            <p><strong>Billed To:</strong> {appt['name']}</p>
            <p><strong>Email:</strong> {appt['email']}</p>
            <p><strong>Date of Service:</strong> {appt['date']} @ {appt['time']}</p>
            <hr style="border:none;border-top:1px solid #eee;margin:20px 0;">
            <table style="width:100%;font-size:15px;">
                <tr>
                    <td style="padding:8px 0;font-weight:bold;">{appt['message_type']}</td>
                    <td style="padding:8px 0;text-align:right;">${price:,.2f}</td>
                </tr>
                <tr style="font-size:18px;font-weight:bold;color:#ff6b8b;">
                    <td style="padding:15px 0 0;border-top:2px solid #ff6b8b;">Total Amount Due:</td>
                    <td style="padding:15px 0 0;text-align:right;border-top:2px solid #ff6b8b;">${price:,.2f}</td>
                </tr>
            </table>
            <div style="margin-top:40px;text-align:center;font-size:12px;color:#999;">
                Thank you for your business! Payment is due at completion of your therapy session.
            </div>
        </div>
        """
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"Invoice from Bel's Magic Hands — {appt['name']}"
        msg["From"] = f"Bel's Magic Hands <{SMTP_USER}>"
        msg["To"] = appt["email"]
        msg.attach(MIMEText(html, "html"))

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(SMTP_USER, appt["email"], msg.as_string())
        return True
    except Exception as e:
        print(f"Invoice submission runtime failure: {str(e)}")
        return False


# --- Premium Business Cyberpunk UI with Fire Ember Background Engine ---
LOGIN_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Core Login Matrix</title>
    <style>
        :root { --neon: #ff6b8b; --dark: #000000; --panel: rgba(20, 15, 17, 0.85); }
        body { background: var(--dark); color: #fdfafb; font-family: system-ui, sans-serif; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; overflow: hidden; position: relative; }
        #emberCanvas { position: absolute; top: 0; left: 0; width: 100%; height: 100%; z-index: 1; pointer-events: none; }
        .login-card { position: relative; z-index: 2; background: var(--panel); border: 1px solid rgba(255,107,139,0.25); border-radius: 16px; padding: 40px; width: 340px; box-shadow: 0 20px 50px rgba(0,0,0,0.9), 0 0 30px rgba(255, 107, 139, 0.1); backdrop-filter: blur(8px); opacity: 0; transform: translateY(15px); animation: enter 0.5s ease-out forwards; }
        h2 { text-transform: uppercase; letter-spacing: 2px; color: var(--neon); margin: 0 0 8px; text-align: center; font-size: 20px; text-shadow: 0 0 10px rgba(255, 107, 139, 0.4); }
        .sub { color: #a39296; text-align: center; font-size: 13px; margin-bottom: 30px; }
        input { width: 100%; padding: 14px; background: rgba(28, 21, 24, 0.9); border: 1px solid #4a3a3d; border-radius: 8px; color: #fff; box-sizing: border-box; text-align: center; outline: none; margin-bottom: 20px; font-size: 14px; transition: all 0.2s; }
        input:focus { border-color: var(--neon); box-shadow: 0 0 10px rgba(255, 107, 139, 0.3); }
        button { width: 100%; padding: 14px; background: var(--neon); color: #fff; border: none; border-radius: 8px; font-weight: 600; cursor: pointer; font-size: 14px; transition: transform 0.1s, background-color 0.2s; box-shadow: 0 4px 15px rgba(255, 107, 139, 0.4); }
        button:hover { background: #e05372; }
        @keyframes enter { to { opacity: 1; transform: translateY(0); } }
    </style>
</head>
<body>
    <canvas id="emberCanvas"></canvas>
    <div class="login-card">
        <h2>System Access</h2>
        <div class="sub">Provide structural decryption passkey</div>
        {% if error %}<div class="err">⚠️ {{ error }}</div>{% endif %}
        <form method="POST">
            <input type="password" name="password" placeholder="••••••••••••" required>
            <button type="submit">INITIALIZE CONTROL MATRIX</button>
        </form>
    </div>
    <script>
        const canvas = document.getElementById('emberCanvas');
        const ctx = canvas.getContext('2d');
        function resize() { canvas.width = window.innerWidth; canvas.height = window.innerHeight; }
        window.addEventListener('resize', resize); resize();
        const particles = []; const particleCount = 65;
        class Ember {
            constructor() { this.reset(); this.y = Math.random() * canvas.height; }
            reset() { this.x = Math.random() * canvas.width; this.y = canvas.height + Math.random() * 20; this.size = Math.random() * 3 + 1; this.speedY = Math.random() * 1.2 + 0.5; this.speedX = Math.random() * 0.6 - 0.3; const colors = ['rgba(255, 69, 0, ', 'rgba(255, 140, 0, ', 'rgba(255, 107, 139, ', 'rgba(218, 165, 32, ']; this.colorBase = colors[Math.floor(Math.random() * colors.length)]; this.alpha = Math.random() * 0.5 + 0.4; this.fadeSpeed = Math.random() * 0.005 + 0.002; this.wobble = Math.random() * 2; this.wobbleSpeed = Math.random() * 0.02; }
            update() { this.y -= this.speedY; this.x += this.speedX + Math.sin(this.wobble) * 0.2; this.wobble += this.wobbleSpeed; this.alpha -= this.fadeSpeed; if (this.y < -10 || this.alpha <= 0 || this.x < 0 || this.x > canvas.width) this.reset(); }
            draw() { ctx.beginPath(); ctx.arc(this.x, this.y, this.size, 0, Math.PI * 2); ctx.fillStyle = this.colorBase + this.alpha + ')'; ctx.shadowBlur = this.size * 3; ctx.shadowColor = '#ff4500'; ctx.fill(); }
        }
        for (let i = 0; i < particleCount; i++) particles.push(new Ember());
        function animate() { ctx.shadowBlur = 0; ctx.fillStyle = 'rgba(0, 0, 0, 0.15)'; ctx.fillRect(0, 0, canvas.width, canvas.height); for (let i = 0; i < particles.length; i++) { particles[i].update(); particles[i].draw(); } requestAnimationFrame(animate); }
        animate();
    </script>
</body>
</html>
"""

DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Management Command Center</title>
    <style>
        :root { --neon: #ff6b8b; --neon-cyan: #00f0ff; --bg: #070506; --sidebar: #0f0a0c; --panel: #161012; --border: rgba(255, 107, 139, 0.12); }
        body { background: var(--bg); color: #f5eff1; font-family: system-ui, sans-serif; margin: 0; display: flex; height: 100vh; overflow: hidden; }
        .sidebar { width: 280px; background: var(--sidebar); border-right: 1px solid var(--border); display: flex; flex-direction: column; justify-content: space-between; padding: 25px; box-sizing: border-box; }
        .brand-block { display: flex; align-items: center; gap: 12px; font-weight: 700; letter-spacing: 1px; color: #fff; font-size: 15px; }
        .radar-dot { width: 10px; height: 10px; background: #00ffcc; border-radius: 50%; box-shadow: 0 0 10px #00ffcc; }
        .menu-list { display: flex; flex-direction: column; gap: 8px; margin-top: 40px; flex: 1; }
        .nav-btn { display: flex; align-items: center; gap: 12px; background: transparent; border: 1px solid transparent; color: #9c8b90; width: 100%; padding: 12px 16px; border-radius: 8px; text-align: left; font-size: 14px; font-weight: 600; cursor: pointer; transition: all 0.2s; }
        .nav-btn.active { background: rgba(255, 107, 139, 0.08); border-color: rgba(255, 107, 139, 0.2); color: var(--neon); }
        .logout-btn { border: 1px solid rgba(255,74,74,0.3); color: #ff4a4a; text-decoration: none; text-align: center; padding: 12px; border-radius: 8px; font-size: 13px; font-weight: 600; }
        .main-frame { flex: 1; display: flex; flex-direction: column; overflow: hidden; }
        .top-stat-bar { background: var(--sidebar); border-bottom: 1px solid var(--border); padding: 15px 35px; display: flex; gap: 40px; align-items: center; }
        .mini-metric { font-size: 12px; color: #8f8084; text-transform: uppercase; font-weight: 600; }
        .mini-metric span { display: block; font-size: 15px; color: #fff; font-weight: 700; margin-top: 2px; }
        .content-container { flex: 1; padding: 35px; overflow-y: auto; box-sizing: border-box; }
        .view-pane { display: none; }
        .view-pane.active { display: block; }
        .grid-layout { display: grid; grid-template-columns: 2fr 1fr; gap: 30px; }
        .panel { background: var(--panel); border: 1px solid var(--border); border-radius: 12px; padding: 25px; box-shadow: 0 4px 25px rgba(0,0,0,0.3); }
        .panel h3 { margin: 0 0 20px; color: var(--neon); font-size: 15px; text-transform: uppercase; letter-spacing: 0.5px; border-bottom: 1px solid var(--border); padding-bottom: 12px; }
        .record-card { background: #1d1618; border-radius: 8px; padding: 16px; margin-bottom: 12px; border-left: 4px solid var(--neon); display: flex; justify-content: space-between; align-items: center; }
        .record-card .name { font-weight: 600; color: #fff; font-size: 15px; }
        .record-card .details { font-size: 13px; color: #9c8b90; margin-top: 3px; }
        .status-pill { background: rgba(255, 107, 139, 0.1); color: var(--neon); padding: 4px 10px; border-radius: 6px; font-size: 11px; font-weight: 700; text-transform: uppercase; }
        .btn-action { background: transparent; border: 1px solid var(--neon); color: var(--neon); padding: 10px 16px; border-radius: 6px; font-size: 13px; font-weight: 600; cursor: pointer; transition: all 0.2s; width: 100%; margin-bottom: 10px; text-align: center; display: block; text-decoration: none; box-sizing: border-box; }
        .btn-action:hover { background: var(--neon); color: #fff; }
        .btn-invoice { background: rgba(0, 240, 255, 0.1); border: 1px solid var(--neon-cyan); color: var(--neon-cyan); padding: 5px 10px; border-radius: 6px; font-size: 11px; font-weight: bold; cursor: pointer; transition: all 0.2s; margin-top: 6px; display: inline-block; }
        .btn-invoice:hover { background: var(--neon-cyan); color: #000; }
        .json-output { background: #0d090a; color: #00ffcc; font-family: monospace; padding: 15px; border-radius: 6px; font-size: 12px; overflow-x: auto; max-height: 300px; white-space: pre-wrap; margin-top: 15px; border: 1px solid rgba(0,255,204,0.1); }
        
        /* Modal Layering Layout styling */
        .modal-bg { position: fixed; top:0; left:0; width:100%; height:100%; background:rgba(0,0,0,0.7); backdrop-filter:blur(4px); display:none; justify-content:center; align-items:center; z-index:10000; }
        .modal-box { background:var(--panel); border:1px solid var(--neon); padding:30px; border-radius:12px; width:400px; box-shadow:0 10px 40px rgba(0,0,0,0.8); }
        .modal-box h4 { color:var(--neon); margin:0 0 20px; text-transform:uppercase; font-size:16px; }
        .modal-box label { display:block; font-size:12px; color:#8f8084; margin-bottom:6px; text-transform:uppercase; }
        .modal-box input, .modal-box textarea { width:100%; padding:10px; background:rgba(0,0,0,0.3); border:1px solid var(--border); border-radius:6px; color:#fff; box-sizing:border-box; margin-bottom:15px; outline:none; }
        .modal-box input:focus, .modal-box textarea:focus { border-color:var(--neon); }
        .modal-flex { display:flex; gap:10px; }
    </style>
</head>
<body>

    <div class="sidebar">
        <div>
            <div class="brand-block"><div class="radar-dot"></div>MANAGEMENT PLATFORM</div>
            <div class="menu-list">
                <button class="nav-btn active" onclick="navigatePanel(this, 'appointments')">📋 Appointments Stream</button>
                <button class="nav-btn" onclick="navigatePanel(this, 'diagnostics')">🛰️ Health & Diagnostics</button>
                <button class="nav-btn" onclick="navigatePanel(this, 'records')">🗂️ Secondary Database Records</button>
            </div>
        </div>
        <a href="/api/logout" class="logout-btn">TERMINATE ADMIN SESSION</a>
    </div>

    <div class="main-frame">
        <div class="top-stat-bar">
            <div class="mini-metric">Engine Pipeline <span>SQLite3 Core</span></div>
            <div class="mini-metric">Live Availability <span id="nav-avail-val">100%</span></div>
            <div class="mini-metric">Server Latency <span id="nav-lat-val">0.00ms</span></div>
        </div>

        <div class="content-container">
            <div id="pane-appointments" class="view-pane active">
                <div class="grid-layout">
                    <div class="panel">
                        <h3>Appointments Storage Logs</h3>
                        {% if appointments %}
                            {% for appt in appointments %}
                            <div class="record-card">
                                <div>
                                    <div class="name">{{ appt.name }}</div>
                                    <div class="details">Type: {{ appt.message_type }} | Contact: {{ appt.phone or 'None' }}</div>
                                    {% if appt.email %}<div class="details" style="color:#888;">Email: {{ appt.email }}</div>{% endif %}
                                    <button class="btn-invoice" onclick="sendInvoice('{{ appt.id }}')">⚡ SEND INVOICE TO EMAIL</button>
                                </div>
                                <div style="text-align: right;">
                                    <div style="font-weight: 600; font-size:14px; margin-bottom:4px;">{{ appt.date }} @ {{ appt.time }}</div>
                                    <span class="status-pill">{{ appt.status }}</span>
                                </div>
                            </div>
                            {% endfor %}
                        {% else %}
                            <p style="color:#8f8084; font-style:italic; font-size:14px;">No active entries mapped to structural logs.</p>
                        {% endif %}
                    </div>
                    <div class="panel">
                        <h3>View Internal Application Schemas</h3>
                        <button class="btn-action" onclick="fetchInternalData('/api/internal/appointments', 'appointments-json')">Load Appointments Matrix</button>
                        <button class="btn-action" onclick="fetchInternalData('/api/services', 'appointments-json')">Inspect Active Services</button>
                        <div id="appointments-json" class="json-output" style="display:none;"></div>
                    </div>
                </div>
            </div>

            <div id="pane-diagnostics" class="view-pane">
                <div class="panel">
                    <h3>Asynchronous Node Telemetry</h3>
                    <button class="btn-action" onclick="fetchInternalData('/api/health', 'health-json')">Fetch Health Matrix</button>
                    <div id="health-json" class="json-output" style="display:none;"></div>
                </div>
            </div>

            <div id="pane-records" class="view-pane">
                <div class="grid-layout">
                    <div class="panel">
                        <h3>Client Profile Matrix</h3>
                        <div id="client-list-target">
                            <p style="color:#8f8084; font-size:13px; font-style:italic;">Click "Load Client Database Records" to map the live stream view.</p>
                        </div>
                    </div>
                    <div class="panel">
                        <h3>Staff Client Actions</h3>
                        <button class="btn-action" style="background:var(--neon); color:#000;" onclick="openClientModal()">➕ ADD NEW CLIENT PROFILE</button>
                        <button class="btn-action" onclick="loadClientList()">Load Client Database Records</button>
                        <div id="records-json" class="json-output" style="display:none;"></div>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <div class="modal-bg" id="clientModal">
        <div class="modal-box">
            <h4>Register Client Profile</h4>
            <form id="clientForm" onsubmit="submitClientForm(event)">
                <label>Full Name *</label>
                <input type="text" id="m_name" required>
                
                <label>Date of Birth</label>
                <input type="text" id="m_dob" placeholder="YYYY-MM-DD">
                
                <label>Phone Number</label>
                <input type="text" id="m_phone">
                
                <label>Address</label>
                <input type="text" id="m_address">
                
                <label>Clinical Massage Notes</label>
                <textarea id="m_notes" rows="3" placeholder="Injuries, preferences, pressure adjustments..."></textarea>
                
                <div class="modal-flex">
                    <button type="submit" style="background:var(--neon); color:#fff; border:none; padding:12px; border-radius:6px; font-weight:bold; cursor:pointer; flex:1;">SAVE ENTRY</button>
                    <button type="button" onclick="closeClientModal()" style="background:#4a3a3d; color:#fff; border:none; padding:12px; border-radius:6px; font-weight:bold; cursor:pointer; flex:1;">CANCEL</button>
                </div>
            </form>
        </div>
    </div>

    <script>
        function navigatePanel(btn, paneId) {
            document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
            document.querySelectorAll('.view-pane').forEach(p => p.classList.remove('active'));
            btn.classList.add('active');
            document.getElementById('pane-' + paneId).classList.add('active');
            if(paneId === 'records') { loadClientList(); }
        }

        async function fetchInternalData(endpoint, outputId) {
            const container = document.getElementById(outputId);
            try {
                const r = await fetch(endpoint);
                const data = await r.json();
                container.style.display = "block";
                container.innerText = JSON.stringify(data, null, 2);
            } catch (err) { alert("Data feed load failure."); }
        }

        async function sendInvoice(apptId) {
            if(!confirm("Send transaction invoice to client via secure SMTP relay?")) return;
            try {
                const r = await fetch(`/api/internal/appointments/${apptId}/invoice`, { method: 'POST' });
                const d = await r.json();
                if(d.status === 'success') { alert("Invoice successfully dispatched to backend email worker thread."); }
                else { alert("Error: " + d.error); }
            } catch(e) { alert("Failed to invoke automated invoice dispatch."); }
        }

        function openClientModal() { document.getElementById('clientModal').style.display = 'flex'; }
        function closeClientModal() { document.getElementById('clientModal').style.display = 'none'; document.getElementById('clientForm').reset(); }

        async function submitClientForm(e) {
            e.preventDefault();
            const payload = {
                name: document.getElementById('m_name').value,
                dob: document.getElementById('m_dob').value,
                phone: document.getElementById('m_phone').value,
                address: document.getElementById('m_address').value,
                notes: document.getElementById('m_notes').value
            };
            try {
                const r = await fetch('/api/records', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                if(r.ok) { closeClientModal(); loadClientList(); }
                else { alert("Failed structural payload delivery."); }
            } catch(err) { alert("Database entry injection failure."); }
        }

        async function loadClientList() {
            const container = document.getElementById('client-list-target');
            try {
                const r = await fetch('/api/records');
                const data = await r.json();
                if(data.length === 0) {
                    container.innerHTML = `<p style="color:#8f8084; font-size:13px; font-style:italic;">No client matrix models tracked.</p>`;
                    return;
                }
                let html = '';
                data.forEach(c => {
                    html += `
                    <div class="record-card" style="border-left-color:#00f0ff;">
                        <div>
                            <div class="name">${c.name}</div>
                            <div class="details">DOB: ${c.dob || 'None'} | Phone: ${c.phone || 'None'}</div>
                            ${c.notes ? `<div class="details" style="color:#ff6b8b; font-style:italic;">* ${c.notes}</div>` : ''}
                        </div>
                    </div>`;
                });
                container.innerHTML = html;
            } catch(e) { container.innerHTML = 'Error loading records profile framework.'; }
        }

        async function syncTelemetry() {
            try {
                const response = await fetch('/api/health');
                const metrics = await response.json();
                document.getElementById('nav-avail-val').innerText = metrics.availability + "%";
                document.getElementById('nav-lat-val').innerText = metrics.latency + "ms";
            } catch (err) {}
        }
        syncTelemetry();
        setInterval(syncTelemetry, 4000);
    </script>
</body>
</html>
"""


# --- Core Web Interface Endpoints ---
@app.route("/")
def home_redirect():
    return redirect(url_for("admin_login"))


@app.route("/api/Home", methods=["GET", "POST"])
def admin_login():
    if session.get("logged_in"):
        return redirect(url_for("admin_dashboard"))
    error = None
    if request.method == "POST":
        if request.form.get("password") == ADMIN_PASSWORD:
            session["logged_in"] = True
            return redirect(url_for("admin_dashboard"))
        else:
            error = "Invalid credential configuration."
    return render_template_string(LOGIN_HTML, error=error)


@app.route("/api/dashboard", methods=["GET"])
@require_admin_session
def admin_dashboard():
    with get_db() as conn:
        appointments = conn.execute("SELECT * FROM appointments ORDER BY date, time").fetchall()
    return render_template_string(DASHBOARD_HTML, appointments=[dict(r) for r in appointments])


@app.route("/api/logout")
def admin_logout():
    session.clear()
    return redirect(url_for("admin_login"))


# --- Secure Internal Invoice API Endpoint ---
@app.route("/api/internal/appointments/<int:appt_id>/invoice", methods=["POST"])
@require_admin_session
def trigger_appointment_invoice(appt_id):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM appointments WHERE id = ?", (appt_id,)).fetchone()
    if row is None:
        return jsonify({"error": "Appointment configuration model unmapped"}), 404
    
    appt_data = dict(row)
    if not appt_data.get("email"):
        return jsonify({"error": "Selected system appointment contains no valid client destination email address"}), 400
        
    threading.Thread(target=send_invoice_email_worker, args=(appt_data,), daemon=True).start()
    return jsonify({"status": "success", "msg": "Invoice passed down processing execution stream."})


@app.route("/api/internal/appointments", methods=["GET"])
@require_admin_session
def get_internal_appointments():
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM appointments ORDER BY date, time").fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/api/services", methods=["GET"])
def get_services():
    return jsonify(SERVICES)


# ---- CLIENT RECORDS ENDPOINTS ----
@app.route("/api/records", methods=["GET"])
def get_records():
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM records ORDER BY created_at DESC").fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/api/records", methods=["POST"])
def create_record():
    data = request.get_json()
    if not data or not data.get("name", "").strip():
        return jsonify({"error": "Name is required"}), 400

    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO records (name, dob, address, phone, notes) VALUES (?, ?, ?, ?, ?)",
            (data["name"], data.get("dob"), data.get("address"), data.get("phone"), data.get("notes")),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM records WHERE id = ?", (cur.lastrowid,)).fetchone()

    return jsonify(dict(row)), 201


# ---- SQUARESAPCE INTAKE CHANNELS ----
@app.route("/api/appointments", methods=["POST"])
@require_api_key
def create_appointment():
    data = request.get_json()
    required = ["name", "message_type", "date", "time"]
    missing = [f for f in required if not data or not data.get(f, "").strip()]
    if missing:
        return jsonify({"error": f"Missing: {', '.join(missing)}"}), 400

    svc = SERVICES.get(data.get("message_type", ""), {})
    price = svc.get("price", 0)

    with get_db() as conn:
        cur = conn.execute(
            """INSERT INTO appointments (name, email, phone, message_type, date, time, notes, price)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                data["name"],
                data.get("email"),
                data.get("phone"),
                data["message_type"],
                data["date"],
                data["time"],
                data.get("notes"),
                price,
            ),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM appointments WHERE id = ?", (cur.lastrowid,)).fetchone()

    data_with_price = dict(row)
    threading.Thread(target=send_confirmation_email, args=(data_with_price,), daemon=True).start()
    return jsonify(data_with_price), 201


@app.route("/api/health", methods=["GET"])
def health():
    start = time.perf_counter()
    uptime_seconds = int(time.time() - APP_START_TIME)
    latency = round((time.perf_counter() - start) * 1000, 2)
    entry = {"time": int(time.time()), "status": "online", "uptime": uptime_seconds, "latency": latency}
    STATUS_HISTORY.append(entry)
    if len(STATUS_HISTORY) > MAX_HISTORY:
        STATUS_HISTORY.pop(0)

    return jsonify({"status": "online", "uptime": uptime_seconds, "latency": latency, "availability": 100, "history": STATUS_HISTORY})


init_db()

def _keep_alive():
    url = "https://api-1ilr.onrender.com/api/health"
    while True:
        try: urllib.request.urlopen(url, timeout=15)
        except: pass
        time.sleep(600)

threading.Thread(target=_keep_alive, daemon=True).start()

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
