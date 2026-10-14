"""Pytest tests for agents.ask_sae_agent and dashboard.page_ask (Phase 7).

Validation/context/sovereignty tests never require a live Ollama server —
they either bypass __init__ (object.__new__) or monkeypatch the LLM call.
Dashboard render tests use Streamlit's AppTest and don't submit a question
(that path requires live Ollama and is verified manually, matching the
existing test_ollama_generation.py convention of keeping live-Ollama tests
separate from the fast suite).
"""

import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import pytest

from agents.ask_sae_agent import AskSAEAgent, MAX_QUESTION_CHARS, gather_context
from agents.tutor_agent import SovereigntyError


def _bare_agent() -> AskSAEAgent:
    """An AskSAEAgent with __init__ (and its sovereignty check / ChatOllama
    construction) skipped, for testing pure validation logic without Ollama.
    """
    return object.__new__(AskSAEAgent)


# ---------------------------------------------------------------------------
# Question validation
# ---------------------------------------------------------------------------

def test_empty_question_returns_error_not_answer():
    result = _bare_agent().ask("")
    assert result["answer"] is None
    assert result["error"]
    assert result["grounded"] is False
    assert result["sources"] == []


def test_whitespace_only_question_returns_error():
    result = _bare_agent().ask("   \n\t  ")
    assert result["error"]
    assert result["answer"] is None


def test_too_long_question_returns_error():
    result = _bare_agent().ask("x" * (MAX_QUESTION_CHARS + 1))
    assert result["error"]
    assert str(MAX_QUESTION_CHARS) in result["error"]
    assert result["answer"] is None


def test_question_at_exact_limit_does_not_fail_length_check():
    # Bare agent has no _llm, so this fails at the LLM call — but ask()
    # catches that broadly and returns a graceful error, not a raised
    # exception (see test_ollama_unavailable_returns_error_not_exception).
    # Asserting the error is NOT the "too long" message proves a
    # question of exactly MAX_QUESTION_CHARS clears the length check
    # (i.e. the boundary is inclusive, `>` not `>=`).
    result = _bare_agent().ask("x" * MAX_QUESTION_CHARS)
    assert result["error"] is not None
    assert "too long" not in result["error"].lower()


# ---------------------------------------------------------------------------
# Context gathering — never fabricates
# ---------------------------------------------------------------------------

def test_gather_context_is_honest_when_nothing_exists():
    context = gather_context(
        student_id="nonexistent_student_for_tests",
        concept_id="nonexistent_concept_xyz",
        domain="Nonexistent Domain",
    )
    assert context["grounded"] is False
    assert context["sources"] == []
    assert context["lesson"] is None
    assert context["chroma_chunks"] == []


def test_gather_context_finds_cached_lesson(tmp_path, monkeypatch):
    """Hermetic: writes a fake lesson cache file, doesn't depend on the
    repo's real data/lessons/ contents.
    """
    import agents.ask_sae_agent as asa

    monkeypatch.setattr(asa, "_LESSON_CACHE_DIR", tmp_path)
    fake_lesson = {
        "concept_id": "test_concept",
        "domain": "Test Domain",
        "introduction": "A test introduction with enough length to matter.",
        "theory": "Some test theory content.",
    }
    (tmp_path / "test_domain_test_concept.json").write_text(json.dumps(fake_lesson))

    context = gather_context(student_id="", concept_id="test_concept", domain="Test Domain")
    assert context["grounded"] is True
    assert context["lesson"] == fake_lesson
    assert any("test_concept" in s for s in context["sources"])


def test_no_fabricated_sources_when_ungrounded():
    context = gather_context(student_id="", concept_id="", domain="")
    assert context["grounded"] is False
    assert context["sources"] == []
    assert context["mastery"] is None


# ---------------------------------------------------------------------------
# Sovereignty
# ---------------------------------------------------------------------------

def test_sovereignty_blocks_non_local_ollama_endpoint(monkeypatch):
    import agents.ask_sae_agent as asa

    monkeypatch.setattr(asa, "OLLAMA_BASE_URL", "https://api.some-external-host.example.com")
    with pytest.raises(SovereigntyError):
        asa.AskSAEAgent()


def test_sovereignty_allows_localhost_endpoint(monkeypatch):
    import agents.ask_sae_agent as asa

    monkeypatch.setattr(asa, "OLLAMA_BASE_URL", "http://localhost:11434")
    agent = asa.AskSAEAgent()  # ChatOllama construction is lazy — no network call here
    assert agent is not None


# ---------------------------------------------------------------------------
# Failure handling — no silent fallback to a hosted provider
# ---------------------------------------------------------------------------

def test_ollama_unavailable_returns_error_not_exception(monkeypatch):
    import agents.ask_sae_agent as asa

    monkeypatch.setattr(asa, "OLLAMA_BASE_URL", "http://localhost:11434")
    agent = asa.AskSAEAgent()

    class _BrokenLLM:
        def invoke(self, *_args, **_kwargs):
            raise ConnectionError("Ollama is not running")

    agent._llm = _BrokenLLM()
    result = agent.ask("What is a variable?")
    assert result["error"] is not None
    assert result["answer"] is None
    assert "local" in result["error"].lower() or "ollama" in result["error"].lower()


def test_response_contract_always_has_expected_keys():
    result = _bare_agent().ask("")
    expected_keys = {
        "answer", "grounded", "sources", "concept_id",
        "domain", "mastery", "suggested_action", "error",
    }
    assert expected_keys.issubset(result.keys())


# ---------------------------------------------------------------------------
# Dashboard — imports, registration, headless render
# ---------------------------------------------------------------------------

def test_page_ask_imports_successfully():
    from dashboard.page_ask import page_ask
    assert callable(page_ask)


def test_page_ask_is_no_longer_routed_its_question_box_lives_on_the_tutor_page():
    import dashboard.app as app_module
    assert "ask" not in app_module._PAGES and "ask" in app_module._HIDDEN_PAGE_IDS
    from dashboard.page_ask import page_ask, render_ask_panel     # code kept, still importable
    assert callable(page_ask) and callable(render_ask_panel)


def test_page_ask_renders_headlessly_without_active_concept():
    from streamlit.testing.v1 import AppTest

    def _run():
        import streamlit as st
        st.session_state["student_id"] = "test_student_no_concept"
        st.session_state["student_name"] = "Test"
        from dashboard.page_ask import page_ask
        page_ask()

    at = AppTest.from_function(_run)
    at.run(timeout=60)
    assert not at.exception


def test_page_home_still_renders_after_phase7_changes():
    """Regression check: Phase 7 added a button to page_home.py — confirm
    it still renders cleanly (per Phase 7's 'do not break Phase 6' rule).
    """
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
