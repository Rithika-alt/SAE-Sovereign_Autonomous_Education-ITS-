"""Semantic grading and Socratic probing using sentence-transformers and Ollama."""

import os
import warnings
from typing import Optional

# Suppress noisy __path__ deprecation warnings emitted by transformers' lazy-
# loader for image-processing modules — unrelated to our text-only usage.
warnings.filterwarnings(
    "ignore",
    message=r"Accessing `__path__`",
    category=UserWarning,
)

import numpy as np
from sentence_transformers import SentenceTransformer
from dotenv import load_dotenv

load_dotenv()

_MODEL_NAME = "all-MiniLM-L6-v2"
_encoder: Optional[SentenceTransformer] = None


def _get_encoder() -> SentenceTransformer:
    """Return (or lazily initialise) the shared sentence encoder."""
    global _encoder
    if _encoder is None:
        _encoder = SentenceTransformer(_MODEL_NAME)
    return _encoder


def grade_response(student_response: str, reference_answer: str) -> float:
    """Compute cosine similarity between student response and reference embeddings.

    Uses numpy dot product on L2-normalised vectors — no external API required.

    Args:
        student_response: The student's free-text answer.
        reference_answer: The ground-truth or reference explanation.

    Returns:
        Cosine similarity score in [0.0, 1.0].
    """
    encoder = _get_encoder()
    embeddings = encoder.encode(
        [student_response, reference_answer], normalize_embeddings=True
    )
    score = float(np.dot(embeddings[0], embeddings[1]))
    return max(0.0, min(1.0, score))


def generate_socratic_probe(concept_id: str, student_response: str) -> str:
    """Generate a Socratic follow-up question to deepen the student's reasoning.

    Args:
        concept_id: The concept being assessed.
        student_response: The student's most recent answer.

    Returns:
        A single Socratic question string.
    """
    base_url: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    model: str = os.getenv("OLLAMA_MODEL", "llama3.2")

    try:
        from langchain_ollama import ChatOllama
        from langchain_core.messages import SystemMessage, HumanMessage

        llm = ChatOllama(model=model, base_url=base_url)
        prompt = (
            f"The student answered: '{student_response}'. "
            f"Generate one Socratic question to probe deeper understanding of '{concept_id}'."
        )
        messages = [
            SystemMessage(content="You are a Socratic tutor."),
            HumanMessage(content=prompt),
        ]
        response = llm.invoke(messages)
        return response.content.strip()
    except Exception as exc:
        return (
            f"Can you explain in your own words the core principle behind '{concept_id}'? "
            f"(Probe generation failed: {exc})"
        )


def evaluate_clarification(clarification: str, reference_answer: str) -> float:
    """Re-grade the student's clarification response against the reference.

    Args:
        clarification: The student's follow-up explanation.
        reference_answer: The ground-truth reference.

    Returns:
        Cosine similarity score in [0.0, 1.0].
    """
    return grade_response(clarification, reference_answer)
