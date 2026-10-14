"""Ask SAE's question box now lives on the Adaptive Tutor page, and the sidebar card is gone.

Runs the real app with the model stubbed (no Ollama): the tutor's explanation/question and the
Ask SAE answer are canned, so these tests are about wiring, keys and routing.
"""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import evaluation.event_log as event_log

APP = str(Path(__file__).resolve().parent.parent / "dashboard" / "app.py")
DOMAIN, MODULE = "Digital Marketing", "intro_module"
ROADMAP = {"domain": DOMAIN, "modules": [{"week": 1, "module_id": MODULE, "title": "Intro Module",
                                           "concepts": ["Customer Journey"], "prerequisites": []}]}
RESULT = {"answer": "The customer journey maps a buyer's path.", "grounded": True, "sources": ["Cached lesson"],
          "mastery": 0.4, "suggested_action": {"label": "Continue this lesson", "concept_id": MODULE, "domain": DOMAIN}}


@pytest.fixture
def stubbed(tmp_path, monkeypatch):
    from agents.adaptive_tutor_agent import AdaptiveTutorAgent
    from agents.ask_sae_agent import AskSAEAgent

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(event_log, "_LOG_PATH", tmp_path / "events.jsonl")
    monkeypatch.setattr(event_log, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(AdaptiveTutorAgent, "explain",
                        lambda self, c, d, s: {"sections_used": ["introduction"], "content": "stub explanation"})
    monkeypatch.setattr(AdaptiveTutorAgent, "generate_question",
                        lambda self, c, d, s: {"question": "Stub tutor question?", "correct_answer": "stub", "difficulty": "easy"})
    calls = []

    def ask(self, question, student_id="", concept_id="", domain=""):
        calls.append({"question": question, "concept_id": concept_id, "domain": domain})
        return dict(RESULT)

    monkeypatch.setattr(AskSAEAgent, "ask", ask)
    return calls


def page(name, **state):
    at = AppTest.from_file(APP, default_timeout=180)
    base = dict(student_id="ask-tutor-test", student_name="Ask Tutor", domain=DOMAIN, roadmap=ROADMAP,
                modules_unlocked={MODULE}, current_module_idx=0, page=name)
    for k, v in {**base, **state}.items():
        at.session_state[k] = v
    return at.run()


def labels(at):
    return [b.label for b in at.button]


def md(at):
    return " ".join(m.value for m in at.markdown)


# ---------------------------------------------------------------- the box on the tutor page

def test_the_tutor_page_has_an_ask_a_question_box_beneath_the_tutor(stubbed):
    at = page("tutor")
    assert not at.exception, [str(e.value) for e in at.exception]
    assert "Stub tutor question?" in md(at)                                   # the tutor itself is unchanged
    assert at.text_area(key="tutor_answer_input") is not None
    assert at.text_area(key="tutor_ask_question_input") is not None
    assert "Ask a question" in md(at) and "Ask" in labels(at)


def test_the_ask_box_comes_after_the_tutor_controls(stubbed):
    at = page("tutor")
    keys = [t.key for t in at.text_area]
    assert keys.index("tutor_answer_input") < keys.index("tutor_ask_question_input")
    assert labels(at).index("Submit Answer") < labels(at).index("Ask")


def test_asking_a_question_answers_from_the_current_concept_without_disturbing_the_tutor(stubbed):
    at = page("tutor")
    at.text_area(key="tutor_ask_question_input").set_value("What is a customer journey?")
    next(b for b in at.button if b.label == "Ask").click().run()
    assert not at.exception, [str(e.value) for e in at.exception]
    assert stubbed == [{"question": "What is a customer journey?", "concept_id": MODULE, "domain": DOMAIN}]
    assert "The customer journey maps a buyer's path." in md(at)
    assert "What is a customer journey?" in md(at)
    assert "Stub tutor question?" in md(at)                                   # tutor question still shown, not reloaded
    assert len(at.session_state["ask_sae_history"]) == 1


def test_an_empty_question_shows_a_warning_and_calls_nothing(stubbed):
    at = page("tutor")
    next(b for b in at.button if b.label == "Ask").click().run()
    assert [w for w in at.warning if "enter a question" in w.value]
    assert stubbed == []


def test_there_is_only_one_continue_this_lesson_button_even_with_answered_questions(stubbed):
    history = [{"question": f"q{i}", "result": dict(RESULT), "timestamp": f"10:0{i}"} for i in range(3)]
    at = page("tutor", ask_sae_history=history)
    assert not at.exception, [str(e.value) for e in at.exception]
    assert labels(at).count("📖 Continue this lesson") == 1                  # the tutor's own; the panel's is hidden
    assert not any("ask_sae_continue_lesson" in (b.key or "") or "tutor_ask_continue_lesson" in (b.key or "") for b in at.button)


def test_panel_widget_keys_are_namespaced_so_two_panels_can_share_a_page():
    def both():
        import streamlit as st
        from dashboard.page_ask import render_ask_panel
        render_ask_panel(st.session_state, "c", "d", key_prefix="tutor_ask", show_action=False)
        render_ask_panel(st.session_state, "c", "d")                            # default prefix, as on the old page

    at = AppTest.from_function(both, default_timeout=120).run()
    assert not at.exception, [str(e.value) for e in at.exception]
    assert {t.key for t in at.text_area} == {"tutor_ask_question_input", "ask_sae_question_input"}


def test_the_old_ask_page_function_still_works_with_its_original_keys(stubbed):
    def old_page():
        from dashboard.page_ask import page_ask
        page_ask()

    at = AppTest.from_function(old_page, default_timeout=120).run()
    assert not at.exception, [str(e.value) for e in at.exception]
    assert at.text_area(key="ask_sae_question_input") is not None


# ---------------------------------------------------------------- sidebar and routing

def test_the_sidebar_no_longer_has_an_ask_sae_card(stubbed):
    at = page("home")
    nav = [b.label for b in at.sidebar.button]
    assert nav == ["Home", "Roadmap", "Adaptive Tutor", "Knowledge Graph", "Log Out"]
    assert not any("Ask" in label for label in nav)


def test_a_session_still_on_the_old_ask_page_lands_on_the_tutor_page(stubbed):
    at = page("ask")
    assert not at.exception, [str(e.value) for e in at.exception]
    assert at.session_state["page"] == "tutor"
    assert at.text_area(key="tutor_ask_question_input") is not None


def test_home_has_an_ask_a_question_button_that_opens_the_tutor_page(stubbed):
    at = page("home")
    assert not any("Ask SAE a question" in label for label in labels(at))
    next(b for b in at.button if b.label == "💬 Ask a question").click().run()
    assert at.session_state["page"] == "tutor" and not at.exception, [str(e.value) for e in at.exception]
