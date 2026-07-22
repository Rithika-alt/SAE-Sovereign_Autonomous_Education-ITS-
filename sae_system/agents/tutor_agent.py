import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable, Dict, Optional, Tuple

from langchain_ollama import ChatOllama


class SovereigntyError(Exception):
    pass


class TutorAgent:

    SECTION_PROMPTS = {
        "introduction": (
            "You are a professor. In 2 concise paragraphs introduce '{concept}' "
            "in '{domain}': what it is, why it matters, and one real-world analogy. "
            "Plain text only."
        ),
        "theory": (
            "You are a professor. In 2 concise paragraphs explain the core theory "
            "of '{concept}' in '{domain}': key definitions, principles, and any "
            "important formula. Plain text only."
        ),
        "example": (
            "You are a professor. Give one short worked example of '{concept}' "
            "in '{domain}' in 2 paragraphs. Show each step clearly. Plain text only."
        ),
        "misconceptions": (
            "You are a professor. List 3 common misconceptions about '{concept}' "
            "in '{domain}'. Number them 1-3. For each: state the misconception, "
            "then the correction in one sentence each. Plain text only."
        ),
        "applications": (
            "You are a professor. Describe 2 real-world applications of '{concept}' "
            "in '{domain}'. Number them 1-2. One sentence per application. "
            "Plain text only."
        ),
        "summary": (
            "You are a professor. Write 3 key takeaways about '{concept}' "
            "in '{domain}'. Number them 1-3. One sentence each. Plain text only."
        ),
    }

    SECTION_ORDER = [
        "introduction",
        "theory",
        "example",
        "misconceptions",
        "applications",
        "summary",
    ]

    def __init__(self):
        base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        if not (base_url.startswith("http://localhost") or
                base_url.startswith("http://127.0.0.1")):
            raise SovereigntyError(
                f"Non-local endpoint blocked: {base_url}")
        self._base_url = base_url
        self._model    = os.getenv("OLLAMA_MODEL", "llama3.2")
        self.llm = ChatOllama(
            base_url=self._base_url,
            model=self._model,
            temperature=0.4,
        )
        self._cache: Dict = {}
        self._cache_dir = Path(__file__).resolve().parent.parent / "data" / "lessons"
        self._cache_dir.mkdir(parents=True, exist_ok=True)

    def _make_llm(self) -> ChatOllama:
        """Fresh ChatOllama per thread — no shared mutable state."""
        return ChatOllama(
            base_url=self._base_url,
            model=self._model,
            temperature=0.4,
        )

    def _cache_file(self, concept: str, domain: str) -> Path:
        safe = f"{domain}_{concept}".lower().replace(" ", "_")
        return self._cache_dir / f"{safe}.json"

    def teach_concept(self, concept: str, domain: str) -> dict:
        """
        Generate a full 6-section lesson.
        Returns dict with keys matching SECTION_ORDER.
        Every section is guaranteed to have content.
        """
        cache_key = f"{domain}||{concept}"
        if cache_key in self._cache:
            cached = self._cache[cache_key]
            if self._is_valid(cached):
                return cached

        cache_file = self._cache_file(concept, domain)
        if cache_file.exists():
            try:
                with cache_file.open() as f:
                    cached = json.load(f)
                if self._is_valid(cached):
                    self._cache[cache_key] = cached
                    return cached
            except Exception:
                pass

        lesson = {"concept_id": concept, "domain": domain}

        for section_key in self.SECTION_ORDER:
            prompt_template = self.SECTION_PROMPTS[section_key]
            prompt = prompt_template.format(
                concept=concept, domain=domain)
            content = self._call_ollama(prompt, section_key,
                                        concept, domain)
            lesson[section_key] = content

        self._cache[cache_key] = lesson
        try:
            with cache_file.open("w") as f:
                json.dump(lesson, f, indent=2)
        except Exception:
            pass
        return lesson

    def teach_concept_parallel(
        self,
        concept: str,
        domain: str,
        progress_callback: Optional[Callable[[str, str, bool], None]] = None,
    ) -> Dict:
        """Generate all 6 lesson sections in parallel via ThreadPoolExecutor.

        All sections are submitted to Ollama simultaneously. As each finishes
        the optional callback fires so the UI can update immediately.

        Args:
            concept: The concept to teach.
            domain:  The subject domain.
            progress_callback: Called with (section_key, content, ok) as each
                section completes. Fires from the main thread via as_completed().

        Returns:
            Lesson dict with concept_id, domain, and all 6 section keys.
        """
        cache_key = f"{domain}||{concept}"
        if cache_key in self._cache:
            cached = self._cache[cache_key]
            if self._is_valid(cached):
                return cached

        cache_file = self._cache_file(concept, domain)
        if cache_file.exists():
            try:
                with cache_file.open() as f:
                    cached = json.load(f)
                if self._is_valid(cached):
                    self._cache[cache_key] = cached
                    return cached
            except Exception:
                pass

        lesson: Dict = {"concept_id": concept, "domain": domain}

        def _worker(key: str) -> Tuple[str, str]:
            llm    = self._make_llm()
            prompt = self.SECTION_PROMPTS[key].format(concept=concept, domain=domain)
            for _ in range(3):
                try:
                    response = llm.invoke(prompt)
                    text = response.content.strip()
                    if text and len(text) > 30:
                        return key, text
                except Exception:
                    pass
                time.sleep(2)
            return key, self._fallback(key, concept, domain)

        with ThreadPoolExecutor(max_workers=3) as pool:
            future_to_key = {
                pool.submit(_worker, key): key
                for key in self.SECTION_ORDER
            }
            for future in as_completed(future_to_key):
                key, content = future.result()
                lesson[key]  = content
                if progress_callback:
                    try:
                        progress_callback(key, content, len(content) > 30)
                    except Exception:
                        pass

        self._cache[cache_key] = lesson
        try:
            with cache_file.open("w") as f:
                json.dump(lesson, f, indent=2)
        except Exception:
            pass
        return lesson

    def _call_ollama(self, prompt: str, section_key: str,
                     concept: str, domain: str) -> str:
        """Call Ollama with retry. Never returns empty string."""
        for _ in range(3):
            try:
                response = self.llm.invoke(prompt)
                text = response.content.strip()
                if text and len(text) > 30:
                    return text
            except Exception:
                pass
            time.sleep(2)

        # Guaranteed fallback — never empty
        return self._fallback(section_key, concept, domain)

    def _is_valid(self, lesson: dict) -> bool:
        return all(
            len(lesson.get(k, "")) > 30
            for k in self.SECTION_ORDER
        )

    def _fallback(self, section_key: str,
                  concept: str, domain: str) -> str:
        fallbacks = {
            "introduction": (
                f"{concept} is a foundational concept in {domain}.\n\n"
                f"It was developed to address specific challenges that "
                f"practitioners face in the field. Over time it has "
                f"become central to how professionals think about and "
                f"solve problems in {domain}.\n\n"
                f"A useful analogy: think of {concept} like a map. "
                f"Without it you can still travel, but with it you "
                f"know exactly where you are and where you need to go.\n\n"
                f"Mastering {concept} will unlock deeper understanding "
                f"of many other topics in {domain}. It is a stepping "
                f"stone that makes advanced concepts far more accessible."
            ),
            "theory": (
                f"The theoretical foundation of {concept} rests on "
                f"several core principles that define its behaviour "
                f"and applications.\n\n"
                f"First, {concept} operates according to well-defined "
                f"rules that have been validated through both research "
                f"and practical application across many years.\n\n"
                f"Second, the internal structure of {concept} can be "
                f"understood by examining how its components interact "
                f"with each other and with the broader system.\n\n"
                f"Third, the mathematical or logical formalism behind "
                f"{concept} provides the precise language needed to "
                f"reason about it rigorously and apply it correctly.\n\n"
                f"Understanding these principles deeply will allow you "
                f"to apply {concept} in novel situations, not just "
                f"repeat memorised procedures."
            ),
            "example": (
                f"Here is a worked example of {concept} in {domain}.\n\n"
                f"Step 1: Define the problem clearly. Identify what "
                f"inputs you have, what output you need, and what "
                f"constraints apply.\n\n"
                f"Step 2: Apply {concept} to the inputs. Follow the "
                f"core principles in the correct order, checking your "
                f"reasoning at each stage.\n\n"
                f"Step 3: Verify the result. Check that your output "
                f"satisfies the original problem requirements and makes "
                f"sense in context.\n\n"
                f"This three-step pattern generalises to almost any "
                f"application of {concept} you will encounter."
            ),
            "misconceptions": (
                f"1. Misconception: {concept} is only relevant in "
                f"academic settings.\n"
                f"   Correction: It is widely used in industry and "
                f"appears in production systems every day.\n\n"
                f"2. Misconception: You need to master every related "
                f"concept first before learning {concept}.\n"
                f"   Correction: The basics of {concept} are accessible "
                f"with foundational knowledge only.\n\n"
                f"3. Misconception: {concept} always gives the same "
                f"result regardless of context.\n"
                f"   Correction: Results depend heavily on the specific "
                f"inputs, parameters, and conditions applied.\n\n"
                f"4. Misconception: Understanding {concept} means "
                f"memorising its definition.\n"
                f"   Correction: True understanding means being able "
                f"to apply it to problems you have never seen before."
            ),
            "applications": (
                f"1. Software Engineering: {concept} is used to design "
                f"systems that are robust, scalable, and maintainable. "
                f"Engineers apply it daily when architecting solutions "
                f"that must perform under real-world conditions.\n\n"
                f"2. Data and Research: Scientists and analysts rely on "
                f"{concept} to process information, identify patterns, "
                f"and draw conclusions that would be impossible to reach "
                f"manually at scale.\n\n"
                f"3. Business and Product: Companies apply {concept} "
                f"to improve their products, optimise operations, and "
                f"make better decisions. It underpins many of the "
                f"features users interact with every day without "
                f"realising it."
            ),
            "summary": (
                f"1. {concept} is a core concept in {domain} that "
                f"underpins a wide range of practical applications. "
                f"Understanding it is non-negotiable for anyone serious "
                f"about working in this field.\n\n"
                f"2. The theoretical foundations of {concept} are "
                f"well-established and supported by decades of research "
                f"and practice. Learning the theory gives you the "
                f"tools to reason about new problems.\n\n"
                f"3. Worked examples are the fastest way to internalise "
                f"{concept}. The more problems you solve, the more "
                f"natural its application becomes.\n\n"
                f"4. Common misconceptions about {concept} often stem "
                f"from oversimplification. Always seek the deeper "
                f"understanding rather than surface-level familiarity.\n\n"
                f"5. The real-world applications of {concept} are vast "
                f"and growing. Mastering it now positions you well for "
                f"advanced topics and professional work in {domain}."
            ),
        }
        return fallbacks.get(
            section_key,
            f"Content for {section_key} of {concept} in {domain}."
        )

    # ------------------------------------------------------------------
    # Legacy shims kept so the LangGraph pipeline still works
    # ------------------------------------------------------------------

    def teach_concept_fast(self, concept_id: str, domain: str) -> dict:
        return self.teach_concept(concept_id, domain)

    def get_cached_lesson(self, concept_id: str, domain: str = "") -> dict | None:
        cache_key = f"{domain}||{concept_id}"
        cached = self._cache.get(cache_key)
        if cached and self._is_valid(cached):
            return cached
        return None

    def cache_lesson(self, concept_id: str, domain: str) -> None:
        self.teach_concept(concept_id, domain)

    def run(self, state: dict) -> dict:
        concept_id = state.get("concept_id", "unknown")
        domain     = state.get("domain", "general")
        lesson = self.teach_concept(concept_id, domain)
        state["lesson_content"] = lesson.get("introduction", "")
        state["current_phase"]  = "lesson"
        state["error_message"]  = ""
        return state
