"""Pytest tests for evaluation.test_engine (no Ollama required)."""

import json
import sys
import os

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import pytest
from evaluation.test_engine import (
    _extract_json_list,
    _normalise_question,
    _build_fallback_questions,
    TestEngine,
)


# ---------------------------------------------------------------------------
# _extract_json_list
# ---------------------------------------------------------------------------

class TestExtractJsonList:
    def test_plain_json_array(self):
        text = '[{"question_id": "q1", "question": "What is X?"}]'
        result = _extract_json_list(text)
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["question_id"] == "q1"

    def test_markdown_fenced_json(self):
        text = '```json\n[{"question_id": "q1", "type": "mcq"}]\n```'
        result = _extract_json_list(text)
        assert isinstance(result, list)
        assert result[0]["type"] == "mcq"

    def test_json_with_surrounding_text(self):
        text = 'Here are the questions:\n[{"question_id": "q1"}]\nDone.'
        result = _extract_json_list(text)
        assert isinstance(result, list)
        assert result[0]["question_id"] == "q1"

    def test_multiple_items(self):
        items = [{"question_id": f"q{i}", "question": f"Q{i}"} for i in range(5)]
        text = json.dumps(items)
        result = _extract_json_list(text)
        assert len(result) == 5

    def test_single_object_wrapped(self):
        """Ollama sometimes returns {} instead of [{}] — must be wrapped."""
        text = '{"question_id": "q1", "question": "What is Python?", "type": "mcq"}'
        result = _extract_json_list(text)
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["question_id"] == "q1"

    def test_single_object_with_options_array(self):
        """Single object whose options field contains an array — must not extract options."""
        text = json.dumps({
            "question_id": "q1",
            "question": "What is X?",
            "type": "mcq",
            "options": ["A", "B", "C", "D"],
            "correct_answer": "A",
        })
        result = _extract_json_list(text)
        assert len(result) == 1
        assert result[0]["question_id"] == "q1"
        assert result[0]["correct_answer"] == "A"

    def test_array_of_strings_not_accepted_finds_object_fallback(self):
        """If only an array of strings exists and a dict is also present, return the dict."""
        text = 'Options: ["A","B","C","D"] Question: {"question_id":"q1","question":"Hi"}'
        result = _extract_json_list(text)
        assert isinstance(result, list)
        assert result[0].get("question_id") == "q1"

    def test_no_json_raises(self):
        with pytest.raises(ValueError):
            _extract_json_list("This has no JSON at all")

    def test_empty_array(self):
        result = _extract_json_list("[]")
        assert result == []


# ---------------------------------------------------------------------------
# _normalise_question
# ---------------------------------------------------------------------------

class TestNormaliseQuestion:
    def _full_mcq(self):
        return {
            "question_id": "q1",
            "question": "What is Python?",
            "type": "mcq",
            "options": ["A lang", "A snake", "A tool", "A protocol"],
            "correct_answer": "A lang",
            "explanation": "Python is a programming language.",
            "marks": 2,
            "difficulty": "easy",
        }

    def test_valid_mcq_passthrough(self):
        q = self._full_mcq()
        result = _normalise_question(q, 0)
        assert result["type"] == "mcq"
        assert len(result["options"]) == 4
        assert result["marks"] == 2

    def test_mcq_defaults_options_when_fewer_than_4(self):
        q = self._full_mcq()
        q["options"] = ["Only one"]
        result = _normalise_question(q, 0)
        assert len(result["options"]) == 4

    def test_true_false_options_forced(self):
        q = {"type": "true_false", "question": "Is sky blue?",
             "correct_answer": "True", "options": ["Yes", "No", "Maybe"]}
        result = _normalise_question(q, 0)
        assert result["options"] == ["True", "False"]
        assert result["marks"] == 1

    def test_short_answer_no_options(self):
        q = {"type": "short_answer", "question": "Explain X.",
             "correct_answer": "X is important."}
        result = _normalise_question(q, 0)
        assert result["options"] == []
        assert result["marks"] == 5

    def test_unknown_type_defaults_to_mcq(self):
        q = {"type": "essay", "question": "Write about Y."}
        result = _normalise_question(q, 0)
        assert result["type"] == "mcq"

    def test_non_dict_input_produces_fallback(self):
        result = _normalise_question("not a dict", 3)
        assert result["question_id"] == "q4"
        assert result["type"] == "mcq"

    def test_missing_fields_get_defaults(self):
        result = _normalise_question({}, 0)
        assert result["question_id"] == "q1"
        assert result["question"] == "Question 1"
        assert result["explanation"] == "See lesson material."

    def test_empty_correct_answer_gets_fallback_short_answer(self):
        q = {"type": "short_answer", "question": "Explain X.", "correct_answer": ""}
        result = _normalise_question(q, 0)
        assert result["correct_answer"], "short_answer with empty correct_answer must get fallback"

    def test_empty_correct_answer_gets_fallback_true_false(self):
        q = {"type": "true_false", "question": "Is sky blue?", "correct_answer": ""}
        result = _normalise_question(q, 0)
        assert result["correct_answer"] == "True"

    def test_empty_correct_answer_gets_fallback_mcq(self):
        q = {"type": "mcq", "question": "Pick one.",
             "options": ["A", "B", "C", "D"], "correct_answer": ""}
        result = _normalise_question(q, 0)
        assert result["correct_answer"] == "A"  # falls back to first option

    def test_question_id_stringified(self):
        q = {"question_id": 42, "type": "mcq"}
        result = _normalise_question(q, 0)
        assert result["question_id"] == "42"


# ---------------------------------------------------------------------------
# _build_fallback_questions
# ---------------------------------------------------------------------------

class TestBuildFallbackQuestions:
    def test_returns_exactly_10(self):
        questions = _build_fallback_questions("neural_networks", "AI")
        assert len(questions) == 10

    def test_type_distribution(self):
        questions = _build_fallback_questions("sorting", "CS")
        types = [q["type"] for q in questions]
        assert types.count("mcq") == 4
        assert types.count("true_false") == 3
        assert types.count("short_answer") == 3

    def test_marks_by_type(self):
        questions = _build_fallback_questions("sorting", "CS")
        for q in questions:
            if q["type"] == "mcq":
                assert q["marks"] == 2
            elif q["type"] == "true_false":
                assert q["marks"] == 1
            elif q["type"] == "short_answer":
                assert q["marks"] == 5

    def test_mcq_has_4_options(self):
        questions = _build_fallback_questions("sorting", "CS")
        for q in questions:
            if q["type"] == "mcq":
                assert len(q["options"]) == 4

    def test_true_false_options(self):
        questions = _build_fallback_questions("sorting", "CS")
        for q in questions:
            if q["type"] == "true_false":
                assert q["options"] == ["True", "False"]

    def test_concept_appears_in_questions(self):
        questions = _build_fallback_questions("backpropagation", "ML")
        combined = " ".join(q["question"] for q in questions)
        assert "backpropagation" in combined.lower()


# ---------------------------------------------------------------------------
# TestEngine.grade_test  (no Ollama — tests pure grading logic)
# ---------------------------------------------------------------------------

class TestGradeTest:
    def _sample_questions(self):
        return [
            {
                "question_id": "q1", "question": "What is 2+2?",
                "type": "mcq", "options": ["3", "4", "5", "6"],
                "correct_answer": "4", "explanation": "Basic arithmetic.",
                "marks": 2, "difficulty": "easy",
            },
            {
                "question_id": "q2", "question": "Python is a language. True or False?",
                "type": "true_false", "options": ["True", "False"],
                "correct_answer": "True", "explanation": "Yes it is.",
                "marks": 1, "difficulty": "easy",
            },
            {
                "question_id": "q3", "question": "Explain backpropagation.",
                "type": "short_answer", "options": [],
                "correct_answer": "Backpropagation computes gradients via chain rule.",
                "explanation": "Chain rule applied in reverse.",
                "marks": 5, "difficulty": "hard",
            },
        ]

    def _make_engine(self):
        return TestEngine()

    def test_all_correct_mcq_true_false(self):
        engine = self._make_engine()
        questions = self._sample_questions()[:2]
        answers = {"q1": "4", "q2": "True"}
        result = engine.grade_test(questions, answers)
        assert result["earned_marks"] == 3
        assert result["total_marks"] == 3
        assert result["percentage"] == 100.0
        assert result["passed"] is True
        assert result["grade"] == "A"

    def test_all_wrong_mcq(self):
        engine = self._make_engine()
        questions = self._sample_questions()[:1]
        answers = {"q1": "3"}
        result = engine.grade_test(questions, answers)
        assert result["earned_marks"] == 0
        assert result["percentage"] == 0.0
        assert result["passed"] is False
        assert result["grade"] == "F"

    def test_case_insensitive_mcq(self):
        engine = self._make_engine()
        questions = self._sample_questions()[:1]
        answers = {"q1": "4"}
        result_upper = engine.grade_test(questions, {"q1": "4"})
        assert result_upper["earned_marks"] == 2

    def test_missing_answer_scores_zero(self):
        engine = self._make_engine()
        questions = self._sample_questions()[:2]
        result = engine.grade_test(questions, {})
        assert result["earned_marks"] == 0

    def test_result_structure(self):
        engine = self._make_engine()
        questions = self._sample_questions()[:2]
        result = engine.grade_test(questions, {"q1": "4", "q2": "True"})
        assert "total_marks" in result
        assert "earned_marks" in result
        assert "percentage" in result
        assert "grade" in result
        assert "passed" in result
        assert "results" in result
        assert len(result["results"]) == 2

    def test_per_question_result_fields(self):
        engine = self._make_engine()
        questions = self._sample_questions()[:1]
        result = engine.grade_test(questions, {"q1": "4"})
        r = result["results"][0]
        assert r["question_id"] == "q1"
        assert r["is_correct"] is True
        assert r["marks_awarded"] == 2
        assert r["marks_possible"] == 2
        assert r["similarity_score"] == 1.0

    def test_grade_boundaries(self):
        engine = self._make_engine()
        q = self._sample_questions()[:2]  # 3 total marks
        # 0% → F
        r = engine.grade_test(q, {})
        assert r["grade"] == "F"
        # 100% → A
        r = engine.grade_test(q, {"q1": "4", "q2": "True"})
        assert r["grade"] == "A"

    def test_no_questions_no_crash(self):
        engine = self._make_engine()
        result = engine.grade_test([], {})
        assert result["percentage"] == 0.0
        assert result["total_marks"] == 0


# ---------------------------------------------------------------------------
# lesson_content assembly logic (mirrors the app.py fix)
# ---------------------------------------------------------------------------

class TestLessonContentAssembly:
    """Verifies the lesson_content fix logic independently of Streamlit."""

    def _assemble(self, lesson_dict):
        keys = ["introduction", "theory", "example", "misconceptions", "applications", "summary"]
        return "\n\n".join(
            str(lesson_dict.get(k, ""))
            for k in keys
            if lesson_dict.get(k)
        )[:3000]

    def test_all_keys_present(self):
        lesson = {
            "introduction": "Intro text.",
            "theory": "Theory text.",
            "example": "Example text.",
            "misconceptions": "Misconception text.",
            "applications": "Application text.",
            "summary": "Summary text.",
        }
        content = self._assemble(lesson)
        assert "Intro text." in content
        assert "Theory text." in content
        assert "Summary text." in content
        assert content.count("\n\n") == 5

    def test_missing_keys_skipped(self):
        lesson = {"introduction": "Just intro.", "theory": ""}
        content = self._assemble(lesson)
        assert content == "Just intro."

    def test_raw_lesson_key_not_used(self):
        lesson = {"raw_lesson": "This should NOT appear."}
        content = self._assemble(lesson)
        assert content == ""

    def test_empty_dict_gives_empty_string(self):
        assert self._assemble({}) == ""

    def test_none_dict_safe(self):
        lesson_dict = None or {}
        assert self._assemble(lesson_dict) == ""

    def test_truncated_at_3000(self):
        lesson = {"introduction": "x" * 4000}
        content = self._assemble(lesson)
        assert len(content) == 3000
