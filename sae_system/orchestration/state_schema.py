"""State schema for the SAE LangGraph state machine."""

from typing import TypedDict, List


class GraphState(TypedDict):
    """Shared state passed between all nodes in the SAE graph."""

    student_id: str
    concept_id: str
    domain: str
    lesson_content: str
    student_response: str
    reference_answer: str
    semantic_score: float
    logic_score: float
    composite_score: float
    mastery_level: float          # per concept, 0.0–1.0
    cognitive_load_score: float
    response_history: List[str]   # last 3 student responses
    current_phase: str            # "lesson", "audit", "clarification", "retry", "complete"
    session_id: str
    error_message: str
    next_concept_id: str
    proof_hash: str
