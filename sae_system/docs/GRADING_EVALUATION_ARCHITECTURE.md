# Grading Evaluation Architecture — Phase 9

Methodology: **Measure → Diagnose → Improve → Validate.** No change to the
production grader was made until the baseline was measured; no threshold
was changed without benchmark evidence; the multi-signal evaluator was only
integrated into the one caller (Adaptive Tutor) actually re-validated
against the original failure it was built to fix.

## 1. Current baseline (Step 1 audit)

`evaluation/semantic_auditor.py::grade_response(student_response, reference_answer) -> float`
— cosine similarity between L2-normalised `all-MiniLM-L6-v2` sentence
embeddings (`sentence-transformers`, local, CPU-only), clamped to `[0, 1]`.
Pure function, no side effects, returns a bare float — **unchanged by this
phase** (see Section 6, compatibility).

`config.SEMANTIC_PASS_THRESHOLD = 0.60` is the single source of truth
(established Phase 2; previously duplicated with conflicting defaults 0.45
vs 0.85 across `test_engine.py`/`auditor_agent.py`/`state_graph.py` — that
inconsistency no longer exists; there was nothing left to find here in
Step 1's "are there multiple thresholds/defaults" check). Consumed by
`test_engine.py::grade_test`, `agents/auditor_agent.py`,
`orchestration/state_graph.py`, `agents/adaptive_tutor_agent.py`.

Pass/fail is strictly binary: `passed = similarity >= SEMANTIC_PASS_THRESHOLD`.
No partial score is represented anywhere in production — `TestEngine.grade_test`
awards full marks or zero for short-answer questions, never partial marks.
Malformed/empty answers short-circuit to `similarity = 0.0` without calling
the embedder (`test_engine.py`, `adaptive_tutor_agent.py` both do this).
Mastery propagation: the test-grading path hard-overwrites
`KnowledgeGraph.update_mastery(concept_id, percentage/100)`; the Phase 8
Adaptive Tutor path blends `0.7*old + 0.3*new_evidence` rather than
overwriting (a single question is much lower-stakes than a full test).

## 2. Existing benchmark material found and reused (Step 2)

`sae_system/data/eval/grading_gold_set.json` and
`sae_system/evaluation/grading_evaluator.py` **already existed from Phase 2**
— a 40-item hand-labeled short-answer gold set plus
`load_gold_set`/`evaluate_semantic_grader`/`compare_thresholds`/
`evaluate_mcq_tf_pipeline`. Phase 9 **extended** this rather than building
a parallel benchmark: 9 new items were added (bringing the short_answer set
to 49) and `grading_evaluator.py` gained two new functions
(`evaluate_by_category`, `sweep_thresholds`). No new gold-set file or
benchmark runner module was created — extending the existing one was both
possible and clearly the right call here.

## 3. Benchmark structure

`data/eval/grading_gold_set.json`'s `short_answer` array. Each item:
```json
{
  "id": "sa_048", "question": "...", "reference_answer": "...",
  "candidate_answer": "...", "expected_label": "pass|fail",
  "expected_label_3way": "correct|partial|incorrect", "case": "..."
}
```
`expected_label` (binary) is the original Phase 2 field — every existing
consumer (`system_evaluator.py`, `page_system_evaluation.py`) that reads it
is unaffected by the phase 9 additions. `expected_label_3way` is new and
additive, backward-compatible, retrofitted onto all 40 original items via a
fixed `case -> label` mapping and set explicitly on all 9 new items. Every
label is human-specified, not LLM-generated (Step 4).

14 categories, 49 items total:

| Case | n | Maps to Phase 9 category |
|---|---|---|
| correct | 6 | A — Clearly correct |
| paraphrase | 5 | B — Correct, different wording |
| different_abstraction *(new)* | 4 | C — Correct, different abstraction |
| partial_answer | 4 | D — Partially correct |
| confidently_wrong | 4 | E — Incorrect, lexically similar |
| semantically_similar_but_factually_wrong | 4 | E |
| irrelevant | 3 | F — Irrelevant |
| empty_answer | 2 | G — Empty |
| hard_application_correct *(new)* | 3 | H — Hard application, correct |
| hard_application_partial *(new)* | 2 | H — Hard application, partial |
| negation | 3 | (false-positive stress test) |
| keyword_only | 3 | (false-positive stress test) |
| ambiguous | 3 | (false-positive stress test) |
| overly_verbose | 3 | (length-robustness stress test) |

`sa_048` is the **verbatim** question/reference/answer from Phase 8's live
Scenario B run — not a re-invented example. Its gold label is `partial`
(3-way) / `fail` (binary), decided by re-reading the actual answer: it names
the right general category ("classification") but never commits to a
recommendation for the specific scenario asked. This was a deliberate
choice **not** to force the original failure case to "correct" — see
Section 8.

## 4. Baseline results (Step 5) — `evaluation/reports/phase9_baseline.json`

At production threshold (0.60), N=49:

**Accuracy 61.2% · Precision 54.2% · Recall 61.9% · F1 57.8%** (TP=13 FP=11 TN=17 FN=8)

Category-level accuracy (the number that matters — the aggregate above
hides two opposite failure modes):

| Category | Accuracy | Mean similarity | Failure mode |
|---|---|---|---|
| different_abstraction | **0%** (0/4) | 0.376 | False negative — correct answers scored too low |
| hard_application_correct | **33%** (1/3) | 0.561 | False negative |
| paraphrase | 60% (3/5) | 0.574 | Mixed |
| semantically_similar_but_factually_wrong | 75% (3/4) | 0.566 | Mixed |
| confidently_wrong | **0%** (0/4) | 0.766 | False positive — wrong answers scored too high |
| keyword_only | **0%** (0/3) | 0.701 | False positive |
| negation | **0%** (0/3) | 0.884 | False positive, most severe |
| correct / irrelevant / empty / ambiguous / overly_verbose / partial_answer / hard_application_partial | 100% | — | Grader already handles these |

This is the precise, measured version of Phase 8's informal observation:
cosine similarity conflates *topical relatedness* with *correctness*. It
scores negated, keyword-dumped, and confidently-wrong-but-on-topic answers
as highly similar (0.70–0.88) purely because they share vocabulary with the
reference, while scoring genuinely correct answers that use different
words, analogies, or framings as dissimilar (0.34–0.56).

## 5. Threshold sweep (Step 6) — no change justified

Swept 0.40 to 0.85 in 0.05 steps against all 49 items:

| Threshold | Accuracy | F1 |
|---|---|---|
| 0.40 | 59.2% | 64.3% (best recall) |
| 0.55 | 59.2% | 58.3% |
| **0.60 (current)** | **61.2%** | **57.8%** |
| 0.65 | 55.1% | 47.6% |
| 0.85 | 57.1% | 16.0% (recall collapses) |

0.60 is the single best-accuracy point in the sweep and near-best on F1.
Lowering it would worsen the false-positive categories (confidently_wrong/
negation/keyword_only already score 0.70+ similarity — a lower threshold
only passes more of them); raising it would worsen the false-negative
categories further (different_abstraction/hard_application_correct already
score under 0.60). **No threshold in the sweep fixes both failure modes at
once — this is a structural ceiling of a single similarity signal, not a
tuning problem. The production threshold was not changed.**

## 6. Multi-signal evaluator (Steps 7-9)

Three signals investigated; two kept, one measured and dropped:

- **Semantic similarity** — reused unchanged (`grade_response`).
- **Lexical coverage** (`coverage_score`, new, `evaluation/multi_signal_grader.py`)
  — deterministic bag-of-words overlap between the reference answer's
  content words (a small fixed stopword list, no repo NLP resource existed
  to reuse for per-answer concept extraction — documented as a deliberate
  "simple because nothing richer exists" choice, not a lazy shortcut) and
  the student answer. **Measured, not assumed, contribution**: combined as
  `semantic >= threshold OR coverage >= 0.5`, accuracy **dropped** to 59.2%
  (from 61.2%) — it introduced a new false positive
  (`semantically_similar_but_factually_wrong` dropped 75%->50%) without
  fixing any existing failure category. **Not used in the production
  decision rule** as a result — kept only as a cheap, transparent value
  surfaced in `reason` text, per Step 8's "do not overfit": a signal that
  measurably doesn't help isn't kept just because it exists.
- **LLM judge** (`LLMJudge`, `evaluation/multi_signal_grader.py`) — one
  local Ollama call (`ChatOllama`, `temperature=0.0`), structured JSON
  output `{label: correct|partial|incorrect, contradicts_reference: bool,
  reasoning: str}`. This is where Step 7's "contradiction" and
  "completeness" signals were **deliberately folded into one structured
  call rather than built as separate heuristics** — a reliable heuristic
  negation/contradiction detector needs real NLI, which nothing in this
  repo provides; a naive keyword check (flagging "not"/"n't") would be
  exactly the kind of unreliable fake signal Step 8 prohibits. Degrades
  safely: returns `None` (never a fabricated verdict) on any Ollama failure
  or malformed response — measured 0 failures across 49 real calls in this
  benchmark run.

**Measured result — `evaluation/reports/phase9_multisignal.json`:**

| Configuration | Accuracy | Precision | Recall | F1 |
|---|---|---|---|---|
| A: Semantic-only (baseline) | 61.2% | 54.2% | 61.9% | 57.8% |
| B: Semantic OR coverage≥0.5 | 59.2% (worse) | 52.0% | 61.9% | 56.5% |
| **C: LLM judge (label="correct"=pass)** | **98.0%** | **100%** | 95.2% | **97.6%** |
| D: C + contradiction override | 98.0% | 100% | 95.2% | 97.6% (identical — override never triggered beyond C) |

Category breakdown for **C**: every category reached 100% except
`overly_verbose` (67%, 2/3 — one false negative, see Section 9) — including
**different_abstraction 0%→100%** and **hard_application_correct 33%→100%**,
the two categories that directly motivated this phase, and
**confidently_wrong/negation/keyword_only, all 0%→100%**, fixing the
semantic grader's false-positive problem as a side effect, not a separate
engineering effort.

**A real bug was caught during this benchmarking, not before it**: the
first implementation mapped `label in ("correct", "partial")` to "pass."
Measuring against the gold set showed this would have turned 10
correctly-identified partial answers into false positives, since the
existing binary gold labels (and the rest of SAE's mastery system) treat
partial answers as `fail`. Fixed to `label == "correct"` only — see
`multi_signal_grader.grade_multi_signal`'s docstring for the full
before/after.

## 7. Decision rule (Step 9) — rule-based, not a tuned weighted formula

```
if judge ran successfully:
    label = judge.label                      # authoritative; measured 98.0% accuracy
else:
    label = "correct" if semantic >= threshold else "incorrect"   # degrade path
passed = (label == "correct")                 # "partial" never silently counts as pass
```

A rule-based decision (judge label is authoritative, full stop) outperformed
every weighted-combination alternative tried (semantic+coverage) and is
strictly easier to explain than a tuned formula — exactly the outcome
Step 9 says to prefer when it happens. No arbitrary weights were needed.

## 8. Partial credit (Step 12)

The judge's `partial` label is preserved and exposed (`result["label"]`,
`result["llm_judge"]`), but:
- It is **not** treated as passing for binary pass/fail decisions (Section 6).
- Where it **is** now used: `AdaptiveTutorAgent.evaluate_and_update`'s
  mastery blend. The LLM never assigns a mastery number — a fixed, disclosed
  table (`_LABEL_TO_EVIDENCE_SCORE = {"correct": 1.0, "partial": 0.5,
  "incorrect": 0.0}`) converts the judge's category into the same
  `0.7*old + 0.3*evidence` blend Phase 8 already used, so a partial answer
  now moves mastery by half as much as a fully correct one instead of being
  indistinguishable from a wrong one. This is Phase 9's actual partial-credit
  integration — deliberately scoped to the Adaptive Tutor only (Section 10),
  not to `TestEngine.grade_test`'s marks-awarded logic, which stays
  strictly binary (full/zero marks) — that path affects roadmap unlocking
  and certification and was not touched (Step 13).

## 9. Adaptive Tutor validation (Step 20) — see report for live numbers

Re-ran Phase 8's exact Scenario B question/reference/answer (verbatim, not
re-generated) through the new `evaluate_and_update`, plus fresh Scenario
A/B runs with newly-generated questions. Results reported in the Phase 9
final report rather than duplicated here, to avoid this doc going stale —
the point of this section is the *method* (re-run the literal original
failure case, don't just claim victory) rather than a number that will
drift as the model/questions vary run to run.

## 10. Production integration (Step 13) — scope boundary, explicit

**Integrated**: `agents/adaptive_tutor_agent.py::AdaptiveTutorAgent.evaluate_and_update`
now uses `grade_multi_signal` instead of calling `grade_response` directly.
This is the one caller Phase 8 already identified as suffering from the
false-negative problem, and the one this phase explicitly re-validates
(Step 20).

**Deliberately NOT integrated**: `evaluation/test_engine.py::TestEngine.grade_test`
(the dashboard's main test-grading path — affects `modules_passed`,
roadmap unlocking, and certificate generation) and `agents/auditor_agent.py`
(the CLI-only dialogue path — affects `mastery_log.jsonl` proof-of-learning
entries). Both would need their own explicit before/after validation against
their specific downstream effects (Step 13's exact warning) before adopting
a ~5-18s-per-call judge in a path that currently grades 3 short-answer
questions per test submission (adding 15-54s to every test) or gates a
tamper-evident proof log. Left for a future phase's deliberate decision, not
silently changed here.

## 11. Compatibility (Step 10)

`evaluation/semantic_auditor.py::grade_response` — **byte-for-byte
unchanged**. All four existing callers (`test_engine.py`, `auditor_agent.py`,
`state_graph.py`, and `adaptive_tutor_agent.py`'s degrade path) continue to
work exactly as before. `grade_multi_signal` is a new, separate function in
a new module — opt-in, not a replacement.

## 12. Sovereignty (Step 16)

`LLMJudge.__init__` performs the identical guard every other agent in this
codebase uses: raises `SovereigntyError` (imported, not redefined) before
constructing anything if `OLLAMA_BASE_URL` isn't `localhost`/`127.0.0.1`.
Verified directly: non-local URL → raised; localhost → succeeds
(`ChatOllama` construction is lazy, no network call at construction time).
On any judge failure, `grade_multi_signal` degrades to semantic-only — it
never substitutes a hosted provider, and no such fallback path exists
anywhere in this code to be accidentally triggered.

## 13. Performance (Step 15)

Semantic-only: effectively instant per call (local embedding, no network).
LLM judge: mean **8.25s** per call (N=47, excludes two latency values
inflated by an unrelated mid-benchmark session pause — see
`evaluation/reports/phase9_multisignal.json`'s `judge_performance` note),
min 4.9s, max 17.7s. Zero judge failures across 49 real calls. This ~8s
cost is the direct reason the judge was **not** wired into `TestEngine`
(3 short-answer questions/test) or high-frequency paths — it's a reasonable
one-time wait for a single Adaptive Tutor question/answer exchange, not for
a full test submission.

## 14. Known limitations (real, not hypothetical)

- One measured false negative in the 49-item benchmark: `sa_037`
  (overly_verbose case) — judge said "incorrect," gold says "correct."
  A genuinely long, correct-but-rambling answer occasionally reads as
  evasive to the judge. 1/49 — disclosed, not hidden.
- 3-way label agreement (`correct`/`partial`/`incorrect` vs
  `expected_label_3way`) is 81.6% (40/49), lower than the 98.0% binary
  figure — the judge is more willing to call an answer "partial" than the
  hand-authored gold labels are in several categories (`ambiguous`,
  `keyword_only`). This is a real, disclosed disagreement about where the
  partial/incorrect boundary should sit, not a bug — binary pass/fail
  (what production actually uses) is unaffected since `partial` never
  counts as `pass` either way.
- The 49-item gold set was authored by the same process implementing this
  phase. A 98.0% result on a self-authored benchmark is real evidence the
  approach works on the failure modes it targets, but is not independent
  proof of generalization to arbitrary future questions — normal validity
  caveat for any small hand-built benchmark, stated plainly rather than
  overclaimed.
- LLM judge latency (~8s/call) makes it unsuitable for the full-test-grading
  path without further work (batching, a faster/smaller judge model, or
  async grading) — not attempted in this phase, since `TestEngine` wasn't
  in scope (Section 10).
