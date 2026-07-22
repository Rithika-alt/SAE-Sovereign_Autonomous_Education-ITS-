"""Proof-of-learning: tamper-evident hash receipts and append-only mastery log."""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict

LOG_PATH = Path(__file__).resolve().parent.parent / "mastery_log.jsonl"


def generate_hash(
    student_id: str,
    concept_id: str,
    session_id: str,
    composite_score: float,
) -> str:
    """Compute a SHA-256 proof hash for a completed learning event.

    The hash is derived from the concatenated string
    ``{student_id}:{concept_id}:{session_id}:{composite_score:.4f}``.

    Args:
        student_id: Learner identifier.
        concept_id: Concept that was mastered.
        session_id: UUID of the current session.
        composite_score: Final composite score (will be formatted to 4 d.p.).

    Returns:
        Hex-encoded SHA-256 digest string.
    """
    raw = f"{student_id}:{concept_id}:{session_id}:{composite_score:.4f}"
    return hashlib.sha256(raw.encode()).hexdigest()


def append_to_log(
    proof_hash: str,
    student_id: str,
    concept_id: str,
    composite_score: float,
) -> None:
    """Append a JSON line to the mastery log file.

    Args:
        proof_hash: SHA-256 proof hash from generate_hash.
        student_id: Learner identifier.
        concept_id: Concept that was mastered.
        composite_score: Final composite score.
    """
    entry: Dict = {
        "hash": proof_hash,
        "student_id": student_id,
        "concept_id": concept_id,
        "composite_score": composite_score,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    with LOG_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")


def read_log(student_id: str) -> List[Dict]:
    """Read all log entries for a given student.

    Args:
        student_id: Learner identifier to filter by.

    Returns:
        List of log entry dicts for this student.
    """
    if not LOG_PATH.exists():
        return []
    entries: List[Dict] = []
    with LOG_PATH.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                if entry.get("student_id") == student_id:
                    entries.append(entry)
            except json.JSONDecodeError:
                continue
    return entries
