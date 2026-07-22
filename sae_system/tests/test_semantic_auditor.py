"""Pytest tests for evaluation.semantic_auditor.grade_response."""

import sys
import os

# Ensure the project root is importable when running pytest from sae_system/
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from evaluation.semantic_auditor import grade_response


def test_semantically_equivalent_different_words():
    """Semantically equivalent but lexically different responses should score ≥ 0.60."""
    student_response = (
        "Backpropagation calculates how much each weight contributed to the error "
        "by moving backwards through the network using the chain rule."
    )
    reference = (
        "Back-prop computes gradients of the loss with respect to each parameter "
        "by applying the chain rule in reverse through the computation graph."
    )
    score = grade_response(student_response, reference)
    assert score >= 0.60, f"Expected score ≥ 0.60, got {score:.4f}"


def test_vague_but_directionally_correct():
    """Vague but directionally correct response should score in [0.30, 0.75)."""
    student_response = "It's something to do with how the network learns from mistakes."
    reference = (
        "Backpropagation is the algorithm that computes gradients used to update "
        "network weights during training."
    )
    score = grade_response(student_response, reference)
    assert 0.30 <= score < 0.75, f"Expected 0.30 ≤ score < 0.75, got {score:.4f}"


def test_confident_but_incorrect():
    """Confidently wrong response (describes the attention mechanism, not backprop) should score < 0.65."""
    student_response = (
        "Backpropagation describes how attention scores are computed by taking the "
        "dot product of query and key vectors and normalising with a softmax."
    )
    reference = (
        "Backpropagation is the algorithm that computes gradients used to update "
        "network weights during training."
    )
    score = grade_response(student_response, reference)
    assert score < 0.65, f"Expected score < 0.65, got {score:.4f}"
