"""Adaptive Tutor — Phase 8.

"Teach me based on what you know about my current understanding," as
distinct from Phase 7's Ask SAE ("answer my question"). See
docs/ADAPTIVE_TUTOR_ARCHITECTURE.md for the full design rationale.

Deterministic, rule-based adaptation only — no ML personalization, no
reinforcement learning. The LLM explains and asks; it never assigns
mastery, score, or completion. Those stay governed by the existing
evaluator (evaluation.semantic_auditor.grade_response) and the existing
mastery store (memory.graph_engine.KnowledgeGraph.update_mastery).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from json_repair import repair_json
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_ollama import ChatOllama

from agents.tutor_agent import SovereigntyError, TutorAgent
from config import OLLAMA_BASE_URL, OLLAMA_MODEL, SEMANTIC_PASS_THRESHOLD
from evaluation import perf_trace as _perf

# Mirrors the identical constant/purpose in evaluation/system_evaluator.py
# and evaluation/recommendation_engine.py — not a new invented value.
STALE_REVIEW_DAYS = 14

# New in Phase 8, disclosed here — see docs/ADAPTIVE_TUTOR_ARCHITECTURE.md
# Section 6 for why a single question blends into mastery rather than
# overwriting it the way a full 10-question test does.
MASTERY_BLEND_WEIGHT_NEW = 0.3

MODE_STRUGGLING = "struggling"
MODE_DEVELOPING = "developing"
MODE_STRONG = "strong"
MODE_MASTERED_RETENTION = "mastered_retention"

_MODE_LABELS = {
    MODE_STRUGGLING: "Guided Practice",
    MODE_DEVELOPING: "Guided Practice",
    MODE_STRONG: "Challenge",
    MODE_MASTERED_RETENTION: "Concept Review",
}


@dataclass(frozen=True)
class TutorState:
    student_id: str
    domain: str
    concept_id: str
    mastery: float
    mode: str
    recent_attempts: List[Dict] = field(default_factory=list)
    recent_failure: bool = False
    weak_prerequisite: Optional[str] = None
    days_since_review: Optional[int] = None
    reasons: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class TeachingStrategy:
    mode_label: str
    explanation_depth: str      # "scaffolded" | "standard" | "concise"
    example_style: str          # "concrete_simple" | "guided" | "application"
    question_difficulty: str    # "easy" | "medium" | "hard"
    hints_enabled: bool
    review_prerequisite: Optional[str]
    objective: str


# ---------------------------------------------------------------------------
# Diagnosis — pure read, no LLM
# ---------------------------------------------------------------------------

def _recent_attempts_for_concept(student_id: str, concept_id: str, limit: int = 3) -> List[Dict]:
    from evaluation.event_log import read_events, EVT_TEST_ATTEMPT

    events = [
        e for e in read_events(student_id=student_id, event_type=EVT_TEST_ATTEMPT)
        if e.get("concept_id") == concept_id
    ]
    events.sort(key=lambda e: e.get("timestamp", ""))
    return events[-limit:]


def _find_weak_prerequisite(student_id: str, concept_id: str) -> Optional[str]:
    try:
        from memory.graph_engine import KnowledgeGraph

        graph = KnowledgeGraph(student_id=student_id)
        for prereq_id in graph.get_prerequisites(concept_id):
            if graph.get_mastery(prereq_id) < SEMANTIC_PASS_THRESHOLD:
                return prereq_id
    except Exception:
        pass
    return None


def diagnose_tutor_state(student_id: str, concept_id: str, domain: str) -> TutorState:
    """Determine the student's actual current state for one concept.
    Every field here is a real measured value or an explicit None/empty —
    nothing here is inferred or fabricated.
    """
    from memory.graph_engine import KnowledgeGraph, MASTERY_THRESHOLD

    graph = KnowledgeGraph(student_id=student_id)
    mastery = graph.get_mastery(concept_id)

    days_since_review: Optional[int] = None
    try:
        data = graph.get_graph_data()
        node = next((n for n in data.get("nodes", []) if n.get("id") == concept_id), None)
        if node and node.get("last_reviewed"):
            reviewed_dt = datetime.fromisoformat(node["last_reviewed"])
            if reviewed_dt.tzinfo is None:
                reviewed_dt = reviewed_dt.replace(tzinfo=timezone.utc)
            days_since_review = (datetime.now(timezone.utc) - reviewed_dt).days
    except Exception:
        days_since_review = None

    recent_attempts = _recent_attempts_for_concept(student_id, concept_id)
    recent_failure = bool(recent_attempts) and not recent_attempts[-1].get("passed", True)

    reasons: List[str] = []

    if mastery < SEMANTIC_PASS_THRESHOLD:
        mode = MODE_STRUGGLING
        reasons.append(
            f"Mastery is {mastery:.0%}, below the {SEMANTIC_PASS_THRESHOLD:.0%} pass threshold."
        )
    elif mastery < MASTERY_THRESHOLD:
        mode = MODE_DEVELOPING
        reasons.append(
            f"Mastery is {mastery:.0%} — passing but below the "
            f"{MASTERY_THRESHOLD:.0%} mastered threshold."
        )
    else:
        if days_since_review is not None and days_since_review > STALE_REVIEW_DAYS:
            mode = MODE_MASTERED_RETENTION
            reasons.append(
                f"Mastery is {mastery:.0%} but it was last reviewed "
                f"{days_since_review} days ago (over the {STALE_REVIEW_DAYS}-day "
                "retention window)."
            )
        else:
            mode = MODE_STRONG
            reasons.append(f"Mastery is {mastery:.0%}, at or above the mastered threshold.")

    if recent_failure:
        if mode in (MODE_STRONG, MODE_MASTERED_RETENTION):
            mode = MODE_DEVELOPING
        last = recent_attempts[-1]
        reasons.append(
            f"Most recent test attempt on this concept scored "
            f"{last.get('percentage', 0):.0f}% and did not pass."
        )

    weak_prereq = _find_weak_prerequisite(student_id, concept_id)
    if weak_prereq:
        reasons.append(
            f"Prerequisite '{weak_prereq.replace('_', ' ').title()}' has mastery "
            f"below the {SEMANTIC_PASS_THRESHOLD:.0%} threshold."
        )

    return TutorState(
        student_id=student_id,
        domain=domain,
        concept_id=concept_id,
        mastery=mastery,
        mode=mode,
        recent_attempts=recent_attempts,
        recent_failure=recent_failure,
        weak_prerequisite=weak_prereq,
        days_since_review=days_since_review,
        reasons=reasons,
    )


# ---------------------------------------------------------------------------
# Strategy — pure rule, no LLM
# ---------------------------------------------------------------------------

def choose_teaching_strategy(state: TutorState) -> TeachingStrategy:
    """Deterministic mapping from TutorState.mode to concrete teaching
    parameters. See docs/ADAPTIVE_TUTOR_ARCHITECTURE.md Section 5 for the
    rule table this implements.
    """
    concept_label = state.concept_id.replace("_", " ").title()

    if state.mode == MODE_STRUGGLING:
        strategy = TeachingStrategy(
            mode_label=_MODE_LABELS[MODE_STRUGGLING],
            explanation_depth="scaffolded",
            example_style="concrete_simple",
            question_difficulty="easy",
            hints_enabled=True,
            review_prerequisite=state.weak_prerequisite,
            objective=f"Build a solid foundation in {concept_label} with a simple, concrete example.",
        )
    elif state.mode == MODE_DEVELOPING:
        strategy = TeachingStrategy(
            mode_label=_MODE_LABELS[MODE_DEVELOPING],
            explanation_depth="standard",
            example_style="guided",
            question_difficulty="medium",
            hints_enabled=True,
            review_prerequisite=state.weak_prerequisite,
            objective=f"Reinforce {concept_label} with a guided example and a moderate question.",
        )
    elif state.mode == MODE_MASTERED_RETENTION:
        strategy = TeachingStrategy(
            mode_label=_MODE_LABELS[MODE_MASTERED_RETENTION],
            explanation_depth="concise",
            example_style="application",
            question_difficulty="hard",
            hints_enabled=False,
            review_prerequisite=state.weak_prerequisite,
            objective=f"Refresh {concept_label} with an application question, since it hasn't been reviewed recently.",
        )
    else:  # MODE_STRONG
        strategy = TeachingStrategy(
            mode_label=_MODE_LABELS[MODE_STRONG],
            explanation_depth="concise",
            example_style="application",
            question_difficulty="hard",
            hints_enabled=False,
            review_prerequisite=state.weak_prerequisite,
            objective=f"Stretch understanding of {concept_label} with a harder, application-oriented question.",
        )
    return strategy


_SECTIONS_BY_DEPTH = {
    "scaffolded": ["introduction", "example"],
    "standard": ["introduction", "theory", "example"],
    "concise": ["theory", "applications"],
}

_QUESTION_SYSTEM_PROMPT = (
    "You are SAE, a local educational tutor. Generate exactly one short-answer "
    "question and a model reference answer, at the requested difficulty. "
    "Return ONLY valid JSON: {\"question\": \"...\", \"correct_answer\": \"...\"}. "
    "No markdown, no extra text."
)


class AdaptiveTutorAgent:
    """Diagnoses, explains, questions, and evaluates for one concept at a
    time. Composes TutorAgent for grounded lesson content rather than
    duplicating lesson generation/caching/sovereignty.
    """

    def __init__(self) -> None:
        if not (
            OLLAMA_BASE_URL.startswith("http://localhost")
            or OLLAMA_BASE_URL.startswith("http://127.0.0.1")
        ):
            raise SovereigntyError(f"OLLAMA_BASE_URL '{OLLAMA_BASE_URL}' is not localhost.")
        self._llm = ChatOllama(base_url=OLLAMA_BASE_URL, model=OLLAMA_MODEL, temperature=0.4)
        self._tutor = TutorAgent()  # own sovereignty check happens again here

        with _perf.span("import.multi_signal_grader"):  # pulls in sentence-transformers on first use
            from evaluation.multi_signal_grader import LLMJudge
        self._judge = LLMJudge()  # own sovereignty check happens again here too

    def explain(self, concept_id: str, domain: str, strategy: TeachingStrategy) -> Dict:
        """Grounded explanation, sliced from the existing cached lesson by
        depth. Reuses TutorAgent.teach_concept — no new Ollama call unless
        this concept has genuinely never been taught before (cache miss).
        """
        lesson = self._tutor.teach_concept(concept_id, domain)
        sections = _SECTIONS_BY_DEPTH[strategy.explanation_depth]
        content = "\n\n".join(lesson.get(s, "") for s in sections if lesson.get(s))
        return {"sections_used": sections, "content": content}

    def generate_question(self, concept_id: str, domain: str, strategy: TeachingStrategy) -> Dict:
        """One focused question at strategy.question_difficulty. Guaranteed
        to return a usable question even if Ollama/JSON parsing fails
        (mirrors TutorAgent's guaranteed-fallback pattern).
        """
        concept_label = concept_id.replace("_", " ").title()
        prompt = (
            f"Concept: '{concept_label}' in '{domain}'. "
            f"Difficulty: {strategy.question_difficulty}. "
            f"Style: {strategy.example_style}."
        )
        try:
            with _perf.label("tutor.question", concept=concept_id):
                response = self._llm.invoke([
                    SystemMessage(content=_QUESTION_SYSTEM_PROMPT),
                    HumanMessage(content=prompt),
                ])
            raw = response.content.strip().strip("```json").strip("```").strip()
            data = json.loads(repair_json(raw))
            question = str(data.get("question", "")).strip()
            correct_answer = str(data.get("correct_answer", "")).strip()
            if question and correct_answer:
                return {"question": question, "correct_answer": correct_answer, "difficulty": strategy.question_difficulty}
        except Exception:
            pass

        return {
            "question": f"In your own words, explain {concept_label} and give one example.",
            "correct_answer": f"{concept_label} is a concept in {domain} — a good answer explains its core idea with a concrete example.",
            "difficulty": strategy.question_difficulty,
        }

    # Deterministic, disclosed mapping from the judge's category to a
    # numeric mastery-blend input. The LLM only ever outputs a category
    # (correct/partial/incorrect) via evaluation.multi_signal_grader — this
    # fixed table, not the LLM, is what turns that into a number. Phase 9
    # Step 12: this is how partial credit safely integrates with the
    # existing binary-at-heart mastery system, without letting generation
    # invent a mastery percentage.
    _LABEL_TO_EVIDENCE_SCORE = {"correct": 1.0, "partial": 0.5, "incorrect": 0.0}

    def evaluate_and_update(
        self,
        student_id: str,
        concept_id: str,
        domain: str,
        question: str,
        reference_answer: str,
        student_answer: str,
    ) -> Dict:
        """Grades via the multi-signal evaluator (Phase 9) — measured at 98.0%
        accuracy vs. 61.2% for semantic-only on the 49-item gold set,
        specifically fixing the different_abstraction/hard_application_correct
        false negatives Phase 8's Scenario B surfaced. Blends the result into
        mastery (see MASTERY_BLEND_WEIGHT_NEW and _LABEL_TO_EVIDENCE_SCORE),
        persists via the existing KnowledgeGraph.update_mastery, and logs a
        compatible EVT_DIALOGUE_ATTEMPT. The LLM plays no role in assigning
        mastery directly — it only produces a label; this method converts
        that to a number via a fixed table, never generation.

        Degrades to semantic-only (identical to the Phase 8 behavior) if the
        LLM judge is unavailable — see evaluation.multi_signal_grader.grade_multi_signal.
        """
        from evaluation.multi_signal_grader import grade_multi_signal
        from evaluation.event_log import log_event, EVT_DIALOGUE_ATTEMPT
        from memory.graph_engine import KnowledgeGraph

        student_answer = (student_answer or "").strip()
        grading = grade_multi_signal(
            question, student_answer, reference_answer,
            threshold=SEMANTIC_PASS_THRESHOLD, judge=self._judge,
        )
        passed = grading["passed"]
        evidence_score = (
            self._LABEL_TO_EVIDENCE_SCORE[grading["label"]]
            if grading["llm_judge"] is not None
            else grading["semantic_score"]  # degraded path — same as Phase 8
        )

        graph = KnowledgeGraph(student_id=student_id)
        mastery_before = graph.get_mastery(concept_id)
        new_mastery = (1 - MASTERY_BLEND_WEIGHT_NEW) * mastery_before + MASTERY_BLEND_WEIGHT_NEW * evidence_score
        new_mastery = max(0.0, min(1.0, new_mastery))
        graph.update_mastery(concept_id, new_mastery)  # also logs EVT_KNOWLEDGE_GRAPH_UPDATE

        log_event(
            EVT_DIALOGUE_ATTEMPT,
            student_id=student_id,
            concept_id=concept_id,
            domain=domain,
            semantic_score=grading["semantic_score"],
            threshold_used=SEMANTIC_PASS_THRESHOLD,
            phase="complete" if passed else "retry",
        )

        return {
            "similarity": grading["semantic_score"],
            "label": grading["label"],
            "reason": grading["reason"],
            "passed": passed,
            "mastery_before": mastery_before,
            "mastery_after": new_mastery,
        }
