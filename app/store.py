"""SQLite storage: handover leads and monthly model spend."""
import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS leads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    name TEXT NOT NULL,
    email TEXT NOT NULL,
    question TEXT NOT NULL,
    reason TEXT NOT NULL,
    transcript TEXT NOT NULL,
    notified INTEGER NOT NULL DEFAULT 0,
    notify_error TEXT
);
CREATE TABLE IF NOT EXISTS usage (
    month TEXT PRIMARY KEY,
    requests INTEGER NOT NULL DEFAULT 0,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    cost_usd REAL NOT NULL DEFAULT 0
);
"""


def current_month() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


class Store:
    def __init__(self, path: Path):
        path = Path(path)
        if str(path) != ":memory:":
            path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._conn.executescript(SCHEMA)
            self._conn.commit()

    # ---- leads ----
    def add_lead(self, name: str, email: str, question: str, reason: str, transcript: list) -> int:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO leads (created_at, name, email, question, reason, transcript) VALUES (?,?,?,?,?,?)",
                (datetime.now(timezone.utc).isoformat(timespec="seconds"), name, email, question, reason,
                 json.dumps(transcript)),
            )
            self._conn.commit()
            return cur.lastrowid

    def mark_notified(self, lead_id: int, error: Optional[str] = None) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE leads SET notified = ?, notify_error = ? WHERE id = ?",
                (0 if error else 1, error, lead_id),
            )
            self._conn.commit()

    def get_lead(self, lead_id: int) -> Optional[dict]:
        with self._lock:
            row = self._conn.execute("SELECT * FROM leads WHERE id = ?", (lead_id,)).fetchone()
        if row is None:
            return None
        lead = dict(row)
        lead["transcript"] = json.loads(lead["transcript"])
        return lead

    def count_leads(self) -> int:
        with self._lock:
            return self._conn.execute("SELECT COUNT(*) FROM leads").fetchone()[0]

    # ---- spend ----
    def month_spend(self, month: Optional[str] = None) -> float:
        with self._lock:
            row = self._conn.execute("SELECT cost_usd FROM usage WHERE month = ?", (month or current_month(),)).fetchone()
        return float(row[0]) if row else 0.0

    def record_usage(self, input_tokens: int, output_tokens: int, cost_usd: float, month: Optional[str] = None) -> None:
        with self._lock:
            self._conn.execute(
                """INSERT INTO usage (month, requests, input_tokens, output_tokens, cost_usd) VALUES (?,1,?,?,?)
                   ON CONFLICT(month) DO UPDATE SET requests = requests + 1,
                   input_tokens = input_tokens + excluded.input_tokens,
                   output_tokens = output_tokens + excluded.output_tokens,
                   cost_usd = cost_usd + excluded.cost_usd""",
                (month or current_month(), input_tokens, output_tokens, cost_usd),
            )
            self._conn.commit()
