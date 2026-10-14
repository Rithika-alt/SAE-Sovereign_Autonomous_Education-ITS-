"""Aggregates learning outcomes, grading accuracy, engagement, and reliability
into one "how well is SAE performing" report for a student.

Each of the four dimensions uses a different evaluation method because they
answer different questions:
  - learning_outcomes: is the student actually mastering concepts, from
    KnowledgeGraph state + event history.
  - grading_accuracy: is the AI grader itself correct, from the static
    gold-standard set (grading_evaluator.py) plus inter-method agreement
    between the test-grading path and the auditor/dialogue path.
  - engagement: is the system being used consistently, from XPEngine +
    session/test-attempt event history.
  - reliability: is the app itself functioning, from Ollama/test-generation/
    dashboard-error event history.

Every function reports an `insufficient_data` flag rather than rendering a
misleading trend/rate from too few data points — see the MIN_EVENTS_FOR_TREND
threshold below.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Dict, List

from evaluation import event_log as _ev

MIN_EVENTS_FOR_TREND = 3
STALE_REVIEW_DAYS = 14


def _week_bucket(iso_ts: str) -> str:
    """Return an ISO 'YYYY-Www' bucket key for weekly aggregation."""
    dt = datetime.fromisoformat(iso_ts)
    year, week, _ = dt.isocalendar()
    return f"{year}-W{week:02d}"


# ---------------------------------------------------------------------------
# 1. Learning outcomes
# ---------------------------------------------------------------------------

def evaluate_learning_outcomes(student_id: str) -> Dict:
    from memory.graph_engine import KnowledgeGraph, MASTERY_THRESHOLD
    from persistence.progress_store import get_enrolled_domains, load_progress

    graph = KnowledgeGraph(student_id=student_id)
    kg_summary = graph.get_student_progress()
    nodes = graph.get_graph_data().get("nodes", [])

    test_events = _ev.read_events(student_id=student_id, event_type=_ev.EVT_TEST_ATTEMPT)
    insufficient = len(test_events) < MIN_EVENTS_FOR_TREND

    pass_rate = None
    weekly_pass_rate: Dict[str, Dict] = {}
    if test_events:
        passed = sum(1 for e in test_events if e.get("passed"))
        pass_rate = round(passed / len(test_events), 3)
        by_week: Dict[str, List[bool]] = defaultdict(list)
        for e in test_events:
            try:
                by_week[_week_bucket(e["timestamp"])].append(bool(e.get("passed")))
            except (KeyError, ValueError):
                continue
        for wk, results in sorted(by_week.items()):
            weekly_pass_rate[wk] = {
                "attempts": len(results),
                "pass_rate": round(sum(results) / len(results), 3),
            }

    module_completion: Dict[str, Dict] = {}
    for domain in get_enrolled_domains(student_id):
        prog = load_progress(student_id, domain)
        total_touched = len(prog["module_progress"])
        module_completion[domain] = {
            "modules_passed": len(prog["modules_passed"]),
            "modules_attempted": total_touched,
        }

    now = datetime.now(timezone.utc)
    at_risk = []
    for n in nodes:
        mastery = n.get("mastery", 0.0)
        last_reviewed = n.get("last_reviewed")
        if mastery >= MASTERY_THRESHOLD and last_reviewed:
            try:
                reviewed_dt = datetime.fromisoformat(last_reviewed)
                if reviewed_dt.tzinfo is None:
                    reviewed_dt = reviewed_dt.replace(tzinfo=timezone.utc)
                if (now - reviewed_dt) > timedelta(days=STALE_REVIEW_DAYS):
                    at_risk.append({
                        "concept_id": n["id"],
                        "mastery": mastery,
                        "days_since_review": (now - reviewed_dt).days,
                    })
            except ValueError:
                continue

    return {
        "insufficient_data": insufficient,
        "total_concepts": kg_summary.get("total_concepts", 0),
        "mastered": kg_summary.get("mastered", 0),
        "in_progress": kg_summary.get("in_progress", 0),
        "not_started": kg_summary.get("not_started", 0),
        "domains": kg_summary.get("domains", {}),
        "weakest_concepts": kg_summary.get("weakest_concepts", []),
        "strongest_concepts": kg_summary.get("strongest_concepts", []),
        "test_pass_rate": pass_rate,
        "test_attempt_count": len(test_events),
        "weekly_pass_rate": weekly_pass_rate,
        "module_completion": module_completion,
        "retention_proxy": {
            "note": (
                "PROXY — concepts mastered but not reviewed in "
                f"{STALE_REVIEW_DAYS}+ days. Not a validated forgetting-curve "
                "measurement; there is no repeated-measurement data to fit one."
            ),
            "at_risk_concepts": at_risk,
        },
    }


# ---------------------------------------------------------------------------
# 2. Grading accuracy
# ---------------------------------------------------------------------------

def evaluate_grading_accuracy(student_id: str) -> Dict:
    from evaluation.grading_evaluator import load_gold_set, compare_thresholds
    from config import SEMANTIC_PASS_THRESHOLD

    gold_set = load_gold_set()
    comparison = compare_thresholds(
        gold_set["short_answer"], thresholds=(0.45, SEMANTIC_PASS_THRESHOLD)
    )

    test_events = _ev.read_events(student_id=student_id, event_type=_ev.EVT_TEST_ATTEMPT)
    dialogue_events = _ev.read_events(student_id=student_id, event_type=_ev.EVT_DIALOGUE_ATTEMPT)

    # Inter-method agreement: pair test/dialogue attempts on the same concept_id
    # (loosely — exact timestamp correlation isn't available), compare pass/fail.
    test_by_concept: Dict[str, List[bool]] = defaultdict(list)
    for e in test_events:
        test_by_concept[e.get("concept_id", "")].append(bool(e.get("passed")))

    agree = disagree = 0
    for e in dialogue_events:
        concept = e.get("concept_id", "")
        dialogue_passed = e.get("phase") == "complete"
        for test_passed in test_by_concept.get(concept, []):
            if test_passed == dialogue_passed:
                agree += 1
            else:
                disagree += 1

    total_compared = agree + disagree
    inter_method_agreement = round(agree / total_compared, 3) if total_compared else None

    return {
        "insufficient_data": False,  # gold-set evaluation is always available
        "gold_set_size": len(gold_set["short_answer"]),
        "current_threshold": SEMANTIC_PASS_THRESHOLD,
        "threshold_comparison": comparison,
        "inter_method_agreement": {
            "insufficient_data": total_compared < MIN_EVENTS_FOR_TREND,
            "agreement_rate": inter_method_agreement,
            "n_compared": total_compared,
            "note": (
                "Compares test-path pass/fail against auditor/dialogue-path "
                "pass/fail for the same concept_id — not a strict per-attempt "
                "pairing, since the two paths don't share an attempt ID."
            ),
        },
    }


# ---------------------------------------------------------------------------
# 3. Engagement
# ---------------------------------------------------------------------------

def evaluate_engagement(student_id: str) -> Dict:
    from integrity.xp_engine import XPEngine

    xp = XPEngine(student_id)
    xp_summary = xp.summary()

    session_events = _ev.read_events(student_id=student_id, event_type=_ev.EVT_SESSION_START)
    test_events = _ev.read_events(student_id=student_id, event_type=_ev.EVT_TEST_ATTEMPT)
    all_activity = sorted(
        session_events + test_events, key=lambda e: e.get("timestamp", "")
    )

    insufficient = len(all_activity) < MIN_EVENTS_FOR_TREND

    weekly_sessions: Dict[str, int] = defaultdict(int)
    for e in session_events:
        try:
            weekly_sessions[_week_bucket(e["timestamp"])] += 1
        except (KeyError, ValueError):
            continue

    weekly_tests: Dict[str, int] = defaultdict(int)
    for e in test_events:
        try:
            weekly_tests[_week_bucket(e["timestamp"])] += 1
        except (KeyError, ValueError):
            continue

    drop_off = None
    if len(all_activity) >= 2:
        timestamps = []
        for e in all_activity:
            try:
                timestamps.append(datetime.fromisoformat(e["timestamp"]))
            except (KeyError, ValueError):
                continue
        if len(timestamps) >= 2:
            gaps_days = [
                (timestamps[i] - timestamps[i - 1]).total_seconds() / 86400
                for i in range(1, len(timestamps))
            ]
            median_gap = statistics.median(gaps_days)
            days_since_last = (
                datetime.now(timezone.utc) - timestamps[-1]
            ).total_seconds() / 86400
            drop_off = {
                "days_since_last_activity": round(days_since_last, 1),
                "historical_median_gap_days": round(median_gap, 1),
                "flagged": days_since_last > max(7.0, median_gap * 3),
            }

    return {
        "insufficient_data": insufficient,
        "xp": xp_summary,
        "sessions_per_week": dict(sorted(weekly_sessions.items())),
        "tests_per_week": dict(sorted(weekly_tests.items())),
        "drop_off": drop_off,
    }


# ---------------------------------------------------------------------------
# 4. Reliability
# ---------------------------------------------------------------------------

def evaluate_reliability() -> Dict:
    """System-wide, not per-student — Ollama/test-gen/dashboard events are logged
    under student_id="system" or the acting student; this reports the aggregate.
    """
    ollama_events = _ev.read_events(event_type=_ev.EVT_OLLAMA_CALL)
    gen_events = _ev.read_events(event_type=_ev.EVT_TEST_GENERATION)
    error_events = _ev.read_events(event_type=_ev.EVT_DASHBOARD_ERROR)

    insufficient = len(ollama_events) < MIN_EVENTS_FOR_TREND

    ollama_success_rate = None
    latency_mean = latency_p95 = None
    if ollama_events:
        successes = [e for e in ollama_events if e.get("success")]
        ollama_success_rate = round(len(successes) / len(ollama_events), 3)
        latencies = sorted(e["latency_s"] for e in ollama_events if "latency_s" in e)
        if latencies:
            latency_mean = round(statistics.mean(latencies), 3)
            if len(latencies) >= 20:
                idx = min(len(latencies) - 1, int(len(latencies) * 0.95))
                latency_p95 = round(latencies[idx], 3)

    cache_hit_rate = None
    if gen_events:
        hits = sum(1 for e in gen_events if e.get("cache_hit"))
        cache_hit_rate = round(hits / len(gen_events), 3)

    return {
        "insufficient_data": insufficient,
        "ollama": {
            "success_rate": ollama_success_rate,
            "n_calls": len(ollama_events),
            "latency_mean_s": latency_mean,
            "latency_p95_s": latency_p95,
            "p95_note": None if latency_p95 is not None else "N < 20 — P95 not computed",
        },
        "test_generation": {
            "cache_hit_rate": cache_hit_rate,
            "n_generations": len(gen_events),
        },
        "dashboard_errors": {
            "count": len(error_events),
            "recent": error_events[-5:],
        },
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def evaluate_all(student_id: str) -> Dict:
    return {
        "student_id": student_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "learning_outcomes": evaluate_learning_outcomes(student_id),
        "grading_accuracy": evaluate_grading_accuracy(student_id),
        "engagement": evaluate_engagement(student_id),
        "reliability": evaluate_reliability(),
    }
