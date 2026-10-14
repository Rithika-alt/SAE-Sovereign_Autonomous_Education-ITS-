# Phase 9 Error Analysis

Source data: `phase9_baseline.json` (semantic-only), `phase9_multisignal.json`
(all configurations), `phase9_multisignal_raw.json` (per-item raw signals).
49-item `short_answer` gold set (`data/eval/grading_gold_set.json`).

## Overall

| Grader | Accuracy | Precision | Recall | F1 |
|---|---|---|---|---|
| Semantic-only (production, threshold 0.60) | 61.2% | 54.2% | 61.9% | 57.8% |
| Semantic OR coverage≥0.5 | 59.2% | 52.0% | 61.9% | 56.5% |
| **LLM judge (label="correct"=pass)** | **98.0%** | **100%** | 95.2% | **97.6%** |

## By category (semantic-only baseline → LLM judge)

| Category | n | Semantic-only | LLM judge |
|---|---|---|---|
| correct | 6 | 100% | 100% |
| paraphrase | 5 | 60% | 100% |
| **different_abstraction** | 4 | **0%** | **100%** |
| partial_answer | 4 | 100% | 100% |
| confidently_wrong | 4 | **0%** | **100%** |
| semantically_similar_but_factually_wrong | 4 | 75% | 100% |
| irrelevant | 3 | 100% | 100% |
| empty_answer | 2 | 100% | 100% |
| **hard_application_correct** | 3 | **33%** | **100%** |
| hard_application_partial | 2 | 100% | 100% |
| negation | 3 | **0%** | **100%** |
| keyword_only | 3 | **0%** | **100%** |
| ambiguous | 3 | 100% | 100% |
| overly_verbose | 3 | 100% | 67% |

Bold rows are where semantic-only failed outright (0-33%) — the LLM judge
fixed every one of them without regressing any category that was already at
100%, except `overly_verbose` (see below).

## False positives — semantic-only (11 items, all fixed by the judge)

All 4 `confidently_wrong` + all 3 `negation` + all 3 `keyword_only` +
1 `semantically_similar_but_factually_wrong` (`sa_032`). Representative
example: `sa_022` (negation) — reference says TCP guarantees reliable
delivery, candidate says TCP guarantees *no* reliability at all (the
opposite claim) — semantic similarity 0.903 (highly confident wrong
"pass"), because the two sentences share almost all their vocabulary and
only differ by negation. The judge correctly read `contradicts_reference`
as unimportant to check separately here since it directly labeled this
"incorrect" — cosine similarity has no mechanism to notice negation at all;
an LLM reading for meaning does.

## False negatives — semantic-only (8 items, 7 fixed by the judge, 1 remains)

All 4 `different_abstraction` + 2/3 `hard_application_correct` +
2/5 `paraphrase` (`sa_009`, `sa_010`) — all fixed by the judge. Example:
`sa_010` (paraphrase) — reference and candidate describe the same firewall
concept with almost no shared vocabulary; similarity 0.369, well under
threshold; judge correctly reads them as equivalent in meaning.

## Remaining false negative under the LLM judge (1 item)

`sa_037` (`overly_verbose`, expected "correct", judge said "incorrect"). A
long, correct-but-meandering answer about `for` loops that buries the actual
answer in several sentences of unrelated framing before getting to the
point. The judge's reasoning (from the raw run) treated the verbosity as
evasiveness. This is disclosed, not hidden — see
`docs/GRADING_EVALUATION_ARCHITECTURE.md` Section 14.

## The Phase 8 Scenario B case, specifically (`sa_048`)

Judge label: **partial** (gold label: partial). The judge's own reasoning:
*"The student's answer correctly identifies supervised learning as a
suitable approach, but lacks specificity regarding the type of algorithm
that would be most appropriate for this problem."* This **matches** the
gold label assigned during benchmark construction — the original Phase 8
"failure" was, on reflection, a genuinely partial answer, not a clean
grader bug. The measured, real improvement from this phase is on the
broader `hard_application_correct` category (33%→100%), where students
*did* give specific, correct answers in different words — that category is
where semantic similarity actually failed and the judge actually fixed it.
Re-validation (Phase 9 Step 20, live) confirmed the judge does not simply
rubber-stamp the original failure case as "correct" — it independently
reached the same partial verdict, and that verdict is now visible and
usable (feeds a 0.5-weighted mastery blend) instead of being an
indistinguishable hard "fail" the way it was in Phase 8's binary path.

## 3-way label disagreements (judge vs. hand-authored `expected_label_3way`)

9/49 items (81.6% agreement). All 9 disagreements are the judge calling
something "partial" where the gold label says "incorrect" (`sa_025`,
`sa_027`, `sa_028`, `sa_029`, `sa_034`, `sa_035`, `sa_036`) — keyword-dump
and ambiguous non-answers that do touch the right topic — plus one
"correct"↔"partial" disagreement (`sa_012`) and the `sa_037` case above.
None of these affect the binary production accuracy figure, since
`partial` never counts as `pass` regardless. They matter only if/when a
genuine partial-credit UI/pipeline is built beyond the Adaptive Tutor's
mastery blend (deferred — see architecture doc Section 10).
