"""Auditor agent: scores student responses and decides phase transitions."""

import os
from dotenv import load_dotenv

load_dotenv()

SEMANTIC_PASS_THRESHOLD = float(os.getenv("SEMANTIC_PASS_THRESHOLD", "0.85"))
SEMANTIC_DIALOGUE_THRESHOLD = float(os.getenv("SEMANTIC_DIALOGUE_THRESHOLD", "0.60"))
LOGIC_GATE_THRESHOLD = float(os.getenv("LOGIC_GATE_THRESHOLD", "0.65"))


class AuditorAgent:
    """Grades student responses using semantic similarity and anti-malpractice logic."""

    def run(self, state: dict) -> dict:
        """Score the student response and set phase/proof fields.

        Args:
            state: GraphState dict containing student_response and reference_answer.

        Returns:
            Updated state with semantic_score, logic_score, composite_score,
            current_phase, and optionally proof_hash set.
        """
        from evaluation.semantic_auditor import grade_response
        from integrity.anti_malpractice import verify_reasoning
        from integrity.proof_of_learning import generate_hash, append_to_log
        from memory.graph_engine import KnowledgeGraph

        student_response: str = state.get("student_response", "")
        reference_answer: str = state.get("reference_answer", "")

        if not reference_answer:
            reference_answer = state.get("lesson_content", "")

        s_semantic: float = grade_response(student_response, reference_answer)
        s_semantic = max(0.0, min(1.0, s_semantic))

        s_logic: float = 0.0
        if s_semantic >= SEMANTIC_PASS_THRESHOLD:
            s_logic = verify_reasoning(student_response, reference_answer)
            s_logic = max(0.0, min(1.0, s_logic))

        composite: float = (s_semantic * 0.7) + (s_logic * 0.3)
        composite = max(0.0, min(1.0, composite))

        state["semantic_score"] = s_semantic
        state["logic_score"] = s_logic
        state["composite_score"] = composite

        if composite >= SEMANTIC_PASS_THRESHOLD and s_logic >= LOGIC_GATE_THRESHOLD:
            proof = generate_hash(
                state.get("student_id", "unknown"),
                state.get("concept_id", "unknown"),
                state.get("session_id", ""),
                composite,
            )
            state["proof_hash"] = proof
            append_to_log(
                proof,
                state.get("student_id", "unknown"),
                state.get("concept_id", "unknown"),
                composite,
            )
            try:
                kg = KnowledgeGraph(student_id=state.get("student_id", "default"))
                kg.update_mastery(state.get("concept_id", "unknown"), composite)
            except Exception:
                pass
            state["current_phase"] = "complete"
        elif SEMANTIC_DIALOGUE_THRESHOLD <= composite < SEMANTIC_PASS_THRESHOLD:
            state["current_phase"] = "clarification"
        else:
            state["current_phase"] = "retry"

        return state
