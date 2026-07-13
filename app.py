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

# Enforced cross-origin script authorization - updated for your live public domains
CORS(app, resources={
    r"/api/*": {
        "origins": [
            "https://www.belsmagichandsmassage.com",
            "https://belsmagichandsmassage.com",
            "https://icosahedron-pug-dad8.squarespace.com"
        ]
    }
})

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
        conn.execute("""
            CREATE TABLE IF NOT EXISTS config_settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        
        # Base setup defaults falling back onto environment specifications
        defaults = [
            ("smtp_host", "smtp.gmail.com"),
            ("smtp_port", "587"),
            ("smtp_user", os.environ.get("SMTP_USER", "bels_massage@belsmagichandsmassage.com")),
            ("smtp_pass", os.environ.get("SMTP_PASS", "")),
            ("maintenance_mode", "false")
        ]
        for key, val in defaults:
            conn.execute("INSERT OR IGNORE INTO config_settings (key, value) VALUES (?, ?)", (key, val))
            
        try:
            conn.execute("ALTER TABLE appointments ADD COLUMN price REAL DEFAULT 0")
        except sqlite3.OperationalError:
            pass
        conn.commit()
    print("Database connection structural mappings validated.")


def get_config_val(key, default=""):
    with get_db() as conn:
        row = conn.execute("SELECT value FROM config_settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default


def get_smtp_config():
    config = {}
    with get_db() as conn:
        rows = conn.execute("SELECT key, value FROM config_settings WHERE key LIKE 'smtp_%'").fetchall()
        for r in rows:
            config[r["key"]] = r["value"]
    return config


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
    cfg = get_smtp_config()
    if not data.get("email") or not cfg.get("smtp_pass"):
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
        msg["From"] = f"Bel's Magic Hands <{cfg['smtp_user']}>"
        msg["To"] = data["email"]
        msg.attach(MIMEText(html, "html"))

        port = int(cfg.get("smtp_port", 587))
        if port == 465:
            with smtplib.SMTP_SSL(cfg["smtp_host"], port, timeout=15) as server:
                server.login(cfg["smtp_user"], cfg["smtp_pass"])
                server.sendmail(cfg["smtp_user"], data["email"], msg.as_string())
        else:
            with smtplib.SMTP(cfg["smtp_host"], port, timeout=15) as server:
                server.starttls()
                server.login(cfg["smtp_user"], cfg["smtp_pass"])
                server.sendmail(cfg["smtp_user"], data["email"], msg.as_string())
        return True
    except Exception as e:
        print(f"SMTP Error: {e}")
        return False


def send_invoice_email_worker(appt):
    cfg = get_smtp_config()
    if not appt.get("email") or not cfg.get("smtp_pass"):
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
        </div>
        """
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"Invoice from Bel's Magic Hands — {appt['name']}"
        msg["From"] = f"Bel's Magic Hands <{cfg['smtp_user']}>"
        msg["To"] = appt["email"]
        msg.attach(MIMEText(html, "html"))

        port = int(cfg.get("smtp_port", 587))
        if port == 465:
            with smtplib.SMTP_SSL(cfg["smtp_host"], port, timeout=15) as server:
                server.login(cfg["smtp_user"], cfg["smtp_pass"])
                server.sendmail(cfg["smtp_user"], appt["email"], msg.as_string())
        else:
            with smtplib.SMTP(cfg["smtp_host"], port, timeout=15) as server:
                server.starttls()
                server.login(cfg["smtp_user"], cfg["smtp_pass"])
                server.sendmail(cfg["smtp_user"], appt["email"], msg.as_string())
        return True
    except Exception as e:
        print(f"SMTP Worker Error: {e}")
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
        .login-card { position: relative; z-index: 2; background: var(--panel); border: 1px solid rgba(255,107,139,0.25); border-radius: 16px; padding: 40px; width: 340px; box-shadow: 0 20px 50px rgba(0,0,0,0.9); backdrop-filter: blur(8px); }
        h2 { text-transform: uppercase; letter-spacing: 2px; color: var(--neon); margin: 0; text-align: center; font-size: 20px; }
        .sub { color: #a39296; text-align: center; font-size: 13px; margin: 5px 0 30px; }
        input { width: 100%; padding: 14px; background: rgba(28, 21, 24, 0.9); border: 1px solid #4a3a3d; border-radius: 8px; color: #fff; box-sizing: border-box; text-align: center; margin-bottom: 20px; outline: none; }
        input:focus { border-color: var(--neon); box-shadow: 0 0 10px rgba(255, 107, 139, 0.3); }
        button { width: 100%; padding: 14px; background: var(--neon); color: #fff; border: none; border-radius: 8px; font-weight: 600; cursor: pointer; }
    </style>
</head>
<body>
    <canvas id="emberCanvas"></canvas>
    <div class="login-card">
        <h2>System Access</h2>
        <div class="sub">Provide structural decryption passkey</div>
        {% if error %}<div style="color:#ff4a4a; text-align:center; margin-bottom:15px;">⚠️ {{ error }}</div>{% endif %}
        <form method="POST">
            <input type="password" name="password" placeholder="••••••••••••" required>
            <button type="submit">INITIALIZE CONTROL MATRIX</button>
        </form>
    </div>
    <script>
        const canvas = document.getElementById('emberCanvas'); const ctx = canvas.getContext('2d');
        function resize() { canvas.width = window.innerWidth; canvas.height = window.innerHeight; }
        window.addEventListener('resize', resize); resize();
        const particles = [];
        class Ember {
            constructor() { this.reset(); this.y = Math.random() * canvas.height; }
            reset() { this.x = Math.random() * canvas.width; this.y = canvas.height + 10; this.size = Math.random() * 3 + 1; this.speedY = Math.random() * 1.2 + 0.5; this.speedX = Math.random() * 0.6 - 0.3; this.alpha = Math.random() * 0.5 + 0.4; }
            update() { this.y -= this.speedY; this.x += this.speedX; this.alpha -= 0.003; if (this.y < -10 || this.alpha <= 0) this.reset(); }
            draw() { ctx.beginPath(); ctx.arc(this.x, this.y, this.size, 0, Math.PI * 2); ctx.fillStyle = 'rgba(255,107,139,' + this.alpha + ')'; ctx.fill(); }
        }
        for (let i = 0; i < 50; i++) particles.push(new Ember());
        function animate() { ctx.fillStyle = 'rgba(0, 0, 0, 0.15)'; ctx.fillRect(0, 0, canvas.width, canvas.height); particles.forEach(p => { p.update(); p.draw(); }); requestAnimationFrame(animate); }
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
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Management Command Center</title>
    <style>
        :root { 
            --neon-pink: #ff6b8b; 
            --neon-pink-glow: rgba(255, 107, 139, 0.3);
            --neon-cyan: #00f0ff; 
            --neon-cyan-glow: rgba(0, 240, 255, 0.25);
            --neon-green: #00ffcc;
            --neon-red: #ff4a4a;
            --bg-main: #0a0608; 
            --bg-sidebar: #12090c; 
            --bg-panel: rgba(26, 18, 21, 0.75); 
            --bg-card: #23171b;
            --border-glow: rgba(255, 107, 139, 0.15); 
            --text-primary: #f5eff1;
            --text-secondary: #a69297;
        }

        * { box-sizing: border-box; margin: 0; padding: 0; }
        
        body { 
            background: var(--bg-main); 
            color: var(--text-primary); 
            font-family: 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; 
            display: flex; 
            height: 100vh; 
            overflow: hidden; 
        }

        /* --- Sidebar Navigation --- */
        .sidebar { 
            width: 300px; 
            background: var(--bg-sidebar); 
            border-right: 1px solid var(--border-glow); 
            display: flex; 
            flex-direction: column; 
            justify-content: space-between; 
            padding: 30px 20px; 
            box-shadow: 5px 0 25px rgba(0,0,0,0.5);
            z-index: 10;
        }

        .brand-block { 
            display: flex; 
            align-items: center; 
            gap: 14px; 
            font-weight: 800; 
            color: #fff; 
            font-size: 14px; 
            letter-spacing: 2px;
            text-transform: uppercase;
            padding-bottom: 25px;
            border-bottom: 1px solid rgba(255, 255, 255, 0.05);
        }
        
        .radar-dot { 
            width: 12px; 
            height: 12px; 
            border-radius: 50%; 
            position: relative;
        }
        .radar-dot::after {
            content: '';
            position: absolute;
            width: 100%; height: 100%;
            border-radius: 50%;
            animation: pulse 2s infinite;
            opacity: 0.5;
        }
        .radar-dot.online { background: var(--neon-green); box-shadow: 0 0 12px var(--neon-green); }
        .radar-dot.online::after { background: var(--neon-green); }
        .radar-dot.offline { background: var(--neon-red); box-shadow: 0 0 12px var(--neon-red); }
        .radar-dot.offline::after { background: var(--neon-red); }

        @keyframes pulse {
            0% { transform: scale(1); opacity: 0.5; }
            100% { transform: scale(2.5); opacity: 0; }
        }

        .menu-list { 
            display: flex; 
            flex-direction: column; 
            gap: 12px; 
            margin-top: 35px; 
            flex: 1; 
        }
        
        .nav-btn { 
            display: flex; 
            align-items: center; 
            gap: 14px; 
            background: transparent; 
            border: 1px solid transparent; 
            color: var(--text-secondary); 
            width: 100%; 
            padding: 14px 18px; 
            border-radius: 10px; 
            text-align: left; 
            font-size: 14px; 
            font-weight: 600; 
            cursor: pointer; 
            transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1); 
        }
        .nav-btn:hover {
            background: rgba(255, 255, 255, 0.03);
            color: #fff;
        }
        .nav-btn.active { 
            background: rgba(255, 107, 139, 0.08); 
            border: 1px solid rgba(255, 107, 139, 0.25); 
            color: var(--neon-pink); 
            box-shadow: inset 0 0 12px rgba(255, 107, 139, 0.05);
        }

        .logout-btn { 
            border: 1px solid rgba(255, 74, 74, 0.25); 
            color: var(--neon-red); 
            text-decoration: none; 
            text-align: center; 
            padding: 14px; 
            border-radius: 10px; 
            font-size: 13px; 
            font-weight: 700; 
            letter-spacing: 1px;
            transition: all 0.3s;
            background: rgba(255, 74, 74, 0.02);
        }
        .logout-btn:hover {
            background: var(--neon-red);
            color: #fff;
            box-shadow: 0 0 15px rgba(255, 74, 74, 0.4);
        }

        /* --- Main Workframe Engine --- */
        .main-frame { 
            flex: 1; 
            display: flex; 
            flex-direction: column; 
            overflow: hidden; 
        }

        /* Top Status Bar Telemetry */
        .top-stat-bar { 
            background: var(--bg-sidebar); 
            border-bottom: 1px solid var(--border-glow); 
            padding: 20px 40px; 
            display: flex; 
            gap: 50px; 
            align-items: center; 
            box-shadow: 0 4px 20px rgba(0,0,0,0.2);
        }
        
        .mini-metric { 
            font-size: 11px; 
            color: var(--text-secondary); 
            text-transform: uppercase; 
            font-weight: 700; 
            letter-spacing: 1px;
        }
        .mini-metric span { 
            display: block; 
            font-size: 16px; 
            color: #fff; 
            font-weight: 700; 
            margin-top: 4px; 
            font-family: monospace;
        }

        /* Content Container Layout */
        .content-container { 
            flex: 1; 
            padding: 40px; 
            overflow-y: auto; 
            background: linear-gradient(180deg, var(--bg-main) 0%, #050203 100%);
        }
        
        .view-pane { display: none; animation: fadeIn 0.4s ease-out forwards; }
        .view-pane.active { display: block; }

        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(10px); }
            to { opacity: 1; transform: translateY(0); }
        }

        .grid-layout { 
            display: grid; 
            grid-template-columns: 1.6fr 1fr; 
            gap: 35px; 
            align-items: start;
        }

        /* Panel Glassmorphism Aesthetics */
        .panel { 
            background: var(--bg-panel); 
            border: 1px solid var(--border-glow); 
            border-radius: 16px; 
            padding: 30px; 
            box-shadow: 0 10px 40px rgba(0,0,0,0.4); 
            backdrop-filter: blur(12px);
            -webkit-backdrop-filter: blur(12px);
        }
        
        .panel h3 { 
            margin-bottom: 25px; 
            color: var(--text-primary); 
            font-size: 14px; 
            font-weight: 800;
            text-transform: uppercase; 
            letter-spacing: 1.5px; 
            border-bottom: 1px solid rgba(255, 255, 255, 0.05); 
            padding-bottom: 15px; 
            display: flex;
            align-items: center;
            gap: 10px;
        }

        /* --- Dynamic Record Elements & Component Cards --- */
        .record-card { 
            background: var(--bg-card); 
            border-radius: 12px; 
            padding: 20px; 
            margin-bottom: 16px; 
            border-left: 4px solid var(--neon-pink); 
            display: flex; 
            justify-content: space-between; 
            align-items: center; 
            box-shadow: 0 4px 15px rgba(0,0,0,0.15);
            transition: transform 0.2s, border-color 0.2s;
        }
        .record-card:hover {
            transform: translateX(4px);
        }
        .record-card .name { font-weight: 700; color: #fff; font-size: 16px; }
        .record-card .details { font-size: 13px; color: var(--text-secondary); margin-top: 5px; }
        
        .status-pill { 
            background: rgba(255, 107, 139, 0.12); 
            color: var(--neon-pink); 
            padding: 6px 12px; 
            border-radius: 20px; 
            font-size: 11px; 
            font-weight: 800; 
            text-transform: uppercase; 
            letter-spacing: 0.5px;
            display: inline-block;
            border: 1px solid rgba(255, 107, 139, 0.2);
        }
        .status-pill.done { background: rgba(0, 255, 204, 0.1); color: var(--neon-green); border-color: rgba(0, 255, 204, 0.2); }
        .status-pill.cancelled { background: rgba(255, 74, 74, 0.1); color: var(--neon-red); border-color: rgba(255, 74, 74, 0.2); }
        
        /* Interactive Control Actions */
        .btn-action { 
            background: transparent; 
            border: 1px solid var(--neon-pink); 
            color: var(--neon-pink); 
            padding: 14px 20px; 
            border-radius: 10px; 
            font-size: 13px; 
            font-weight: 700; 
            cursor: pointer; 
            transition: all 0.3s; 
            width: 100%; 
            margin-bottom: 12px; 
            text-align: center; 
            display: block; 
            text-decoration: none; 
            box-sizing: border-box; 
            letter-spacing: 0.5px;
            text-transform: uppercase;
        }
        .btn-action:hover { 
            background: var(--neon-pink); 
            color: #000; 
            box-shadow: 0 0 20px var(--neon-pink-glow);
            font-weight: 800;
        }
        
        .btn-invoice { 
            background: rgba(0, 240, 255, 0.05); 
            border: 1px solid var(--neon-cyan); 
            color: var(--neon-cyan); 
            padding: 6px 12px; 
            border-radius: 6px; 
            font-size: 11px; 
            font-weight: 700; 
            cursor: pointer; 
            margin-top: 10px; 
            display: inline-block; 
            transition: all 0.2s;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        .btn-invoice:hover {
            background: var(--neon-cyan);
            color: #000;
            box-shadow: 0 0 12px var(--neon-cyan-glow);
        }
        
        .ctrl-group { display: flex; gap: 6px; margin-top: 12px; }
        .ctrl-btn { 
            padding: 6px 10px; 
            font-size: 11px; 
            font-weight: 700; 
            border: 1px solid rgba(255,255,255,0.1); 
            background: rgba(0,0,0,0.2); 
            color: #ccc; 
            cursor: pointer; 
            border-radius: 6px; 
            transition: all 0.2s;
        }
        .ctrl-btn:hover { background: #fff; color: #000; border-color: #fff; }
        .ctrl-btn.danger:hover { background: var(--neon-red); color: #fff; border-color: var(--neon-red); box-shadow: 0 0 10px rgba(255,74,74,0.3); }

        /* Configuration Toggles */
        .switch-wrap { 
            display: flex; 
            align-items: center; 
            justify-content: space-between; 
            margin-bottom: 25px; 
            background: rgba(0,0,0,0.2); 
            padding: 16px 20px; 
            border-radius: 12px; 
            border: 1px solid rgba(255,255,255,0.05); 
        }
        .switch { position: relative; display: inline-block; width: 48px; height: 26px; }
        .switch input { opacity: 0; width: 0; height: 0; }
        .slider { position: absolute; cursor: pointer; top: 0; left: 0; right: 0; bottom: 0; background-color: #2c1e21; transition: .3s; border-radius: 24px; border: 1px solid rgba(255,255,255,0.05); }
        .slider:before { position: absolute; content: ""; height: 18px; width: 18px; left: 3px; bottom: 3px; background-color: var(--text-secondary); transition: .3s; border-radius: 50%; }
        input:checked + .slider { background-color: rgba(255, 107, 139, 0.2); border-color: var(--neon-pink); }
        input:checked + .slider:before { transform: translateX(22px); background-color: var(--neon-pink); box-shadow: 0 0 8px var(--neon-pink); }

        /* Infrastructure Schemas Terminals */
        .json-output { 
            background: #080406; 
            color: var(--neon-cyan); 
            font-family: 'Courier New', Courier, monospace; 
            padding: 18px; 
            border-radius: 10px; 
            font-size: 12px; 
            overflow-x: auto; 
            max-height: 320px; 
            white-space: pre-wrap; 
            margin-top: 18px; 
            border: 1px solid rgba(0, 240, 255, 0.15); 
            box-shadow: inset 0 0 15px rgba(0,0,0,0.6);
        }
        
        /* Tables Configuration */
        .leaderboard-table { width: 100%; border-collapse: collapse; margin-top: 10px; font-size: 14px; }
        .leaderboard-table th, .leaderboard-table td { text-align: left; padding: 14px 10px; border-bottom: 1px solid rgba(255,255,255,0.04); }
        .leaderboard-table th { color: var(--neon-pink); text-transform: uppercase; font-size: 11px; letter-spacing: 1px; font-weight: 700; }
        .leaderboard-table tbody tr:hover { background: rgba(255,255,255,0.02); }

        /* --- Global Operational Modals --- */
        .modal-bg { 
            position: fixed; top:0; left:0; width:100%; height:100%; 
            background: rgba(5, 2, 3, 0.8); 
            backdrop-filter: blur(8px); 
            -webkit-backdrop-filter: blur(8px);
            display: none; justify-content:center; align-items:center; z-index:10000; 
        }
        .modal-box { 
            background: #181013; 
            border: 1px solid rgba(255, 107, 139, 0.3); 
            padding: 35px; 
            border-radius: 16px; 
            width: 440px; 
            box-shadow: 0 20px 60px rgba(0,0,0,0.7);
            animation: modalScale 0.3s cubic-bezier(0.175, 0.885, 0.32, 1.275) forwards;
        }
        @keyframes modalScale {
            from { transform: scale(0.9); opacity: 0; }
            to { transform: scale(1); opacity: 1; }
        }
        .modal-box label { display:block; font-size:11px; color:var(--text-secondary); margin-bottom:8px; text-transform:uppercase; letter-spacing: 1px; font-weight: 700; }
        .modal-box input, .modal-box textarea { 
            width:100%; padding:12px; 
            background: rgba(0,0,0,0.3); 
            border: 1px solid rgba(255,255,255,0.08); 
            border-radius: 8px; 
            color: #fff; box-sizing:border-box; margin-bottom:20px; outline:none; 
            font-size: 14px;
            transition: border-color 0.2s;
        }
        .modal-box input:focus, .modal-box textarea:focus {
            border-color: var(--neon-pink);
        }
        .modal-flex { display:flex; gap:12px; }
    </style>
</head>
<body>

    <div class="sidebar">
        <div>
            <div class="brand-block">
                <div id="platform-status-dot" class="radar-dot {% if maintenance == 'true' %}offline{% else %}online{% endif %}"></div>
                CORE CONTROL CORE
            </div>
            <div class="menu-list">
                <button class="nav-btn active" onclick="navigatePanel(this, 'appointments')">📋 Appointments Stream</button>
                <button class="nav-btn" onclick="navigatePanel(this, 'diagnostics')">🛰️ Health & Diagnostics</button>
                <button class="nav-btn" onclick="navigatePanel(this, 'records')">🗂️ Secondary Sub-Tables</button>
            </div>
        </div>
        <button class="btn-action" style="border-color:var(--neon-cyan); color:var(--neon-cyan); margin-bottom: 16px;" onclick="openSmtpModal()">⚙️ SMTP RELAY</button>
        <a href="/api/logout" class="logout-btn">TERMINATE ADMIN SESSION</a>
    </div>

    <div class="main-frame">
        <div class="top-stat-bar">
            <div class="mini-metric">Engine Pipeline <span>SQLite3 Core</span></div>
            <div class="mini-metric">Tracked Users Online <span id="nav-online-val">0</span></div>
            <div class="mini-metric">Live Availability <span id="nav-avail-val">100%</span></div>
            <div class="mini-metric">Server Latency <span id="nav-lat-val">0.00ms</span></div>
        </div>

        <div class="content-container">
            <div id="pane-appointments" class="view-pane active">
                <div class="grid-layout">
                    <div class="panel">
                        <h3>Appointments Storage Logs</h3>
                        <div id="appointments-list-target">
                            <p style="color:var(--text-secondary); font-style:italic; font-size:14px;">Connecting to structural logs...</p>
                        </div>
                    </div>
                    <div class="panel">
                        <h3>System Directives</h3>
                        <div class="switch-wrap">
                            <span style="font-size:13px; font-weight:700; color:#fff; letter-spacing:0.5px;">🛠️ MAINTENANCE MODE</span>
                            <label class="switch">
                                <input type="checkbox" id="maintToggle" onchange="toggleMaintenance(this)" {% if maintenance == 'true' %}checked{% endif %}>
                                <span class="slider"></span>
                            </label>
                        </div>

                        <h3>View Application Schemas</h3>
                        <button class="btn-action" onclick="fetchInternalData('/api/internal/appointments', 'appointments-json')">Load Appointments Matrix</button>
                        <button class="btn-action" onclick="fetchInternalData('/api/services', 'appointments-json')">Inspect Active Services</button>
                        <button class="btn-action" onclick="fetchInternalData('/api/tos', 'appointments-json')">View Terms API Node</button>
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
                            <p style="color:var(--text-secondary); font-size:13px; font-style:italic;">Loading Client Profiler stream logs...</p>
                        </div>
                        
                        <br>
                        <h3>Arcade Leaderboard Registers</h3>
                        <div id="arcade-leaderboard-target">
                            <table class="leaderboard-table">
                                <thead>
                                    <tr><th>Player</th><th>Score</th><th>Level</th><th>Game Mode</th></tr>
                                </thead>
                                <tbody id="leaderboard-body-rows">
                                    <tr><td colspan="4" style="color:var(--text-secondary); font-style:italic;">Querying game matrix storage clusters...</td></tr>
                                </tbody>
                            </table>
                        </div>
                    </div>
                    <div class="panel">
                        <h3>Staff Profile Engine</h3>
                        <button class="btn-action" style="background:var(--neon-pink); color:#000; font-weight:800;" onclick="openClientModal()">➕ ADD NEW CLIENT PROFILE</button>
                        <button class="btn-action" onclick="loadClientList()">🔄 Refresh Profile Matrix</button>
                        <button class="btn-action" onclick="loadLeaderboardMatrix()">🔄 Refresh Game Leaderboard</button>
                        <button class="btn-action" onclick="fetchInternalData('/api/game-scores', 'records-json')">Inspect Raw Score Cluster</button>
                        <div id="records-json" class="json-output" style="display:none;"></div>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <div class="modal-bg" id="clientModal">
        <div class="modal-box">
            <h4 style="color:var(--neon-pink); margin:0 0 25px; text-transform:uppercase; letter-spacing:1px; font-weight:800;">Register Client Profile</h4>
            <form id="clientForm" onsubmit="submitClientForm(event)">
                <label>Full Name *</label><input type="text" id="m_name" required>
                <label>Date of Birth</label><input type="text" id="m_dob" placeholder="YYYY-MM-DD">
                <label>Phone Number</label><input type="text" id="m_phone">
                <label>Address</label><input type="text" id="m_address">
                <label>Clinical Massage Notes</label><textarea id="m_notes" rows="3"></textarea>
                <div class="modal-flex">
                    <button type="submit" style="background:var(--neon-pink); color:#000; padding:14px; border:none; border-radius:8px; font-weight:800; cursor:pointer; flex:1; text-transform:uppercase; letter-spacing:0.5px;">SAVE ENTRY</button>
                    <button type="button" onclick="closeClientModal()" style="background:#2c1e21; color:#fff; padding:14px; border:none; border-radius:8px; font-weight:700; cursor:pointer; flex:1; text-transform:uppercase; letter-spacing:0.5px;">CANCEL</button>
                </div>
            </form>
        </div>
    </div>

    <div class="modal-bg" id="smtpModal">
        <div class="modal-box">
            <h4 style="color:var(--neon-cyan); margin:0 0 25px; text-transform:uppercase; letter-spacing:1px; font-weight:800;">SMTP Relaying Configurations</h4>
            <form id="smtpForm" onsubmit="submitSmtpForm(event)">
                <label>SMTP Relay Host</label><input type="text" id="s_host" required>
                <label>Port</label><input type="text" id="s_port" required>
                <label>Sender Email Address</label><input type="email" id="s_user" required>
                <label>Relay Password / App Key</label><input type="password" id="s_pass" placeholder="••••••••••••">
                <div class="modal-flex">
                    <button type="submit" style="background:var(--neon-cyan); color:#000; padding:14px; border:none; border-radius:8px; font-weight:800; cursor:pointer; flex:1; text-transform:uppercase; letter-spacing:0.5px;">UPDATE CONFIGS</button>
                    <button type="button" onclick="closeSmtpModal()" style="background:#2c1e21; color:#fff; padding:14px; border:none; border-radius:8px; font-weight:700; cursor:pointer; flex:1; text-transform:uppercase; letter-spacing:0.5px;">CANCEL</button>
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
            if(paneId === 'records') { loadClientList(); loadLeaderboardMatrix(); }
        }

        async function toggleMaintenance(chk) {
            try {
                await fetch('/api/internal/maintenance', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ maintenance: chk.checked ? 'true' : 'false' })
                });
                const dot = document.getElementById('platform-status-dot');
                if(chk.checked) {
                    dot.className = "radar-dot offline";
                } else {
                    dot.className = "radar-dot online";
                }
            } catch(e) { alert("Failed to switch maintenance mode configurations."); }
        }

        async function modifyStatus(apptId, newStatus) {
            try {
                const r = await fetch(`/api/appointments/${apptId}`, {
                    method: 'PATCH',
                    headers: {'Content-Type': 'application/json', 'X-API-Key': 'bels-magic-hands-2026'},
                    body: JSON.stringify({ status: newStatus })
                });
                if(r.ok) {
                    const pill = document.getElementById(`status-pill-${apptId}`);
                    if(pill) {
                        pill.className = `status-pill ${newStatus}`;
                        pill.innerText = newStatus;
                    }
                } else { alert("Failed to modify state parameters."); }
            } catch(e) { alert("Network interaction fault updating status."); }
        }

        async function deleteAppointment(apptId) {
            if(!confirm("Purge appointment record entirely from system log arrays?")) return;
            try {
                const r = await fetch(`/api/appointments/${apptId}`, {
                    method: 'DELETE',
                    headers: {'X-API-Key': 'bels-magic-hands-2026'}
                });
                if(r.ok) { 
                    const el = document.getElementById(`appt-card-${apptId}`);
                    if(el) el.remove(); 
                }
                else { alert("Authorization or lookup exception removing mapping."); }
            } catch(e) { alert("Execution crash communicating with drop channel."); }
        }

        async function fetchInternalData(endpoint, outputId) {
            const container = document.getElementById(outputId);
            try {
                const r = await fetch(endpoint);
                const data = await r.json();
                container.style.display = "block";
                container.innerText = JSON.stringify(data, null, 2);
            } catch (err) { alert("Data stream mapping extraction breakdown."); }
        }

        async function sendInvoice(apptId) {
            try {
                const r = await fetch(`/api/internal/appointments/${apptId}/invoice`, { method: 'POST' });
                const d = await r.json();
                if(d.status === 'success') { alert("Invoice processing stream targeted successfully."); }
                else { alert("Error: " + d.error); }
            } catch(e) { alert("Exception handling async email transaction routing."); }
        }

        function openClientModal() { document.getElementById('clientModal').style.display = 'flex'; }
        function closeClientModal() { document.getElementById('clientModal').style.display = 'none'; document.getElementById('clientForm').reset(); }

        async function openSmtpModal() {
            try {
                const r = await fetch('/api/internal/smtp');
                const cfg = await r.json();
                document.getElementById('s_host').value = cfg.smtp_host || '';
                document.getElementById('s_port').value = cfg.smtp_port || '';
                document.getElementById('s_user').value = cfg.smtp_user || '';
                document.getElementById('s_pass').value = ''; 
                document.getElementById('smtpModal').style.display = 'flex';
            } catch(e) { alert("Could not fetch remote SMTP matrix elements."); }
        }
        function closeSmtpModal() { document.getElementById('smtpModal').style.display = 'none'; }

        async function submitSmtpForm(e) {
            e.preventDefault();
            const payload = {
                smtp_host: document.getElementById('s_host').value,
                smtp_port: document.getElementById('s_port').value,
                smtp_user: document.getElementById('s_user').value,
                smtp_pass: document.getElementById('s_pass').value
            };
            try {
                const r = await fetch('/api/internal/smtp', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                if(r.ok) { alert("SMTP configurations rewritten persistently."); closeSmtpModal(); }
            } catch(err) { alert("Network mutation rejected."); }
        }

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
            } catch(err) { alert("Error persisting client profile registry array."); }
        }

        async function loadClientList() {
            const container = document.getElementById('client-list-target');
            try {
                const r = await fetch('/api/records');
                const data = await r.json();
                if(data.length === 0) {
                    container.innerHTML = `<p style="color:var(--text-secondary); font-size:13px; font-style:italic;">No client accounts indexed.</p>`;
                    return;
                }
                let html = '';
                data.forEach(c => {
                    html += `<div class="record-card" style="border-left-color:var(--neon-cyan);">
                        <div>
                            <div class="name">${c.name}</div>
                            <div class="details">DOB: ${c.dob || 'None'} | Phone: ${c.phone || 'None'}</div>
                            ${c.notes ? `<div class="details" style="color:var(--neon-pink); font-style:italic;">* ${c.notes}</div>` : ''}
                        </div>
                    </div>`;
                });
                container.innerHTML = html;
            } catch(e) { container.innerHTML = 'Fault matching profiles data feed.'; }
        }

        async function loadLeaderboardMatrix() {
            const target = document.getElementById('leaderboard-body-rows');
            try {
                const r = await fetch('/api/leaderboard?limit=10');
                const data = await r.json();
                if(data.length === 0) {
                    target.innerHTML = `<tr><td colspan="4" style="color:var(--text-secondary); text-align:center;">No high scores mapped yet.</td></tr>`;
                    return;
                }
                let html = '';
                data.forEach(row => {
                    html += `<tr>
                        <td><strong>${row.player_name}</strong></td>
                        <td style="color:var(--neon-green); font-weight:bold;">${row.score}</td>
                        <td>${row.level || 'N/A'}</td>
                        <td><span class="status-pill done" style="font-size:9px;">${row.game_mode || 'Default'}</span></td>
                    </tr>`;
                });
                target.innerHTML = html;
            } catch(e) { target.innerHTML = `<tr><td colspan="4" style="color:var(--neon-red);">Telemetry failure mapping arcade cluster scores.</td></tr>`; }
        }

        async function updateAppointmentsLog() {
            const container = document.getElementById('appointments-list-target');
            if (!container) return;
            try {
                const r = await fetch('/api/internal/appointments');
                const data = await r.json();
                if (data.length === 0) {
                    container.innerHTML = `<p style="color:var(--text-secondary); font-style:italic; font-size:14px;">No active entries mapped to structural logs.</p>`;
                    return;
                }
                let html = '';
                data.forEach(appt => {
                    html += `
                    <div class="record-card" id="appt-card-${appt.id}">
                        <div>
                            <div class="name">${appt.name}</div>
                            <div class="details">Type: ${appt.message_type} | Contact: ${appt.phone || 'None'}</div>
                            ${appt.email ? `<div class="details" style="color:#888;">Email: ${appt.email}</div>` : ''}
                            ${appt.notes ? `<div class="details" style="color:#736467; font-style:italic;">* ${appt.notes}</div>` : ''}
                            
                            <div class="ctrl-group">
                                <button class="ctrl-btn" onclick="modifyStatus('${appt.id}', 'done')">✔ Done</button>
                                <button class="ctrl-btn" onclick="modifyStatus('${appt.id}', 'cancelled')">❌ Cancel</button>
                                <button class="ctrl-btn danger" onclick="deleteAppointment('${appt.id}')">🗑 Delete</button>
                            </div>
                            <button class="btn-invoice" onclick="sendInvoice('${appt.id}')">⚡ DISPATCH EMAIL INVOICE</button>
                        </div>
                        <div style="text-align: right;">
                            <div style="font-weight: 700; font-size:14px; margin-bottom:6px; font-family:monospace;">${appt.date} <span style="color:var(--text-secondary); font-weight:normal;">@</span> ${appt.time}</div>
                            <span class="status-pill ${appt.status}" id="status-pill-${appt.id}">${appt.status}</span>
                        </div>
                    </div>`;
                });
                container.innerHTML = html;
            } catch (err) {
                console.log("Error updating appointments feed:", err);
            }
        }

        async function syncTelemetry() {
            try {
                const response = await fetch('/api/health');
                const metrics = await response.json();
                document.getElementById('nav-avail-val').innerText = metrics.availability + "%";
                document.getElementById('nav-lat-val').innerText = metrics.latency + "ms";
                
                const dot = document.getElementById('platform-status-dot');
                if (metrics.status === 'maintenance') {
                    dot.className = "radar-dot offline";
                } else {
                    dot.className = "radar-dot online";
                }
                
                const userRes = await fetch('/api/online');
                const userData = await userRes.json();
                document.getElementById('nav-online-val').innerText = userData.online;
            } catch (err) {}
        }

        // Run baseline setup routines on initialization
        updateAppointmentsLog();
        syncTelemetry();

        // 2-Second loop execution for automatic updates 
        setInterval(updateAppointmentsLog, 2000);
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
    m_mode = get_config_val("maintenance_mode", "false")
    return render_template_string(DASHBOARD_HTML, maintenance=m_mode)


@app.route("/api/logout")
def admin_logout():
    session.clear()
    return redirect(url_for("admin_login"))


# --- Persistent Configuration Overrides ---
@app.route("/api/internal/smtp", methods=["GET"])
@require_admin_session
def get_smtp_settings():
    return jsonify(get_smtp_config())


@app.route("/api/internal/smtp", methods=["POST"])
@require_admin_session
def save_smtp_settings():
    data = request.get_json() or {}
    with get_db() as conn:
        for key in ["smtp_host", "smtp_port", "smtp_user"]:
            if key in data:
                conn.execute("INSERT OR REPLACE INTO config_settings (key, value) VALUES (?, ?)", (key, str(data[key])))
        if data.get("smtp_pass"):
            conn.execute("INSERT OR REPLACE INTO config_settings (key, value) VALUES (?, ?)", ("smtp_pass", str(data["smtp_pass"])))
        conn.commit()
    return jsonify({"status": "success"})


@app.route("/api/internal/maintenance", methods=["POST"])
@require_admin_session
def save_maintenance_settings():
    data = request.get_json() or {}
    mode = data.get("maintenance", "false")
    with get_db() as conn:
        conn.execute("INSERT OR REPLACE INTO config_settings (key, value) VALUES ('maintenance_mode', ?)", (mode,))
        conn.commit()
    return jsonify({"status": "success"})


# --- Invoice Automation Thread Dispatchers ---
@app.route("/api/internal/appointments/<int:appt_id>/invoice", methods=["POST"])
@require_admin_session
def trigger_appointment_invoice(appt_id):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM appointments WHERE id = ?", (appt_id,)).fetchone()
    if row is None:
        return jsonify({"error": "Appointment unmapped"}), 404
    
    appt_data = dict(row)
    if not appt_data.get("email"):
        return jsonify({"error": "Selected appointment contains no client destination email"}), 400
        
    threading.Thread(target=send_invoice_email_worker, args=(appt_data,), daemon=True).start()
    return jsonify({"status": "success"})


@app.route("/api/internal/appointments", methods=["GET"])
@require_admin_session
def get_internal_appointments():
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM appointments ORDER BY date, time").fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/api/tos", methods=["GET"])
def get_tos():
    return jsonify({"version": "3.0", "title": "Terms of Service", "effectiveDate": "2026-06-22", "updated": True})


@app.route("/api/services", methods=["GET"])
def get_services():
    return jsonify(SERVICES)


# ---- CLIENT RECORDS ENDPOINTS ----
@app.route("/api/records", methods=["GET"])
def get_records():
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM records ORDER BY created_at DESC").fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/api/records/<int:record_id>", methods=["GET"])
def get_record(record_id):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM records WHERE id = ?", (record_id,)).fetchone()
    if row is None: return jsonify({"error": "Record not found"}), 404
    return jsonify(dict(row))


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


@app.route("/api/records/<int:record_id>", methods=["PUT"])
def update_record(record_id):
    data = request.get_json() or {}
    with get_db() as conn:
        existing = conn.execute("SELECT * FROM records WHERE id = ?", (record_id,)).fetchone()
        if existing is None: return jsonify({"error": "Record not found"}), 404
        conn.execute(
            "UPDATE records SET name=?, dob=?, address=?, phone=?, notes=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (data.get("name", existing["name"]), data.get("dob", existing["dob"]), data.get("address", existing["address"]), data.get("phone", existing["phone"]), data.get("notes", existing["notes"]), record_id)
        )
        conn.commit()
        row = conn.execute("SELECT * FROM records WHERE id = ?", (record_id,)).fetchone()
    return jsonify(dict(row))


@app.route("/api/records/<int:record_id>", methods=["DELETE"])
def delete_record(record_id):
    with get_db() as conn:
        existing = conn.execute("SELECT * FROM records WHERE id = ?", (record_id,)).fetchone()
        if existing is None: return jsonify({"error": "Record not found"}), 404
        conn.execute("DELETE FROM records WHERE id = ?", (record_id,))
        conn.commit()
    return jsonify({"message": "Record deleted"})


# ---- MINI GAME SYSTEM ENDPOINTS ----
@app.route("/api/game-scores", methods=["GET"])
def get_scores():
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM game_scores ORDER BY played_at DESC").fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/api/game-scores/<int:score_id>", methods=["GET"])
def get_score(score_id):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM game_scores WHERE id = ?", (score_id,)).fetchone()
    if row is None: return jsonify({"error": "Score not found"}), 404
    return jsonify(dict(row))


@app.route("/api/game-scores", methods=["POST"])
def submit_score():
    data = request.get_json()
    if not data or not data.get("player_name", "").strip() or data.get("score") is None:
        return jsonify({"error": "player_name and score are required"}), 400
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO game_scores (player_name, score, level, game_mode, record_id) VALUES (?, ?, ?, ?, ?)",
            (data["player_name"], data["score"], data.get("level"), data.get("game_mode"), data.get("record_id")),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM game_scores WHERE id = ?", (cur.lastrowid,)).fetchone()
    return jsonify(dict(row)), 201


@app.route("/api/leaderboard", methods=["GET"])
def leaderboard():
    limit = request.args.get("limit", 10, type=int)
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM game_scores ORDER BY score DESC LIMIT ?", (limit,)).fetchall()
    return jsonify([dict(r) for r in rows])


# ---- SECURE INTERNAL PUBLIC SQUARESAPCE ENDPOINTS ----
@app.route("/api/appointments", methods=["GET"])
@require_api_key
def get_appointments():
    status = request.args.get("status")
    with get_db() as conn:
        if status:
            rows = conn.execute("SELECT * FROM appointments WHERE status = ? ORDER BY date, time", (status,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM appointments ORDER BY date, time").fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/api/appointments/<int:appt_id>", methods=["GET"])
@require_api_key
def get_appointment(appt_id):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM appointments WHERE id = ?", (appt_id,)).fetchone()
    if row is None: return jsonify({"error": "Appointment unmapped"}), 404
    return jsonify(dict(row))


@app.route("/api/appointments", methods=["POST"])
@require_api_key
def create_appointment():
    data = request.get_json()
    required = ["name", "message_type", "date", "time"]
    missing = [f for f in required if not data or not data.get(f, "").strip()]
    if missing: return jsonify({"error": f"Missing: {', '.join(missing)}"}), 400

    svc = SERVICES.get(data.get("message_type", ""), {})
    price = svc.get("price", 0)

    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO appointments (name, email, phone, message_type, date, time, notes, price) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (data["name"], data.get("email"), data.get("phone"), data["message_type"], data["date"], data["time"], data.get("notes"), price),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM appointments WHERE id = ?", (cur.lastrowid,)).fetchone()

    data_with_price = dict(row)
    threading.Thread(target=send_confirmation_email, args=(data_with_price,), daemon=True).start()
    return jsonify(data_with_price), 201


@app.route("/api/appointments/<int:appt_id>", methods=["PATCH"])
@require_api_key
def update_appointment(appt_id):
    data = request.get_json() or {}
    with get_db() as conn:
        existing = conn.execute("SELECT * FROM appointments WHERE id = ?", (appt_id,)).fetchone()
        if existing is None: return jsonify({"error": "Appointment unmapped"}), 404

        if "status" in data:
            if data["status"] not in ("pending", "done", "cancelled"):
                return jsonify({"error": "Invalid status parameter value"}), 400
            conn.execute("UPDATE appointments SET status = ? WHERE id = ?", (data["status"], appt_id))
        if "name" in data: conn.execute("UPDATE appointments SET name = ? WHERE id = ?", (data["name"], appt_id))
        if "message_type" in data:
            svc = SERVICES.get(data["message_type"], {})
            conn.execute("UPDATE appointments SET message_type = ?, price = ? WHERE id = ?", (data["message_type"], svc.get("price", 0), appt_id))
        if "date" in data: conn.execute("UPDATE appointments SET date = ? WHERE id = ?", (data["date"], appt_id))
        if "time" in data: conn.execute("UPDATE appointments SET time = ? WHERE id = ?", (data["time"], appt_id))
        if "notes" in data: conn.execute("UPDATE appointments SET notes = ? WHERE id = ?", (data["notes"], appt_id))
        conn.commit()
        row = conn.execute("SELECT * FROM appointments WHERE id = ?", (appt_id,)).fetchone()
    return jsonify(dict(row))


@app.route("/api/appointments/<int:appt_id>", methods=["DELETE"])
@require_api_key
def delete_appointment_endpoint(appt_id):
    with get_db() as conn:
        existing = conn.execute("SELECT * FROM appointments WHERE id = ?", (appt_id,)).fetchone()
        if existing is None: return jsonify({"error": "Appointment unmapped"}), 404
        conn.execute("DELETE FROM appointments WHERE id = ?", (appt_id,))
        conn.commit()
    return jsonify({"message": "Appointment storage mapping dropped."})


# ---- HEARTBEAT TRACKING LOGIC ----
@app.route("/api/online", methods=["GET", "POST"])
def heartbeat():
    if request.method == "POST":
        visitor_id = (request.json or {}).get("visitor_id")
        if visitor_id: ONLINE_USERS[visitor_id] = time.time()
        
    now = time.time()
    expired = [uid for uid, last_seen in ONLINE_USERS.items() if now - last_seen > ONLINE_TIMEOUT]
    for uid in expired: del ONLINE_USERS[uid]
    return jsonify({"online": len(ONLINE_USERS)})


def format_uptime(seconds):
    days = seconds // 86400
    hours = (seconds % 86400) // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    parts = []
    if days: parts.append(f"{days}d")
    if hours: parts.append(f"{hours}h")
    if minutes: parts.append(f"{minutes}m")
    parts.append(f"{secs}s")
    return " ".join(parts)


@app.route("/api/health", methods=["GET"])
def health():
    start = time.perf_counter()
    m_mode = get_config_val("maintenance_mode", "false")
    status_str = "maintenance" if m_mode == "true" else "online"
    avail_val = 0 if m_mode == "true" else 100
    
    uptime_seconds = int(time.time() - APP_START_TIME)
    latency = round((time.perf_counter() - start) * 1000, 2)
    
    entry = {"time": int(time.time()), "status": status_str, "uptime": uptime_seconds, "latency": latency}
    STATUS_HISTORY.append(entry)
    if len(STATUS_HISTORY) > MAX_HISTORY: STATUS_HISTORY.pop(0)

    return jsonify({
        "status": status_str, "uptime": uptime_seconds, "latency": latency, "availability": avail_val, 
        "formattedUptime": format_uptime(uptime_seconds), "history": STATUS_HISTORY
    })


@app.route("/api/test-email", methods=["POST"])
@require_api_key
def test_email():
    data = request.get_json()
    cfg = get_smtp_config()
    if not data or not data.get("email"):
        return jsonify({"error": "Provide an email in the body: {\"email\": \"you@email.com\"}"}), 400
    if not cfg.get("smtp_pass"):
        return jsonify({"error": "SMTP config passkey is not defined in system configurations."}), 500
    try:
        test_data = {
            "email": data["email"],
            "name": data.get("name", "Test User"),
            "message_type": "Swedish Massage",
            "date": "2026-06-15",
            "time": "10:00",
        }
        result = send_confirmation_email(test_data)
        if result:
            return jsonify({"status": "Email sent successfully!", "to": data["email"]})
        else:
            return jsonify({"error": "Email failed. Check logs."}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


init_db()


def _keep_alive():
    url = "https://api-1ilr.onrender.com/api/health"
    while True:
        try: urllib.request.urlopen(url, timeout=15)
        except: pass
        time.sleep(600)


threading.Thread(target=_keep_alive, daemon=True).start()

if __name__ == "__main__":
    port_val = int(os.environ.get("PORT", 5000))
    app.run(debug=True, host="0.0.0.0", port=port_val)
