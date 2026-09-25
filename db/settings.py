"""
db/settings.py — Application settings (key/value store).
"""
from __future__ import annotations

from db.connection import get_conn


def get_setting(key: str, default: str | None = None) -> str | None:
    with get_conn() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(key: str, value: str) -> None:
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO settings (key, value) VALUES (?,?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value
        """, (key, value))
