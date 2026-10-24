import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "sessions.db"


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn
