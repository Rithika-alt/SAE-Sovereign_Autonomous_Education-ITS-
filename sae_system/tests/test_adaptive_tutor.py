"""Pytest tests for agents.adaptive_tutor_agent and dashboard.page_tutor (Phase 8).

Diagnosis/strategy/mastery-blend tests never require a live Ollama server —
they construct TutorState directly or monkeypatch KnowledgeGraph/event_log.
Dashboard render tests use Streamlit's AppTest and avoid submitting an
answer (that path needs live Ollama; verified manually in Step 20,
consistent with the Phase 7 convention of keeping live-Ollama flows out of
the fast suite).
"""

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import pytest

from agents.adaptive_tutor_agent import (
    AdaptiveTutorAgent,
    MASTERY_BLEND_WEIGHT_NEW,
    MODE_DEVELOPING,
    MODE_MASTERED_RETENTION,
    MODE_STRONG,
    MODE_STRUGGLING,
    STALE_REVIEW_DAYS,
    TutorState,
    choose_teaching_strategy,
    diagnose_tutor_state,
)
from agents.tutor_agent import SovereigntyError
from config import SEMANTIC_PASS_THRESHOLD


def _bare_agent() -> AdaptiveTutorAgent:
    return object.__new__(AdaptiveTutorAgent)


# ---------------------------------------------------------------------------
# Mode banding — mastery thresholds
# ---------------------------------------------------------------------------

def test_low_mastery_is_struggling(monkeypatch):
    _patch_graph(monkeypatch, mastery=0.25, prereqs={}, last_reviewed=None)
    _patch_no_recent_attempts(monkeypatch)
    state = diagnose_tutor_state("s1", "some_concept", "Domain")
    assert state.mode == MODE_STRUGGLING
    assert any("25%" in r for r in state.reasons)

    strategy = choose_teaching_strategy(state)
    assert strategy.explanation_depth == "scaffolded"
    assert strategy.question_difficulty == "easy"
    assert strategy.hints_enabled is True


def test_medium_mastery_is_developing(monkeypatch):
    _patch_graph(monkeypatch, mastery=0.70, prereqs={}, last_reviewed=None)
    _patch_no_recent_attempts(monkeypatch)
    state = diagnose_tutor_state("s1", "some_concept", "Domain")
    assert state.mode == MODE_DEVELOPING

    strategy = choose_teaching_strategy(state)
    assert strategy.explanation_depth == "standard"
    assert strategy.question_difficulty == "medium"


def test_high_fresh_mastery_is_strong(monkeypatch):
    _patch_graph(monkeypatch, mastery=0.90, prereqs={}, last_reviewed=_iso_days_ago(2))
    _patch_no_recent_attempts(monkeypatch)
    state = diagnose_tutor_state("s1", "some_concept", "Domain")
    assert state.mode == MODE_STRONG

    strategy = choose_teaching_strategy(state)
    assert strategy.explanation_depth == "concise"
    assert strategy.question_difficulty == "hard"
    assert strategy.hints_enabled is False


def test_high_stale_mastery_is_mastered_retention(monkeypatch):
    _patch_graph(monkeypatch, mastery=0.90, prereqs={}, last_reviewed=_iso_days_ago(STALE_REVIEW_DAYS + 5))
    _patch_no_recent_attempts(monkeypatch)
    state = diagnose_tutor_state("s1", "some_concept", "Domain")
    assert state.mode == MODE_MASTERED_RETENTION
    assert state.days_since_review > STALE_REVIEW_DAYS

    strategy = choose_teaching_strategy(state)
    assert strategy.question_difficulty == "hard"


# ---------------------------------------------------------------------------
# Recent performance modifiers
# ---------------------------------------------------------------------------

def test_recent_failure_pulls_strong_down_to_developing(monkeypatch):
    _patch_graph(monkeypatch, mastery=0.90, prereqs={}, last_reviewed=_iso_days_ago(1))
    _patch_recent_attempts(monkeypatch, [{
        "concept_id": "some_concept", "passed": False, "percentage": 40.0,
        "timestamp": "2026-01-01T00:00:00+00:00",
    }])
    state = diagnose_tutor_state("s1", "some_concept", "Domain")
    assert state.recent_failure is True
    assert state.mode == MODE_DEVELOPING  # pulled down from strong
    assert any("did not pass" in r for r in state.reasons)


def test_strong_recent_performance_keeps_strong_mode(monkeypatch):
    _patch_graph(monkeypatch, mastery=0.90, prereqs={}, last_reviewed=_iso_days_ago(1))
    _patch_recent_attempts(monkeypatch, [{
        "concept_id": "some_concept", "passed": True, "percentage": 95.0,
        "timestamp": "2026-01-01T00:00:00+00:00",
    }])
    state = diagnose_tutor_state("s1", "some_concept", "Domain")
    assert state.recent_failure is False
    assert state.mode == MODE_STRONG


# ---------------------------------------------------------------------------
# Prerequisite adaptation
# ---------------------------------------------------------------------------

def test_weak_prerequisite_is_surfaced_when_real(monkeypatch):
    _patch_graph(monkeypatch, mastery=0.70, prereqs={"foundations": 0.30}, last_reviewed=None)
    _patch_no_recent_attempts(monkeypatch)
    state = diagnose_tutor_state("s1", "concept_b", "Domain")
    assert state.weak_prerequisite == "foundations"
    assert any("foundations" in r.lower() or "Foundations" in r for r in state.reasons)


def test_no_weak_prerequisite_when_all_prereqs_strong(monkeypatch):
    _patch_graph(monkeypatch, mastery=0.70, prereqs={"foundations": 0.95}, last_reviewed=None)
    _patch_no_recent_attempts(monkeypatch)
    state = diagnose_tutor_state("s1", "concept_b", "Domain")
    assert state.weak_prerequisite is None


# ---------------------------------------------------------------------------
# No fabricated reasoning
# ---------------------------------------------------------------------------

def test_diagnosis_reasons_reference_real_measured_values(monkeypatch):
    _patch_graph(monkeypatch, mastery=0.42, prereqs={}, last_reviewed=None)
    _patch_no_recent_attempts(monkeypatch)
    state = diagnose_tutor_state("s1", "some_concept", "Domain")
    # The exact mastery percentage must appear verbatim in the reasoning —
    # proof it's derived from the real value, not a generic template claim.
    assert any("42%" in r for r in state.reasons)


def test_tutor_state_is_immutable_dataclass():
    state = TutorState(
        student_id="s1", domain="D", concept_id="c", mastery=0.5, mode=MODE_DEVELOPING,
    )
    with pytest.raises(Exception):
        state.mastery = 0.9  # frozen dataclass — mutation must fail


# ---------------------------------------------------------------------------
# Mastery blending — LLM never assigns mastery directly
# ---------------------------------------------------------------------------

def test_evaluate_and_update_blends_not_overwrites(monkeypatch):
    import agents.adaptive_tutor_agent as ata

    class _FakeGraph:
        def __init__(self, student_id):
            self.updated_with = None

        def get_mastery(self, concept_id):
            return 0.5  # prior mastery

        def update_mastery(self, concept_id, score):
            self.updated_with = score

    fake_graph_holder = {}

    def _fake_kg(student_id=""):
        g = _FakeGraph(student_id)
        fake_graph_holder["graph"] = g
        return g

    # multi_signal_grader.py does `from evaluation.semantic_auditor import
    # grade_response` at module load — that binds its OWN local name, so
    # patching evaluation.semantic_auditor.grade_response afterward would
    # NOT affect it. Must patch the name where it's actually looked up.
    monkeypatch.setattr("memory.graph_engine.KnowledgeGraph", _fake_kg)
    monkeypatch.setattr("evaluation.multi_signal_grader.grade_response", lambda a, b: 1.0)
    monkeypatch.setattr("evaluation.event_log.log_event", lambda *a, **k: None)

    agent = _bare_agent()
    agent._judge = None  # exercise the degrade-to-semantic-only path deterministically
    result = agent.evaluate_and_update("s1", "c1", "D", "Some question?", "reference answer", "a matching answer")

    expected = (1 - MASTERY_BLEND_WEIGHT_NEW) * 0.5 + MASTERY_BLEND_WEIGHT_NEW * 1.0
    assert result["mastery_before"] == 0.5
    assert abs(result["mastery_after"] - expected) < 1e-9
    assert abs(fake_graph_holder["graph"].updated_with - expected) < 1e-9
    assert result["passed"] is True


def test_evaluate_and_update_empty_answer_scores_zero(monkeypatch):
    class _FakeGraph:
        def get_mastery(self, concept_id):
            return 0.8

        def update_mastery(self, concept_id, score):
            pass

    monkeypatch.setattr("memory.graph_engine.KnowledgeGraph", lambda student_id="": _FakeGraph())
    monkeypatch.setattr("evaluation.event_log.log_event", lambda *a, **k: None)

    agent = _bare_agent()
    agent._judge = None
    result = agent.evaluate_and_update("s1", "c1", "D", "Some question?", "reference", "")
    assert result["similarity"] == 0.0
    assert result["passed"] is False


# ---------------------------------------------------------------------------
# Sovereignty
# ---------------------------------------------------------------------------

def test_sovereignty_blocks_non_local_endpoint(monkeypatch):
    import agents.adaptive_tutor_agent as ata

    monkeypatch.setattr(ata, "OLLAMA_BASE_URL", "https://api.external-host.example.com")
    with pytest.raises(SovereigntyError):
        ata.AdaptiveTutorAgent()


def test_sovereignty_allows_localhost(monkeypatch):
    import agents.adaptive_tutor_agent as ata

    monkeypatch.setattr(ata, "OLLAMA_BASE_URL", "http://localhost:11434")
    agent = ata.AdaptiveTutorAgent()  # lazy ChatOllama — no network call at construction
    assert agent is not None


# ---------------------------------------------------------------------------
# Failure handling — no external fallback
# ---------------------------------------------------------------------------

def test_question_generation_falls_back_gracefully_on_llm_failure():
    from agents.adaptive_tutor_agent import TeachingStrategy

    agent = _bare_agent()

    class _BrokenLLM:
        def invoke(self, *_a, **_k):
            raise ConnectionError("Ollama down")

    agent._llm = _BrokenLLM()
    strategy = TeachingStrategy(
        mode_label="Guided Practice", explanation_depth="standard", example_style="guided",
        question_difficulty="medium", hints_enabled=True, review_prerequisite=None,
        objective="test",
    )
    result = agent.generate_question("some_concept", "Domain", strategy)
    # Guaranteed fallback — never raises, always returns a usable question.
    assert result["question"]
    assert result["correct_answer"]


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

def test_page_tutor_imports_successfully():
    from dashboard.page_tutor import page_tutor
    assert callable(page_tutor)


def test_page_tutor_registered_in_router():
    import dashboard.app as app_module
    assert "tutor" in app_module._PAGES
    assert app_module._PAGES["tutor"].__name__ == "page_tutor"


def test_page_tutor_renders_headlessly_without_active_concept():
    from streamlit.testing.v1 import AppTest

    def _run():
        import streamlit as st
        st.session_state["student_id"] = "test_student_no_concept"
        st.session_state["student_name"] = "Test"
        from dashboard.page_tutor import page_tutor
        page_tutor()

    at = AppTest.from_function(_run)
    at.run(timeout=60)
    assert not at.exception


def test_page_home_and_ask_still_render_after_phase8():
    """Regression check: Phase 8 didn't touch Phase 6/7 pages — confirm both
    still render cleanly.
    """
    from streamlit.testing.v1 import AppTest

    def _run_home():
        import streamlit as st
        st.session_state["student_id"] = "699c235c-3ce7-4a43-b391-ea04b6559579"
        st.session_state["student_name"] = "Test Student"
        from dashboard.page_home import page_home
        page_home()

    def _run_ask():
        import streamlit as st
        st.session_state["student_id"] = "699c235c-3ce7-4a43-b391-ea04b6559579"
        st.session_state["student_name"] = "Test Student"
        from dashboard.page_ask import page_ask
        page_ask()

    at_home = AppTest.from_function(_run_home)
    at_home.run(timeout=60)
    assert not at_home.exception

    at_ask = AppTest.from_function(_run_ask)
    at_ask.run(timeout=60)
    assert not at_ask.exception


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

def _iso_days_ago(days: int) -> str:
    from datetime import datetime, timedelta, timezone
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def _patch_graph(monkeypatch, mastery, prereqs, last_reviewed):
    """prereqs: dict[prereq_concept_id, mastery]"""
    class _FakeGraph:
        def __init__(self, student_id=""):
            pass

        def get_mastery(self, concept_id):
            if concept_id in prereqs:
                return prereqs[concept_id]
            return mastery

        def get_graph_data(self):
            node = {"id": "some_concept", "last_reviewed": last_reviewed} if last_reviewed else {"id": "some_concept"}
            return {"nodes": [node], "edges": []}

        def get_prerequisites(self, concept_id):
            return list(prereqs.keys())

    monkeypatch.setattr("memory.graph_engine.KnowledgeGraph", _FakeGraph)
    monkeypatch.setattr("memory.graph_engine.MASTERY_THRESHOLD", 0.85)


def _patch_no_recent_attempts(monkeypatch):
    monkeypatch.setattr("evaluation.event_log.read_events", lambda **kwargs: [])


def _patch_recent_attempts(monkeypatch, attempts):
    monkeypatch.setattr("evaluation.event_log.read_events", lambda **kwargs: attempts)
