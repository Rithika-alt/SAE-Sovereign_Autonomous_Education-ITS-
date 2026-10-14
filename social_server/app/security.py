"""Password hashing and session-token helpers for the social server.

Same pbkdf2_hmac scheme as sae_system/auth/auth.py, reimplemented here
since this is a separately deployed service — not a shared import.
"""

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from app.db import get_connection

_SESSION_TTL = timedelta(days=30)


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), iterations=260_000
    ).hex()
    return f"{h}:{salt}"


def verify_password(password: str, stored: str) -> bool:
    try:
        stored_hash, salt = stored.split(":", 1)
        h = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt.encode("utf-8"), iterations=260_000
        ).hex()
        return secrets.compare_digest(h, stored_hash)
    except Exception:
        return False


def create_session(social_id: str) -> str:
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + _SESSION_TTL
    conn = get_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO sessions (token, social_id, expires_at) VALUES (%s, %s, %s)",
                    (token, social_id, expires_at),
                )
    finally:
        conn.close()
    return token


def resolve_session(token: str) -> Optional[str]:
    """Return the social_id for a live session token, or None if invalid/expired."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT social_id FROM sessions WHERE token = %s AND expires_at > now()",
                (token,),
            )
            row = cur.fetchone()
            return row["social_id"] if row else None
    finally:
        conn.close()


def delete_session(token: str) -> None:
    conn = get_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM sessions WHERE token = %s", (token,))
    finally:
        conn.close()
