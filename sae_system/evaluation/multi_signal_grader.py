"""Multi-signal grading — Phase 9.

Motivated by a measured, not intuited, gap: evaluation/reports/phase9_baseline.json
shows the single-signal semantic grader (evaluation/semantic_auditor.grade_response)
scores 0% accuracy on 'different_abstraction' answers and 33% on
'hard_application_correct' answers (false negatives — correct answers marked
wrong), while also scoring 0% on 'confidently_wrong', 'keyword_only', and
'negation' answers (false positives — wrong answers marked correct, similarity
0.70-0.88 despite being factually wrong). A threshold sweep (0.40-0.85) never
fixes both failure modes at once — see docs/GRADING_EVALUATION_ARCHITECTURE.md.

This module does NOT modify or replace evaluation.semantic_auditor.grade_response
(Phase 9 Step 10: preserve existing API compatibility — test_engine.py,
auditor_agent.py, state_graph.py, adaptive_tutor_agent.py all call it directly
and are unaffected by this file existing). It adds a new, opt-in, richer
grading path: grade_multi_signal().

Signals:
  1. Semantic similarity  — reuses grade_response(), unchanged.
  2. Lexical coverage     — deterministic bag-of-words overlap between the
                             reference answer's key terms and the student
                             answer. Intentionally simple: no per-answer
                             "concept representation" exists anywhere in the
                             repo to reuse (roadmap modules have a `concepts`
                             list, but that's per-module, not per-question),
                             so a richer NLP pipeline would be new
                             infrastructure built on nothing, not reuse.
  3 & 5. Contradiction / completeness — folded into the LLM judge's
                             structured output rather than built as separate
                             heuristics. A reliable heuristic negation/
                             contradiction detector needs real NLI, which
                             doesn't exist in this repo; a naive keyword
                             heuristic (e.g. flagging "not"/"n't") would be
                             unreliable and is exactly the kind of fake
                             signal Phase 9 prohibits. This consolidation is
                             a deliberate, documented decision.
  4. LLM judge            — one local Ollama call, structured JSON output,
                             same sovereignty guard as every other agent in
                             this codebase. Degrades safely (returns None,
                             never fabricates a verdict) on any failure.
"""

from __future__ import annotations

import json
import re
from typing import Dict, List, Optional

from json_repair import repair_json
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_ollama import ChatOllama

from agents.tutor_agent import SovereigntyError
from config import OLLAMA_BASE_URL, OLLAMA_MODEL
from evaluation import perf_trace as _perf
from evaluation.semantic_auditor import grade_response

# Not from the repo's existing stopword list — none exists. This is a small,
# fixed, documented list of English function words, not a fabricated NLP
# resource.
_STOPWORDS = frozenset("""
a an the is are was were be been being to of in on at for with and or but
if then so that this these those it its it's as by from into about over
under between up down out off again further than too very can will just
do does did doing have has had having you your yours i we our ours they
their them he she his her not no nor which what who whom
""".split())


def _key_terms(text: str) -> set:
    words = re.findall(r"[a-zA-Z']+", text.lower())
    return {w for w in words if len(w) > 2 and w not in _STOPWORDS}


def coverage_score(student_answer: str, reference_answer: str) -> float:
    """Fraction of the reference answer's key terms that also appear in the
    student answer. Deterministic, no embeddings, no LLM call. In [0, 1];
    0.0 if the reference has no key terms (nothing to cover) or the student
    answer is empty.
    """
    ref_terms = _key_terms(reference_answer)
    if not ref_terms or not student_answer:
        return 0.0
    student_terms = _key_terms(student_answer)
    return round(len(ref_terms & student_terms) / len(ref_terms), 4)


_JUDGE_SYSTEM_PROMPT = (
    "You are a strict but fair grading assistant for an educational platform. "
    "Given a question, a reference (model) answer, and a student's answer, "
    "judge the student's answer by MEANING, not exact wording — a student "
    "may use different words, an analogy, or a different valid angle and "
    "still be correct, as long as the core meaning matches the reference. "
    "Return ONLY valid JSON: "
    '{"label": "correct"|"partial"|"incorrect", "contradicts_reference": true|false, '
    '"reasoning": "one concise sentence"}. No markdown, no extra text.'
)


class LLMJudge:
    """Local-only structured judge. Same sovereignty guard as every other
    agent (TutorAgent, RoadmapAgent, SearcherAgent, AskSAEAgent,
    AdaptiveTutorAgent) — raises SovereigntyError before constructing
    anything if OLLAMA_BASE_URL isn't localhost/127.0.0.1.
    """

    def __init__(self) -> None:
        if not (
            OLLAMA_BASE_URL.startswith("http://localhost")
            or OLLAMA_BASE_URL.startswith("http://127.0.0.1")
        ):
            raise SovereigntyError(f"OLLAMA_BASE_URL '{OLLAMA_BASE_URL}' is not localhost.")
        self._llm = ChatOllama(base_url=OLLAMA_BASE_URL, model=OLLAMA_MODEL, temperature=0.0)

    def judge(self, question: str, student_answer: str, reference_answer: str) -> Optional[Dict]:
        """Returns {label, contradicts_reference, reasoning} or None on any
        failure (Ollama unreachable, malformed response) — never fabricates
        a verdict when it can't actually judge.
        """
        prompt = (
            f"Question: {question}\n\n"
            f"Reference answer: {reference_answer}\n\n"
            f"Student answer: {student_answer}"
        )
        try:
            with _perf.label("grader.llm_judge"):
                response = self._llm.invoke([
                    SystemMessage(content=_JUDGE_SYSTEM_PROMPT),
                    HumanMessage(content=prompt),
                ])
            raw = response.content.strip().strip("```json").strip("```").strip()
            data = json.loads(repair_json(raw))
            label = data.get("label")
            if label not in ("correct", "partial", "incorrect"):
                return None
            return {
                "label": label,
                "contradicts_reference": bool(data.get("contradicts_reference", False)),
                "reasoning": str(data.get("reasoning", "")).strip(),
            }
        except Exception:
            return None


def grade_multi_signal(
    question: str,
    student_answer: str,
    reference_answer: str,
    threshold: float,
    judge: Optional[LLMJudge] = None,
) -> Dict:
    """Combine semantic similarity, lexical coverage, and (if a judge is
    supplied) the LLM judge into one explainable grading decision.

    Decision rule (evidence-derived — see evaluation/reports/phase9_multisignal.json
    and docs/GRADING_EVALUATION_ARCHITECTURE.md for the full benchmark
    comparison behind this specific rule):
      1. If the LLM judge ran successfully, its label is authoritative for
         pass/fail. Measured on the 49-item gold set: 98.0% accuracy, 100%
         precision, 0 false positives, 1 false negative — vs. 61.2%
         accuracy for semantic-only. It specifically fixed the categories
         that motivated this phase: different_abstraction 0%->100%,
         hard_application_correct 33%->100%, while also fixing semantic's
         false positives on confidently_wrong/negation/keyword_only
         (all 0%->100%).
      2. `label == "partial"` is NEVER treated as passing. This was an
         actual bug caught during Phase 9 benchmarking: naively mapping
         partial->pass would have turned 10 correctly-identified partial
         answers into false positives, since the existing gold labels (and
         the rest of SAE's mastery system) are strictly binary. Partial is
         exposed for evidence/future use (Step 12), not silently promoted
         to full credit.
      3. Coverage was benchmarked as an OR-combination with semantic
         (`semantic >= threshold OR coverage >= 0.5`) and made results
         *worse* (59.2% vs 61.2% accuracy) — so it is NOT part of the
         decision rule. It's still computed and exposed in `reason` as a
         cheap, transparent secondary data point, per Step 11's
         "every reason should be tied to actual measured signals," not
         because it improves the label.
      4. If the judge is unavailable (Ollama down, disabled, malformed
         response), degrade to semantic-only: correct if
         semantic >= threshold. No "partial" band without the judge —
         nothing else in the pipeline can produce that distinction.

    Never fabricates a value that wasn't actually computed: `llm_judge` is
    None (not a guessed dict) whenever the judge didn't run or failed.
    """
    semantic = grade_response(student_answer, reference_answer) if student_answer else 0.0
    coverage = coverage_score(student_answer, reference_answer)

    judge_result = judge.judge(question, student_answer, reference_answer) if judge else None

    if judge_result is not None:
        label = judge_result["label"]
        reason = (
            f"LLM judge: {judge_result['reasoning']} "
            f"(semantic={semantic:.2f}, coverage={coverage:.2f})"
        )
    else:
        label = "correct" if semantic >= threshold else "incorrect"
        reason = (
            f"LLM judge unavailable — degraded to semantic-only "
            f"(semantic={semantic:.2f} vs threshold={threshold:.2f}, coverage={coverage:.2f} not used)"
        )

    return {
        "semantic_score": round(semantic, 4),
        "coverage_score": coverage,
        "llm_judge": judge_result,
        "label": label,
        "passed": label == "correct",
        "reason": reason,
    }
