"""Pytest tests for evaluation.learning_canvas (Phase 10).

Pure data-model tests — no Streamlit/Plotly involved (that's the point of
separating the view model from rendering, Step 22).
"""

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from evaluation.learning_canvas import (
    STATUS_AVAILABLE, STATUS_DEVELOPING, STATUS_LOCKED, STATUS_MASTERED, STATUS_WEAK,
    _node_status, build_learning_canvas, get_concept_detail,
)


# ---------------------------------------------------------------------------
# Status derivation — reuses config.SEMANTIC_PASS_THRESHOLD / MASTERY_THRESHOLD,
# not a second classification system (Hard Rule 3).
# ---------------------------------------------------------------------------

def test_status_mastered_at_or_above_mastery_threshold():
    from memory.graph_engine import MASTERY_THRESHOLD
    assert _node_status(MASTERY_THRESHOLD, True) == STATUS_MASTERED
    assert _node_status(1.0, True) == STATUS_MASTERED


def test_status_developing_between_pass_and_mastery_threshold():
    from config import SEMANTIC_PASS_THRESHOLD
    from memory.graph_engine import MASTERY_THRESHOLD
    midpoint = (SEMANTIC_PASS_THRESHOLD + MASTERY_THRESHOLD) / 2
    assert _node_status(midpoint, True) == STATUS_DEVELOPING


def test_status_weak_below_pass_threshold_but_nonzero():
    from config import SEMANTIC_PASS_THRESHOLD
    assert _node_status(SEMANTIC_PASS_THRESHOLD / 2, True) == STATUS_WEAK


def test_status_available_when_zero_mastery_and_prereqs_met():
    assert _node_status(0.0, True) == STATUS_AVAILABLE


def test_status_locked_when_zero_mastery_and_prereqs_not_met():
    assert _node_status(0.0, False) == STATUS_LOCKED


# ---------------------------------------------------------------------------
# build_learning_canvas — correctness against real repo data
# ---------------------------------------------------------------------------

_REAL_STUDENT = "699c235c-3ce7-4a43-b391-ea04b6559579"
_REAL_DOMAIN = "Machine Learning"


def test_canvas_nodes_all_exist_in_knowledge_graph():
    from memory.graph_engine import KnowledgeGraph
    canvas = build_learning_canvas(_REAL_STUDENT, _REAL_DOMAIN)
    graph = KnowledgeGraph(student_id=_REAL_STUDENT)
    real_ids = {n["id"] for n in graph.get_graph_data_by_domain(_REAL_DOMAIN)["nodes"]}
    canvas_ids = {n["id"] for n in canvas["nodes"]}
    assert canvas_ids == real_ids
    assert canvas_ids, "expected the real fixture data to be non-empty"


def test_canvas_edges_all_exist_in_knowledge_graph():
    from memory.graph_engine import KnowledgeGraph
    canvas = build_learning_canvas(_REAL_STUDENT, _REAL_DOMAIN)
    graph = KnowledgeGraph(student_id=_REAL_STUDENT)
    real_edges = {(e["source"], e["target"]) for e in graph.get_graph_data_by_domain(_REAL_DOMAIN)["edges"]}
    canvas_edges = {(e["source"], e["target"]) for e in canvas["edges"]}
    assert canvas_edges == real_edges


def test_canvas_mastery_matches_stored_progress():
    from memory.graph_engine import KnowledgeGraph
    canvas = build_learning_canvas(_REAL_STUDENT, _REAL_DOMAIN)
    graph = KnowledgeGraph(student_id=_REAL_STUDENT)
    for node in canvas["nodes"]:
        assert node["mastery"] == graph.get_mastery(node["id"])


def test_canvas_current_concept_matches_passed_argument():
    canvas = build_learning_canvas(_REAL_STUDENT, _REAL_DOMAIN, current_module_id="supervised_learning")
    assert canvas["current_concept_id"] == "supervised_learning"
    current_nodes = [n for n in canvas["nodes"] if n["is_current"]]
    assert len(current_nodes) == 1
    assert current_nodes[0]["id"] == "supervised_learning"


def test_canvas_domain_isolation():
    """Only the requested domain's nodes appear — no cross-domain leakage."""
    canvas = build_learning_canvas(_REAL_STUDENT, _REAL_DOMAIN)
    for node in canvas["nodes"]:
        assert node["domain"] == _REAL_DOMAIN


def test_canvas_recommendations_come_from_recommendation_engine_not_reinvented():
    """Cross-check: every recommendation the canvas surfaces is also
    produced by the standalone recommendation_engine — no second algorithm.
    """
    from evaluation.recommendation_engine import recommend_next_actions
    canvas = build_learning_canvas(_REAL_STUDENT, _REAL_DOMAIN, current_module_id="supervised_learning")
    direct = recommend_next_actions(_REAL_STUDENT, max_recommendations=3)
    direct_ids = {(r.get("action"), r.get("concept_id")) for r in direct}
    for rec in canvas["recommendations"]:
        assert (rec.get("action"), rec.get("concept_id")) in direct_ids


# ---------------------------------------------------------------------------
# Missing/empty data — graceful handling
# ---------------------------------------------------------------------------

def test_canvas_empty_for_student_with_no_progress():
    canvas = build_learning_canvas("nonexistent_student_xyz_canvas_test", _REAL_DOMAIN)
    assert canvas["insufficient_data"] is True
    assert canvas["nodes"] == []
    assert canvas["edges"] == []
    assert canvas["top_recommendation"] is None


def test_canvas_empty_domain_string():
    canvas = build_learning_canvas("nonexistent_student_xyz_canvas_test", "")
    assert canvas["insufficient_data"] is True


def test_canvas_no_current_module_id_still_builds():
    canvas = build_learning_canvas(_REAL_STUDENT, _REAL_DOMAIN)  # no current_module_id passed
    assert canvas["insufficient_data"] is False
    assert canvas["current_concept_id"] is None
    assert all(not n["is_current"] for n in canvas["nodes"])


# ---------------------------------------------------------------------------
# get_concept_detail
# ---------------------------------------------------------------------------

def test_get_concept_detail_returns_none_for_unknown_concept():
    canvas = build_learning_canvas(_REAL_STUDENT, _REAL_DOMAIN)
    assert get_concept_detail(canvas, "definitely_not_a_real_concept_id") is None


def test_get_concept_detail_includes_prerequisite_details():
    canvas = build_learning_canvas(_REAL_STUDENT, _REAL_DOMAIN, current_module_id="supervised_learning")
    detail = get_concept_detail(canvas, "supervised_learning")
    assert detail is not None
    assert detail["is_current"] is True
    assert isinstance(detail["prerequisite_details"], list)
    for p in detail["prerequisite_details"]:
        assert set(p.keys()) == {"id", "label", "status", "mastery"}


# ---------------------------------------------------------------------------
# Dashboard — imports, registration, headless render, routing
# (routing tested directly, not via simulated click — Step 24: AppTest
# button clicks that call st.rerun() are a known harness hang, per Phase 6.)
# ---------------------------------------------------------------------------

def test_page_canvas_imports_successfully():
    from dashboard.page_canvas import page_canvas
    assert callable(page_canvas)


def test_page_canvas_is_hidden_from_router_and_nav_but_its_code_remains():
    # The Learning Canvas page was hidden from the sidebar/router (code kept).
    import dashboard.app as app_module
    assert "canvas" not in app_module._PAGES
    assert "canvas" in app_module._HIDDEN_PAGE_IDS
    from dashboard.page_canvas import page_canvas   # module still importable
    assert callable(page_canvas)


def test_go_to_adaptive_tutor_sets_focus_and_navigates(monkeypatch):
    import streamlit as st
    from dashboard.page_canvas import _go_to_adaptive_tutor

    class _RerunSentinel(Exception):
        pass

    def _fake_rerun():
        raise _RerunSentinel()

    monkeypatch.setattr(st, "rerun", _fake_rerun)

    ss = {}
    try:
        _go_to_adaptive_tutor(ss, "classification_algorithms")
    except _RerunSentinel:
        pass
    assert ss["tutor_focus_concept_id"] == "classification_algorithms"
    assert ss["page"] == "tutor"


def test_go_to_ask_sae_sets_module_index_and_navigates(monkeypatch):
    import streamlit as st
    from dashboard.page_canvas import _go_to_ask_sae

    class _RerunSentinel(Exception):
        pass

    def _fake_rerun():
        raise _RerunSentinel()

    monkeypatch.setattr(st, "rerun", _fake_rerun)

    ss = {"roadmap": {"modules": [{"module_id": "classification_algorithms"}, {"module_id": "other"}]}}
    try:
        _go_to_ask_sae(ss, "classification_algorithms")
    except _RerunSentinel:
        pass
    assert ss["current_module_idx"] == 0
    assert ss["page"] == "ask"


def test_page_canvas_renders_headlessly_with_real_data():
    from streamlit.testing.v1 import AppTest

    def _run():
        import streamlit as st
        # AppTest.from_function execs only this function's own source, with
        # no access to the enclosing module's globals — module-level
        # constants like _REAL_STUDENT aren't visible here, so the values
        # are inlined (same gotcha caught and documented in Phase 7).
        st.session_state["student_id"] = "699c235c-3ce7-4a43-b391-ea04b6559579"
        st.session_state["student_name"] = "Test Student"
        st.session_state["domain"] = "Machine Learning"
        from dashboard.page_canvas import page_canvas
        page_canvas()

    at = AppTest.from_function(_run)
    at.run(timeout=60)
    assert not at.exception


def test_page_canvas_renders_headlessly_with_no_domain_empty_state():
    from streamlit.testing.v1 import AppTest

    def _run():
        import streamlit as st
        st.session_state["student_id"] = "canvas_empty_state_test"
        st.session_state["student_name"] = "New Student"
        from dashboard.page_canvas import page_canvas
        page_canvas()

    at = AppTest.from_function(_run)
    at.run(timeout=60)
    assert not at.exception


def test_page_home_still_renders_after_phase10_changes():
    """Regression check: Phase 10 added a button to page_home.py."""
    from streamlit.testing.v1 import AppTest

    def _run():
        import streamlit as st
        st.session_state["student_id"] = "699c235c-3ce7-4a43-b391-ea04b6559579"
        st.session_state["student_name"] = "Test Student"
        from dashboard.page_home import page_home
        page_home()

    at = AppTest.from_function(_run)
    at.run(timeout=60)
    assert not at.exception
