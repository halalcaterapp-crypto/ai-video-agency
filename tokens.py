"""
tokens.py — Single-use access token management using SQLite.

Each token is a unique URL-safe string tied to one free video submission.
Once consumed, the token is marked 'used' and cannot be reused.
"""

import os
import secrets
import sqlite3
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "tokens.db")


def _conn():
    return sqlite3.connect(DB_PATH)


def init_db():
    """Create the tokens table if it doesn't exist."""
    with _conn() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS tokens (
                token        TEXT PRIMARY KEY,
                created_at   TEXT NOT NULL,
                used_at      TEXT,
                used_by_email TEXT,
                status       TEXT NOT NULL DEFAULT 'unused'
            )
        """)
        db.commit()


def generate_tokens(count: int = 10) -> list:
    """Generate `count` new single-use tokens. Returns list of token strings."""
    init_db()
    new_tokens = []
    with _conn() as db:
        for _ in range(count):
            while True:
                token = secrets.token_urlsafe(10)
                exists = db.execute(
                    "SELECT 1 FROM tokens WHERE token=?", (token,)
                ).fetchone()
                if not exists:
                    break
            db.execute(
                "INSERT INTO tokens (token, created_at, status) VALUES (?, ?, 'unused')",
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
        row = db.execute(
            "SELECT status FROM tokens WHERE token=?", (token,)
        ).fetchone()
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
        cur = db.execute(
            """UPDATE tokens
               SET status='used', used_at=?, used_by_email=?
               WHERE token=? AND status='unused'""",
            (datetime.utcnow().isoformat(), email, token),
        )
        db.commit()
        return cur.rowcount == 1


def list_tokens() -> list:
    """Return all tokens for the admin view."""
    init_db()
    with _conn() as db:
        return db.execute(
            "SELECT token, status, used_by_email, used_at, created_at "
            "FROM tokens ORDER BY created_at DESC"
        ).fetchall()
