"""Test generation must never serve questions copied from the prompt's own examples.

Bug: the prompts contained worked examples about "supervised learning" for EVERY domain,
and the small local model copied them verbatim — a Digital Marketing test opened with
"What does supervised learning require?" (and the same copy sat in the Blockchain and
Unsupervised Learning caches). The prompts are now structure-only, and copies/placeholders
are rejected both when generated and when read back from the cache.
"""

import json
from types import SimpleNamespace

import pytest

import evaluation.test_engine as te

DM_CONCEPT, DM_DOMAIN = "introduction_to_digital_market", "Digital Marketing"
MCQ_COPY = {
    "question_id": "q1", "question": "What does supervised learning require?",
    "options": ["Labelled training data with input-output pairs", "Only unlabelled data with no target variable",
                "A reward signal from the environment", "No data at all — it learns from rules"],
    "correct_answer": "Labelled training data with input-output pairs",
    "explanation": "e", "difficulty": "easy",
}


_GOOD = [
    ("What does customer acquisition cost measure in digital marketing?",
     "The total spend needed to win one new customer", ["The price of one product", "A tax on advertising revenue", "The number of website visitors"]),
    ("Which stage of the customer journey comes first?",
     "Awareness of the brand and its offer", ["Final conversion into a sale", "Loyalty and repeat purchase", "Post-sale customer support"]),
    ("What is search engine optimization mainly used for?",
     "Improving organic visibility in search results", ["Printing brochures for events", "Auditing financial statements", "Training sales teams"]),
    ("Which metric shows the share of visitors who complete a desired action?",
     "Conversion rate across the funnel", ["Server response time", "Office rental costs", "Employee headcount growth"]),
]


def good_mcq(i):
    q, correct, wrong = _GOOD[(i - 1) % len(_GOOD)]
    return {"question_id": f"q{i}", "question": q, "options": [correct] + wrong, "correct_answer": correct,
            "explanation": "e", "difficulty": "easy"}


@pytest.fixture
def engine(tmp_path):
    e = te.TestEngine()
    e._cache_dir = tmp_path
    return e


# ---------------------------------------------------------------- the prompt

@pytest.mark.parametrize("q_type", ["mcq", "true_false", "short_answer"])
def test_prompts_contain_no_concrete_example_content(engine, q_type):
    prompt = engine._type_prompt(q_type, 3, DM_CONCEPT, DM_DOMAIN, "Customer journey and CAC.")
    assert "supervised" not in prompt.lower() and "labelled" not in prompt.lower()
    assert "<a question about the concept>" in prompt or "<a statement about the concept>" in prompt \
        or "<an open-ended question about the concept>" in prompt
    assert f"'{DM_CONCEPT}' in '{DM_DOMAIN}'" in prompt
    assert "never ask about any other subject" in prompt
    assert "Customer journey and CAC." in prompt            # lesson content still included


def test_no_legacy_example_text_remains_in_any_prompt(engine):
    for q_type in ("mcq", "true_false", "short_answer"):
        prompt = engine._type_prompt(q_type, 3, "Blockchain Basics", "Blockchain", "x").lower()
        assert not any(fragment in prompt for fragment in te._LEGACY_EXAMPLE_FRAGMENTS)


# ---------------------------------------------------------------- detection rules

def test_a_copied_example_is_flagged_for_a_non_ml_test():
    assert te._copies_prompt_example(MCQ_COPY, DM_CONCEPT, DM_DOMAIN)
    tf = {"question": "Supervised learning requires labelled training data. True or False?", "correct_answer": "True"}
    sa = {"question": "Explain why supervised learning needs labelled data.", "correct_answer": "x"}
    assert te._copies_prompt_example(tf, "blockchain_fundamentals", "Blockchain")
    assert te._copies_prompt_example(sa, "html_fundamentals", "Web Development")     # 'html' must not count as 'ml'


def test_the_same_question_is_fine_when_the_test_is_about_machine_learning():
    assert not te._copies_prompt_example(MCQ_COPY, "supervised_learning", "Machine Learning")
    assert not te._copies_prompt_example(MCQ_COPY, "introduction_to_ml", "Machine Learning")


def test_it_is_fine_when_the_lesson_itself_covers_supervised_learning():
    assert not te._copies_prompt_example(MCQ_COPY, DM_CONCEPT, DM_DOMAIN,
                                         lesson_content="This lesson compares rule-based targeting with supervised learning.")


def test_genuine_domain_questions_are_never_flagged():
    assert te._unusable_reason(good_mcq(1), DM_CONCEPT, DM_DOMAIN) is None
    assert te._unusable_reason("not a dict", DM_CONCEPT, DM_DOMAIN) is None            # normaliser handles it


@pytest.mark.parametrize("field,value", [
    ("question", "<a question about the concept>"),
    ("correct_answer", "<the exact text of the one correct option>"),
])
def test_template_placeholder_text_is_rejected(field, value):
    q = {**good_mcq(2), field: value}
    assert te._unusable_reason(q, DM_CONCEPT, DM_DOMAIN) == "contains template placeholder text"


def test_real_questions_with_angle_brackets_in_code_are_not_mistaken_for_placeholders():
    q = {"question": "Which HTML tag creates a paragraph: <p> or <div>?", "correct_answer": "<p>", "options": ["<p>", "<div>", "<a>", "<b>"]}
    # short tags (1-2 chars of content like <p>, <b>, <a>) are below the placeholder length floor
    assert te._PLACEHOLDER_RE.search(te._question_blob({"question": "Use <p> for text", "correct_answer": "<p>"})) is None


# ---------------------------------------------------------------- generation: the copy is dropped, the slot is padded

def stub_model(monkeypatch, questions):
    monkeypatch.setattr(te, "_ollama_invoke", lambda llm, messages, **k: SimpleNamespace(content=json.dumps(questions)))


def test_a_copied_example_in_the_model_output_is_rejected_and_replaced(engine, monkeypatch):
    stub_model(monkeypatch, [MCQ_COPY, good_mcq(2), good_mcq(3), good_mcq(4)])
    out = engine._generate_questions_of_type("mcq", 4, 2, DM_CONCEPT, DM_DOMAIN, "customer acquisition cost")
    assert len(out) == 4
    assert not any("supervised" in json.dumps(q).lower() for q in out)
    questions = [q["question"] for q in out]
    assert len(set(questions)) == 4                                    # nothing repeated
    assert {good_mcq(i)["question"] for i in (2, 3, 4)} <= set(questions)   # the 3 good ones kept
    assert MCQ_COPY["question"] not in questions


def test_placeholder_output_is_rejected(engine, monkeypatch):
    junk = {**good_mcq(1), "question": "<a question about the concept>"}
    stub_model(monkeypatch, [junk, good_mcq(2), good_mcq(3), good_mcq(4)])
    out = engine._generate_questions_of_type("mcq", 4, 2, DM_CONCEPT, DM_DOMAIN, "x")
    assert not any("<" in q["question"] for q in out) and len(out) == 4


def test_ml_tests_keep_a_question_that_matches_an_old_example(engine, monkeypatch):
    stub_model(monkeypatch, [MCQ_COPY, good_mcq(2), good_mcq(3), good_mcq(4)])
    out = engine._generate_questions_of_type("mcq", 4, 2, "supervised_learning", "Machine Learning", "x")
    assert any("supervised learning require" in q["question"] for q in out)


# ---------------------------------------------------------------- the cache gate

def write_cache(engine, concept, domain, questions):
    engine._cache_file(concept, domain).write_text(json.dumps(questions), encoding="utf-8")


def ten_questions(concept, domain):
    return te._build_fallback_questions(concept, domain)


def test_a_contaminated_cached_test_is_discarded_so_it_regenerates(engine, caplog):
    qs = ten_questions(DM_CONCEPT, DM_DOMAIN)
    qs[0] = {**MCQ_COPY, "marks": 2}                                       # exactly what Teena's cache held
    write_cache(engine, DM_CONCEPT, DM_DOMAIN, qs)
    with caplog.at_level("WARNING"):
        assert engine._load_cache(DM_CONCEPT, DM_DOMAIN) == []
    assert any("Discarding cached test" in r.getMessage() and "q1" in r.getMessage() for r in caplog.records)


def test_a_clean_cached_test_is_still_served(engine):
    qs = ten_questions(DM_CONCEPT, DM_DOMAIN)
    write_cache(engine, DM_CONCEPT, DM_DOMAIN, qs)
    assert engine._load_cache(DM_CONCEPT, DM_DOMAIN) == qs


def test_an_ml_cached_test_containing_the_old_example_is_kept(engine):
    qs = ten_questions("supervised_learning", "Machine Learning")
    qs[0] = {**MCQ_COPY, "marks": 2}
    write_cache(engine, "supervised_learning", "Machine Learning", qs)
    assert engine._load_cache("supervised_learning", "Machine Learning") == qs     # on-topic: no needless 3-minute regeneration


def test_generate_test_regenerates_instead_of_serving_a_contaminated_cache(engine, monkeypatch):
    qs = ten_questions(DM_CONCEPT, DM_DOMAIN)
    qs[0] = {**MCQ_COPY, "marks": 2}
    write_cache(engine, DM_CONCEPT, DM_DOMAIN, qs)
    calls = []
    monkeypatch.setattr(te.TestEngine, "_generate_questions_of_type",
                        lambda self, q_type, count, marks, *a, **kw: calls.append(q_type) or
                        te._fallback_questions_for_type(q_type, count, DM_CONCEPT, DM_DOMAIN))
    out = engine.generate_test(DM_CONCEPT, DM_DOMAIN, "lesson")
    assert sorted(calls) == ["mcq", "short_answer", "true_false"]            # the cache was NOT used
    assert len(out) == 10 and not any("supervised" in json.dumps(q).lower() for q in out)
