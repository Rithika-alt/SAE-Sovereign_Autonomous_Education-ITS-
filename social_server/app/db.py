"""PostgreSQL connection helper for the social server.

Deliberately self-contained (not shared with sae_system/auth/db.py) — this
service is deployed independently of any student's local stack.
"""

import os

import psycopg2
from psycopg2.extras import RealDictCursor


def get_connection():
    """Return a new connection to the social DB. Raises if DATABASE_URL unset."""
    url = os.getenv("SOCIAL_DATABASE_URL")
    if not url:
        raise RuntimeError("SOCIAL_DATABASE_URL not set.")
    return psycopg2.connect(url, cursor_factory=RealDictCursor)
