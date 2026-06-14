from flask import Flask, request, jsonify
from flask_cors import CORS
import sqlite3
import os
from datetime import datetime
from functools import wraps
import threading
import time
import urllib.request
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import json

app = Flask(__name__)
CORS(app)

ONLINE_USERS = {}
ONLINE_TIMEOUT = 60

API_KEY = "bels-magic-hands-2026"

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
    print("Database initialized.")


def require_api_key(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if request.headers.get("X-API-Key") != API_KEY:
            return jsonify({"error": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated


def send_confirmation_email(data):
    if not data.get("email"):
        print("Email skipped: no customer email provided")
        return False
    if not SMTP_PASS:
        print("Email skipped: SMTP_PASS env var not set in Render")
        return False
    try:
        svc = SERVICES.get(data.get("message_type", ""), {})
        price = svc.get("price", 0)
        duration = svc.get("duration", "")

        html = f"""
        <div style="font-family:Segoe UI,Arial,sans-serif;max-width:500px;margin:0 auto;background:#faf6f4;padding:32px;border-radius:12px;">
            <div style="text-align:center;margin-bottom:24px;">
                <h1 style="color:#d4838f;margin:0;font-size:22px;">Bel's Magic Hands Massage</h1>
                <p style="color:#888;margin:4px 0 0;font-size:12px;">Appointment Confirmation</p>
            </div>
            <p style="color:#322834;font-size:14px;">Hi <strong>{data['name']}</strong>,</p>
            <p style="color:#555;font-size:13px;">Your appointment has been booked. Here are the details:</p>
            <div style="background:white;border-radius:8px;padding:16px;margin:16px 0;border:1px solid #eee;">
                <table style="width:100%;font-size:13px;color:#322834;">
                    <tr><td style="padding:6px 0;color:#888;">Service</td><td style="padding:6px 0;text-align:right;"><strong>{data.get('message_type','')}</strong></td></tr>
                    <tr><td style="padding:6px 0;color:#888;">Duration</td><td style="padding:6px 0;text-align:right;">{duration}</td></tr>
                    <tr><td style="padding:6px 0;color:#888;">Date</td><td style="padding:6px 0;text-align:right;">{data.get('date','')}</td></tr>
                    <tr><td style="padding:6px 0;color:#888;">Time</td><td style="padding:6px 0;text-align:right;">{data.get('time','')}</td></tr>
                    <tr><td style="padding:6px 0;color:#888;border-top:1px solid #eee;">Price</td><td style="padding:6px 0;text-align:right;border-top:1px solid #eee;"><strong style="color:#d4838f;">${price:.0f}</strong></td></tr>
                </table>
            </div>
            <p style="color:#888;font-size:11px;text-align:center;margin-top:24px;">Thank you for choosing Bel's Magic Hands!</p>
        </div>
        """

        msg = MIMEMultipart("alternative")
        msg["Subject"] = "Appointment Confirmed \u2014 Bel's Magic Hands"
        msg["From"] = f"Bel's Magic Hands <{SMTP_USER}>"
        msg["To"] = data["email"]
        msg.attach(MIMEText(html, "html"))

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(SMTP_USER, data["email"], msg.as_string())
        print(f"Confirmation email sent to {data['email']}")
        return True
    except Exception as e:
        print(f"Email send failed: {e}")
        return False


# ---- HOME ----

@app.route("/")
def home():
    return jsonify({
        "api": "Bel's Magic Hands Therapy",
        "services": SERVICES,
        "message": "Use /api/appointments to book",
        "endpoints": {
            "POST /api/appointments": "Book an appointment",
            "GET /api/appointments": "List appointments",
            "PATCH /api/appointments/<id>": "Update status",
            "GET /api/services": "List services with prices",
            "GET /api/health": "Health check"
        }
    })

# --  TOS Version -- 
@app.route("/api/tos", methods=["GET"])
def get_tos():
    return jsonify({
        "version": "2.0",
        "title": "Terms of Service",
        "effectiveDate": "2026-06-15",
        "updated": True
    })

# ---- SERVICES ----

@app.route("/api/services", methods=["GET"])
def get_services():
    return jsonify(SERVICES)


# ---- PEOPLE ENDPOINTS ----

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


# ---- GAME ENDPOINTS ----

@app.route("/api/game-scores", methods=["GET"])
def get_scores():
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM game_scores ORDER BY played_at DESC"
        ).fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/api/game-scores/<int:score_id>", methods=["GET"])
def get_score(score_id):
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM game_scores WHERE id = ?", (score_id,)
        ).fetchone()
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
        rows = conn.execute(
            "SELECT * FROM game_scores ORDER BY score DESC LIMIT ?", (limit,)
        ).fetchall()
    return jsonify([dict(r) for r in rows])


# ---- APPOINTMENT ENDPOINTS ----

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
            rows = conn.execute(
                "SELECT * FROM appointments ORDER BY date, time"
            ).fetchall()
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

# -- Online People counter -- #
@app.route("/api/online", methods=["POST"])
def heartbeat():
    visitor_id = request.json.get("visitor_id")

    if not visitor_id:
        return jsonify({"error": "visitor_id required"}), 400

    ONLINE_USERS[visitor_id] = time.time()

    now = time.time()

    expired = [
        uid for uid, last_seen in ONLINE_USERS.items()
        if now - last_seen > ONLINE_TIMEOUT
    ]

    for uid in expired:
        del ONLINE_USERS[uid]

    return jsonify({
        "online": len(ONLINE_USERS)
    })


@app.route("/api/online", methods=["GET"])
def get_online():
    now = time.time()

    expired = [
        uid for uid, last_seen in ONLINE_USERS.items()
        if now - last_seen > ONLINE_TIMEOUT
    ]

    for uid in expired:
        del ONLINE_USERS[uid]

    return jsonify({
        "online": len(ONLINE_USERS)
    })

 # --- Change here --- #
def format_uptime(seconds):
    days = seconds // 86400
    hours = (seconds % 86400) // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60

    parts = []

    if days:
        parts.append(f"{days}d")

    if hours:
        parts.append(f"{hours}h")

    if minutes:
        parts.append(f"{minutes}m")

    if secs or not parts:
        parts.append(f"{secs}s")

    return " ".join(parts)


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

# -- Old helth check -- #
# @app.route("/api/health", methods=["GET"])
# def health():
    # return jsonify({"status": "ok"})

# --  New Health Check -- #
@app.route("/api/health", methods=["GET"])
def health():

    global LAST_INCIDENT

    start = time.perf_counter()

    uptime_seconds = int(time.time() - APP_START_TIME)

    status = "online"

    latency = round(
        (time.perf_counter() - start) * 1000,
        2
    )

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

    online_count = sum(
        1 for h in STATUS_HISTORY
        if h["status"] == "online"
    )

    availability = round(
        (online_count / len(STATUS_HISTORY)) * 100,
        2
    ) if STATUS_HISTORY else 100

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
        return jsonify({"error": "SMTP_PASS env var is not set in Render. Go to Environment tab and add it."}), 500
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
            return jsonify({"error": "Email failed. Check Render logs for details. Make sure SMTP_USER and SMTP_PASS are set in Environment tab."}), 500
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
