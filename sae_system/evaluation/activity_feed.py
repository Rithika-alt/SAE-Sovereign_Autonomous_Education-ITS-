"""Activity Timeline + Intelligent Notifications — Phase 11.

Existing Events -> Activity Normalization -> Timeline + Notifications ->
Existing Lesson / Canvas / Ask SAE / Tutor.

Reuses evaluation/event_log.py (Phase 3) as the sole source of history —
no second history store. Reuses evaluation/recommendation_engine.py (Phase
6) for forward-looking "what should I do" notifications rather than
reimplementing weak-concept/stale-review detection; this module adds only
the genuinely new capability recommendation_engine doesn't have:
backward-looking "what changed" detection, derived from
EVT_KNOWLEDGE_GRAPH_UPDATE's mastery_before/mastery_after fields (already
logged by memory/graph_engine.py::update_mastery on every mastery change,
for both the test-grading and Adaptive Tutor paths).

No LLM is used anywhere in this module (Hard Rule: deterministic
notifications) — every rule below is a plain comparison against real
logged/stored values.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional

# Events shown in the student-facing timeline. Deliberately excludes
# infra-level telemetry (ollama_call, test_generation, dashboard_error,
# agent_execution for roadmap/searcher) that exists for Phase 3/9's
# system-evaluation purposes but means nothing to a student.
_TIMELINE_EVENT_TYPES = {
    "session_start", "test_attempt", "dialogue_attempt",
    "knowledge_graph_update", "domain_completed", "agent_execution",
}

# Minimum mastery delta to surface as a standalone "mastery improved" (or
# "declined") timeline/notification entry — filters out noise from tiny
# blend-weighted nudges so the feed isn't dominated by trivial changes.
_NOTABLE_DELTA = 0.03


def _fmt_concept(concept_id: str) -> str:
    return (concept_id or "").replace("_", " ").title()


def _concept_domain_map(student_id: str) -> Dict[str, str]:
    """concept_id -> domain, from the real KnowledgeGraph — the only place
    that mapping actually lives. Needed because
    memory/graph_engine.py::update_mastery's EVT_KNOWLEDGE_GRAPH_UPDATE
    events don't carry a domain field (update_mastery itself is never
    passed one); resolving via the graph avoids adding a new field to that
    call site just for this module's benefit.
    """
    from memory.graph_engine import KnowledgeGraph
    graph = KnowledgeGraph(student_id=student_id)
    return {n["id"]: n.get("domain", "") for n in graph.get_graph_data().get("nodes", [])}


def _normalize_event(event: Dict, concept_domains: Dict[str, str]) -> Optional[Dict]:
    """Turn one raw event_log record into a student-friendly timeline
    entry, or None if this event type/shape isn't timeline-worthy. Never
    invents a timestamp or detail that wasn't in the raw event.
    """
    etype = event.get("event_type")
    ts = event.get("timestamp")
    if etype not in _TIMELINE_EVENT_TYPES or not ts:
        return None

    concept_id = event.get("concept_id")
    domain = event.get("domain") or concept_domains.get(concept_id, "")

    if etype == "session_start":
        return {
            "timestamp": ts, "icon": "➡️", "kind": "session_start",
            "title": f"Started a session in {domain}" if domain else "Started a session",
            "detail": "", "concept_id": None, "domain": domain,
        }

    if etype == "test_attempt":
        passed = event.get("passed")
        pct = event.get("percentage")
        icon = "✅" if passed else "⚠️"
        title = f"{'Passed' if passed else 'Attempted'} the {_fmt_concept(concept_id)} test"
        detail = f"Score: {pct:.0f}%" if isinstance(pct, (int, float)) else ""
        return {
            "timestamp": ts, "icon": icon, "kind": "test_attempt",
            "title": title, "detail": detail, "concept_id": concept_id, "domain": domain,
        }

    if etype == "dialogue_attempt":
        label = event.get("label")  # AdaptiveTutorAgent (Phase 9+) sets this
        phase = event.get("phase")  # AuditorAgent (CLI path) sets this instead
        outcome = label or phase or "attempted"
        icon = {"correct": "✅", "complete": "✅", "partial": "🟡", "incorrect": "⚠️", "retry": "⚠️"}.get(outcome, "•")
        return {
            "timestamp": ts, "icon": icon, "kind": "dialogue_attempt",
            "title": f"Tutor question on {_fmt_concept(concept_id)}: {outcome}",
            "detail": "", "concept_id": concept_id, "domain": domain,
        }

    if etype == "knowledge_graph_update":
        delta = event.get("delta")
        if not isinstance(delta, (int, float)) or abs(delta) < _NOTABLE_DELTA:
            return None  # tiny/no-op change — not timeline-worthy
        direction = "improved" if delta > 0 else "declined"
        icon = "📈" if delta > 0 else "📉"
        after = event.get("mastery_after")
        return {
            "timestamp": ts, "icon": icon, "kind": "mastery_change",
            "title": f"Mastery {direction}: {_fmt_concept(concept_id)}",
            "detail": f"{event.get('mastery_before', 0):.0%} -> {after:.0%}" if isinstance(after, (int, float)) else "",
            "concept_id": concept_id, "domain": domain,
            "mastery_before": event.get("mastery_before"), "mastery_after": after,
        }

    if etype == "domain_completed":
        return {
            "timestamp": ts, "icon": "🎉", "kind": "domain_completed",
            "title": f"Completed the {domain} domain!",
            "detail": f"{event.get('modules_completed', '?')} modules", "concept_id": None, "domain": domain,
        }

    if etype == "agent_execution" and event.get("agent") == "ask_sae":
        grounded = event.get("grounded")
        return {
            "timestamp": ts, "icon": "💬", "kind": "ask_sae",
            "title": f"Asked SAE about {_fmt_concept(concept_id)}" if concept_id else "Asked SAE a question",
            "detail": "Grounded in your lesson" if grounded else "General knowledge answer",
            "concept_id": concept_id, "domain": domain,
        }

    return None


def build_activity_timeline(student_id: str, domain: Optional[str] = None, limit: int = 50) -> List[Dict]:
    """Reverse-chronological, student-friendly activity feed.

    Handles malformed/empty events gracefully: read_events already skips
    unparseable lines; _normalize_event returns None (silently dropped,
    not crashed on) for anything missing a timestamp or an unrecognized shape.
    """
    from evaluation.event_log import read_events

    raw = read_events(student_id=student_id)
    concept_domains = _concept_domain_map(student_id)
    entries = []
    for event in raw:
        entry = _normalize_event(event, concept_domains)
        if entry is None:
            continue
        if domain and entry["domain"] and entry["domain"] != domain:
            continue
        entries.append(entry)

    entries.sort(key=lambda e: e["timestamp"], reverse=True)
    return entries[:limit]


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------

def _milestone_notifications(student_id: str, domain: Optional[str]) -> List[Dict]:
    """Backward-looking: did a recent KG update cross MASTERY_THRESHOLD, or
    move mastery notably? This is the one genuinely new detection this
    module adds — recommendation_engine only looks at current state, not
    history.
    """
    from evaluation.event_log import read_events
    from memory.graph_engine import MASTERY_THRESHOLD

    events = read_events(student_id=student_id, event_type="knowledge_graph_update")
    concept_domains = _concept_domain_map(student_id)

    notes = []
    seen_concepts = set()
    for e in sorted(events, key=lambda e: e["timestamp"], reverse=True):
        concept_id = e.get("concept_id")
        event_domain = e.get("domain") or concept_domains.get(concept_id, "")
        if domain and event_domain and event_domain != domain:
            continue
        before, after = e.get("mastery_before"), e.get("mastery_after")
        if concept_id in seen_concepts or not isinstance(before, (int, float)) or not isinstance(after, (int, float)):
            continue
        seen_concepts.add(concept_id)

        if before < MASTERY_THRESHOLD <= after:
            notes.append({
                "type": "milestone", "priority": "high",
                "title": f"{_fmt_concept(concept_id)} mastered!",
                "message": f"Mastery reached {after:.0%}, crossing the {MASTERY_THRESHOLD:.0%} mastered threshold.",
                "concept_id": concept_id, "domain": event_domain,
            })
        elif (after - before) >= _NOTABLE_DELTA:
            notes.append({
                "type": "improvement", "priority": "low",
                "title": f"{_fmt_concept(concept_id)} improved",
                "message": f"Mastery moved {before:.0%} -> {after:.0%}.",
                "concept_id": concept_id, "domain": event_domain,
            })
        if len(notes) >= 5:
            break
    return notes


def build_notifications(student_id: str, domain: Optional[str] = None, max_notifications: int = 6) -> List[Dict]:
    """Deterministic, actionable notifications. Every entry traces to a
    real measured value — either a logged event (milestones/improvements)
    or the existing recommendation_engine (weak concepts, stale review,
    prerequisites — not reimplemented here, just reformatted).

    Each notification: {type, priority, title, message, concept_id, domain,
    actions: ["lesson", "ask", "tutor"]}. Rendering/routing is the caller's
    job (dashboard pages) — this stays pure/testable.
    """
    notes: List[Dict] = []

    # Backward-looking: what changed (this module's own logic).
    notes.extend(_milestone_notifications(student_id, domain))

    # Forward-looking: what needs attention (recommendation_engine, reused
    # as-is — not a second recommendation algorithm).
    from evaluation.recommendation_engine import recommend_next_actions
    for rec in recommend_next_actions(student_id, max_recommendations=3):
        if not rec.get("concept_id"):
            continue
        if domain and rec.get("domain") not in (domain, None):
            continue
        priority = {"high": "high", "medium": "medium", "low": "low"}.get(rec.get("priority"), "medium")
        notes.append({
            "type": rec.get("action", "recommendation"),
            "priority": priority,
            "title": rec.get("concept_label") or "Recommended action",
            "message": rec["reason"],
            "concept_id": rec["concept_id"],
            "domain": rec.get("domain"),
        })

    # Dedup by (type, concept_id) — same concept shouldn't produce two
    # notifications of the same kind (Hard Rule: no notification spam).
    seen = set()
    deduped = []
    for n in notes:
        key = (n["type"], n["concept_id"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(n)

    priority_order = {"high": 0, "medium": 1, "low": 2}
    deduped.sort(key=lambda n: priority_order.get(n["priority"], 3))
    return deduped[:max_notifications]
