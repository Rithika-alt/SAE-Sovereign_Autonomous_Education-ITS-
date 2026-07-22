"""
Diagnostic tests for Ollama test generation.
Run with:  pytest tests/test_ollama_generation.py -v -s

These tests require Ollama to be running (ollama serve).
They are intentionally verbose so failures are self-explanatory.
"""

import json
import os
import sys
import time

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL    = os.getenv("OLLAMA_MODEL",    "llama3.2")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_llm():
    from langchain_ollama import ChatOllama
    return ChatOllama(base_url=OLLAMA_BASE_URL, model=OLLAMA_MODEL, temperature=0.5)


# ---------------------------------------------------------------------------
# Step 1 — Is Ollama reachable at all?
# ---------------------------------------------------------------------------

def test_ollama_reachable():
    """Ollama HTTP endpoint must respond before any generation test runs."""
    import requests
    try:
        r = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=5)
        assert r.status_code == 200, (
            f"Ollama responded with {r.status_code}. "
            "Expected 200 from /api/tags."
        )
        models = [m["name"] for m in r.json().get("models", [])]
        print(f"\n  Ollama reachable. Available models: {models}")
        assert any(OLLAMA_MODEL in m for m in models), (
            f"Model '{OLLAMA_MODEL}' not found in Ollama. "
            f"Pull it with:  ollama pull {OLLAMA_MODEL}\n"
            f"Available: {models}"
        )
        print(f"  Model '{OLLAMA_MODEL}' confirmed present.")
    except requests.exceptions.ConnectionError:
        pytest.fail(
            f"Cannot reach Ollama at {OLLAMA_BASE_URL}. "
            "Start it with:  ollama serve"
        )


# ---------------------------------------------------------------------------
# Step 2 — Can Ollama produce any text at all?
# ---------------------------------------------------------------------------

def test_ollama_basic_invoke():
    """Ollama must return a non-empty response to a trivial prompt."""
    llm = _make_llm()
    start = time.time()
    print(f"\n  Calling Ollama ({OLLAMA_MODEL}) with a trivial prompt…")
    response = llm.invoke("Reply with the single word: HELLO")
    elapsed  = time.time() - start
    print(f"  Response ({elapsed:.1f}s): {response.content!r}")
    assert response.content.strip(), "Ollama returned an empty response."
    print("  Basic invoke: PASSED")


# ---------------------------------------------------------------------------
# Step 3 — Does Ollama return valid JSON for a simple array prompt?
# ---------------------------------------------------------------------------

def test_ollama_returns_json_array():
    """Ollama must return valid JSON when asked — tested with a question-shaped array."""
    llm = _make_llm()
    prompt = (
        'Return ONLY a valid JSON array containing exactly one question object. '
        'No explanation, no markdown.\n'
        '[{"question_id":"q1","question":"What is 2+2?","type":"mcq",'
        '"options":["3","4","5","6"],"correct_answer":"4",'
        '"explanation":"Basic arithmetic.","marks":2,"difficulty":"easy"}]'
    )
    print("\n  Asking Ollama for a question JSON array…")
    start    = time.time()
    response = llm.invoke(prompt)
    elapsed  = time.time() - start
    raw      = response.content.strip()
    print(f"  Raw response ({elapsed:.1f}s): {raw[:300]!r}")

    from evaluation.test_engine import _extract_json_list
    try:
        result = _extract_json_list(raw)
        print(f"  Parsed {len(result)} question(s): {result}")
        assert isinstance(result, list), f"Expected list, got {type(result)}"
        assert len(result) >= 1, "Expected at least 1 question dict"
        assert isinstance(result[0], dict), f"Expected dict item, got {type(result[0])}"
        print("  JSON array extraction: PASSED")
    except ValueError as exc:
        pytest.fail(
            f"_extract_json_list failed: {exc}\n"
            f"Raw Ollama output was: {raw!r}"
        )


# ---------------------------------------------------------------------------
# Step 4 — Does Ollama produce ONE well-formed question object?
# ---------------------------------------------------------------------------

def test_ollama_single_question():
    """Ollama must return a single valid question JSON object."""
    llm = _make_llm()
    prompt = (
        "Generate exactly ONE MCQ question about Python. "
        "Return ONLY valid JSON (no markdown, no explanation):\n"
        '[{"question_id":"q1","question":"...","type":"mcq",'
        '"options":["A","B","C","D"],"correct_answer":"A",'
        '"explanation":"...","marks":2,"difficulty":"easy"}]'
    )
    print("\n  Asking Ollama for a single question…")
    start    = time.time()
    response = llm.invoke(prompt)
    elapsed  = time.time() - start
    raw      = response.content.strip()
    print(f"  Raw response ({elapsed:.1f}s):\n  {raw[:500]!r}")

    from evaluation.test_engine import _extract_json_list, _normalise_question
    questions = _extract_json_list(raw)
    assert len(questions) >= 1, f"Expected at least 1 question, got {len(questions)}"
    q = _normalise_question(questions[0], 0)
    print(f"  Normalised question: {json.dumps(q, indent=2)}")

    assert q["question"],       "question field is empty"
    assert q["type"] == "mcq",  f"Expected mcq, got {q['type']}"
    assert len(q["options"]) == 4, f"Expected 4 options, got {q['options']}"
    assert q["correct_answer"], "correct_answer is empty"
    print("  Single question generation: PASSED")


# ---------------------------------------------------------------------------
# Step 5 — Full generate_test() with real lesson content
# ---------------------------------------------------------------------------

def test_generate_test_with_lesson_content():
    """TestEngine.generate_test() must return 10 valid questions given real lesson content."""
    from evaluation.test_engine import TestEngine

    lesson_content = """
    Introduction to Regression in Machine Learning:
    Regression is a supervised learning technique used to predict continuous
    numerical values. Unlike classification, which predicts discrete labels,
    regression models output a real number.

    Theory:
    Linear regression models the relationship between input features X and
    output y using a linear equation: y = wX + b, where w are weights and b
    is the bias. The model is trained by minimising the Mean Squared Error
    (MSE) loss using gradient descent.

    Key concepts:
    - Mean Squared Error (MSE): average of squared differences between
      predicted and actual values.
    - Gradient descent: iterative optimisation algorithm that adjusts weights
      by computing the gradient of the loss function.
    - Overfitting: when the model fits training data too closely and fails on
      new data. Regularisation (L1/L2) helps prevent this.

    Example:
    Predicting house prices from square footage. If a 1000 sq ft house costs
    $200,000 and a 2000 sq ft house costs $350,000, a regression model learns
    the linear relationship and can predict prices for unseen sizes.
    """

    engine = TestEngine()
    print(f"\n  Calling generate_test(concept='regression', domain='Machine Learning')")
    print(f"  Lesson content length: {len(lesson_content)} chars")
    start     = time.time()
    questions = engine.generate_test("regression", "Machine Learning", lesson_content)
    elapsed   = time.time() - start

    print(f"\n  Generation time: {elapsed:.1f}s")
    print(f"  Questions returned: {len(questions)}")
    for i, q in enumerate(questions):
        print(f"  Q{i+1} [{q['type']}] marks={q['marks']} | {q['question'][:60]!r}")
        if q["type"] == "mcq":
            print(f"       options={q['options']}")

    assert len(questions) == 10, (
        f"Expected 10 questions, got {len(questions)}. "
        "Check earlier log output for the Ollama response."
    )

    types = [q["type"] for q in questions]
    mcq_count = types.count("mcq")
    tf_count  = types.count("true_false")
    sa_count  = types.count("short_answer")
    print(f"\n  Type breakdown: MCQ={mcq_count}, T/F={tf_count}, ShortAnswer={sa_count}")
    # llama3.2 doesn't always follow exact counts — assert at least 1 of each type
    assert mcq_count >= 1,  f"Expected at least 1 MCQ, got {mcq_count}"
    assert tf_count  >= 1,  f"Expected at least 1 true/false, got {tf_count}"
    assert sa_count  >= 1,  f"Expected at least 1 short answer, got {sa_count}"

    for q in questions:
        assert q["question"], f"Q {q['question_id']} has empty question text"
        assert q["correct_answer"], (
            f"Q {q['question_id']} ({q['type']}) has no correct_answer even after fallback. "
            "Check _normalise_question fallback logic."
        )
        if q["type"] == "mcq":
            assert len(q["options"]) == 4, (
                f"Q {q['question_id']} MCQ has {len(q['options'])} options, expected 4"
            )

    print("\n  generate_test: PASSED — 10 valid questions returned")


# ---------------------------------------------------------------------------
# Step 6 — generate_test() with EMPTY lesson content (the bug scenario)
# ---------------------------------------------------------------------------

def test_generate_test_empty_lesson_warns_but_still_returns_10():
    """Even with no lesson content, generate_test must return exactly 10 questions.

    This test reproduces the original bug where lesson_content was always ''
    because app.py used the wrong dict key 'raw_lesson'. The test engine should
    log a WARNING and still produce fallback or LLM-generated questions.
    """
    from evaluation.test_engine import TestEngine
    import logging

    engine = TestEngine()

    # Capture the WARNING that _should_ be emitted when content is empty
    warning_emitted = []
    original_warning = engine.__class__.__dict__.get("generate_test")

    import logging
    log_records = []

    class _Capture(logging.Handler):
        def emit(self, record):
            log_records.append(record)

    handler = _Capture()
    logging.getLogger("evaluation.test_engine").addHandler(handler)

    try:
        print("\n  Calling generate_test with EMPTY lesson_content…")
        start     = time.time()
        questions = engine.generate_test("linear_regression", "Machine Learning", "")
        elapsed   = time.time() - start
        print(f"  Returned {len(questions)} questions in {elapsed:.1f}s")

        # Check the warning was logged
        warnings = [r for r in log_records if r.levelno == logging.WARNING
                    and "EMPTY" in r.getMessage()]
        print(f"  'lesson_content is EMPTY' warning emitted: {bool(warnings)}")
        assert warnings, (
            "Expected a WARNING log saying lesson_content is EMPTY, but none was emitted. "
            "Check that generate_test() still has the empty-content guard."
        )

        assert len(questions) == 10, f"Expected 10 questions, got {len(questions)}"
        print("  Empty-content fallback: PASSED — 10 questions still returned")

    finally:
        logging.getLogger("evaluation.test_engine").removeHandler(handler)


# ---------------------------------------------------------------------------
# Step 7 — grade_test() round-trip with generated questions
# ---------------------------------------------------------------------------

def test_grade_test_round_trip():
    """Generate questions then grade them — full round-trip through the engine."""
    from evaluation.test_engine import TestEngine

    lesson = (
        "Supervised learning uses labelled training data. "
        "The model learns a mapping from inputs to outputs. "
        "Common algorithms include linear regression, decision trees, and SVMs."
    )

    engine    = TestEngine()
    print("\n  Generating questions for grade round-trip test…")
    questions = engine.generate_test("supervised_learning", "Machine Learning", lesson)
    assert len(questions) == 10

    # Build answers: answer MCQ/T-F correctly, leave short_answer blank
    answers = {}
    for q in questions:
        if q["type"] in ("mcq", "true_false"):
            answers[q["question_id"]] = q["correct_answer"]

    print(f"  Grading with {len(answers)} answers provided (short answers left blank)…")
    result = engine.grade_test(questions, answers)

    print(f"  Result: {result['earned_marks']}/{result['total_marks']} "
          f"({result['percentage']}%) grade={result['grade']} passed={result['passed']}")

    assert result["total_marks"] > 0
    assert 0 <= result["earned_marks"] <= result["total_marks"]
    assert 0.0 <= result["percentage"] <= 100.0
    assert result["grade"] in ("A", "B", "C", "F")
    assert isinstance(result["passed"], bool)
    assert len(result["results"]) == 10
    print("  Grade round-trip: PASSED")
