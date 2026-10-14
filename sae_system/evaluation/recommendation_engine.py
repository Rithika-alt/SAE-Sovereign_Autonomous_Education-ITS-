"""Rule-based "next best action" recommendations — Phase 6.2.

Deliberately transparent, not a black-box ranker: every recommendation is a
direct, explainable derivation from real KnowledgeGraph/progress_store/
event_log data. No fabricated reasoning — every `reason` string is built
from an actual measured value (mastery %, days since review, last test
score), never an inferred claim like "you struggle with base cases" that
the system has no data to support.

Stateless and dashboard-independent by design (reads student data, never
touches st.session_state) so it can be called from page_home.py, a future
"Ask SAE" intent handler (Phase 7), or a future notification job (Phase 16)
without duplicating this logic in each place.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}
STALE_REVIEW_DAYS = 14

_ROADMAP_DIR = Path(__file__).resolve().parent.parent / "data" / "roadmaps"


def _load_roadmap(domain: str) -> Optional[Dict]:
    """Read a cached roadmap directly (same file convention as RoadmapAgent),
    avoiding a dependency on RoadmapAgent's Ollama/sovereignty setup for what
    is otherwise a pure data read.
    """
    safe = domain.lower().replace(" ", "_")
    path = _ROADMAP_DIR / f"{safe}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _last_failed_attempt(student_id: str, concept_id: str) -> Optional[Dict]:
    """Return the most recent test_attempt event for concept_id if it was a failure."""
    from evaluation.event_log import read_events, EVT_TEST_ATTEMPT

    events = [
        e for e in read_events(student_id=student_id, event_type=EVT_TEST_ATTEMPT)
        if e.get("concept_id") == concept_id
    ]
    if not events:
        return None
    events.sort(key=lambda e: e.get("timestamp", ""))
    last = events[-1]
    return last if not last.get("passed") else None


def recommend_next_actions(student_id: str, max_recommendations: int = 3) -> List[Dict]:
    """Return up to max_recommendations rule-based recommendations, highest priority first.

    Each item: {action, concept_id, concept_label, domain, priority, reason, cta_label}
    """
    from memory.graph_engine import KnowledgeGraph, MASTERY_THRESHOLD
    from persistence.progress_store import get_enrolled_domains, load_progress

    enrolled = get_enrolled_domains(student_id)
    if not enrolled:
        return [{
            "action": "start_domain",
            "concept_id": None,
            "concept_label": None,
            "domain": None,
            "priority": "high",
            "reason": "You haven't started a learning domain yet.",
            "cta_label": "Choose a domain",
        }]

    graph = KnowledgeGraph(student_id=student_id)
    nodes = graph.get_graph_data().get("nodes", [])
    recommendations: List[Dict] = []

    # Rule 1 — weak concept (mastery below threshold) with a recent failed attempt.
    for n in nodes:
        mastery = n.get("mastery", 0.0)
        if 0.0 < mastery < MASTERY_THRESHOLD:
            failed = _last_failed_attempt(student_id, n["id"])
            if failed:
                recommendations.append({
                    "action": "practice",
                    "concept_id": n["id"],
                    "concept_label": n["id"].replace("_", " ").title(),
                    "domain": n.get("domain", ""),
                    "priority": "high",
                    "reason": (
                        f"Mastery is {mastery:.0%} (below the {MASTERY_THRESHOLD:.0%} "
                        f"threshold) and your last test attempt scored "
                        f"{failed.get('percentage', 0):.0f}%."
                    ),
                    "cta_label": "Practice this concept",
                })

    # Rule 2 — weak concept, no recorded failure yet (e.g. never tested).
    for n in nodes:
        mastery = n.get("mastery", 0.0)
        if 0.0 < mastery < MASTERY_THRESHOLD and not any(
            r["concept_id"] == n["id"] for r in recommendations
        ):
            recommendations.append({
                "action": "review",
                "concept_id": n["id"],
                "concept_label": n["id"].replace("_", " ").title(),
                "domain": n.get("domain", ""),
                "priority": "medium",
                "reason": f"Mastery is {mastery:.0%}, below the {MASTERY_THRESHOLD:.0%} threshold.",
                "cta_label": "Review this concept",
            })

    # Rule 3 — mastered but stale (same retention-proxy definition as system_evaluator).
    now = datetime.now(timezone.utc)
    for n in nodes:
        mastery = n.get("mastery", 0.0)
        last_reviewed = n.get("last_reviewed")
        if mastery >= MASTERY_THRESHOLD and last_reviewed:
            try:
                reviewed_dt = datetime.fromisoformat(last_reviewed)
                if reviewed_dt.tzinfo is None:
                    reviewed_dt = reviewed_dt.replace(tzinfo=timezone.utc)
            except ValueError:
                continue
            days = (now - reviewed_dt).days
            if days > STALE_REVIEW_DAYS:
                recommendations.append({
                    "action": "review",
                    "concept_id": n["id"],
                    "concept_label": n["id"].replace("_", " ").title(),
                    "domain": n.get("domain", ""),
                    "priority": "medium",
                    "reason": f"Mastered {days} days ago and hasn't been reviewed since.",
                    "cta_label": "Quick review",
                })

    # Rule 4 — continue an unlocked-but-not-passed module, per enrolled domain.
    for domain in enrolled:
        prog = load_progress(student_id, domain)
        in_progress_modules = prog["modules_unlocked"] - prog["modules_passed"]
        roadmap = _load_roadmap(domain)
        if not in_progress_modules or not roadmap:
            continue
        modules_by_id = {m["module_id"]: m for m in roadmap.get("modules", [])}
        candidates = [modules_by_id[mid] for mid in in_progress_modules if mid in modules_by_id]
        if not candidates:
            continue
        next_module = min(candidates, key=lambda m: m.get("week", 999))
        attempted = prog["module_progress"].get(next_module["module_id"], 0.0) > 0
        recommendations.append({
            "action": "continue",
            "concept_id": next_module["module_id"],
            "concept_label": next_module.get("title", next_module["module_id"]),
            "domain": domain,
            "priority": "high" if attempted else "medium",
            "reason": (
                "You've attempted this module but haven't passed it yet."
                if attempted else
                f"Week {next_module.get('week', '?')} of your {domain} roadmap is unlocked and ready."
            ),
            "cta_label": f"Continue {domain}",
        })

    recommendations.sort(key=lambda r: PRIORITY_ORDER.get(r["priority"], 3))
    return recommendations[:max_recommendations]


def top_recommendation(student_id: str) -> Optional[Dict]:
    """Convenience wrapper for a single "recommended for you" card."""
    recs = recommend_next_actions(student_id, max_recommendations=1)
    return recs[0] if recs else None
