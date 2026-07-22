"""Local JSON file-based user store — used when PostgreSQL is unreachable."""

import json
import logging
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger(__name__)

_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "users.json"


def _load() -> dict:
    if _DB_PATH.exists():
        try:
            return json.loads(_DB_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"students": {}}


def _save(data: dict) -> None:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    _DB_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


def create_student(
    student_id: str, name: str, username: str, email: str, password_hash: str
) -> None:
    data = _load()
    key = email.lower().strip()
    if key in data["students"]:
        raise ValueError(f"Email already registered: {email}")
    data["students"][key] = {
        "student_id": student_id,
        "name": name,
        "username": username,
        "email": key,
        "password_hash": password_hash,
        "domain": "",
    }
    _save(data)
    logger.info("local_db: student created — %s (%s)", username, email)


def get_student_by_email(email: str) -> Optional[Dict]:
    return _load()["students"].get(email.lower().strip())


def email_exists(email: str) -> bool:
    return email.lower().strip() in _load()["students"]


def username_exists(username: str) -> bool:
    uname = username.strip()
    return any(s["username"] == uname for s in _load()["students"].values())


def update_student_domain(student_id: str, domain: str) -> None:
    data = _load()
    for student in data["students"].values():
        if student["student_id"] == student_id:
            student["domain"] = domain
            _save(data)
            return
