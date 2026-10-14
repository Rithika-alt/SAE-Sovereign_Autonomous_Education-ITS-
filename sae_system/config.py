"""Single source of truth for cross-cutting SAE settings.

Before this module existed, SEMANTIC_PASS_THRESHOLD was read via os.getenv
independently in evaluation/test_engine.py (default "0.45"), agents/auditor_agent.py
(default "0.85"), and orchestration/state_graph.py (default "0.85") — three
call sites, two different fallback values for the same env var. Since .env
sets SEMANTIC_PASS_THRESHOLD=0.45, all three happened to resolve to 0.45 at
runtime, but removing that line (or any environment without it set) would
have silently split the test-grading path and the dialogue/auditor path onto
different thresholds with no error or warning.

SEMANTIC_THRESHOLD_DEFAULT below is evidence-based, not guessed: measured via
evaluation/grading_evaluator.py against sae_system/data/eval/grading_gold_set.json
(40 hand-labeled short-answer items). A sweep from 0.30-0.90 found the best
accuracy/F1 balance at ~0.58-0.60 (67.5% accuracy, F1 64.9%) — better than
both the old defaults (0.45: 62.5% accuracy, F1 63.4%, precision 48.1%,
recall 92.9%, so it rubber-stamps confidently-wrong/negated/keyword-only
answers as "pass"; 0.85: 65.0% accuracy but recall only 14.3%, so it fails
most genuinely correct paraphrased answers). Even the best threshold on this
sweep tops out around 65-67% accuracy — cosine similarity between sentence
embeddings captures topical relatedness, not factual correctness or negation,
so no single global threshold cleanly separates "correct" from "confidently
wrong but on-topic." This is a structural limitation of similarity-only
grading, not something threshold-tuning alone can fix — see
SAE_ARCHITECTURE_AUDIT.md for the full evidence and a discussion of
mitigations (e.g. combining similarity with the auditor path's logic_score
check, which already exists for the dialogue path in
integrity/anti_malpractice.py but isn't used by the test-grading path).

Re-run `python -m evaluation.grading_evaluator` after materially changing
the gold set or the embedding model to re-validate this default.
"""

from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()

# Evidence-based default (see module docstring). Override via SEMANTIC_PASS_THRESHOLD
# env var if needed, but changing it should be backed by a re-run of grading_evaluator.
SEMANTIC_THRESHOLD_DEFAULT = 0.60
SEMANTIC_PASS_THRESHOLD: float = float(
    os.getenv("SEMANTIC_PASS_THRESHOLD", str(SEMANTIC_THRESHOLD_DEFAULT))
)

# Gate for the auditor/dialogue path's reasoning check (agents/auditor_agent.py).
LOGIC_GATE_THRESHOLD: float = float(os.getenv("LOGIC_GATE_THRESHOLD", "0.65"))

# Below this composite score, the auditor path offers clarification instead of
# marking the attempt complete or failed outright (agents/auditor_agent.py,
# orchestration/state_graph.py).
SEMANTIC_DIALOGUE_THRESHOLD: float = float(os.getenv("SEMANTIC_DIALOGUE_THRESHOLD", "0.60"))

OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "llama3.2")
