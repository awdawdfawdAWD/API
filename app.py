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
        svc = SERVICES.get(data.get("message_type", ""), {})
        price = svc.get("price", 0)
        duration = svc.get("duration", "")

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


# --- Premium Business Cyberpunk UI ---
LOGIN_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Core Login Matrix</title>
    <style>
        :root { --neon: #ff6b8b; --dark: #0a0809; --panel: #140f11; }
        body { background: var(--dark); color: #fdfafb; font-family: system-ui, sans-serif; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; }
        .login-card { background: var(--panel); border: 1px solid rgba(255,107,139,0.15); border-radius: 16px; padding: 40px; width: 340px; box-shadow: 0 20px 50px rgba(0,0,0,0.6); opacity: 0; transform: translateY(15px); animation: enter 0.5s ease-out forwards; }
        h2 { text-transform: uppercase; letter-spacing: 2px; color: var(--neon); margin: 0 0 8px; text-align: center; font-size: 20px; }
        .sub { color: #807175; text-align: center; font-size: 13px; margin-bottom: 30px; }
        input { width: 100%; padding: 14px; background: #1c1518; border: 1px solid #362a2d; border-radius: 8px; color: #fff; box-sizing: border-box; text-align: center; outline: none; margin-bottom: 20px; font-size: 14px; transition: border 0.2s; }
        input:focus { border-color: var(--neon); }
        button { width: 100%; padding: 14px; background: var(--neon); color: #fff; border: none; border-radius: 8px; font-weight: 600; cursor: pointer; font-size: 14px; transition: transform 0.1s; }
        button:hover { background: #e05372; }
        button:active { transform: scale(0.99); }
        .err { color: #ff4a4a; text-align: center; font-size: 13px; margin-bottom: 15px; animation: jitter 0.3s ease; }
        @keyframes enter { to { opacity: 1; transform: translateY(0); } }
        @keyframes jitter { 0%, 100% { transform: translateX(0); } 30% { transform: translateX(-4px); } 70% { transform: translateX(4px); } }
    </style>
</head>
<body>
    <div class="login-card">
        <h2>System Access</h2>
        <div class="sub">Provide structural decryption passkey</div>
        {% if error %}<div class="err">⚠️ {{ error }}</div>{% endif %}
        <form method="POST">
            <input type="password" name="password" placeholder="••••••••••••" required>
            <button type="submit">INITIALIZE CONTROL MATRIX</button>
        </form>
    </div>
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
        
        /* Persistent Left Control Column */
        .sidebar { width: 280px; background: var(--sidebar); border-right: 1px solid var(--border); display: flex; flex-direction: column; justify-content: space-between; padding: 25px; box-sizing: border-box; }
        .brand-block { display: flex; align-items: center; gap: 12px; font-weight: 700; letter-spacing: 1px; color: #fff; font-size: 15px; }
        .radar-dot { width: 10px; height: 10px; background: #00ffcc; border-radius: 50%; box-shadow: 0 0 10px #00ffcc; animation: pulse 2s infinite; }
        
        .menu-list { display: flex; flex-direction: column; gap: 8px; margin-top: 40px; flex: 1; }
        .nav-btn { display: flex; align-items: center; gap: 12px; background: transparent; border: 1px solid transparent; color: #9c8b90; width: 100%; padding: 12px 16px; border-radius: 8px; text-align: left; font-size: 14px; font-weight: 600; cursor: pointer; transition: all 0.2s; }
        .nav-btn:hover { color: #fff; background: rgba(255,255,255,0.03); }
        .nav-btn.active { background: rgba(255, 107, 139, 0.08); border-color: rgba(255, 107, 139, 0.2); color: var(--neon); }
        .logout-btn { border: 1px solid rgba(255,74,74,0.3); color: #ff4a4a; text-decoration: none; text-align: center; padding: 12px; border-radius: 8px; font-size: 13px; font-weight: 600; transition: background 0.2s; }
        .logout-btn:hover { background: #ff4a4a; color: #fff; }

        /* Main Workspace Frame */
        .main-frame { flex: 1; display: flex; flex-direction: column; overflow: hidden; }
        .top-stat-bar { background: var(--sidebar); border-bottom: 1px solid var(--border); padding: 15px 35px; display: flex; gap: 40px; align-items: center; }
        .mini-metric { font-size: 12px; color: #8f8084; text-transform: uppercase; font-weight: 600; }
        .mini-metric span { display: block; font-size: 15px; color: #fff; font-weight: 700; margin-top: 2px; }

        .content-container { flex: 1; padding: 35px; overflow-y: auto; box-sizing: border-box; }
        .view-pane { display: none; animation: slideUp 0.35s cubic-bezier(0.1, 1, 0.1, 1) forwards; }
        .view-pane.active { display: block; }
        
        .grid-layout { display: grid; grid-template-columns: 2fr 1fr; gap: 30px; }
        .panel { background: var(--panel); border: 1px solid var(--border); border-radius: 12px; padding: 25px; box-shadow: 0 4px 25px rgba(0,0,0,0.3); }
        .panel h3 { margin: 0 0 20px; color: var(--neon); font-size: 15px; text-transform: uppercase; letter-spacing: 0.5px; border-bottom: 1px solid var(--border); padding-bottom: 12px; }
        
        /* Queue Data Cards */
        .record-card { background: #1d1618; border-radius: 8px; padding: 16px; margin-bottom: 12px; border-left: 4px solid var(--neon); display: flex; justify-content: space-between; align-items: center; }
        .record-card .name { font-weight: 600; color: #fff; font-size: 15px; }
        .record-card .details { font-size: 13px; color: #9c8b90; margin-top: 3px; }
        .status-pill { background: rgba(255, 107, 139, 0.1); color: var(--neon); padding: 4px 10px; border-radius: 6px; font-size: 11px; font-weight: 700; text-transform: uppercase; }

        /* Tech Diagnostic Rows */
        .info-row { display: flex; justify-content: space-between; padding: 14px 0; border-bottom: 1px dashed rgba(255,255,255,0.05); font-size: 14px; }
        .info-row:last-child { border: none; }
        .info-row label { color: #8f8084; }
        .info-row value { font-weight: 600; color: #fff; }

        /* Quick-Action Controls */
        .btn-action { background: transparent; border: 1px solid var(--neon); color: var(--neon); padding: 10px 16px; border-radius: 6px; font-size: 13px; font-weight: 600; cursor: pointer; transition: all 0.2s; width: 100%; margin-bottom: 10px; text-align: center; display: block; text-decoration: none; }
        .btn-action:hover { background: var(--neon); color: #fff; }
        
        .json-output { background: #0d090a; color: #00ffcc; font-family: monospace; padding: 15px; border-radius: 6px; font-size: 12px; overflow-x: auto; max-height: 300px; white-space: pre-wrap; margin-top: 15px; border: 1px solid rgba(0,255,204,0.1); }

        @keyframes pulse { 0%, 100% { opacity: 0.5; } 50% { opacity: 1; box-shadow: 0 0 12px #00ffcc; } }
        @keyframes slideUp { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: translateY(0); } }
    </style>
</head>
<body>

    <div class="sidebar">
        <div>
            <div class="brand-block">
                <div class="radar-dot"></div>
                MANAGEMENT PLATFORM
            </div>
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
                                    {% if appt.notes %}<div class="details" style="color:#736467; font-style:italic;">* {{ appt.notes }}</div>{% endif %}
                                </div>
                                <div style="text-align: right;">
                                    <div style="font-weight: 600; font-size:14px; margin-bottom:4px;">{{ appt.date }} @ {{ appt.time }}</div>
                                    <span class="status-pill">{{ appt.status }}</span>
                                </div>
                            </div>
                            {% endfor %}
                        {% else %}
                            <p style="color:#8f8084; font-style:italic; font-size:14px;">No active client entries mapped to structural storage logs.</p>
                        {% endif %}
                    </div>
                    <div class="panel">
                        <h3>View Internal Application Schemas</h3>
                        <button class="btn-action" onclick="fetchInternalData('/api/internal/appointments', 'appointments-json')">Load Appointments Matrix</button>
                        <button class="btn-action" onclick="fetchInternalData('/api/services', 'appointments-json')">Inspect Active Services</button>
                        <button class="btn-action" onclick="fetchInternalData('/api/tos', 'appointments-json')">View Terms API Node</button>
                        <div id="appointments-json" class="json-output" style="display:none;"></div>
                    </div>
                </div>
            </div>

            <div id="pane-diagnostics" class="view-pane">
                <div class="grid-layout">
                    <div class="panel">
                        <h3>Asynchronous Node Telemetry</h3>
                        <div class="info-row"><label>Engine Core Status</label><value style="color:#00ffcc;">ONLINE</value></div>
                        <div class="info-row"><label>Internal Runtime Latency</label><value id="diag-latency">-</value></div>
                        <div class="info-row"><label>Calculated Cluster Uptime</label><value id="diag-uptime">-</value></div>
                        <div class="info-row"><label>Node Security Encryption</label><value>AES-GCM TLSv1.3</value></div>
                    </div>
                    <div class="panel">
                        <h3>System Actions</h3>
                        <button class="btn-action" onclick="fetchInternalData('/api/health', 'health-json')">Fetch Health Matrix</button>
                        <button class="btn-action" onclick="window.location.reload();">🔄 Recalibrate Console</button>
                        <div id="health-json" class="json-output" style="display:none;"></div>
                    </div>
                </div>
            </div>

            <div id="pane-records" class="view-pane">
                <div class="grid-layout">
                    <div class="panel">
                        <h3>Relational Auxiliary Sub-Tables</h3>
                        <div class="info-row"><label>User Client Profiles Table</label><value>Running / Encrypted</value></div>
                        <div class="info-row"><label>Game Session Leaderboard Storage</label><value>Isolated Cluster</value></div>
                        <div class="info-row"><label>Active Tracking Monitors</label><value>Broadcasting</value></div>
                    </div>
                    <div class="panel">
                        <h3>Access Sub-Tables</h3>
                        <button class="btn-action" onclick="fetchInternalData('/api/records', 'records-json')">Load Client Database Records</button>
                        <button class="btn-action" onclick="fetchInternalData('/api/game-scores', 'records-json')">Load Miniature Game Registers</button>
                        <button class="btn-action" onclick="fetchInternalData('/api/leaderboard', 'records-json')">Load High Scores Matrix</button>
                        <div id="records-json" class="json-output" style="display:none;"></div>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <script>
        function navigatePanel(btn, paneId) {
            document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
            document.querySelectorAll('.view-pane').forEach(p => p.classList.remove('active'));
            btn.classList.add('active');
            document.getElementById('pane-' + paneId).classList.add('active');
        }

        async function fetchInternalData(endpoint, outputId) {
            const container = document.getElementById(outputId);
            try {
                const r = await fetch(endpoint);
                const data = await r.json();
                container.style.display = "block";
                container.innerText = JSON.stringify(data, null, 2);
            } catch (err) {
                container.style.display = "block";
                container.innerText = "Error pulling internal data feed.";
            }
        }

        async function syncTelemetry() {
            try {
                const response = await fetch('/api/health');
                const metrics = await response.json();
                
                // Top Global Summary Bar Sync
                document.getElementById('nav-avail-val').innerText = metrics.availability + "%";
                document.getElementById('nav-lat-val').innerText = metrics.latency + "ms";
                
                // Diagnostics Panel Viewports Sync
                document.getElementById('diag-latency').innerText = metrics.latency + " ms";
                document.getElementById('diag-uptime').innerText = metrics.uptime + " seconds";
            } catch (err) {
                console.error("Telemetry pipeline connection failed:", err);
            }
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


# --- Secure Internal Admin Bridge to prevent browser Authorization Errors ---
@app.route("/api/internal/appointments", methods=["GET"])
@require_admin_session
def get_internal_appointments():
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM appointments ORDER BY date, time").fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/api/tos", methods=["GET"])
def get_tos():
    return jsonify({
        "version": "2.0",
        "title": "Terms of Service",
        "effectiveDate": "2026-06-15",
        "updated": True
    })


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
    if row is None:
        return jsonify({"error": "Record not found"}), 404
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
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided"}), 400

    with get_db() as conn:
        existing = conn.execute("SELECT * FROM records WHERE id = ?", (record_id,)).fetchone()
        if existing is None:
            return jsonify({"error": "Record not found"}), 404

        conn.execute(
            """UPDATE records
               SET name = ?, dob = ?, address = ?, phone = ?, notes = ?, updated_at = CURRENT_TIMESTAMP
               WHERE id = ?""",
            (
                data.get("name", existing["name"]),
                data.get("dob", existing["dob"]),
                data.get("address", existing["address"]),
                data.get("phone", existing["phone"]),
                data.get("notes", existing["notes"]),
                record_id,
            ),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM records WHERE id = ?", (record_id,)).fetchone()

    return jsonify(dict(row))


@app.route("/api/records/<int:record_id>", methods=["DELETE"])
def delete_record(record_id):
    with get_db() as conn:
        existing = conn.execute("SELECT * FROM records WHERE id = ?", (record_id,)).fetchone()
        if existing is None:
            return jsonify({"error": "Record not found"}), 404

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
    if row is None:
        return jsonify({"error": "Score not found"}), 404
    return jsonify(dict(row))


@app.route("/api/game-scores", methods=["POST"])
def submit_score():
    data = request.get_json()
    if not data or not data.get("player_name", "").strip() or data.get("score") is None:
        return jsonify({"error": "player_name and score are required"}), 400

    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO game_scores (player_name, score, level, game_mode, record_id) VALUES (?, ?, ?, ?, ?)",
            (
                data["player_name"],
                data["score"],
                data.get("level"),
                data.get("game_mode"),
                data.get("record_id"),
            ),
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
            rows = conn.execute(
                "SELECT * FROM appointments WHERE status = ? ORDER BY date, time", (status,)
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM appointments ORDER BY date, time").fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/api/appointments/<int:appt_id>", methods=["GET"])
@require_api_key
def get_appointment(appt_id):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM appointments WHERE id = ?", (appt_id,)).fetchone()
    if row is None:
        return jsonify({"error": "Appointment not found"}), 404
    return jsonify(dict(row))


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

    return jsonify(dict(row)), 201


@app.route("/api/appointments/<int:appt_id>", methods=["PATCH"])
@require_api_key
def update_appointment(appt_id):
    data = request.get_json()
    with get_db() as conn:
        existing = conn.execute("SELECT * FROM appointments WHERE id = ?", (appt_id,)).fetchone()
        if existing is None:
            return jsonify({"error": "Appointment not found"}), 404

        if "status" in data:
            if data["status"] not in ("pending", "done", "cancelled"):
                return jsonify({"error": "Invalid status"}), 400
            conn.execute("UPDATE appointments SET status = ? WHERE id = ?", (data["status"], appt_id))

        if "name" in data:
            conn.execute("UPDATE appointments SET name = ? WHERE id = ?", (data["name"], appt_id))
        if "message_type" in data:
            conn.execute("UPDATE appointments SET message_type = ? WHERE id = ?", (data["message_type"], appt_id))
        if "date" in data:
            conn.execute("UPDATE appointments SET date = ? WHERE id = ?", (data["date"], appt_id))
        if "time" in data:
            conn.execute("UPDATE appointments SET time = ? WHERE id = ?", (data["time"], appt_id))
        if "notes" in data:
            conn.execute("UPDATE appointments SET notes = ? WHERE id = ?", (data["notes"], appt_id))

        conn.commit()
        row = conn.execute("SELECT * FROM appointments WHERE id = ?", (appt_id,)).fetchone()

    return jsonify(dict(row))


@app.route("/api/appointments/<int:appt_id>", methods=["DELETE"])
@require_api_key
def delete_appointment(appt_id):
    with get_db() as conn:
        existing = conn.execute("SELECT * FROM appointments WHERE id = ?", (appt_id,)).fetchone()
        if existing is None:
            return jsonify({"error": "Appointment not found"}), 404
        conn.execute("DELETE FROM appointments WHERE id = ?", (appt_id,))
        conn.commit()
    return jsonify({"message": "Appointment deleted"})


# ---- HEARTBEAT TRACKING LOGIC ----
@app.route("/api/online", methods=["POST"])
def heartbeat():
    visitor_id = request.json.get("visitor_id")
    if not visitor_id:
        return jsonify({"error": "visitor_id required"}), 400

    ONLINE_USERS[visitor_id] = time.time()
    now = time.time()
    expired = [uid for uid, last_seen in ONLINE_USERS.items() if now - last_seen > ONLINE_TIMEOUT]
    for uid in expired:
        del ONLINE_USERS[uid]

    return jsonify({"online": len(ONLINE_USERS)})


@app.route("/api/online", methods=["GET"])
def get_online():
    now = time.time()
    expired = [uid for uid, last_seen in ONLINE_USERS.items() if now - last_seen > ONLINE_TIMEOUT]
    for uid in expired:
        del ONLINE_USERS[uid]

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
    if secs or not parts: parts.append(f"{secs}s")
    return " ".join(parts)


@app.route("/api/health", methods=["GET"])
def health():
    global LAST_INCIDENT
    start = time.perf_counter()
    uptime_seconds = int(time.time() - APP_START_TIME)
    status = "online"
    latency = round((time.perf_counter() - start) * 1000, 2)

    if status != "online":
        LAST_INCIDENT = int(time.time())

    entry = {
        "time": int(time.time()),
        "status": status,
        "uptime": uptime_seconds,
        "latency": latency
    }
    STATUS_HISTORY.append(entry)

    if len(STATUS_HISTORY) > MAX_HISTORY:
        STATUS_HISTORY.pop(0)

    online_count = sum(1 for h in STATUS_HISTORY if h["status"] == "online")
    availability = round((online_count / len(STATUS_HISTORY)) * 100, 2) if STATUS_HISTORY else 100

    return jsonify({
        "status": status,
        "uptime": uptime_seconds,
        "latency": latency,
        "availability": availability,
        "lastIncident": LAST_INCIDENT,
        "history": STATUS_HISTORY
    })


@app.route("/api/test-email", methods=["POST"])
@require_api_key
def test_email():
    data = request.get_json()
    if not data or not data.get("email"):
        return jsonify({"error": "Provide an email in the body: {\"email\": \"you@email.com\"}"}), 400
    if not SMTP_PASS:
        return jsonify({"error": "SMTP_PASS env var is not set in Render."}), 500
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
        try:
            urllib.request.urlopen(url, timeout=15)
        except:
            pass
        time.sleep(600)


threading.Thread(target=_keep_alive, daemon=True).start()

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
