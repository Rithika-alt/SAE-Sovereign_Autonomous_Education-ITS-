"""Auth logic: register, login, logout, session validation."""

import hashlib
import logging
import os
import secrets
import uuid
from typing import Dict, Optional, Tuple

from auth import cache, db

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Password hashing  (pbkdf2_hmac — stdlib, no extra deps)
# ---------------------------------------------------------------------------

def _hash_password(password: str) -> str:
    """Return 'hash:salt' string suitable for storage."""
    salt = secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        iterations=260_000,
    ).hex()
    return f"{h}:{salt}"


def _verify_password(password: str, stored: str) -> bool:
    """Return True if password matches the stored 'hash:salt' string."""
    try:
        stored_hash, salt = stored.split(":", 1)
        h = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt.encode("utf-8"),
            iterations=260_000,
        ).hex()
        return secrets.compare_digest(h, stored_hash)
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def _validate_registration(
    name: str, username: str, email: str, password: str, confirm: str
) -> Optional[str]:
    """Return an error string or None if valid."""
    if not name.strip():
        return "Full name is required."
    if len(username.strip()) < 3:
        return "Username must be at least 3 characters."
    if not username.replace("_", "").replace("-", "").isalnum():
        return "Username may only contain letters, numbers, _ and -."
    if "@" not in email or "." not in email.split("@")[-1]:
        return "Enter a valid email address."
    if len(password) < 8:
        return "Password must be at least 8 characters."
    if password != confirm:
        return "Passwords do not match."
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def register(
    name: str, username: str, email: str, password: str, confirm: str
) -> Tuple[bool, str]:
    """Register a new student.

    Returns (success, message).
    """
    err = _validate_registration(name, username, email, password, confirm)
    if err:
        return False, err

    email    = email.lower().strip()
    username = username.strip()

    try:
        if db.email_exists(email):
            return False, "An account with that email already exists."
        if db.username_exists(username):
            return False, "That username is already taken."

        student_id    = str(uuid.uuid4())
        password_hash = _hash_password(password)

        db.create_student(student_id, name.strip(), username, email, password_hash)
        logger.info("Registered new student: %s (%s)", username, email)
        return True, "Account created! You can now log in."

    except RuntimeError as exc:
        # DATABASE_URL not set — running without Docker
        logger.warning("DB not available during register: %s", exc)
        return False, (
            "Database is not connected. "
            "Start PostgreSQL via  docker compose up  and retry."
        )
    except Exception as exc:
        logger.error("Registration failed: %s", exc)
        return False, f"Registration failed: {exc}"


def login(email: str, password: str) -> Tuple[bool, str, Optional[Dict]]:
    """Authenticate a student.

    Returns (success, message, student_dict_or_None).
    student_dict keys: student_id, name, username, email, domain
    """
    email = email.lower().strip()

    # 1 — Try Redis profile cache first (fast path — avoids DB on repeat logins)
    cached = cache.get_cached_student_profile(email)
    if cached:
        if _verify_password(password, cached["password_hash"]):
            token  = secrets.token_urlsafe(32)
            public = _public(cached)
            cache.set_session(token, {**public, "token": token})
            logger.info("Login via cache hit: %s", email)
            return True, "Welcome back!", {**public, "token": token}
        return False, "Incorrect password.", None

    # 2 — Fall back to PostgreSQL
    try:
        student = db.get_student_by_email(email)
        if not student:
            return False, "No account found with that email.", None

        if not _verify_password(password, student["password_hash"]):
            return False, "Incorrect password.", None

        # Cache profile in Redis so next login is instant
        cache.cache_student_profile(email, dict(student))

        token  = secrets.token_urlsafe(32)
        public = _public(student)
        cache.set_session(token, {**public, "token": token})
        logger.info("Login via DB: %s", email)
        return True, "Welcome back!", {**public, "token": token}

    except RuntimeError as exc:
        logger.warning("DB not available during login: %s", exc)
        return False, (
            "Database is not connected. "
            "Start PostgreSQL via  docker compose up  and retry."
        ), None
    except Exception as exc:
        logger.error("Login error: %s", exc)
        return False, f"Login error: {exc}", None


def logout(token: str) -> None:
    """Invalidate a session token."""
    cache.delete_session(token)


def get_session(token: str) -> Optional[Dict]:
    """Return the student dict for a live session token, or None."""
    return cache.get_session(token)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _public(student: Dict) -> Dict:
    """Strip password_hash before passing student data to the UI."""
    return {
        "student_id": student["student_id"],
        "name":       student["name"],
        "username":   student["username"],
        "email":      student["email"],
        "domain":     student.get("domain", ""),
    }
