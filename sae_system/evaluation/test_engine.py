"""Test engine: generates 10-question proctored tests via Ollama."""

import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_ollama import ChatOllama

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Retry / JSON helpers
# ---------------------------------------------------------------------------

def _ollama_invoke(llm: ChatOllama, messages: list, max_retries: int = 3, delay: float = 2.0) -> Any:
    """Invoke Ollama with retry logic and per-attempt logging."""
    last_exc: Exception = RuntimeError("No attempts made")
    for attempt in range(max_retries):
        logger.info(
            "Ollama invoke attempt %d/%d (model=%s)",
            attempt + 1, max_retries, llm.model,
        )
        try:
            response = llm.invoke(messages)
            logger.info(
                "Ollama invoke attempt %d succeeded — response length: %d chars",
                attempt + 1, len(response.content),
            )
            return response
        except Exception as exc:
            last_exc = exc
            logger.warning(
                "Ollama invoke attempt %d/%d failed: %s: %s",
                attempt + 1, max_retries, type(exc).__name__, exc,
            )
            if attempt < max_retries - 1:
                logger.info("Waiting %.1fs before next attempt…", delay)
                time.sleep(delay)

    logger.error(
        "All %d Ollama invoke attempts failed. Last error: %s",
        max_retries, last_exc,
    )
    raise last_exc


def _extract_json_list(text: str) -> List[Dict]:
    """Extract a list of question dicts from an LLM response.

    Handles four Ollama output shapes:
      1. Proper array:           [{"question_id": ...}, ...]
      2. Single object:          {"question_id": ...}          → wrapped in list
      3. Array inside prose:     Here are the questions: [...]
      4. Markdown fenced:        ```json\n[...]\n```
    """
    logger.debug("_extract_json_list called with %d chars", len(text))

    # Strip markdown code fence if present
    fence = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", text)
    if fence:
        logger.debug("Markdown code fence detected — extracting content inside fence")
        text = fence.group(1)

    text = text.strip()

    # --- Pass 1: try parsing the entire response directly ---
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            # Ensure it's a list of dicts (not a list of strings like ["A","B","C"])
            if parsed and all(isinstance(item, dict) for item in parsed):
                logger.info("JSON parse (full text) succeeded — %d question dicts", len(parsed))
                return parsed
            elif not parsed:
                logger.info("JSON parse succeeded — empty array")
                return parsed
            logger.debug("Full-text parse gave list of non-dicts — trying other strategies")
        elif isinstance(parsed, dict):
            # Ollama returned a single question object — wrap it
            logger.info("Ollama returned a single JSON object — wrapping in list")
            return [parsed]
    except json.JSONDecodeError:
        pass

    # --- Pass 2: find the outermost [...] that contains dicts ---
    # Walk forward to find '[' that starts an array of objects (not an options list)
    pos = 0
    while pos < len(text):
        arr_start = text.find("[", pos)
        if arr_start == -1:
            break
        arr_end = text.rfind("]")
        if arr_end <= arr_start:
            break
        candidate = text[arr_start:arr_end + 1]
        try:
            result = json.loads(candidate)
            if isinstance(result, list) and all(isinstance(item, dict) for item in result):
                logger.info(
                    "JSON array extraction succeeded — %d question dicts (pos %d:%d)",
                    len(result), arr_start, arr_end + 1,
                )
                return result
            # This array wasn't a list of dicts — move past this '[' and try again
            pos = arr_start + 1
        except json.JSONDecodeError:
            pos = arr_start + 1

    # --- Pass 3: find the outermost {...} and wrap it ---
    obj_start = text.find("{")
    obj_end   = text.rfind("}")
    if obj_start != -1 and obj_end > obj_start:
        candidate = text[obj_start:obj_end + 1]
        try:
            result = json.loads(candidate)
            if isinstance(result, dict):
                logger.info("Extracted single JSON object and wrapped in list")
                return [result]
        except json.JSONDecodeError as exc:
            logger.error("json.loads on object candidate failed: %s. Candidate: %r", exc, candidate[:300])

    logger.error(
        "All extraction strategies failed. Raw text (first 500 chars): %r", text[:500]
    )
    raise ValueError("No valid JSON array or object found in LLM response")


# ---------------------------------------------------------------------------
# Question validation / normalisation
# ---------------------------------------------------------------------------

_REQUIRED_FIELDS = {
    "question_id", "question", "type",
    "correct_answer", "explanation", "marks", "difficulty",
}


def _normalise_question(q: Any, idx: int) -> Dict:
    """Ensure a question dict has all required fields with sensible defaults."""
    if not isinstance(q, dict):
        logger.warning(
            "Question %d is not a dict (got %s), using empty dict fallback",
            idx, type(q).__name__,
        )
        q = {}

    q_type = q.get("type", "mcq")
    if q_type not in ("mcq", "short_answer", "true_false"):
        logger.warning(
            "Question %d has unknown type %r, defaulting to 'mcq'", idx, q_type
        )
        q_type = "mcq"

    options = q.get("options", [])
    if not isinstance(options, list):
        options = []
    # Strip out single-letter options (A/B/C/D) — they mean Ollama used placeholder format
    if q_type == "mcq":
        options = [o for o in options if isinstance(o, str) and len(o.strip()) > 2]
        if len(options) < 4:
            logger.debug(
                "Question %d (mcq) has only %d valid options, using generic fallback", idx, len(options)
            )
            options = [
                f"This is answer choice 1 for this question",
                f"This is answer choice 2 for this question",
                f"This is answer choice 3 for this question",
                f"This is answer choice 4 for this question",
            ]
    elif q_type == "true_false":
        options = ["True", "False"]
    else:
        options = []

    missing = _REQUIRED_FIELDS - set(q.keys())
    if missing:
        logger.debug("Question %d is missing fields: %s", idx, missing)

    marks_default = {"true_false": 1, "mcq": 2, "short_answer": 5}.get(q_type, 2)

    # Fallback correct_answer when LLM omits it (common with short_answer)
    correct_answer = str(q.get("correct_answer", "")).strip()
    if not correct_answer:
        if q_type == "true_false":
            correct_answer = "True"
        elif q_type == "short_answer":
            correct_answer = "Refer to lesson material for the model answer."
        else:
            correct_answer = options[0] if options else "A"
        logger.debug(
            "Question %d (%s) missing correct_answer — using fallback: %r",
            idx, q_type, correct_answer,
        )

    return {
        "question_id":   str(q.get("question_id",  f"q{idx + 1}")),
        "question":      str(q.get("question",      f"Question {idx + 1}")),
        "type":          q_type,
        "options":       options,
        "correct_answer": correct_answer,
        "explanation":   str(q.get("explanation",   "See lesson material.")),
        "marks":         int(q.get("marks",          marks_default)),
        "difficulty":    q.get("difficulty",         "medium"),
    }


def _build_fallback_questions(concept_id: str, domain: str) -> List[Dict]:
    """Return 10 generic placeholder questions when Ollama fails."""
    logger.warning(
        "Using fallback questions for concept='%s' domain='%s' — "
        "check earlier logs for why Ollama generation failed",
        concept_id, domain,
    )
    questions: List[Dict] = []

    for i in range(4):
        questions.append({
            "question_id":   f"q{i+1}",
            "question":      f"Which of the following best describes {concept_id}? (Question {i+1})",
            "type":          "mcq",
            "options": [
                f"A core concept in {domain}",
                "An unrelated algorithm",
                "A database term",
                "A networking protocol",
            ],
            "correct_answer": f"A core concept in {domain}",
            "explanation":    f"{concept_id} is a fundamental concept in {domain}.",
            "marks":          2,
            "difficulty":     "easy",
        })

    for i in range(3):
        questions.append({
            "question_id":   f"q{i+5}",
            "question":      f"{concept_id} is an important topic in {domain}. True or False?",
            "type":          "true_false",
            "options":       ["True", "False"],
            "correct_answer":"True",
            "explanation":   f"Yes, {concept_id} is a key topic in {domain}.",
            "marks":          1,
            "difficulty":     "easy",
        })

    for i in range(3):
        questions.append({
            "question_id":   f"q{i+8}",
            "question":      f"In your own words, explain the significance of {concept_id} in {domain}. (Question {i+1})",
            "type":          "short_answer",
            "options":       [],
            "correct_answer":f"{concept_id} is significant in {domain} because it underpins many practical applications.",
            "explanation":   "A good answer mentions key principles and at least one real-world use.",
            "marks":          5,
            "difficulty":     "medium",
        })

    return questions


# ---------------------------------------------------------------------------
# TestEngine
# ---------------------------------------------------------------------------

class TestEngine:
    """Generates 10-question tests for a concept using Ollama."""

    def __init__(self) -> None:
        self.base_url: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        self.model: str    = os.getenv("OLLAMA_MODEL", "llama3.2")
        logger.info(
            "TestEngine initialised — base_url=%s model=%s",
            self.base_url, self.model,
        )
        self._llm = ChatOllama(
            model=self.model, base_url=self.base_url, temperature=0.5
        )
        self._cache_dir = Path(__file__).resolve().parent.parent / "data" / "tests"
        self._cache_dir.mkdir(parents=True, exist_ok=True)

    def _cache_file(self, concept_id: str, domain: str) -> Path:
        safe = f"{domain}_{concept_id}".lower().replace(" ", "_")
        return self._cache_dir / f"{safe}.json"

    def _load_cache(self, concept_id: str, domain: str) -> List[Dict]:
        """Return cached questions if they exist and are valid, else empty list."""
        path = self._cache_file(concept_id, domain)
        if not path.exists():
            return []
        try:
            with path.open() as f:
                questions = json.load(f)
            if isinstance(questions, list) and len(questions) == 10:
                logger.info(
                    "Loaded %d questions from cache: %s", len(questions), path
                )
                return questions
        except Exception as exc:
            logger.warning("Cache read failed (%s) — regenerating", exc)
        return []

    def _save_cache(self, concept_id: str, domain: str, questions: List[Dict]) -> None:
        """Persist questions to disk."""
        path = self._cache_file(concept_id, domain)
        try:
            with path.open("w") as f:
                json.dump(questions, f, indent=2)
            logger.info("Cached %d questions to %s", len(questions), path)
        except Exception as exc:
            logger.warning("Cache write failed: %s", exc)

    def generate_test(
        self,
        concept_id: str,
        domain: str,
        lesson_content: str,
    ) -> List[Dict]:
        """Generate a 10-question mixed-format test (4 MCQ, 3 T/F, 3 SA).

        Logs every step so failures can be diagnosed from the terminal.
        Always returns exactly 10 questions; uses fallback if Ollama fails.
        """
        logger.info(
            "generate_test START — concept='%s' domain='%s' lesson_content_len=%d chars",
            concept_id, domain, len(lesson_content),
        )

        cached = self._load_cache(concept_id, domain)
        if cached:
            logger.info("generate_test CACHE HIT — returning %d cached questions", len(cached))
            return cached

        if not lesson_content.strip():
            logger.warning(
                "lesson_content is EMPTY for concept='%s'. "
                "Test questions will be generated without lesson context. "
                "Check that page_test() is passing the correct lesson dict keys.",
                concept_id,
            )

        system_prompt = (
            f"Generate a 10-question test for the concept '{concept_id}' in '{domain}'. "
            "Return ONLY valid JSON — a list of 10 question objects with NO extra text.\n\n"
            "STRICT RULES:\n"
            "1. MCQ: options must be 4 full descriptive sentences (not single letters like A/B/C/D).\n"
            "2. correct_answer must be the EXACT full text of one of the options.\n"
            "3. true_false: options must be [\"True\", \"False\"] only.\n"
            "4. short_answer: no options field needed.\n\n"
            "Example of ONE correct MCQ object:\n"
            "{\n"
            '  "question_id": "q1",\n'
            '  "question": "What does supervised learning require?",\n'
            '  "type": "mcq",\n'
            '  "options": [\n'
            '    "Labelled training data with input-output pairs",\n'
            '    "Only unlabelled data with no target variable",\n'
            '    "A reward signal from the environment",\n'
            '    "No data at all — it learns from rules"\n'
            '  ],\n'
            '  "correct_answer": "Labelled training data with input-output pairs",\n'
            '  "explanation": "Supervised learning trains on labelled examples where the correct output is known.",\n'
            '  "marks": 2,\n'
            '  "difficulty": "easy"\n'
            "}\n\n"
            f"Generate exactly: 4 MCQ (marks=2), 3 true_false (marks=1), 3 short_answer (marks=5).\n"
            "Vary difficulty across easy/medium/hard.\n"
            f"Base all questions on this lesson content about '{concept_id}':\n\n"
            + lesson_content[:2000]
        )

        logger.info(
            "System prompt built — total length: %d chars (lesson slice: %d chars)",
            len(system_prompt), min(len(lesson_content), 2000),
        )

        try:
            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=f"Generate the test for: {concept_id}"),
            ]
            response = _ollama_invoke(self._llm, messages)

            raw_text = response.content
            logger.info(
                "LLM response received — %d chars. First 300: %r",
                len(raw_text), raw_text[:300],
            )

            raw_questions = _extract_json_list(raw_text)
            logger.info(
                "Extracted %d raw questions from LLM response",
                len(raw_questions),
            )

            questions = [_normalise_question(q, i) for i, q in enumerate(raw_questions[:10])]
            logger.info("Normalised %d questions", len(questions))

            if len(questions) < 10:
                needed = 10 - len(questions)
                logger.warning(
                    "Only %d questions returned by LLM, padding with %d fallback questions",
                    len(questions), needed,
                )
                questions.extend(
                    _build_fallback_questions(concept_id, domain)[:needed]
                )

            questions = questions[:10]
            self._save_cache(concept_id, domain, questions)
            logger.info(
                "generate_test SUCCESS — returning %d questions for concept='%s'",
                len(questions), concept_id,
            )
            return questions

        except Exception as exc:
            logger.error(
                "generate_test FAILED for concept='%s' domain='%s': %s: %s — "
                "returning fallback questions",
                concept_id, domain, type(exc).__name__, exc,
                exc_info=True,
            )
            return _build_fallback_questions(concept_id, domain)

    def grade_test(
        self,
        questions: List[Dict],
        answers: Dict[str, str],
    ) -> Dict:
        """Grade a completed test. Short answers graded via semantic similarity."""
        from evaluation.semantic_auditor import grade_response

        SHORT_ANSWER_PASS = float(os.getenv("SEMANTIC_PASS_THRESHOLD", "0.60"))
        logger.info(
            "grade_test START — %d questions, %d answers, SA_pass_threshold=%.2f",
            len(questions), len(answers), SHORT_ANSWER_PASS,
        )

        total_marks = sum(q["marks"] for q in questions)
        earned      = 0
        results     = []

        for q in questions:
            qid         = q["question_id"]
            student_ans = answers.get(qid, "").strip()
            correct     = q["correct_answer"].strip()
            q_type      = q["type"]

            if q_type == "short_answer":
                sim        = grade_response(student_ans, correct) if student_ans else 0.0
                is_correct = sim >= SHORT_ANSWER_PASS
                awarded    = q["marks"] if is_correct else 0
                sim_score  = round(sim, 3)
                logger.debug(
                    "Q %s (short_answer): similarity=%.3f pass=%s awarded=%d/%d",
                    qid, sim, is_correct, awarded, q["marks"],
                )
            else:
                is_correct = student_ans.lower() == correct.lower()
                awarded    = q["marks"] if is_correct else 0
                sim_score  = 1.0 if is_correct else 0.0
                logger.debug(
                    "Q %s (%s): student=%r correct=%r match=%s awarded=%d/%d",
                    qid, q_type, student_ans, correct, is_correct, awarded, q["marks"],
                )

            earned += awarded
            results.append({
                "question_id":    qid,
                "question":       q["question"],
                "type":           q_type,
                "student_answer": student_ans,
                "correct_answer": correct,
                "explanation":    q["explanation"],
                "is_correct":     is_correct,
                "marks_awarded":  awarded,
                "marks_possible": q["marks"],
                "similarity_score": sim_score,
            })

        percentage = round((earned / total_marks * 100) if total_marks > 0 else 0, 1)
        grade      = (
            "A" if percentage >= 85 else
            "B" if percentage >= 70 else
            "C" if percentage >= 60 else "F"
        )
        passed = percentage >= 60

        logger.info(
            "grade_test COMPLETE — earned=%d/%d (%.1f%%) grade=%s passed=%s",
            earned, total_marks, percentage, grade, passed,
        )

        return {
            "total_marks":  total_marks,
            "earned_marks": earned,
            "percentage":   percentage,
            "grade":        grade,
            "passed":       passed,
            "results":      results,
        }
