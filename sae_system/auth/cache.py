"""Redis helpers for SAE session caching.

Gracefully degrades to no-op when REDIS_URL is not set or Redis is unreachable.
The app still works — it just won't have Redis-backed sessions.
"""

import json
import logging
import os
from typing import Dict, Optional

logger = logging.getLogger(__name__)

_SESSION_TTL = 86_400      # 24 hours — session token lifetime
_PROFILE_TTL = 3_600       # 1 hour  — cached student profile

# In-memory fallback stores — used when Redis is not running.
# Survive as long as the Streamlit server process lives.
_mem_sessions: Dict[str, Dict] = {}
_mem_profiles: Dict[str, Dict] = {}


def _get_redis():
    """Return a redis.Redis client or None if not configured / unreachable."""
    url = os.getenv("REDIS_URL")
    if not url:
        return None
    try:
        import redis
        client = redis.Redis.from_url(
            url,
            decode_responses=True,
            socket_timeout=1,
            socket_connect_timeout=1,
        )
        client.ping()
        return client
    except Exception as exc:
        logger.debug("Redis unavailable (%s) — using in-memory fallback.", exc)
        return None


# ---------------------------------------------------------------------------
# Session  (token → student dict)
# ---------------------------------------------------------------------------

def set_session(token: str, student: Dict) -> None:
    """Store session in Redis; fall back to in-memory dict when Redis is down."""
    _mem_sessions[token] = student          # always write memory fallback
    r = _get_redis()
    if r is None:
        return
    try:
        r.setex(f"session:{token}", _SESSION_TTL, json.dumps(student))
        logger.debug("Session set for token=%s student=%s", token[:8], student.get("email"))
    except Exception as exc:
        logger.warning("Redis set_session failed: %s", exc)


def get_session(token: str) -> Optional[Dict]:
    """Return student dict for a live session token, or None."""
    if not token:
        return None
    r = _get_redis()
    if r is not None:
        try:
            raw = r.get(f"session:{token}")
            if raw:
                r.expire(f"session:{token}", _SESSION_TTL)
                return json.loads(raw)
        except Exception as exc:
            logger.warning("Redis get_session failed: %s", exc)
    # Redis unavailable or token not found in Redis — check in-memory store
    return _mem_sessions.get(token)


def delete_session(token: str) -> None:
    """Remove a session (logout)."""
    _mem_sessions.pop(token, None)
    r = _get_redis()
    if r is None:
        return
    try:
        r.delete(f"session:{token}")
    except Exception as exc:
        logger.warning("Redis delete_session failed: %s", exc)


# ---------------------------------------------------------------------------
# Student profile cache  (email → student dict)
# ---------------------------------------------------------------------------

def cache_student_profile(email: str, student: Dict) -> None:
    r = _get_redis()
    if r is None:
        return
    try:
        r.setex(f"student:{email.lower()}", _PROFILE_TTL, json.dumps(student))
    except Exception:
        pass


def get_cached_student_profile(email: str) -> Optional[Dict]:
    r = _get_redis()
    if r is None:
        return None
    try:
        raw = r.get(f"student:{email.lower()}")
        return json.loads(raw) if raw else None
    except Exception:
        return None


def invalidate_student_profile(email: str) -> None:
    r = _get_redis()
    if r is None:
        return
    try:
        r.delete(f"student:{email.lower()}")
    except Exception:
        pass
