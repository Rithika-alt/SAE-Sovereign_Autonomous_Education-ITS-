"""Ask SAE — grounded question answering. Phase 7.

Core loop: Student Question -> Context/Retrieval -> Local Answer ->
Evidence/Explanation -> Optional Lesson Routing.

Deliberately narrow: this is NOT an intent router across Tutor/Auditor/
Roadmap/Searcher agents (see docs/ASK_SAE_ARCHITECTURE.md's Scope Note).
It answers a question directly, using whatever real curriculum context is
available, and is honest when none is.

Sovereignty: mirrors the exact guard TutorAgent/RoadmapAgent/SearcherAgent
use — raises SovereigntyError (imported, not redefined) if OLLAMA_BASE_URL
isn't localhost/127.0.0.1. This happens in __init__, before any network call.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_ollama import ChatOllama

from agents.tutor_agent import SovereigntyError
from config import OLLAMA_BASE_URL, OLLAMA_MODEL
from evaluation import perf_trace as _perf

MAX_QUESTION_CHARS = 2000  # see docs/ASK_SAE_ARCHITECTURE.md "Limits established"

_LESSON_CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "lessons"

_SYSTEM_PROMPT = (
    "You are SAE, a local, honest educational tutor. Rules:\n"
    "1. If curriculum context is provided below, ground your answer in it "
    "and prefer it over general knowledge when they conflict.\n"
    "2. If no curriculum context is provided, answer from general knowledge "
    "but say plainly that this isn't grounded in the student's own course "
    "material.\n"
    "3. Never invent citations, sources, or claim you retrieved something "
    "you were not given.\n"
    "4. Be concise but explanatory: prioritize teaching over just stating a "
    "final answer. Use an example when it helps.\n"
    "5. If you are uncertain, say so directly instead of guessing "
    "confidently."
)


def _lesson_cache_path(concept_id: str, domain: str) -> Path:
    """Mirrors TutorAgent._cache_file's path convention exactly (data/lessons/{domain}_{concept}.json)."""
    safe = f"{domain}_{concept_id}".lower().replace(" ", "_")
    return _LESSON_CACHE_DIR / f"{safe}.json"


def _load_cached_lesson(concept_id: str, domain: str) -> Optional[Dict]:
    """Read a cached lesson from disk if one exists — a pure lookup, never
    triggers generation (unlike TutorAgent.teach_concept on a cache miss).
    """
    path = _lesson_cache_path(concept_id, domain)
    if not path.exists():
        _perf.cache_event("ask_lesson", "miss", concept=concept_id)
        return None
    try:
        with _perf.span("cache.ask_lesson", tier="disk", concept=concept_id):
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _query_chromadb(concept_id: str, domain: str, question: str) -> List[str]:
    """Best-effort secondary context source. Usually empty on the dashboard
    path — see docs/ASK_SAE_ARCHITECTURE.md — never fatal if unavailable.
    """
    try:
        from memory.chroma_store import collection_exists, query_documents
        if not collection_exists(concept_id):
            return []
        return query_documents(concept_id, domain, question, n_results=2)
    except Exception:
        return []


def gather_context(student_id: str, concept_id: str, domain: str) -> Dict:
    """Collect real, available context for a question. Never fabricates —
    every field here reflects something that actually exists on disk/in the
    graph, or is explicitly empty/None.
    """
    lesson = _load_cached_lesson(concept_id, domain) if concept_id and domain else None
    chroma_chunks = _query_chromadb(concept_id, domain, "") if concept_id and domain else []

    mastery: Optional[float] = None
    if concept_id and student_id:
        try:
            from memory.graph_engine import KnowledgeGraph
            graph = KnowledgeGraph(student_id=student_id)
            m = graph.get_mastery(concept_id)
            mastery = m if m else None  # 0.0 means "no data" here, same as elsewhere in the codebase
        except Exception:
            mastery = None

    sources: List[str] = []
    if lesson:
        sources.append(f"Cached lesson for '{concept_id}' ({domain})")
    if chroma_chunks:
        sources.append(f"{len(chroma_chunks)} supplementary reference chunk(s) for '{concept_id}'")

    return {
        "lesson": lesson,
        "chroma_chunks": chroma_chunks,
        "mastery": mastery,
        "sources": sources,
        "grounded": bool(lesson or chroma_chunks),
    }


def _build_context_block(context: Dict, concept_id: str, domain: str) -> str:
    if not context["grounded"]:
        return ""

    parts = []
    lesson = context.get("lesson")
    if lesson:
        parts.append(
            f"Curriculum context for '{concept_id}' ({domain}):\n"
            f"{lesson.get('introduction', '')}\n\n{lesson.get('theory', '')}"
        )
    for chunk in context.get("chroma_chunks", []):
        parts.append(f"Supplementary reference:\n{chunk}")

    mastery = context.get("mastery")
    if mastery is not None:
        parts.append(f"(Student's current mastery of '{concept_id}': {mastery:.0%})")

    return "\n\n---\n\n".join(parts)


class AskSAEAgent:
    """Answers one grounded question at a time. Stateless across calls
    (session-scoped history, if any, is the caller's/dashboard's concern).
    """

    def __init__(self) -> None:
        if not (
            OLLAMA_BASE_URL.startswith("http://localhost")
            or OLLAMA_BASE_URL.startswith("http://127.0.0.1")
        ):
            raise SovereigntyError(f"OLLAMA_BASE_URL '{OLLAMA_BASE_URL}' is not localhost.")
        self._llm = ChatOllama(base_url=OLLAMA_BASE_URL, model=OLLAMA_MODEL, temperature=0.3)

    def ask(
        self,
        question: str,
        student_id: str = "",
        concept_id: str = "",
        domain: str = "",
    ) -> Dict:
        """Answer one question. Returns the Ask SAE response contract:
        {answer, grounded, sources, concept_id, domain, mastery,
         suggested_action, error}. Exactly one of `answer`/`error` is set.
        """
        question = (question or "").strip()
        if not question:
            return self._error("Please enter a question.", concept_id, domain)
        if len(question) > MAX_QUESTION_CHARS:
            return self._error(
                f"That question is too long ({len(question)} characters). "
                f"Please keep it under {MAX_QUESTION_CHARS} characters.",
                concept_id, domain,
            )

        context = gather_context(student_id, concept_id, domain)
        context_block = _build_context_block(context, concept_id, domain)

        user_message = (
            f"{context_block}\n\n---\n\nStudent question: {question}"
            if context_block else
            f"Student question: {question}\n\n"
            "(No curriculum context is available for this question — say so "
            "before answering from general knowledge.)"
        )

        try:
            with _perf.label("ask_sae.answer", concept=concept_id):
                response = self._llm.invoke([
                    SystemMessage(content=_SYSTEM_PROMPT),
                    HumanMessage(content=user_message),
                ])
            answer = response.content.strip()
        except Exception as exc:
            return self._error(
                f"The local model (Ollama) is unavailable: {exc}. "
                "Ask SAE only uses local inference and will not fall back to "
                "an external provider — please check that Ollama is running.",
                concept_id, domain,
            )

        suggested_action = None
        if concept_id and domain:
            suggested_action = {
                "label": "Continue this lesson",
                "concept_id": concept_id,
                "domain": domain,
            }

        from evaluation.event_log import log_event, EVT_AGENT_EXECUTION
        log_event(
            EVT_AGENT_EXECUTION, student_id=student_id, agent="ask_sae",
            concept_id=concept_id or None, domain=domain or None,
            grounded=context["grounded"], question_preview=question[:120],
        )

        return {
            "answer": answer,
            "grounded": context["grounded"],
            "sources": context["sources"],
            "concept_id": concept_id or None,
            "domain": domain or None,
            "mastery": context["mastery"],
            "suggested_action": suggested_action,
            "error": None,
        }

    @staticmethod
    def _error(message: str, concept_id: str, domain: str) -> Dict:
        return {
            "answer": None,
            "grounded": False,
            "sources": [],
            "concept_id": concept_id or None,
            "domain": domain or None,
            "mastery": None,
            "suggested_action": None,
            "error": message,
        }
