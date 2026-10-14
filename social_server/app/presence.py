"""Presence is derived from last_seen, stamped on every authenticated
request (see dependencies.get_current_social_id) — no separate presence
service or Redis needed for the MVP.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

ONLINE_WINDOW = timedelta(seconds=90)


def is_online(last_seen: Optional[datetime]) -> bool:
    if last_seen is None:
        return False
    if last_seen.tzinfo is None:
        last_seen = last_seen.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - last_seen < ONLINE_WINDOW
