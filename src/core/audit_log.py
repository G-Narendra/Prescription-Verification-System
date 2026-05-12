"""
Audit Log — SQLite-backed HIPAA-ready decision trail.
Every prescription decision (approve/reject/escalate) is logged with pharmacist ID.
"""
import sqlite3
import os
from datetime import datetime
from typing import Optional
from dotenv import load_dotenv

load_dotenv()
AUDIT_DB = os.getenv("AUDIT_DB_PATH", "./data/audit.db")


def _conn():
    os.makedirs(os.path.dirname(AUDIT_DB) if os.path.dirname(AUDIT_DB) else ".", exist_ok=True)
    return sqlite3.connect(AUDIT_DB)


def init_db():
    with _conn() as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                prescription_id TEXT NOT NULL,
                patient_name TEXT,
                drugs TEXT NOT NULL,
                ai_risk_level TEXT NOT NULL,
                ai_flags TEXT,
                pharmacist_id TEXT NOT NULL,
                pharmacist_decision TEXT NOT NULL,
                pharmacist_notes TEXT,
                auto_approved INTEGER DEFAULT 0
            )
        """)
        con.commit()


def log_decision(
    prescription_id: str,
    patient_name: str,
    drugs: str,
    ai_risk_level: str,
    ai_flags: str,
    pharmacist_id: str,
    pharmacist_decision: str,
    pharmacist_notes: str = "",
    auto_approved: bool = False,
):
    init_db()
    with _conn() as con:
        con.execute("""
            INSERT INTO audit_log
            (timestamp, prescription_id, patient_name, drugs, ai_risk_level,
             ai_flags, pharmacist_id, pharmacist_decision, pharmacist_notes, auto_approved)
            VALUES (?,?,?,?,?,?,?,?,?,?)
        """, (
            datetime.now().isoformat(),
            prescription_id,
            patient_name,
            drugs,
            ai_risk_level,
            ai_flags,
            pharmacist_id,
            pharmacist_decision,
            pharmacist_notes,
            int(auto_approved),
        ))
        con.commit()


def get_recent_logs(limit: int = 20):
    init_db()
    with _conn() as con:
        rows = con.execute(
            "SELECT * FROM audit_log ORDER BY timestamp DESC LIMIT ?", (limit,)
        ).fetchall()
    cols = ["id", "timestamp", "prescription_id", "patient_name", "drugs",
            "ai_risk_level", "ai_flags", "pharmacist_id", "pharmacist_decision",
            "pharmacist_notes", "auto_approved"]
    return [dict(zip(cols, r)) for r in rows]
