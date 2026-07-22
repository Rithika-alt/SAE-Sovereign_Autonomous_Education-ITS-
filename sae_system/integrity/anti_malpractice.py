"""Anti-malpractice layer: requests and verifies student reasoning before marking mastery."""

import os
from dotenv import load_dotenv

load_dotenv()

LOGIC_GATE_THRESHOLD: float = float(os.getenv("LOGIC_GATE_THRESHOLD", "0.65"))


def request_reasoning(concept_id: str) -> str:
    """Return a prompt asking the student to justify their answer.

    Args:
        concept_id: The concept being assessed.

    Returns:
        A challenge string presented to the student.
    """
    return (
        "Before this module is marked complete, explain in your own words "
        "WHY your answer is correct, and what the core principle behind "
        f"'{concept_id}' is."
    )


def verify_reasoning(explanation: str, reference_answer: str) -> float:
    """Score the student's reasoning explanation against the reference answer.

    Uses semantic_auditor.grade_response for scoring — no external API calls.

    Args:
        explanation: The student's reasoning explanation.
        reference_answer: Ground-truth reference.

    Returns:
        Similarity score in [0.0, 1.0].
    """
    from evaluation.semantic_auditor import grade_response

    return grade_response(explanation, reference_answer)


def reasoning_passes(logic_score: float) -> bool:
    """Return True if the logic score meets the configured gate threshold.

    Args:
        logic_score: Score returned by verify_reasoning.

    Returns:
        True if the student's reasoning is sufficiently sound.
    """
    return logic_score >= LOGIC_GATE_THRESHOLD
