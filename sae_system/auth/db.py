"""PostgreSQL helpers for SAE auth.

Falls back to a local JSON file store (auth/local_db.py) when PostgreSQL is
not configured or unreachable — so the app runs without Docker.
"""

import logging
import os
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------

def _connect():
    """Return a new psycopg2 connection or raise if not configured/reachable."""
    url = os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL not set.")
    import psycopg2
    from psycopg2.extras import RealDictCursor
    return psycopg2.connect(url, cursor_factory=RealDictCursor)


def _pg_unavailable(exc: Exception) -> bool:
    """True when the exception means PostgreSQL is not reachable (not a logic error)."""
    t = type(exc).__name__
    return isinstance(exc, RuntimeError) or t in ("OperationalError", "InterfaceError")


# ---------------------------------------------------------------------------
# Student CRUD  (each function tries PostgreSQL, falls back to local JSON store)
# ---------------------------------------------------------------------------

def create_student(
    student_id: str,
    name: str,
    username: str,
    email: str,
    password_hash: str,
) -> None:
    """Insert a new student. Falls back to local JSON store if PostgreSQL is down."""
    sql = """
        INSERT INTO students (student_id, name, username, email, password_hash)
        VALUES (%s, %s, %s, %s, %s)
    """
    try:
        conn = _connect()
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute(sql, (student_id, name, username, email, password_hash))
            logger.info("PG: student created — %s (%s)", username, email)
        finally:
            conn.close()
    except Exception as exc:
        if _pg_unavailable(exc):
            logger.info("PG unavailable — writing to local_db (%s)", exc)
            from auth import local_db
            local_db.create_student(student_id, name, username, email, password_hash)
        else:
            raise


def get_student_by_email(email: str) -> Optional[Dict]:
    """Return student row as dict, or None. Falls back to local JSON store."""
    try:
        conn = _connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM students WHERE email = %s", (email.lower().strip(),)
                )
                row = cur.fetchone()
                return dict(row) if row else None
        finally:
            conn.close()
    except Exception as exc:
        if _pg_unavailable(exc):
            from auth import local_db
            return local_db.get_student_by_email(email)
        raise


def email_exists(email: str) -> bool:
    try:
        conn = _connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM students WHERE email = %s", (email.lower().strip(),)
                )
                return cur.fetchone() is not None
        finally:
            conn.close()
    except Exception as exc:
        if _pg_unavailable(exc):
            from auth import local_db
            return local_db.email_exists(email)
        raise


def username_exists(username: str) -> bool:
    try:
        conn = _connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM students WHERE username = %s", (username.strip(),)
                )
                return cur.fetchone() is not None
        finally:
            conn.close()
    except Exception as exc:
        if _pg_unavailable(exc):
            from auth import local_db
            return local_db.username_exists(username)
        raise


def update_student_domain(student_id: str, domain: str) -> None:
    try:
        conn = _connect()
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE students SET domain = %s WHERE student_id = %s",
                        (domain, student_id),
                    )
        finally:
            conn.close()
    except Exception as exc:
        if _pg_unavailable(exc):
            from auth import local_db
            local_db.update_student_domain(student_id, domain)
        else:
            raise
