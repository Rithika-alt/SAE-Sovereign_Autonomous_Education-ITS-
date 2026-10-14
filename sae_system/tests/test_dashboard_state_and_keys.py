"""Regression tests for the two Streamlit duplicate-element-key crashes (B1, B2)
and for the session-defaults factory introduced to fix B1.

B1: pages did ``from dashboard.app import _SS_DEFAULTS``. Streamlit runs app.py
as the main script, not as ``dashboard.app``, so that import executed the whole
app a second time in the same run -> render_sidebar() twice -> duplicate key
``nav_home``.
B2: Ask SAE rendered every answer's "Continue this lesson" button with one
fixed key, and renders the latest answer plus all earlier ones in a single run.
"""

import ast
import time
from pathlib import Path

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from dashboard.state import make_session_defaults

DASHBOARD = Path(__file__).resolve().parent.parent / "dashboard"

EXPECTED_KEYS = {
    "page", "prev_page", "auth_token", "student_id", "student_name", "student_email",
    "student_username", "domain", "session_start", "roadmap", "current_module_idx",
    "current_concept_idx", "lesson", "lesson_section", "video_path", "video_ready", "questions",
    "grade_result", "modules_passed", "modules_unlocked", "module_progress", "test_phase",
    "test_answers", "test_q_index", "question_start_time", "test_grade_result", "test_terminated",
    "proctor", "certificate_path", "social_token", "social_id", "social_display_name",
}


# ---------------------------------------------------------------- B1: no page re-executes app.py

def _imports_dashboard_app(path: Path) -> list:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    bad = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "dashboard.app":
            bad.append(node.lineno)
        elif isinstance(node, ast.ImportFrom) and node.module == "dashboard" and any(a.name == "app" for a in node.names):
            bad.append(node.lineno)
        elif isinstance(node, ast.Import) and any(a.name == "dashboard.app" for a in node.names):
            bad.append(node.lineno)
    return bad


@pytest.mark.parametrize("path", sorted(p for p in DASHBOARD.glob("*.py") if p.name != "app.py"), ids=lambda p: p.name)
def test_no_dashboard_module_imports_dashboard_app(path):
    assert _imports_dashboard_app(path) == [], (
        f"{path.name} imports dashboard.app — under Streamlit that re-executes the whole app "
        "(duplicate nav_* keys). Import from dashboard.state instead."
    )


def test_state_module_has_no_streamlit_dependency():
    tree = ast.parse((DASHBOARD / "state.py").read_text(encoding="utf-8"))
    imported = {n.module if isinstance(n, ast.ImportFrom) else a.name
                for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))
                for a in (n.names if isinstance(n, ast.Import) else [n])}
    assert not any(str(m).startswith("streamlit") for m in imported if m)


# ---------------------------------------------------------------- the defaults factory

def test_defaults_have_exactly_the_original_keys():
    assert set(make_session_defaults()) == EXPECTED_KEYS


def test_defaults_are_fresh_objects_every_call_so_sessions_never_share_state():
    a, b = make_session_defaults(), make_session_defaults()
    for key in ("modules_passed", "modules_unlocked", "module_progress", "test_answers"):
        assert a[key] is not b[key]
    a["modules_passed"].add("student-A-progress")
    a["test_answers"]["q1"] = "x"
    assert b["modules_passed"] == set() and b["test_answers"] == {}


def test_question_start_time_is_not_frozen_at_import():
    first = make_session_defaults()["question_start_time"]
    time.sleep(0.02)
    assert make_session_defaults()["question_start_time"] > first


def test_default_values_unchanged():
    d = make_session_defaults()
    assert d["page"] == "domain_select" and d["prev_page"] == "domain_select"
    assert d["modules_passed"] == set() and d["module_progress"] == {} and d["test_phase"] is None
    assert d["test_terminated"] is False and d["social_token"] == ""


# ---------------------------------------------------------------- B1: the exact path that crashed

@pytest.mark.parametrize("module_name", ["page_tutor", "page_ask", "page_canvas", "page_activity"])
def test_jump_to_lesson_resets_test_state_without_importing_the_app(module_name, monkeypatch):
    import importlib

    mod = importlib.import_module(f"dashboard.{module_name}")
    monkeypatch.setattr(st, "rerun", lambda: None)
    ss = {
        "roadmap": {"modules": [{"module_id": "supervised_learning"}, {"module_id": "deep_learning"}]},
        "domain": "Machine Learning",
        "test_answers": {"q1": "stale"}, "test_phase": "running", "test_q_index": 7, "proctor": object(),
    }
    mod._jump_to_lesson(ss, "deep_learning", "Machine Learning")
    assert ss["page"] == "loading_lesson" and ss["current_module_idx"] == 1
    assert ss["test_answers"] == {} and ss["test_phase"] is None
    assert ss["test_q_index"] == 0 and ss["proctor"] is None and ss["test_terminated"] is False


# ---------------------------------------------------------------- B2: unique answer-button keys

def _answers_app():
    import streamlit as st
    from dashboard import page_ask

    result = {"answer": "a", "grounded": False, "sources": [], "mastery": None,
              "suggested_action": {"label": "Continue this lesson", "concept_id": "c", "domain": "d"}}
    page_ask._render_answer(st.session_state, result, key_suffix="latest")
    page_ask._render_answer(st.session_state, result, key_suffix="h1")
    page_ask._render_answer(st.session_state, result, key_suffix="h2")


def _same_key_twice_app():
    import streamlit as st
    from dashboard import page_ask

    result = {"answer": "a", "grounded": False, "sources": [], "mastery": None,
              "suggested_action": {"label": "Continue this lesson", "concept_id": "c", "domain": "d"}}
    page_ask._render_answer(st.session_state, result)
    page_ask._render_answer(st.session_state, result)


def test_multiple_answers_with_actions_render_without_duplicate_keys():
    at = AppTest.from_function(_answers_app, default_timeout=120).run()
    assert not at.exception, [e.value for e in at.exception]
    assert len(at.button) == 3
    keys = [b.key for b in at.button]
    assert len(set(keys)) == 3 and all(k.startswith("ask_sae_continue_lesson_") for k in keys)


def test_reusing_one_key_still_raises_proving_the_test_can_fail():
    at = AppTest.from_function(_same_key_twice_app, default_timeout=120).run()
    assert at.exception and "DuplicateElementKey" in str(at.exception[0].value) + str(at.exception[0])
