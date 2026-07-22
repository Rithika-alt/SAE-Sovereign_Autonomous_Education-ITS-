"""Affective pacing: monitors cognitive load and de-escalates when students are overwhelmed."""

import math
import os
from typing import List

from dotenv import load_dotenv

load_dotenv()

COMPLEXITY_THRESHOLD: float = float(os.getenv("COMPLEXITY_THRESHOLD", "0.75"))


def compute_entropy(text: str) -> float:
    """Compute normalised Shannon entropy of token frequency distribution.

    Tokenises by whitespace, computes -sum(p*log2(p)), and normalises
    to [0, 1] by dividing by log2(vocab_size).

    Args:
        text: Input text string.

    Returns:
        Normalised entropy in [0.0, 1.0]. Returns 0.0 for empty text.
    """
    tokens = text.split()
    if not tokens:
        return 0.0

    freq: dict = {}
    for tok in tokens:
        freq[tok] = freq.get(tok, 0) + 1

    vocab_size = len(freq)
    if vocab_size <= 1:
        return 0.0

    total = len(tokens)
    entropy = 0.0
    for count in freq.values():
        p = count / total
        entropy -= p * math.log2(p)

    normalised = entropy / math.log2(vocab_size)
    return max(0.0, min(1.0, normalised))


def compute_cognitive_load(response_history: List[str]) -> float:
    """Compute rolling mean entropy over the last 3 responses.

    Args:
        response_history: List of student response strings (up to last 3 used).

    Returns:
        Mean normalised entropy in [0.0, 1.0].
    """
    recent = response_history[-3:] if len(response_history) >= 3 else response_history
    if not recent:
        return 0.0
    scores = [compute_entropy(r) for r in recent]
    return sum(scores) / len(scores)


def should_deescalate(cognitive_load_score: float) -> bool:
    """Return True if cognitive load exceeds the configured complexity threshold.

    Args:
        cognitive_load_score: Current cognitive load metric in [0, 1].

    Returns:
        True if de-escalation is recommended.
    """
    return cognitive_load_score > COMPLEXITY_THRESHOLD


def get_consolidation_concept(concept_id: str, graph) -> str:
    """Return the prerequisite concept with the lowest mastery score.

    Used for de-escalation: drop back to the weakest prerequisite to consolidate
    before advancing further.

    Args:
        concept_id: Current concept node.
        graph: KnowledgeGraph instance.

    Returns:
        concept_id of the weakest prerequisite, or concept_id itself if none exist.
    """
    prereqs = graph.get_prerequisites(concept_id)
    if not prereqs:
        return concept_id
    return min(prereqs, key=lambda p: graph.get_mastery(p))
