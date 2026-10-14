"""Test-generation quality and bounded cost.

Problems this guards against (all seen in real tests):
  * a runaway model response ran for 20+ minutes (no token cap)
  * wrong correct answers (the normaliser snapped them to the nearest option at cutoff 0.4)
    and invented "answer choice 1..4" options
  * out-of-syllabus questions copied from prompt examples
  * the same fact asked three times across MCQ / true-false / short-answer
  * generic, identical filler ("Which of the following best describes X? (Question 1..4)")
"""

import json
import re
from types import SimpleNamespace

import pytest

import evaluation.test_engine as te

CONCEPT, DOMAIN = "introduction_to_digital_market", "Digital Marketing"

MCQ = [
    ("What does customer acquisition cost measure in digital marketing?", "The total spend needed to win one new customer",
     ["The price of one product", "A tax on advertising revenue", "The number of website visitors"]),
    ("Which stage of the customer journey comes first?", "Awareness of the brand and its offer",
     ["Final conversion into a sale", "Loyalty and repeat purchase", "Post-sale customer support"]),
    ("What is search engine optimization mainly used for?", "Improving organic visibility in search results",
     ["Printing brochures for events", "Auditing financial statements", "Training sales teams"]),
    ("Which metric shows the share of visitors who complete a desired action?", "Conversion rate across the funnel",
     ["Server response time", "Office rental costs", "Employee headcount growth"]),
    ("What is the purpose of a content calendar in marketing?", "Planning and scheduling content across channels",
     ["Calculating employee payroll", "Designing office furniture", "Repairing network cables"]),
]
TF = [
    ("The customer journey always follows a single fixed path. True or False?", "False"),
    ("Search engine optimization aims to improve organic visibility. True or False?", "True"),
    ("Email marketing can be personalised using customer data. True or False?", "True"),
]
SA = [
    ("Explain how the customer journey guides a marketing strategy.", "It maps awareness, consideration and conversion so campaigns can target each stage."),
    ("Describe how customer acquisition cost is calculated and why it matters.", "Total acquisition spend divided by new customers won; it shows whether campaigns are profitable."),
    ("Why do marketers use content calendars across channels?", "To plan, schedule and coordinate content so messaging stays consistent over time."),
]


def mcq(i):
    q, c, w = MCQ[i]
    return {"question_id": f"q{i}", "question": q, "options": [c] + w, "correct_answer": c, "explanation": "e", "difficulty": "easy"}


def tf(i):
    q, a = TF[i]
    return {"question_id": f"t{i}", "question": q, "correct_answer": a, "explanation": "e", "difficulty": "easy"}


def sa(i):
    q, a = SA[i]
    return {"question_id": f"s{i}", "question": q, "correct_answer": a, "explanation": "e", "difficulty": "medium"}


def reply(questions):
    return SimpleNamespace(content=json.dumps({"questions": questions}))


@pytest.fixture
def engine(tmp_path):
    e = te.TestEngine()
    e._cache_dir = tmp_path
    return e


@pytest.fixture
def roadmaps(tmp_path, monkeypatch):
    d = tmp_path / "roadmaps"
    d.mkdir()
    (d / "digital_marketing.json").write_text(json.dumps({"domain": DOMAIN, "modules": [
        {"module_id": CONCEPT, "title": "Introduction to Digital Marketing",
         "concepts": ["Customer Journey", "Search Engine Optimization", "Email Campaigns", "Conversion Funnels"]}]}), encoding="utf-8")
    (d / "blockchain.json").write_text(json.dumps({"domain": "Blockchain", "modules": [
        {"module_id": "b1", "title": "B", "concepts": ["Merkle Trees", "Proof of Work", "Smart Contracts", "Consensus Protocols"]}]}), encoding="utf-8")
    (d / "quantum.json").write_text(json.dumps({"domain": "Quantum", "modules": [
        {"module_id": "q1", "title": "Q", "concepts": ["Qubit Entanglement", "Superposition States", "Quantum Gates"]}]}), encoding="utf-8")
    monkeypatch.setattr(te, "_ROADMAP_DIR", d)
    return d


class Model:
    """Stub for _ollama_invoke: pops one scripted reply per call and records every prompt."""

    def __init__(self, monkeypatch, replies):
        self.prompts, self.llms, self.replies = [], [], list(replies)
        monkeypatch.setattr(te, "_ollama_invoke", self)

    def __call__(self, llm, messages, **kw):
        self.llms.append(llm)
        self.prompts.append(messages[0].content)
        r = self.replies.pop(0) if self.replies else reply([])
        if isinstance(r, Exception):
            raise r
        return r


# ---------------------------------------------------------------- bounded cost

@pytest.mark.parametrize("q_type", ["mcq", "true_false", "short_answer"])
def test_every_call_is_token_capped_and_uses_json_mode(engine, q_type):
    llm = engine._make_llm(q_type)
    assert llm.num_predict == te._TOKEN_CAPS[q_type] and llm.format == "json"


def test_caps_leave_headroom_over_measured_typical_output_but_far_below_a_runaway():
    # measured typical output: mcq 514, true_false 236, short_answer 288 tokens (real sessions)
    assert te._TOKEN_CAPS["mcq"] >= 514 * 1.5 and te._TOKEN_CAPS["true_false"] >= 236 * 1.5 and te._TOKEN_CAPS["short_answer"] >= 288 * 1.5
    assert sum(te._TOKEN_CAPS.values()) < 3000        # vs ~7500 tokens (18+ min) for a runaway to the 8k context


# ---------------------------------------------------------------- JSON extraction

def test_json_mode_wrapper_object_is_unwrapped():
    out = te._extract_json_list(json.dumps({"questions": [mcq(0), mcq(1)]}))
    assert [q["question_id"] for q in out] == ["q0", "q1"]


def test_a_single_question_object_is_still_wrapped():
    assert len(te._extract_json_list(json.dumps(mcq(0)))) == 1


def test_truncated_output_at_the_token_cap_keeps_the_complete_questions():
    text = json.dumps({"questions": [mcq(0), mcq(1), mcq(2)]})
    cut = text[: text.rindex('"question_id"') + 20]                      # chop the third question in half
    out = te._extract_json_list(cut)
    assert len(out) >= 2 and out[0]["question"] == MCQ[0][0]


def test_prose_with_no_json_still_raises():
    with pytest.raises(ValueError):
        te._extract_json_list("Sorry, I cannot help with that.")


# ---------------------------------------------------------------- strict structure checks

def bad(q, **changes):
    return {**q, **changes}


@pytest.mark.parametrize("changes,fragment", [
    ({"options": ["a one", "b two", "c three"]}, "exactly 4"),
    ({"options": ["Same text here", "Same text here", "Another one", "A fourth"]}, "distinct"),
    ({"options": ["A", "B", "C", "D"]}, "just a letter"),
    ({"correct_answer": "A reward signal from the environment"}, "not one of the options"),
    ({"correct_answer": ""}, "no correct_answer"),
    ({"question": "Hi?"}, "too short"),
])
def test_unsound_mcq_is_rejected_not_patched(changes, fragment):
    assert fragment in te._structure_problem(bad(mcq(0), **changes), "mcq")


def test_a_valid_mcq_passes_and_a_near_verbatim_answer_is_repaired_to_the_exact_option():
    q = bad(mcq(0), correct_answer="the total spend needed to win one new customer.")
    assert te._structure_problem(q, "mcq") is None
    assert te._repair_mcq(q)["correct_answer"] == MCQ[0][1]


def test_a_wrong_answer_is_no_longer_snapped_onto_a_random_option():
    # the old normaliser (difflib cutoff 0.4) would have mapped this onto an option and marked it correct
    q = bad(mcq(0), correct_answer="Spend on win customers")
    assert te._structure_problem(q, "mcq") == "correct_answer is not one of the options"


def test_two_near_identical_options_are_rejected():
    q = bad(mcq(0), options=["Improving organic search visibility", "Improving organic search visibility today",
                              "Printing brochures", "Auditing accounts"], correct_answer="Improving organic search visibility")
    assert te._structure_problem(q, "mcq") == "two options are near-identical"


def test_true_false_rules():
    assert te._structure_problem(tf(0), "true_false") is None
    assert "not exactly True or False" in te._structure_problem(bad(tf(0), correct_answer="Maybe"), "true_false")
    assert "phrased as a question" in te._structure_problem(
        bad(tf(0), question="What is the customer journey in marketing today?"), "true_false")


def test_short_answer_needs_a_gradable_model_answer():
    assert te._structure_problem(sa(0), "short_answer") is None
    assert "too short" in te._structure_problem(bad(sa(0), correct_answer="It depends."), "short_answer")


# ---------------------------------------------------------------- grounding in the lesson

LESSON = " ".join(
    "Digital marketing promotes products using search engines, email, social media and content. The customer journey "
    "moves from awareness to consideration to conversion. Customer acquisition cost divides spending by new customers. "
    "Search engine optimization improves organic visibility. Content calendars schedule posts across channels.".split()
)


def test_an_off_syllabus_question_is_not_grounded_but_real_ones_are():
    terms = te._lesson_terms(CONCEPT, DOMAIN, LESSON * 2)
    assert len(terms) >= 25
    assert te._is_grounded(mcq(0), terms) and te._is_grounded(tf(1), terms)
    off = {"question": "What does supervised learning require?", "correct_answer": "Labelled training data with input-output pairs"}
    assert not te._is_grounded(off, terms)
    assert not te._is_grounded({"question": "How do blockchains reach consensus on transactions?", "correct_answer": "By proof of work"}, terms)


def test_grounding_is_skipped_when_there_is_no_real_lesson_text():
    assert te._is_grounded({"question": "anything at all here", "correct_answer": "x"}, te._lesson_terms(CONCEPT, DOMAIN, ""))


# ---------------------------------------------------------------- repetition

def test_rephrased_duplicates_are_detected_and_different_questions_are_not():
    assert te._similar("What is the Customer Journey in digital marketing?",
                       "What is the Customer Journey in Digital Marketing and its significance?")
    assert not te._similar(MCQ[0][0], MCQ[1][0])
    assert not te._similar(TF[1][0], MCQ[0][0])


# ---------------------------------------------------------------- generation loop

def test_bad_and_duplicate_questions_are_dropped_and_one_retry_fills_the_gap(engine, monkeypatch, roadmaps):
    junk = bad(mcq(0), options=["only", "two"])                    # malformed
    model = Model(monkeypatch, [
        reply([mcq(0), mcq(0), junk, mcq(1)]),                      # 2 usable (one duplicate, one malformed)
        reply([mcq(2), mcq(3), mcq(4)]),                            # retry supplies the rest
    ])
    out = engine._generate_questions_of_type("mcq", 4, 2, CONCEPT, DOMAIN, LESSON)
    assert [q["question"] for q in out] == [MCQ[0][0], MCQ[1][0], MCQ[2][0], MCQ[3][0]]
    assert len(model.prompts) == 2                                  # exactly one retry
    assert MCQ[0][0] in model.prompts[1] and MCQ[1][0] in model.prompts[1]     # told not to repeat what it already has
    assert "Generate exactly 3" in model.prompts[1]                 # asked for the shortfall + 1 spare (2 needed)


def test_a_perfect_first_reply_costs_exactly_one_model_call(engine, monkeypatch):
    model = Model(monkeypatch, [reply([mcq(0), mcq(1), mcq(2), mcq(3)])])
    out = engine._generate_questions_of_type("mcq", 4, 2, CONCEPT, DOMAIN, LESSON)
    assert len(out) == 4 and len(model.prompts) == 1


def test_no_retry_is_started_after_the_time_budget(engine, monkeypatch, roadmaps):
    model = Model(monkeypatch, [reply([mcq(0)]), reply([mcq(1), mcq(2), mcq(3)])])
    out = engine._generate_questions_of_type("mcq", 4, 2, CONCEPT, DOMAIN, LESSON, deadline=0)
    assert len(model.prompts) == 1 and len(out) == 4              # padded with syllabus filler instead
    assert sum(q["question"] in {m[0] for m in MCQ} for q in out) == 1


def test_a_failing_model_call_is_retried_once_then_filler_is_used(engine, monkeypatch, roadmaps):
    model = Model(monkeypatch, [ConnectionError("down"), ConnectionError("down")])
    out = engine._generate_questions_of_type("true_false", 3, 1, CONCEPT, DOMAIN, LESSON)
    assert len(model.prompts) == 2 and len(out) == 3
    assert all(te._structure_problem(q, "true_false") is None for q in out)


def test_out_of_syllabus_questions_are_rejected_when_there_is_lesson_text(engine, monkeypatch, roadmaps):
    off = {"question_id": "x", "question": "How do blockchains reach consensus on transactions?",
           "options": ["By proof of work", "By a coin flip", "By a vote of banks", "By email"],
           "correct_answer": "By proof of work", "explanation": "e"}
    Model(monkeypatch, [reply([off, mcq(0), mcq(1), mcq(2), mcq(3)])])
    out = engine._generate_questions_of_type("mcq", 4, 2, CONCEPT, DOMAIN, LESSON * 2)
    assert off["question"] not in [q["question"] for q in out] and len(out) == 4


# ---------------------------------------------------------------- the full test

def scripted_full_test(monkeypatch):
    return Model(monkeypatch, [
        reply([mcq(0), mcq(1), mcq(2), mcq(3)]),
        reply([tf(0), tf(1), tf(2)]),
        reply([sa(0), sa(1), sa(2)]),
    ])


def test_generate_test_runs_types_in_order_and_tells_later_types_what_was_asked(engine, monkeypatch):
    model = scripted_full_test(monkeypatch)
    out = engine.generate_test(CONCEPT, DOMAIN, LESSON)
    assert len(out) == 10 and [q["type"] for q in out] == ["mcq"] * 4 + ["true_false"] * 3 + ["short_answer"] * 3
    assert len(model.prompts) == 3                                    # one call per type, no retries
    assert "already asked" not in model.prompts[0]
    assert MCQ[0][0] in model.prompts[1] and "already asked" in model.prompts[1]
    assert MCQ[0][0] in model.prompts[2] and TF[0][0] in model.prompts[2]
    assert [q["question_id"] for q in out] == [f"q{i}" for i in range(1, 11)]
    assert len({q["question"] for q in out}) == 10                    # nothing repeated


def test_progress_is_reported_per_type(engine, monkeypatch):
    scripted_full_test(monkeypatch)
    seen = []
    engine.generate_test(CONCEPT, DOMAIN, LESSON, progress=lambda t, n: seen.append((t, n)))
    assert seen == [("mcq", 4), ("true_false", 3), ("short_answer", 3)]


def test_every_model_call_failing_still_yields_ten_valid_distinct_on_syllabus_questions(engine, monkeypatch, roadmaps):
    Model(monkeypatch, [ConnectionError("x")] * 6)
    out = engine.generate_test(CONCEPT, DOMAIN, LESSON)
    assert len(out) == 10
    assert len({q["question"] for q in out}) == 10                    # not "(Question 1) (Question 2)..." clones
    for q in out:
        assert te._structure_problem(q, q["type"]) is None
    blob = json.dumps(out)
    assert "supervised" not in blob.lower() and "unrelated algorithm" not in blob


# ---------------------------------------------------------------- syllabus-based filler

def test_filler_mcq_uses_the_modules_own_concepts_and_genuinely_wrong_distractors(roadmaps):
    out = te._grounded_fallback_questions("mcq", 4, CONCEPT, DOMAIN)
    own = {"Customer Journey", "Search Engine Optimization", "Email Campaigns", "Conversion Funnels"}
    for q in out:
        assert q["correct_answer"] in own and q["correct_answer"] in q["options"]
        assert len(set(q["options"])) == 4
        assert not (set(q["options"]) - {q["correct_answer"]}) & own        # distractors are from other domains
    assert len({q["correct_answer"] for q in out}) == 4                       # a different concept each time
    assert len({q["question"] for q in out}) >= 3


def test_filler_true_false_mixes_true_and_false_with_correct_answers(roadmaps):
    out = te._grounded_fallback_questions("true_false", 4, CONCEPT, DOMAIN)
    assert {q["correct_answer"] for q in out} == {"True", "False"}
    for q in out:
        in_module = any(c in q["question"] for c in ("Customer Journey", "Search Engine Optimization", "Email Campaigns", "Conversion Funnels"))
        assert (q["correct_answer"] == "True") == in_module


def test_filler_short_answers_are_distinct(roadmaps):
    out = te._grounded_fallback_questions("short_answer", 3, CONCEPT, DOMAIN)
    assert len({q["question"] for q in out}) == 3


def test_filler_skips_concepts_that_were_already_asked(roadmaps):
    out = te._grounded_fallback_questions("mcq", 2, CONCEPT, DOMAIN, avoid=["Explain the Customer Journey"])
    assert "Customer Journey" not in {q["correct_answer"] for q in out}


def test_with_no_roadmap_data_the_generic_fallback_still_returns_questions(tmp_path, monkeypatch):
    monkeypatch.setattr(te, "_ROADMAP_DIR", tmp_path / "missing")
    out = te._grounded_fallback_questions("mcq", 4, "sorting", "CS")
    assert len(out) == 4 and all(q["type"] == "mcq" for q in out)


def test_options_that_differ_by_one_short_but_decisive_word_are_not_called_identical():
    q = {"question": "Which protocol guarantees ordered delivery of data?", "correct_answer": "TCP is connection oriented and reliable",
         "options": ["TCP is connection oriented and reliable", "UDP is connection oriented and reliable",
                     "ICMP carries routing hints only", "ARP resolves hardware addresses"]}
    assert te._structure_problem(q, "mcq") is None


# ---------------------------------------------------------------- filler bugs found in the live run

OWN_REAL = ["Customer Journey", "Search Engine Optimization", "Email Campaigns", "Conversion Funnels", "Content Calendars",
            "Retargeting Basics", "Audience Segmentation", "Brand Voice", "Landing Pages", "Marketing Analytics",
            "Social Listening", "Lead Nurturing"]


@pytest.fixture
def junky_roadmaps(tmp_path, monkeypatch):
    """Roadmaps containing what real ones contain: placeholders, bare domain names, snake_case ids."""
    d = tmp_path / "junk_roadmaps"
    d.mkdir()
    own = OWN_REAL[:4] + ["concept4", "ad_budgeting", "digital marketing"] + OWN_REAL[4:]
    (d / "digital_marketing.json").write_text(json.dumps({"modules": [
        {"module_id": CONCEPT, "title": "Introduction to Digital Marketing", "concepts": own}]}), encoding="utf-8")
    (d / "blockchain.json").write_text(json.dumps({"modules": [{"module_id": "b", "title": "B", "concepts": [
        "Merkle Trees", "concept1", "blockchain", "smart_contract_principles", "Proof of Work", "Consensus Protocols"]}]}), encoding="utf-8")
    (d / "quantum.json").write_text(json.dumps({"modules": [{"module_id": "q", "title": "Q", "concepts": [
        "Qubit Entanglement", "concept2", "quantum_gates", "Superposition States", "Topic 3"]}]}), encoding="utf-8")
    monkeypatch.setattr(te, "_ROADMAP_DIR", d)
    return d


DOMAIN_NAMES = {"digital marketing", "blockchain", "quantum"}


@pytest.mark.parametrize("raw", ["concept4", "Concept 12", "topic_3", "item-7", "module1", "blockchain", "Digital Marketing", "", "   ", None, 42])
def test_placeholders_and_bare_domain_names_are_not_concepts(raw):
    assert te._clean_concept(raw, DOMAIN_NAMES) is None


@pytest.mark.parametrize("raw,expected", [
    ("ad_budgeting", "Ad budgeting"), ("Bayes_theory", "Bayes theory"), ("market_analysis", "Market analysis"),
    ("Git", "Git"), ("SVN", "SVN"), ("evm", "evm"), ("Customer Journey", "Customer Journey"),
])
def test_real_concepts_are_kept_and_identifiers_become_readable(raw, expected):
    assert te._clean_concept(raw, DOMAIN_NAMES) == expected


def test_the_syllabus_excludes_placeholders_for_this_module_and_for_the_distractor_pool(junky_roadmaps):
    title, own, others = te._syllabus_for(CONCEPT, DOMAIN)
    assert "concept4" not in own and "digital marketing" not in [c.lower() for c in own] and "Ad budgeting" in own
    junk = {"concept1", "concept2", "blockchain", "Topic 3", "smart_contract_principles", "quantum_gates"}
    assert not junk & set(others)
    assert {"Merkle Trees", "Smart contract principles", "Quantum gates", "Qubit Entanglement"} <= set(others)


def test_filler_options_never_contain_placeholders_or_identifiers(junky_roadmaps):
    out = te._grounded_fallback_questions("mcq", 4, CONCEPT, DOMAIN)
    shown = [o for q in out for o in q["options"]]
    assert not [o for o in shown if "_" in o or o.lower().startswith(("concept", "topic")) or o.lower() == "blockchain"]
    for q in out:
        assert q["correct_answer"] in q["options"] and len(set(q["options"])) == 4


def _subjects(questions):
    """The concept each filler question is about (MCQ answer; quoted concept for true/false and short answer)."""
    out = []
    for q in questions:
        if q["type"] == "mcq":
            out.append(q["correct_answer"])
        elif q["type"] == "true_false" and q["correct_answer"] == "True":
            out.append(re.match(r'"([^"]+)"', q["question"]).group(1))
        elif q["type"] == "short_answer":
            out.append(re.search(r'"([^"]+)"', q["question"]).group(1))
    return out


def test_filler_does_not_reuse_a_concept_across_question_types(engine, monkeypatch, junky_roadmaps):
    """The live run asked about 'History of Digital Marketing' as an MCQ answer AND as a true/false subject."""
    Model(monkeypatch, [ConnectionError("x")] * 6)
    out = engine.generate_test(CONCEPT, DOMAIN, LESSON)
    subjects = _subjects(out)
    assert len(subjects) >= 8 and len(subjects) == len(set(subjects)), subjects
    assert len({q["question"] for q in out}) == 10


def test_concepts_already_asked_as_answers_are_avoided_even_though_they_are_not_in_the_question_text(junky_roadmaps):
    out = te._grounded_fallback_questions("short_answer", 3, CONCEPT, DOMAIN, avoid=["Which one is a topic covered in X?", "Customer Journey"])
    assert "Customer Journey" not in {re.search(r'"([^"]+)"', q["question"]).group(1) for q in out}


def test_generate_test_passes_earlier_mcq_answers_to_later_filler(engine, monkeypatch, junky_roadmaps):
    seen = []
    real = te.TestEngine._generate_questions_of_type

    def spy(self, q_type, count, marks, *a, **kw):
        seen.append((q_type, list(kw.get("avoid_topics") or [])))
        return real(self, q_type, count, marks, *a, **kw)

    monkeypatch.setattr(te.TestEngine, "_generate_questions_of_type", spy)
    Model(monkeypatch, [ConnectionError("x")] * 6)
    engine.generate_test(CONCEPT, DOMAIN, LESSON)
    assert [t for t, _ in seen] == ["mcq", "true_false", "short_answer"]
    assert seen[0][1] == [] and len(seen[1][1]) == 4 and len(seen[2][1]) == 4      # the 4 MCQ answers reach the later types
