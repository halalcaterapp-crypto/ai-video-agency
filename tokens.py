"""
tokens.py — Single-use access token management.

Uses PostgreSQL when DATABASE_URL is set (Railway production).
Falls back to SQLite for local development.
"""

import os
import secrets
from datetime import datetime

DATABASE_URL = os.environ.get("DATABASE_URL", "")

# ── Backend detection ──────────────────────────────────────────────────────────
if DATABASE_URL:
    import psycopg2
    import psycopg2.extras
    PH = "%s"          # PostgreSQL placeholder

    def _conn():
        return psycopg2.connect(DATABASE_URL)

else:
    import sqlite3
    PH = "?"           # SQLite placeholder
    DB_PATH = os.path.join(os.path.dirname(__file__), "tokens.db")

    def _conn():
        return sqlite3.connect(DB_PATH)


# ── Schema ─────────────────────────────────────────────────────────────────────
def init_db():
    """Create the tokens table if it doesn't exist."""
    with _conn() as db:
        cur = db.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS tokens (
                token         TEXT PRIMARY KEY,
                created_at    TEXT NOT NULL,
                used_at       TEXT,
                used_by_email TEXT,
                status        TEXT NOT NULL DEFAULT 'unused'
            )
        """)
        db.commit()


# ── Public API ─────────────────────────────────────────────────────────────────
def generate_tokens(count: int = 10) -> list:
    """Generate `count` new single-use tokens. Returns list of token strings."""
    init_db()
    new_tokens = []
    with _conn() as db:
        cur = db.cursor()
        for _ in range(count):
            while True:
                token = secrets.token_urlsafe(10)
                cur.execute(f"SELECT 1 FROM tokens WHERE token={PH}", (token,))
                if not cur.fetchone():
                    break
            cur.execute(
                f"INSERT INTO tokens (token, created_at, status) VALUES ({PH}, {PH}, 'unused')",
                (token, datetime.utcnow().isoformat()),
            )
            new_tokens.append(token)
        db.commit()
    return new_tokens


def validate_token(token: str) -> str:
    """Returns 'valid', 'used', or 'invalid'."""
    if not token:
        return "invalid"
    init_db()
    with _conn() as db:
        cur = db.cursor()
        cur.execute(f"SELECT status FROM tokens WHERE token={PH}", (token,))
        row = cur.fetchone()
    if row is None:
        return "invalid"
    return "valid" if row[0] == "unused" else "used"


def consume_token(token: str, email: str) -> bool:
    """
    Atomically mark token as used. Returns True if successful.
    Returns False if token was already used or doesn't exist (race condition safe).
    """
    init_db()
    with _conn() as db:
        cur = db.cursor()
        cur.execute(
            f"""UPDATE tokens
               SET status='used', used_at={PH}, used_by_email={PH}
               WHERE token={PH} AND status='unused'""",
            (datetime.utcnow().isoformat(), email, token),
        )
        db.commit()
        return cur.rowcount == 1


def list_tokens() -> list:
    """Return all tokens for the admin view."""
    init_db()
    with _conn() as db:
        cur = db.cursor()
        cur.execute(
            "SELECT token, status, used_by_email, used_at, created_at "
            "FROM tokens ORDER BY created_at DESC"
        )
        return cur.fetchall()
