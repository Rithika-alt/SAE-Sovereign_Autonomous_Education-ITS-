"""Pytest tests for evaluation.multi_signal_grader and the extended grading
gold set (Phase 9).

Deterministic signal tests (coverage_score) and sovereignty/degrade-path
tests never require live Ollama. The LLM-judge-dependent tests are marked
and kept few in number, matching the established convention (Phase 7/8) of
keeping live-Ollama flows out of the always-fast suite.
"""

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import pytest

from agents.tutor_agent import SovereigntyError
from evaluation.grading_evaluator import load_gold_set
from evaluation.multi_signal_grader import LLMJudge, coverage_score, grade_multi_signal
from config import SEMANTIC_PASS_THRESHOLD


# ---------------------------------------------------------------------------
# Gold set integrity (Step 4 — deterministic, human-defined labels)
# ---------------------------------------------------------------------------

def test_gold_set_has_expanded_categories():
    gold = load_gold_set()["short_answer"]
    cases = {item["case"] for item in gold}
    assert "different_abstraction" in cases
    assert "hard_application_correct" in cases
    assert "hard_application_partial" in cases


def test_every_item_has_both_binary_and_3way_labels():
    gold = load_gold_set()["short_answer"]
    for item in gold:
        assert item["expected_label"] in ("pass", "fail"), item["id"]
        assert item["expected_label_3way"] in ("correct", "partial", "incorrect"), item["id"]


def test_phase8_scenario_b_case_is_labeled_partial_not_forced_pass():
    """The actual Phase 8 Scenario B answer is preserved verbatim (sa_048).
    It must NOT be relabeled 'correct' just because it was the original
    failure case — see Phase 9 Step 20's explicit warning against this.
    """
    gold = load_gold_set()["short_answer"]
    item = next(i for i in gold if i["id"] == "sa_048")
    assert item["expected_label_3way"] == "partial"
    assert item["expected_label"] == "fail"


# ---------------------------------------------------------------------------
# Coverage signal — deterministic, no Ollama
# ---------------------------------------------------------------------------

def test_coverage_identical_text_is_full():
    assert coverage_score("the cat sat on the mat", "the cat sat on the mat") == 1.0


def test_coverage_no_overlap_is_zero():
    assert coverage_score("bananas are yellow fruit", "quantum mechanics describes particles") == 0.0


def test_coverage_empty_student_answer_is_zero():
    assert coverage_score("", "some reference answer with real content") == 0.0


def test_coverage_empty_reference_is_zero():
    assert coverage_score("some student answer", "") == 0.0


def test_coverage_partial_overlap_between_zero_and_one():
    score = coverage_score(
        "supervised learning uses labeled data",
        "supervised learning trains models on labelled data to map inputs to outputs",
    )
    assert 0.0 < score < 1.0


# ---------------------------------------------------------------------------
# Sovereignty
# ---------------------------------------------------------------------------

def test_sovereignty_blocks_non_local_endpoint(monkeypatch):
    import evaluation.multi_signal_grader as msg

    monkeypatch.setattr(msg, "OLLAMA_BASE_URL", "https://api.external-host.example.com")
    with pytest.raises(SovereigntyError):
        msg.LLMJudge()


def test_sovereignty_allows_localhost(monkeypatch):
    import evaluation.multi_signal_grader as msg

    monkeypatch.setattr(msg, "OLLAMA_BASE_URL", "http://localhost:11434")
    judge = msg.LLMJudge()  # lazy ChatOllama — no network call at construction
    assert judge is not None


# ---------------------------------------------------------------------------
# Degrade path — judge unavailable never fabricates a verdict
# ---------------------------------------------------------------------------

def test_judge_returns_none_on_llm_failure():
    judge = object.__new__(LLMJudge)

    class _BrokenLLM:
        def invoke(self, *_a, **_k):
            raise ConnectionError("Ollama down")

    judge._llm = _BrokenLLM()
    result = judge.judge("What is X?", "some answer", "reference answer")
    assert result is None  # never a fabricated guess


def test_judge_returns_none_on_malformed_response():
    judge = object.__new__(LLMJudge)

    class _FakeResponse:
        content = "this is not JSON at all, just prose"

    class _FakeLLM:
        def invoke(self, *_a, **_k):
            return _FakeResponse()

    judge._llm = _FakeLLM()
    result = judge.judge("What is X?", "some answer", "reference answer")
    assert result is None


def test_grade_multi_signal_degrades_without_judge():
    """No judge supplied at all -> falls back to semantic+coverage rule,
    and says so honestly in `reason` rather than pretending a judge ran.
    """
    result = grade_multi_signal(
        question="What is supervised learning?",
        student_answer="Supervised learning trains a model on labelled data.",
        reference_answer="Supervised learning is training a model on labelled data to map inputs to outputs.",
        threshold=SEMANTIC_PASS_THRESHOLD,
        judge=None,
    )
    assert result["llm_judge"] is None
    assert "degraded" in result["reason"].lower()
    assert result["label"] in ("correct", "incorrect")  # no "partial" band without a judge


def test_grade_multi_signal_never_fabricates_judge_output():
    """When the judge fails mid-call, grade_multi_signal must reflect that
    (llm_judge=None), not silently invent a judge verdict.
    """
    class _AlwaysFailsJudge:
        def judge(self, *_a, **_k):
            return None

    result = grade_multi_signal(
        question="Q", student_answer="A", reference_answer="R",
        threshold=SEMANTIC_PASS_THRESHOLD, judge=_AlwaysFailsJudge(),
    )
    assert result["llm_judge"] is None
    assert "degraded" in result["reason"].lower()


# ---------------------------------------------------------------------------
# Edge cases (Step 17)
# ---------------------------------------------------------------------------

def test_grade_multi_signal_missing_student_answer():
    result = grade_multi_signal(
        question="Q", student_answer="", reference_answer="A real reference answer here.",
        threshold=SEMANTIC_PASS_THRESHOLD, judge=None,
    )
    assert result["semantic_score"] == 0.0
    assert result["coverage_score"] == 0.0
    assert result["label"] == "incorrect"


def test_grade_multi_signal_extremely_long_answer_does_not_crash():
    long_answer = "supervised learning " * 2000  # ~40,000 chars
    result = grade_multi_signal(
        question="What is supervised learning?",
        student_answer=long_answer,
        reference_answer="Supervised learning trains a model on labelled data.",
        threshold=SEMANTIC_PASS_THRESHOLD, judge=None,
    )
    assert result["label"] in ("correct", "incorrect")


def test_coverage_score_missing_metadata_is_safe():
    # No question/concept metadata at all — coverage_score only ever needs
    # the two answer strings, so missing "concept metadata" can't break it.
    assert coverage_score("anything", "anything") == 1.0
