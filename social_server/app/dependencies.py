"""Shared FastAPI dependencies — auth extraction + presence tracking."""

from fastapi import Header, HTTPException, status

from app.db import get_connection
from app.security import resolve_session


def get_current_social_id(authorization: str = Header(default="")) -> str:
    """Resolve the Bearer token in the Authorization header to a social_id.

    Also stamps last_seen on the account — this doubles as our presence
    mechanism (an account is "online" if last_seen is recent), avoiding the
    need for a separate presence service.
    """
    if not authorization.startswith("Bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing or malformed Authorization header")

    token = authorization.removeprefix("Bearer ").strip()
    social_id = resolve_session(token)
    if not social_id:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired session")

    conn = get_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE social_accounts SET last_seen = now() WHERE social_id = %s",
                    (social_id,),
                )
    finally:
        conn.close()

    return social_id
