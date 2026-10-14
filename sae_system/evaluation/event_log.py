"""Application telemetry — a generic, append-only JSONL event log.

Deliberately separate from integrity/proof_of_learning.py's mastery_log.jsonl:
that file is a sparse, hash-bearing proof/audit trail for verified mastery
events, and mixing high-volume telemetry (every Ollama call, every dashboard
page load) into it would dilute its purpose and bloat a file meant to stay a
short audit trail. This module owns application-level events instead.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_LOG_PATH = _DATA_DIR / "events.jsonl"

# Timing spans (evaluation/perf_trace.py) are written from many worker threads
# at once; serialise appends so two threads can't interleave one JSON line.
_WRITE_LOCK = threading.Lock()

# Event-type constants — call sites should use these rather than hand-typing strings.
EVT_SESSION_START = "session_start"
EVT_SESSION_END = "session_end"
EVT_TEST_GENERATION = "test_generation"
EVT_TEST_ATTEMPT = "test_attempt"
EVT_DIALOGUE_ATTEMPT = "dialogue_attempt"
EVT_OLLAMA_CALL = "ollama_call"
EVT_XP_AWARDED = "xp_awarded"
EVT_MASTERY_UPDATE = "mastery_update"
EVT_CONCEPT_MASTERED = "concept_mastered"
EVT_DOMAIN_COMPLETED = "domain_completed"
EVT_DASHBOARD_ERROR = "dashboard_error"
EVT_AGENT_EXECUTION = "agent_execution"
EVT_SEARCH_EXECUTION = "search_execution"
EVT_KNOWLEDGE_GRAPH_UPDATE = "knowledge_graph_update"
EVT_PERF_SPAN = "perf_span"  # timing spans — see evaluation/perf_trace.py


def log_event(event_type: str, student_id: str = "system", **fields) -> None:
    """Append one event to data/events.jsonl. Never raises — telemetry must not crash the app."""
    record = {
        "event_type": event_type,
        "student_id": student_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        **fields,
    }
    try:
        _DATA_DIR.mkdir(parents=True, exist_ok=True)
        line = json.dumps(record) + "\n"
        with _WRITE_LOCK:
            with _LOG_PATH.open("a", encoding="utf-8") as f:
                f.write(line)
    except Exception:
        pass


def read_events(
    student_id: Optional[str] = None,
    event_type: Optional[str] = None,
    since: Optional[datetime] = None,
) -> List[Dict]:
    """Read events.jsonl, optionally filtered by student_id, event_type, and/or a since-timestamp.

    Every call re-parses the whole file, so the time is recorded as an
    ``events.read_all`` perf span (the file grows with every event, and
    several dashboard pages call this on every rerun).
    """
    import time

    from evaluation import perf_trace

    t0 = time.perf_counter()
    events = _read_events(student_id, event_type, since)
    try:
        size = _LOG_PATH.stat().st_size if _LOG_PATH.exists() else 0
    except OSError:
        size = 0
    perf_trace.record(
        "events.read_all", (time.perf_counter() - t0) * 1000,
        matched=len(events), file_bytes=size, filter_type=event_type,
    )
    return events


def _read_events(
    student_id: Optional[str] = None,
    event_type: Optional[str] = None,
    since: Optional[datetime] = None,
) -> List[Dict]:
    if not _LOG_PATH.exists():
        return []

    events: List[Dict] = []
    try:
        with _LOG_PATH.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if student_id is not None and record.get("student_id") != student_id:
                    continue
                if event_type is not None and record.get("event_type") != event_type:
                    continue
                if since is not None:
                    try:
                        ts = datetime.fromisoformat(record["timestamp"])
                    except (KeyError, ValueError):
                        continue
                    if ts < since:
                        continue

                events.append(record)
    except Exception:
        return events

    return events
