from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
import sqlite3
import os
from datetime import datetime

app = Flask(__name__, template_folder="templates", static_folder="static")
CORS(app)

DB_PATH = os.path.join(os.path.dirname(__file__), "database.db")


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
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
    print("Database initialized.")


# ---- WEBSITE ----

@app.route("/")
def home():
    return render_template("index.html")


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
def get_appointment(appt_id):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM appointments WHERE id = ?", (appt_id,)).fetchone()
    if row is None:
        return jsonify({"error": "Appointment not found"}), 404
    return jsonify(dict(row))


@app.route("/api/appointments", methods=["POST"])
def create_appointment():
    data = request.get_json()
    required = ["name", "message_type", "date", "time"]
    missing = [f for f in required if not data or not data.get(f, "").strip()]
    if missing:
        return jsonify({"error": f"Missing: {', '.join(missing)}"}), 400

    with get_db() as conn:
        cur = conn.execute(
            """INSERT INTO appointments (name, email, phone, message_type, date, time, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                data["name"],
                data.get("email"),
                data.get("phone"),
                data["message_type"],
                data["date"],
                data["time"],
                data.get("notes"),
            ),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM appointments WHERE id = ?", (cur.lastrowid,)).fetchone()

    return jsonify(dict(row)), 201


@app.route("/api/appointments/<int:appt_id>", methods=["PATCH"])
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
def delete_appointment(appt_id):
    with get_db() as conn:
        existing = conn.execute("SELECT * FROM appointments WHERE id = ?", (appt_id,)).fetchone()
        if existing is None:
            return jsonify({"error": "Appointment not found"}), 404
        conn.execute("DELETE FROM appointments WHERE id = ?", (appt_id,))
        conn.commit()
    return jsonify({"message": "Appointment deleted"})


@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    init_db()
    app.run(debug=True, host="0.0.0.0", port=5000)
