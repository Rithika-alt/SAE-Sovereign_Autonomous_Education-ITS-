"""Test engine: generates 10-question proctored tests via Ollama."""

import difflib
import json
import logging
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from dotenv import load_dotenv
from json_repair import repair_json
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_ollama import ChatOllama

from evaluation import perf_trace as _perf

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
    from evaluation.event_log import log_event, EVT_OLLAMA_CALL

    last_exc: Exception = RuntimeError("No attempts made")
    for attempt in range(max_retries):
        logger.info(
            "Ollama invoke attempt %d/%d (model=%s)",
            attempt + 1, max_retries, llm.model,
        )
        t0 = time.time()
        try:
            response = llm.invoke(messages)
            latency = time.time() - t0
            logger.info(
                "Ollama invoke attempt %d succeeded — response length: %d chars",
                attempt + 1, len(response.content),
            )
            log_event(
                EVT_OLLAMA_CALL, model=llm.model, attempt=attempt + 1,
                success=True, latency_s=round(latency, 3),
            )
            return response
        except Exception as exc:
            latency = time.time() - t0
            last_exc = exc
            logger.warning(
                "Ollama invoke attempt %d/%d failed: %s: %s",
                attempt + 1, max_retries, type(exc).__name__, exc,
            )
            log_event(
                EVT_OLLAMA_CALL, model=llm.model, attempt=attempt + 1,
                success=False, latency_s=round(latency, 3),
                error=f"{type(exc).__name__}: {exc}",
            )
            if attempt < max_retries - 1:
                logger.info("Waiting %.1fs before next attempt…", delay)
                time.sleep(delay)

    logger.error(
        "All %d Ollama invoke attempts failed. Last error: %s",
        max_retries, last_exc,
    )
    raise last_exc


def _coerce_question_list(parsed: Any) -> Optional[List[Dict]]:
    """A list of question dicts from a parsed JSON value, or None.

    Accepts a bare list, a JSON-mode wrapper like {"questions": [...]}, or a
    single question object (wrapped).
    """
    if isinstance(parsed, list):
        return parsed if (not parsed or all(isinstance(i, dict) for i in parsed)) else None
    if isinstance(parsed, dict):
        for key in ("questions", "items", "data", "results"):
            v = parsed.get(key)
            if isinstance(v, list) and v and all(isinstance(i, dict) for i in v):
                return v
        if "question" not in parsed:
            lists = [v for v in parsed.values() if isinstance(v, list) and v and all(isinstance(i, dict) for i in v)]
            if len(lists) == 1:
                return lists[0]
        return [parsed]
    return None


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
        coerced = _coerce_question_list(parsed)
        if coerced is not None:
            logger.info("JSON parse (full text) succeeded — %d question dicts", len(coerced))
            return coerced
        logger.debug("Full-text parse gave list of non-dicts — trying other strategies")
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

    # --- Pass 4: repair near-valid / token-capped (truncated) JSON, keeping the complete objects ---
    try:
        repaired = json.loads(repair_json(text))
        coerced = _coerce_question_list(repaired)
        if coerced:
            logger.warning("JSON needed repair (likely truncated at the token cap) — salvaged %d question dicts", len(coerced))
            return coerced
    except Exception:
        pass

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


def _normalize_choice(s: str) -> str:
    """Collapse whitespace/punctuation/case differences before comparing answers.

    The option text the student picked always comes verbatim from the
    options list, but defends against trivial formatting drift (trailing
    period, double spaces) between correct_answer and the option string.
    """
    return re.sub(r"\s+", " ", s.strip().rstrip(".")).lower()


# Matches a bare "A", "B.", "c)" etc — the placeholder-letter format the
# generation prompt explicitly forbids for MCQ options. Anything else short
# (e.g. a one-word or numeric answer) is a legitimate option and must survive.
_LETTER_PLACEHOLDER_RE = re.compile(r"^[A-Da-d][.\)]?$")


def _normalise_question(
    q: Any,
    idx: int,
    forced_type: Optional[str] = None,
    forced_marks: Optional[int] = None,
) -> Dict:
    """Ensure a question dict has all required fields with sensible defaults.

    forced_type/forced_marks are set by the type-partitioned generation calls
    (see TestEngine._generate_questions_of_type) — they override whatever the
    LLM claims, which is what guarantees a "what is X" question can never be
    mislabelled true_false and rendered as an unanswerable True/False prompt.
    """
    if not isinstance(q, dict):
        logger.warning(
            "Question %d is not a dict (got %s), using empty dict fallback",
            idx, type(q).__name__,
        )
        q = {}

    if forced_type is not None:
        q_type = forced_type
    else:
        q_type = q.get("type", "mcq")
        if q_type not in ("mcq", "short_answer", "true_false"):
            logger.warning(
                "Question %d has unknown type %r, defaulting to 'mcq'", idx, q_type
            )
            q_type = "mcq"

    correct_raw = str(q.get("correct_answer", "")).strip()
    options = q.get("options", [])
    if not isinstance(options, list):
        options = []

    if q_type == "mcq":
        options = [
            o for o in options
            if isinstance(o, str) and o.strip() and not _LETTER_PLACEHOLDER_RE.match(o.strip())
        ]
        if len(options) < 4:
            logger.debug(
                "Question %d (mcq) has only %d valid options, using generic fallback", idx, len(options)
            )
            options = [
                "This is answer choice 1 for this question",
                "This is answer choice 2 for this question",
                "This is answer choice 3 for this question",
                "This is answer choice 4 for this question",
            ]
        # The LLM frequently paraphrases correct_answer slightly instead of
        # copying an option verbatim — that used to make a genuinely correct
        # student pick register as wrong under exact-string comparison.
        # Resolve it to the closest real option so it's always selectable.
        if correct_raw:
            match = difflib.get_close_matches(correct_raw, options, n=1, cutoff=0.4)
            if match:
                correct_answer = match[0]
            elif correct_raw in options:
                correct_answer = correct_raw
            else:
                replace_idx = next(
                    (i for i, o in enumerate(options) if o.startswith("This is answer choice")),
                    len(options) - 1,
                )
                options[replace_idx] = correct_raw
                correct_answer = correct_raw
        else:
            correct_answer = options[0]

    elif q_type == "true_false":
        options = ["True", "False"]
        low = correct_raw.lower()
        correct_answer = "False" if ("false" in low and "true" not in low) else "True"

    else:  # short_answer
        options = []
        correct_answer = correct_raw or "Refer to lesson material for the model answer."

    missing = _REQUIRED_FIELDS - set(q.keys())
    if missing:
        logger.debug("Question %d is missing fields: %s", idx, missing)

    if forced_marks is not None:
        marks = forced_marks
    else:
        marks_default = {"true_false": 1, "mcq": 2, "short_answer": 5}.get(q_type, 2)
        marks = int(q.get("marks", marks_default))

    return {
        "question_id":   str(q.get("question_id",  f"q{idx + 1}")),
        "question":      str(q.get("question",      f"Question {idx + 1}")),
        "type":          q_type,
        "options":       options,
        "correct_answer": correct_answer,
        "explanation":   str(q.get("explanation",   "See lesson material.")),
        "marks":         marks,
        "difficulty":    q.get("difficulty",         "medium"),
    }


def _fallback_questions_for_type(
    q_type: str, count: int, concept_id: str, domain: str, start_idx: int = 0
) -> List[Dict]:
    """Return `count` generic placeholder questions of a single type."""
    questions: List[Dict] = []

    if q_type == "mcq":
        for i in range(count):
            questions.append({
                "question_id":   f"q{start_idx + i + 1}",
                "question":      f"Which of the following best describes {concept_id}? (Question {i + 1})",
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
    elif q_type == "true_false":
        for i in range(count):
            questions.append({
                "question_id":   f"q{start_idx + i + 1}",
                "question":      f"{concept_id} is an important topic in {domain}. True or False?",
                "type":          "true_false",
                "options":       ["True", "False"],
                "correct_answer": "True",
                "explanation":   f"Yes, {concept_id} is a key topic in {domain}.",
                "marks":          1,
                "difficulty":     "easy",
            })
    else:  # short_answer
        for i in range(count):
            questions.append({
                "question_id":   f"q{start_idx + i + 1}",
                "question":      f"In your own words, explain the significance of {concept_id} in {domain}. (Question {i + 1})",
                "type":          "short_answer",
                "options":       [],
                "correct_answer": f"{concept_id} is significant in {domain} because it underpins many practical applications.",
                "explanation":   "A good answer mentions key principles and at least one real-world use.",
                "marks":          5,
                "difficulty":     "medium",
            })

    return questions


def _build_fallback_questions(concept_id: str, domain: str) -> List[Dict]:
    """Return 10 generic placeholder questions when Ollama fails entirely."""
    logger.warning(
        "Using fallback questions for concept='%s' domain='%s' — "
        "check earlier logs for why Ollama generation failed",
        concept_id, domain,
    )
    return (
        _fallback_questions_for_type("mcq", 4, concept_id, domain, 0)
        + _fallback_questions_for_type("true_false", 3, concept_id, domain, 4)
        + _fallback_questions_for_type("short_answer", 3, concept_id, domain, 7)
    )


# ---------------------------------------------------------------------------
# Guards against the model copying prompt examples
# ---------------------------------------------------------------------------
# The prompts used to contain worked examples that were all about "supervised
# learning", whatever the domain. The small local model copied them verbatim — a
# Digital Marketing test opened with "What does supervised learning require?".
# The prompts no longer contain concrete examples; these fragments remain only so
# that copying (in freshly generated questions and in previously cached tests) is
# detected and rejected.
_LEGACY_EXAMPLE_FRAGMENTS = (
    "what does supervised learning require",
    "supervised learning requires labelled training data",
    "explain why supervised learning needs labelled data",
    "labelled training data with input-output pairs",
    "only unlabelled data with no target variable",
)
# If the test itself is about (machine) learning, those example questions are at
# least on topic, so they are not treated as contamination.
_ML_TERMS = {"ml", "ai", "machine", "learning", "supervised", "unsupervised",
             "regression", "classification", "clustering", "neural"}
_PLACEHOLDER_RE = re.compile(r"<[^<>\n]{2,80}>")


def _question_blob(q: Any) -> str:
    if not isinstance(q, dict):
        return ""
    parts = [str(q.get("question", "")), str(q.get("correct_answer", ""))]
    opts = q.get("options")
    if isinstance(opts, list):
        parts.extend(str(o) for o in opts)
    return " ".join(parts)


def _copies_prompt_example(q: Any, concept_id: str, domain: str, lesson_content: str = "") -> bool:
    """True if q reproduces a legacy prompt example in a test that isn't about learning."""
    blob = _question_blob(q).lower()
    if not any(fragment in blob for fragment in _LEGACY_EXAMPLE_FRAGMENTS):
        return False
    if set(re.findall(r"[a-z0-9]+", f"{concept_id} {domain}".lower())) & _ML_TERMS:
        return False
    return "supervised learning" not in lesson_content.lower()


def _unusable_reason(q: Any, concept_id: str, domain: str, lesson_content: str = "") -> Optional[str]:
    """Why a generated question must be thrown away, or None if it is usable."""
    if not isinstance(q, dict):
        return None                      # _normalise_question already handles non-dicts
    if _PLACEHOLDER_RE.search(_question_blob(q)):
        return "contains template placeholder text"
    if _copies_prompt_example(q, concept_id, domain, lesson_content):
        return "copies an example question from the prompt (off-topic for this concept)"
    return None



# ---------------------------------------------------------------------------
# Strict validation of generated questions (runs BEFORE _normalise_question)
# ---------------------------------------------------------------------------
# _normalise_question is lenient by design: it snaps a wrong correct_answer onto the
# nearest option (difflib cutoff 0.4) and invents generic "answer choice 1..4" options
# when the model's are bad. That produced wrong answers and nonsense options, so
# questions are validated here first and rejected (not patched) when unsound.

# Hard cap on generated tokens per call. Without it a runaway response runs until the
# 8192-token context fills: ~18 minutes at the ~7 tokens/s this machine manages.
# Measured typical usage: mcq 514, true_false 236, short_answer 288.
_TOKEN_CAPS = {"mcq": 1000, "true_false": 600, "short_answer": 750}
_TIME_BUDGET_S = 480            # no retry pass is started once a test has run this long
_MIN_GROUNDING = 2              # distinct lesson terms a question must share (calibrated on 70 real questions)
_DUP_THRESHOLD = 0.55           # stem-set Jaccard at/above which two questions count as the same
_STOPWORDS = frozenset(
    "about above after again against also because been before being between both cannot could does doing done "
    "down during each either else from have having here into itself just like many more most much must only "
    "other over same should since some such than that their them then there these they this those through "
    "under until upon very were what when where whether which while whom will with within without would your "
    "following correct best describes true false explain statement answer question".split()
)


def _stems(text: str) -> set:
    out = set()
    for w in re.findall(r"[a-z][a-z0-9\-]{3,}", str(text).lower()):
        if w in _STOPWORDS:
            continue
        out.add(re.sub(r"(ing|ed|es|s|ly)$", "", w) if len(w) > 5 else w)
    return out


def _lesson_terms(concept_id: str, domain: str, lesson_content: str) -> set:
    return _stems(f"{concept_id.replace('_', ' ')} {domain} {lesson_content}")


def _is_grounded(q: Dict, terms: set) -> bool:
    """True if the question shares enough vocabulary with the lesson/syllabus.

    Skipped (True) when there is too little lesson text to judge against.
    """
    if len(terms) < 25:
        return True
    return len(_stems(f"{q.get('question', '')} {q.get('correct_answer', '')}") & terms) >= _MIN_GROUNDING


def _similar(a: str, b: str) -> bool:
    sa, sb = _stems(a), _stems(b)
    if not sa or not sb:
        return False
    return len(sa & sb) / len(sa | sb) >= _DUP_THRESHOLD


def _match_option(correct: str, options: List[str]) -> Optional[str]:
    """The option that correct_answer really refers to (exact, or a near-verbatim copy), else None."""
    norm = {_normalize_choice(o): o for o in options}
    key = _normalize_choice(correct)
    if key in norm:
        return norm[key]
    close = difflib.get_close_matches(key, list(norm), n=1, cutoff=0.9)
    return norm[close[0]] if close else None


_WH_START_RE = re.compile(r"^\s*(what|which|how|why|when|who|where|explain|describe|define)\b", re.I)


def _structure_problem(q: Any, q_type: str) -> Optional[str]:
    """Why a generated question is structurally unsound, or None if it is fine."""
    if not isinstance(q, dict):
        return "not an object"
    text = str(q.get("question", "")).strip()
    if len(text) < 12:
        return "question text is missing or too short"
    answer = str(q.get("correct_answer", "")).strip()
    if not answer:
        return "no correct_answer"

    if q_type == "mcq":
        opts = q.get("options")
        if not isinstance(opts, list) or len(opts) != 4:
            return "options must be a list of exactly 4"
        opts = [str(o).strip() for o in opts]
        if any(len(o) < 2 or _LETTER_PLACEHOLDER_RE.match(o) for o in opts):
            return "an option is empty or just a letter"
        if len({_normalize_choice(o) for o in opts}) < 4:
            return "options are not all distinct"
        words = [set(re.findall(r"[a-z0-9]+", o.lower())) for o in opts]     # ALL words: "TCP ..." vs "UDP ..." differ
        for i, a in enumerate(words):
            for b in words[i + 1:]:
                if len(a | b) >= 4 and len(a & b) / len(a | b) >= 0.8:
                    return "two options are near-identical"
        if _match_option(answer, opts) is None:
            return "correct_answer is not one of the options"
    elif q_type == "true_false":
        if answer.strip().rstrip(".").lower() not in ("true", "false"):
            return "correct_answer is not exactly True or False"
        if _WH_START_RE.match(text):
            return "true/false item is phrased as a question, not a statement"
    else:  # short_answer
        if len(answer) < 25:
            return "model answer is too short to grade against"
    return None


def _repair_mcq(q: Dict) -> Dict:
    """Point correct_answer at the exact option text it refers to (validated beforehand)."""
    opts = [str(o).strip() for o in q.get("options", [])]
    match = _match_option(str(q.get("correct_answer", "")), opts)
    return {**q, "options": opts, "correct_answer": match or q.get("correct_answer")}


# ---------------------------------------------------------------------------
# Syllabus-based filler (used only if generation + one retry still fall short)
# ---------------------------------------------------------------------------
_ROADMAP_DIR = Path(__file__).resolve().parent.parent / "data" / "roadmaps"


def _syllabus_for(concept_id: str, domain: str):
    """(module title, this module's concepts, concepts from OTHER domains) from the roadmap files.

    Real, on-syllabus material for filler questions: correct answers come from the module's own
    concepts and distractors from other domains' roadmaps, so a distractor is genuinely wrong.
    """
    own_file = _ROADMAP_DIR / f"{domain.lower().replace(' ', '_')}.json"
    title, concepts = concept_id.replace("_", " ").title(), []
    try:
        for m in json.loads(own_file.read_text(encoding="utf-8")).get("modules", []):
            mid = str(m.get("module_id", ""))
            if mid == concept_id or mid[:30] == concept_id[:30]:
                title = str(m.get("title") or title)
                concepts = [str(c) for c in m.get("concepts", []) if isinstance(c, (str, int))]
                break
    except Exception:
        pass
    own_terms = _stems(" ".join(concepts) + " " + domain)
    others: List[str] = []
    for f in sorted(_ROADMAP_DIR.glob("*.json")) if _ROADMAP_DIR.exists() else []:
        if f == own_file:
            continue
        try:
            for m in json.loads(f.read_text(encoding="utf-8")).get("modules", []):
                for c in m.get("concepts", []):
                    if isinstance(c, str) and not (_stems(c) & own_terms) and c not in others:
                        others.append(c)
        except Exception:
            continue
    return title, concepts, others


def _grounded_fallback_questions(
    q_type: str, count: int, concept_id: str, domain: str, avoid: Optional[List[str]] = None,
    start_idx: int = 0,
) -> List[Dict]:
    """Distinct, on-syllabus filler questions; generic placeholders only if no roadmap data exists."""
    title, concepts, others = _syllabus_for(concept_id, domain)
    avoid_blob = " ".join(avoid or []).lower()
    # concepts not yet asked about come first; already-asked ones only if we run out
    pool = [c for c in concepts if c.lower() not in avoid_blob] + [c for c in concepts if c.lower() in avoid_blob]
    if not pool or len(others) < 3:
        return _fallback_questions_for_type(q_type, count, concept_id, domain, start_idx)

    out: List[Dict] = []
    mcq_stems = [
        'Which of the following is a topic covered in "{t}"?',
        'Which of these concepts belongs to the {d} module "{t}"?',
        'Which concept is part of "{t}" in {d}?',
        'Which one of the following would you study in "{t}"?',
    ]
    sa_stems = [
        'In your own words, explain "{c}" and why it matters in {d}.',
        'Describe a real-world situation in {d} where "{c}" applies, and what it achieves.',
        'What problem does "{c}" help solve in {d}? Explain briefly.',
    ]
    for i in range(count):
        c = pool[i % len(pool)]
        reuse = i // len(pool)                      # >0 only if a concept has to be asked about again: vary the wording
        qid = f"q{start_idx + i + 1}"
        if q_type == "mcq":
            distractors = [others[(i * 3 + k * 7) % len(others)] for k in range(3)]
            distractors = list(dict.fromkeys(d for d in distractors if d != c))
            k = 0
            while len(distractors) < 3:
                cand = others[(i + k) % len(others)]
                if cand != c and cand not in distractors:
                    distractors.append(cand)
                k += 1
            options = distractors[:3]
            options.insert(i % 4, c)
            out.append({
                "question_id": qid, "question": mcq_stems[i % len(mcq_stems)].format(t=title, d=domain),
                "type": "mcq", "options": options, "correct_answer": c,
                "explanation": f'"{c}" is one of the concepts covered in {title}.', "marks": 2, "difficulty": "easy",
            })
        elif q_type == "true_false":
            is_true = i % 2 == 0
            subject = c if is_true else others[(i * 5) % len(others)]
            out.append({
                "question_id": qid,
                "question": (f'"{subject}" is a topic covered in "{title}" ({domain}). True or False?' if reuse == 0 else
                             f'In {domain}, "{subject}" is part of the module "{title}". True or False?'),
                "type": "true_false", "options": ["True", "False"], "correct_answer": "True" if is_true else "False",
                "explanation": (f'"{c}" is part of {title}.' if is_true else f'"{subject}" belongs to a different subject, not {title}.'),
                "marks": 1, "difficulty": "easy",
            })
        else:
            out.append({
                "question_id": qid, "question": sa_stems[(reuse + i) % len(sa_stems)].format(c=c, d=domain),
                "type": "short_answer", "options": [],
                "correct_answer": f"A good answer defines {c}, explains how it fits into {title}, and gives a concrete example from {domain}.",
                "explanation": "A good answer defines the concept, links it to the module and gives an example.",
                "marks": 5, "difficulty": "medium",
            })
    return out


# ---------------------------------------------------------------------------
# TestEngine
# ---------------------------------------------------------------------------

class TestEngine:
    """Generates 10-question tests for a concept using Ollama."""

    # (type, count, marks) — 3 independent Ollama calls run in parallel,
    # one per type, instead of one call asking for a 10-item mixed list.
    # This is both faster (concurrent instead of one long generation) and
    # more correct: each call's prompt only ever describes one format, so
    # the LLM can no longer mislabel a "what is X" question as true_false.
    _TYPE_PLAN = [("mcq", 4, 2), ("true_false", 3, 1), ("short_answer", 3, 5)]

    def __init__(self) -> None:
        from config import OLLAMA_BASE_URL, OLLAMA_MODEL

        self.base_url: str = OLLAMA_BASE_URL
        self.model: str    = OLLAMA_MODEL
        logger.info(
            "TestEngine initialised — base_url=%s model=%s",
            self.base_url, self.model,
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
                bad = [
                    q.get("question_id", "?") for q in questions
                    if _unusable_reason(q, concept_id, domain) is not None
                ]
                if bad:
                    logger.warning(
                        "Discarding cached test %s: questions %s copy a prompt example or contain "
                        "placeholder text — regenerating", path.name, bad,
                    )
                    return []
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

    def _type_prompt(
        self,
        q_type: str,
        count: int,
        concept_id: str,
        domain: str,
        lesson_content: str,
        avoid: Optional[List[str]] = None,
    ) -> str:
        """Build a prompt that only ever describes ONE question format."""
        header = (
            f"Generate exactly {count} {q_type} test questions for the concept "
            f"'{concept_id}' in '{domain}'. Return ONLY a valid JSON object of the form "
            f'{{"questions": [ ...{count} question objects... ]}} — no markdown, no extra text.\n\n'
            "Every question object needs: question_id, question, correct_answer, "
            "explanation, difficulty (easy/medium/hard — vary it across the set). "
            "Keep every explanation to ONE short sentence (under 20 words). "
            "Each question must test a DIFFERENT fact or idea from the lesson.\n\n"
        )
        if avoid:
            header += (
                "These questions were already asked in this test. Do NOT repeat, rephrase, or ask about "
                "the same fact as any of them:\n" + "\n".join(f"- {a[:140]}" for a in avoid[:12]) + "\n\n"
            )

        # Structure only — NO concrete example content. Earlier versions showed worked
        # examples about "supervised learning" for every domain and the model copied them.
        about = f"'{concept_id}' in '{domain}'"
        shape_note = (
            "Use this structure. Everything in <angle brackets> only describes what goes there: "
            f"replace it with real content about {about}, and never output the angle brackets or "
            "this wording.\n"
        )
        if q_type == "mcq":
            body = (
                "Each question must also include an \"options\" array of exactly 4 "
                "full descriptive sentences (never single letters like A/B/C/D). "
                "\"correct_answer\" MUST be copied EXACTLY, character-for-character, "
                "from one of the 4 options.\n\n"
                + shape_note +
                "{\n"
                '  "question_id": "q1",\n'
                '  "question": "<a question about the concept>",\n'
                '  "options": ["<option 1>", "<option 2>", "<option 3>", "<option 4>"],\n'
                '  "correct_answer": "<the exact text of the one correct option>",\n'
                '  "explanation": "<one sentence on why it is correct>",\n'
                '  "difficulty": "easy"\n'
                "}\n\n"
            )
        elif q_type == "true_false":
            body = (
                "Each question's \"question\" field MUST be a single declarative "
                "statement of fact ending in \"True or False?\" — NEVER phrase it as "
                "a \"What is...\" / \"Which of...\" / \"How does...\" question, since "
                "those cannot be answered with True or False.\n"
                "\"correct_answer\" must be exactly \"True\" or exactly \"False\".\n\n"
                + shape_note +
                "{\n"
                '  "question_id": "q5",\n'
                '  "question": "<a statement about the concept> True or False?",\n'
                '  "correct_answer": "<True or False>",\n'
                '  "explanation": "<one sentence on why>",\n'
                '  "difficulty": "easy"\n'
                "}\n\n"
            )
        else:  # short_answer
            body = (
                "These are open-ended questions — do not include an options field. "
                "\"correct_answer\" should be a 1-2 sentence model answer used for "
                "lenient semantic grading.\n\n"
                + shape_note +
                "{\n"
                '  "question_id": "q8",\n'
                '  "question": "<an open-ended question about the concept>",\n'
                '  "correct_answer": "<a 1-2 sentence model answer>",\n'
                '  "explanation": "<what a good answer mentions>",\n'
                '  "difficulty": "medium"\n'
                "}\n\n"
            )

        return (
            header + body +
            f"Every question must be specifically about {about}; never ask about any other subject.\n\n"
            f"Base every question on this lesson content about '{concept_id}':\n\n"
            + lesson_content[:2000]
        )

    def _make_llm(self, q_type: str) -> ChatOllama:
        """One ChatOllama per call, with a hard token cap and JSON mode.

        num_predict bounds a runaway response (see _TOKEN_CAPS); format="json" makes Ollama emit
        syntactically valid JSON, which removes most parse failures and rambling.
        """
        return ChatOllama(
            model=self.model, base_url=self.base_url, temperature=0.4,
            num_predict=_TOKEN_CAPS.get(q_type, 800), format="json",
        )

    def _generate_questions_of_type(
        self,
        q_type: str,
        count: int,
        marks: int,
        concept_id: str,
        domain: str,
        lesson_content: str,
        avoid: Optional[List[str]] = None,
        deadline: Optional[float] = None,
    ) -> List[Dict]:
        """Generate `count` validated questions of one type.

        Every candidate must pass strict structural validation, be grounded in the lesson, and not
        repeat an earlier question; unsound ones are rejected, never patched. A shortfall gets ONE
        retry (told what not to repeat) before syllabus-based filler is used.
        """
        llm = self._make_llm(q_type)
        terms = _lesson_terms(concept_id, domain, lesson_content)
        seen: List[str] = list(avoid or [])
        accepted: List[Dict] = []
        attempts = 0

        while len(accepted) < count and attempts < 2:
            attempts += 1
            if attempts > 1 and deadline is not None and time.time() > deadline:
                logger.warning("Time budget used up — no retry pass for '%s'", q_type)
                break
            need = count - len(accepted)
            prompt = self._type_prompt(q_type, need if attempts == 1 else need + 1, concept_id, domain,
                                       lesson_content, avoid=seen)
            messages = [
                SystemMessage(content=prompt),
                HumanMessage(content=f"Generate the {q_type} questions for: {concept_id}"),
            ]
            try:
                with _perf.label("test.generate", q_type=q_type, concept=concept_id, attempt=attempts):
                    response = _ollama_invoke(llm, messages)
                raw_questions = _extract_json_list(response.content)
            except Exception as exc:
                logger.error("Generation of '%s' questions failed (attempt %d): %s: %s",
                             q_type, attempts, type(exc).__name__, exc)
                continue
            logger.info("Extracted %d raw '%s' questions (attempt %d)", len(raw_questions), q_type, attempts)

            for q in raw_questions:
                reason = (
                    _unusable_reason(q, concept_id, domain, lesson_content)
                    or _structure_problem(q, q_type)
                    or (None if _is_grounded(q, terms) else "not grounded in the lesson (out of syllabus)")
                    or ("repeats an earlier question" if any(_similar(str(q.get("question", "")), s) for s in seen) else None)
                )
                if reason:
                    logger.warning("Rejecting a generated '%s' question for '%s': %s (%r)",
                                   q_type, concept_id, reason, _question_blob(q)[:80])
                    continue
                norm = _normalise_question(_repair_mcq(q) if q_type == "mcq" else q, len(accepted),
                                           forced_type=q_type, forced_marks=marks)
                accepted.append(norm)
                seen.append(norm["question"])
                if len(accepted) == count:
                    break

        if len(accepted) < count:
            needed = count - len(accepted)
            logger.warning("Only %d/%d valid '%s' questions after %d attempt(s); adding %d syllabus-based filler",
                           len(accepted), count, q_type, attempts, needed)
            accepted.extend(_grounded_fallback_questions(q_type, needed, concept_id, domain, avoid=seen))
        return accepted[:count]

    def generate_test(
        self,
        concept_id: str,
        domain: str,
        lesson_content: str,
        progress: Optional[Callable[[str, int], None]] = None,
    ) -> List[Dict]:
        """Generate a 10-question mixed-format test (4 MCQ, 3 T/F, 3 SA).

        Types run one after another, each told which questions already exist, so a fact is not asked
        twice across formats. (Ollama here serves one request at a time, so running them in parallel
        never saved time.) Always returns exactly 10 questions. ``progress(q_type, n_done)`` is
        called as each type completes.
        """
        from evaluation.event_log import log_event, EVT_TEST_GENERATION

        logger.info(
            "generate_test START — concept='%s' domain='%s' lesson_content_len=%d chars",
            concept_id, domain, len(lesson_content),
        )

        _t_cache = time.perf_counter()
        cached = self._load_cache(concept_id, domain)
        _perf.cache_event(
            "test", "disk" if cached else "miss",
            (time.perf_counter() - _t_cache) * 1000, concept=concept_id,
        )
        if cached:
            logger.info("generate_test CACHE HIT — returning %d cached questions", len(cached))
            log_event(
                EVT_TEST_GENERATION, concept_id=concept_id, domain=domain,
                cache_hit=True, elapsed_s=0.0,
            )
            return cached

        if not lesson_content.strip():
            logger.warning(
                "lesson_content is EMPTY for concept='%s'. "
                "Test questions will be generated without lesson context. "
                "Check that page_test() is passing the correct lesson dict keys.",
                concept_id,
            )

        t_start = time.time()
        deadline = t_start + _TIME_BUDGET_S
        questions: List[Dict] = []
        asked: List[str] = []
        for q_type, count, marks in self._TYPE_PLAN:
            try:
                batch = self._generate_questions_of_type(
                    q_type, count, marks, concept_id, domain, lesson_content,
                    avoid=list(asked), deadline=deadline,
                )
            except Exception as exc:
                logger.error("Type '%s' generation crashed: %s", q_type, exc)
                batch = _grounded_fallback_questions(q_type, count, concept_id, domain, avoid=asked)
            questions.extend(batch)
            asked.extend(q["question"] for q in batch)
            if progress:
                try:
                    progress(q_type, len(batch))
                except Exception:
                    pass

        elapsed = time.time() - t_start
        _perf.record("test.generate_all", elapsed * 1000, concept=concept_id)
        logger.info("Test generation complete in %.1fs", elapsed)

        for i, q in enumerate(questions):
            q["question_id"] = f"q{i + 1}"

        self._save_cache(concept_id, domain, questions)
        logger.info(
            "generate_test SUCCESS — returning %d questions for concept='%s' in %.1fs",
            len(questions), concept_id, elapsed,
        )
        log_event(
            EVT_TEST_GENERATION, concept_id=concept_id, domain=domain,
            cache_hit=False, elapsed_s=round(elapsed, 3),
        )
        return questions

    def grade_test(
        self,
        questions: List[Dict],
        answers: Dict[str, str],
    ) -> Dict:
        """Grade a completed test. Short answers graded via semantic similarity."""
        with _perf.span("import.semantic_auditor"):  # torch/sentence-transformers: slow on first use only
            from evaluation.semantic_auditor import grade_response
        from config import SEMANTIC_PASS_THRESHOLD as SHORT_ANSWER_PASS
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
                is_correct = _normalize_choice(student_ans) == _normalize_choice(correct)
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
