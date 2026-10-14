"""Pytest tests for evaluation.activity_feed (Phase 11).

No LLM involved anywhere — every rule is deterministic, so these tests
never need live Ollama.
"""

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from evaluation.activity_feed import (
    _NOTABLE_DELTA, _normalize_event, build_activity_timeline, build_notifications,
)

_REAL_STUDENT = "699c235c-3ce7-4a43-b391-ea04b6559579"
_REAL_DOMAIN = "Machine Learning"


# ---------------------------------------------------------------------------
# Event normalization
# ---------------------------------------------------------------------------

def test_normalize_test_attempt_pass():
    entry = _normalize_event({
        "event_type": "test_attempt", "timestamp": "2026-08-22T10:00:00+00:00",
        "concept_id": "supervised_learning", "domain": "Machine Learning",
        "passed": True, "percentage": 92.0,
    }, {})
    assert entry is not None
    assert "Passed" in entry["title"]
    assert "92" in entry["detail"]


def test_normalize_test_attempt_fail():
    entry = _normalize_event({
        "event_type": "test_attempt", "timestamp": "2026-08-22T10:00:00+00:00",
        "concept_id": "x", "domain": "D", "passed": False, "percentage": 40.0,
    }, {})
    assert "Attempted" in entry["title"]
    assert entry["icon"] == "⚠️"


def test_normalize_ignores_unknown_event_types():
    assert _normalize_event({"event_type": "ollama_call", "timestamp": "2026-01-01T00:00:00+00:00"}, {}) is None


def test_normalize_ignores_missing_timestamp():
    assert _normalize_event({"event_type": "test_attempt"}, {}) is None


def test_normalize_mastery_change_filters_tiny_deltas():
    tiny = _normalize_event({
        "event_type": "knowledge_graph_update", "timestamp": "2026-08-22T10:00:00+00:00",
        "concept_id": "x", "mastery_before": 0.50, "mastery_after": 0.51, "delta": 0.01,
    }, {})
    assert tiny is None  # below _NOTABLE_DELTA


def test_normalize_mastery_change_surfaces_notable_deltas():
    entry = _normalize_event({
        "event_type": "knowledge_graph_update", "timestamp": "2026-08-22T10:00:00+00:00",
        "concept_id": "x", "mastery_before": 0.50, "mastery_after": 0.70, "delta": 0.20,
    }, {})
    assert entry is not None
    assert entry["icon"] == "📈"
    assert "50%" in entry["detail"] and "70%" in entry["detail"]


def test_normalize_resolves_domain_from_concept_map_when_event_lacks_it():
    """The real bug this fixes: knowledge_graph_update events don't carry a
    domain field at all (confirmed in memory/graph_engine.py) — must fall
    back to the concept->domain map derived from the real KnowledgeGraph.
    """
    entry = _normalize_event({
        "event_type": "knowledge_graph_update", "timestamp": "2026-08-22T10:00:00+00:00",
        "concept_id": "supervised_learning", "mastery_before": 0.5, "mastery_after": 0.8, "delta": 0.3,
    }, {"supervised_learning": "Machine Learning"})
    assert entry["domain"] == "Machine Learning"


def test_normalize_malformed_event_does_not_crash():
    assert _normalize_event({}, {}) is None
    assert _normalize_event({"event_type": "test_attempt", "timestamp": None}, {}) is None


# ---------------------------------------------------------------------------
# Timeline — chronological ordering, isolation, real data
# ---------------------------------------------------------------------------

def test_timeline_is_reverse_chronological():
    timeline = build_activity_timeline(_REAL_STUDENT, _REAL_DOMAIN, limit=50)
    timestamps = [e["timestamp"] for e in timeline]
    assert timestamps == sorted(timestamps, reverse=True)


def test_timeline_respects_limit():
    timeline = build_activity_timeline(_REAL_STUDENT, _REAL_DOMAIN, limit=1)
    assert len(timeline) <= 1


def test_timeline_empty_for_nonexistent_student():
    timeline = build_activity_timeline("nonexistent_student_activity_test", "Anything")
    assert timeline == []


def test_timeline_domain_isolation():
    """Entries with a resolved domain must match the requested domain (entries
    with no resolvable domain, e.g. a bare session_start, pass through)."""
    timeline = build_activity_timeline(_REAL_STUDENT, "Some Domain That Does Not Exist", limit=50)
    for e in timeline:
        if e["domain"]:
            assert e["domain"] == "Some Domain That Does Not Exist"


# ---------------------------------------------------------------------------
# Notifications — real thresholds, dedup, no LLM
# ---------------------------------------------------------------------------

def test_notifications_use_real_mastery_threshold_not_a_new_one():
    import evaluation.activity_feed as af
    from memory.graph_engine import MASTERY_THRESHOLD
    # The module imports MASTERY_THRESHOLD from memory.graph_engine inside
    # the function rather than redefining it — verify no local override exists.
    assert not hasattr(af, "MASTERY_THRESHOLD")
    assert not hasattr(af, "_MASTERY_THRESHOLD")


def test_notifications_are_deduplicated_by_type_and_concept():
    notes = build_notifications(_REAL_STUDENT, _REAL_DOMAIN)
    keys = [(n["type"], n["concept_id"]) for n in notes]
    assert len(keys) == len(set(keys)), f"duplicate (type, concept_id) pairs found: {keys}"


def test_notifications_sorted_by_priority():
    notes = build_notifications(_REAL_STUDENT, _REAL_DOMAIN)
    order = {"high": 0, "medium": 1, "low": 2}
    priorities = [order.get(n["priority"], 3) for n in notes]
    assert priorities == sorted(priorities)


def test_notifications_respect_max_count():
    notes = build_notifications(_REAL_STUDENT, _REAL_DOMAIN, max_notifications=2)
    assert len(notes) <= 2


def test_notifications_empty_for_student_with_no_data():
    notes = build_notifications("nonexistent_student_activity_test", "Anything")
    assert notes == []


def test_every_notification_has_a_real_concept_id():
    """No fabricated activity — every notification traces to an actual concept."""
    notes = build_notifications(_REAL_STUDENT, _REAL_DOMAIN)
    for n in notes:
        assert n["concept_id"], f"notification with no concept_id: {n}"


def test_weak_concept_notifications_come_from_recommendation_engine():
    """Cross-check against the actual recommendation_engine output — not a
    second, reimplemented recommendation algorithm.
    """
    from evaluation.recommendation_engine import recommend_next_actions
    direct = {(r["action"], r["concept_id"]) for r in recommend_next_actions(_REAL_STUDENT, max_recommendations=3)}
    notes = build_notifications(_REAL_STUDENT, _REAL_DOMAIN)
    forward_looking = [n for n in notes if n["type"] not in ("milestone", "improvement")]
    for n in forward_looking:
        assert (n["type"], n["concept_id"]) in direct


# ---------------------------------------------------------------------------
# Dashboard — imports, registration, headless render, routing
# ---------------------------------------------------------------------------

def test_page_activity_imports_successfully():
    from dashboard.page_activity import page_activity
    assert callable(page_activity)


def test_page_activity_is_hidden_from_router_and_nav_but_its_code_remains():
    # The Activity page was hidden from the sidebar/router (code kept). It must not
    # be routable, and a stale session pointing at it is redirected Home.
    import dashboard.app as app_module
    assert "activity" not in app_module._PAGES
    assert "activity" in app_module._HIDDEN_PAGE_IDS
    from dashboard.page_activity import page_activity   # module still importable
    assert callable(page_activity)


def test_go_to_canvas_sets_focus_override(monkeypatch):
    import streamlit as st
    from dashboard.page_activity import _go_to_canvas

    class _RerunSentinel(Exception):
        pass

    monkeypatch.setattr(st, "rerun", lambda: (_ for _ in ()).throw(_RerunSentinel()))

    ss = {}
    try:
        _go_to_canvas(ss, "classification_algorithms")
    except _RerunSentinel:
        pass
    assert ss["canvas_focus_concept_id"] == "classification_algorithms"
    assert ss["page"] == "canvas"
