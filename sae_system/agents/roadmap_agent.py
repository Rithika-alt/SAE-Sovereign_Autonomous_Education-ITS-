"""Roadmap agent: generates 10-week roadmaps in parallel via Ollama."""

import json
import logging
import os
import time
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable, Dict, List, Optional

from json_repair import repair_json
from langchain_ollama import ChatOllama

from agents.tutor_agent import SovereigntyError

logger = logging.getLogger(__name__)

_BATCH_SIZE    = 3    # concurrent Ollama workers — safe for 8 GB machines with llama3.2
_WIKI_WORKERS  = 5    # concurrent Wikipedia HTTP workers
_MODULE_TIMEOUT = 120 # per-thread deadline in seconds before fallback kicks in


class RoadmapAgent:
    """Generates 10-week learning roadmaps with parallel module generation."""

    def __init__(self) -> None:
        base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        if not (
            base_url.startswith("http://localhost")
            or base_url.startswith("http://127.0.0.1")
        ):
            raise SovereigntyError(f"OLLAMA_BASE_URL '{base_url}' is not localhost.")

        self._base_url = base_url
        self._model    = os.getenv("OLLAMA_MODEL", "llama3.2")
        # Shared LLM used only for the sequential title-fetch call.
        self.llm = ChatOllama(
            base_url=self._base_url,
            model=self._model,
            temperature=0.3,
        )
        self.cache_dir = Path(__file__).resolve().parent.parent / "data" / "roadmaps"
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Public API  (interface unchanged — dashboard needs no changes)
    # ------------------------------------------------------------------

    def generate_roadmap(
        self,
        domain: str,
        progress_callback: Optional[Callable[[int, dict], None]] = None,
        student_id: str = "default",
    ) -> Dict:
        """Generate a 10-week roadmap using parallel module generation.

        Cache hit → instant return.
        Cache miss → parallel Ollama generation + parallel Wikipedia enrichment,
        sorted by week, written to disk.
        In both cases, populates the student's knowledge graph (idempotent).

        Args:
            domain: Human-readable domain name.
            progress_callback: Called with (week_number, module_dict) as each
                module completes. Fires from worker threads — must be thread-safe.
            student_id: Scopes the knowledge graph to one student.

        Returns:
            Roadmap dict with 'domain', 'total_weeks', 'modules' (week-sorted).
        """
        safe = domain.lower().replace(" ", "_")
        cache_file = self.cache_dir / f"{safe}.json"
        if cache_file.exists():
            with cache_file.open() as f:
                roadmap = json.load(f)
            self._populate_graph(roadmap, student_id)
            return roadmap

        # Phase 1 — one fast call for all 10 titles
        titles = self._get_titles(domain)

        # Phase 2 — pre-compute every module's static inputs before any thread starts
        module_inputs = self._precompute_module_inputs(domain, titles)

        # Phase 3 — parallel module generation (≤ _BATCH_SIZE concurrent Ollama calls)
        t_start = time.time()
        modules = self._generate_modules_parallel(module_inputs, progress_callback)
        elapsed = time.time() - t_start

        logger.info(
            "Parallel module generation complete: %d modules in %.1fs",
            len(modules), elapsed,
        )
        print(
            f"[RoadmapAgent] {len(modules)} modules generated in {elapsed:.1f}s "
            f"(parallel, batch_size={_BATCH_SIZE})"
        )

        # Phase 4 — parallel Wikipedia resource enrichment (up to _WIKI_WORKERS at once)
        modules = self._enrich_resources_parallel(modules)

        # Always return modules in week order regardless of completion order
        modules.sort(key=lambda m: m["week"])

        roadmap = {"domain": domain, "total_weeks": 10, "modules": modules}
        with cache_file.open("w") as f:
            json.dump(roadmap, f, indent=2)
        self._populate_graph(roadmap, student_id)
        return roadmap

    def _populate_graph(self, roadmap: Dict, student_id: str) -> None:
        """Populate the student's knowledge graph from a roadmap — skips if already done."""
        try:
            from memory.graph_engine import KnowledgeGraph
            graph       = KnowledgeGraph(student_id=student_id)
            domain      = roadmap.get("domain", "")
            graph_data  = graph.get_graph_data()
            already_populated = any(
                (n.get("domain") or "").lower() == domain.lower()
                for n in graph_data["nodes"]
            )
            if not already_populated:
                graph.populate_from_roadmap(roadmap)
                logger.info(
                    "Knowledge graph populated for student='%s' domain='%s'",
                    student_id, domain,
                )
            else:
                logger.debug(
                    "Knowledge graph already populated for student='%s' domain='%s'",
                    student_id, domain,
                )
            # Always run rich schema (idempotent — safe on every load)
            try:
                graph.create_rich_schema(roadmap, student_name=student_id)
            except Exception as schema_exc:
                logger.warning("Rich schema creation failed (non-fatal): %s", schema_exc)
        except Exception as exc:
            logger.warning("Knowledge graph population failed: %s", exc)

    def delete_cache(self, domain: str) -> None:
        """Delete cached roadmap to force regeneration."""
        safe = domain.lower().replace(" ", "_")
        p = self.cache_dir / f"{safe}.json"
        if p.exists():
            p.unlink()

    # ------------------------------------------------------------------
    # Parallel orchestration helpers
    # ------------------------------------------------------------------

    def _precompute_module_inputs(
        self, domain: str, titles: List[str]
    ) -> List[Dict]:
        """Build the complete input spec for every module before threads start.

        Prerequisites are derived statically from the titles list so that
        no thread needs to wait for another thread's result.  The module_id
        formula mirrors the one used inside _generate_module_content exactly.
        """
        all_ids = [t.lower().replace(" ", "_")[:30] for t in titles]
        inputs: List[Dict] = []
        for i, title in enumerate(titles):
            week = i + 1
            difficulty = (
                "Beginner"     if week <= 3 else
                "Intermediate" if week <= 7 else
                "Advanced"
            )
            prior_ids = all_ids[:i]            # mirrors original prior_ids logic
            prereqs   = prior_ids[-2:] if prior_ids else []
            inputs.append({
                "domain":     domain,
                "week":       week,
                "title":      title,
                "difficulty": difficulty,
                "prereqs":    prereqs,
                "module_id":  all_ids[i],
            })
        return inputs

    def _generate_modules_parallel(
        self,
        module_inputs: List[Dict],
        progress_callback: Optional[Callable[[int, dict], None]],
    ) -> List[Dict]:
        """Submit all modules to a bounded thread pool and collect results.

        Callbacks fire the moment each module completes, keeping the UI live.
        Failed threads produce a fallback module — the roadmap always has
        exactly 10 entries.
        """
        modules: List[Dict] = []

        with ThreadPoolExecutor(max_workers=_BATCH_SIZE) as pool:
            future_to_inp = {
                pool.submit(
                    self._generate_module_content,
                    inp["domain"],
                    inp["week"],
                    inp["title"],
                    inp["difficulty"],
                    inp["prereqs"],
                ): inp
                for inp in module_inputs
            }

            for future in as_completed(future_to_inp):
                inp = future_to_inp[future]
                week = inp["week"]
                try:
                    module = future.result()
                except Exception as exc:
                    logger.warning(
                        "Week %d generation failed (%s), using fallback.", week, exc
                    )
                    module = self._fallback_module(
                        inp["domain"], week, inp["title"],
                        inp["difficulty"], inp["prereqs"],
                    )

                modules.append(module)
                if progress_callback:
                    try:
                        progress_callback(week, module)
                    except Exception:
                        pass  # never let a UI callback crash generation

        return modules

    def _enrich_resources_parallel(self, modules: List[Dict]) -> List[Dict]:
        """Fetch Wikipedia resources for all modules concurrently.

        Each module gets one Wikipedia result for its first concept.
        Uses up to _WIKI_WORKERS simultaneous HTTP connections.
        """
        week_to_module = {m["week"]: m for m in modules}

        def _fetch(week: int) -> None:
            module  = week_to_module[week]
            concept = (module.get("concepts") or [""])[0]
            module["resources"] = self._get_resource(concept) if concept else []

        with ThreadPoolExecutor(max_workers=_WIKI_WORKERS) as pool:
            futures = [pool.submit(_fetch, w) for w in week_to_module]
            for future in as_completed(futures):
                try:
                    future.result(timeout=10)
                except Exception:
                    pass  # resource fetch failed — module keeps resources=[]

        return list(week_to_module.values())

    # ------------------------------------------------------------------
    # Per-thread module generator
    # ------------------------------------------------------------------

    def _make_llm(self) -> ChatOllama:
        """Create a fresh ChatOllama for one thread (no shared mutable state)."""
        return ChatOllama(
            base_url=self._base_url,
            model=self._model,
            temperature=0.3,
        )

    def _generate_module_content(
        self,
        domain: str,
        week: int,
        title: str,
        difficulty: str,
        prereqs: List[str],
    ) -> Dict:
        """Generate one module's content via Ollama.

        Creates its own LLM instance so threads share no mutable state.
        Monitors a per-call deadline of _MODULE_TIMEOUT seconds and returns
        the fallback if the deadline is exceeded.
        """
        module_id = title.lower().replace(" ", "_")[:30]
        llm       = self._make_llm()
        deadline  = time.time() + _MODULE_TIMEOUT

        prompt = (
            f"For a {domain} course, generate details for week {week}: '{title}'.\n"
            "Return ONLY valid JSON (no markdown, no explanation):\n"
            "{\n"
            f'  "week": {week},\n'
            f'  "module_id": "{module_id}",\n'
            f'  "title": "{title}",\n'
            '  "description": "2-3 sentence description of this module.",\n'
            '  "concepts": ["concept1", "concept2", "concept3", "concept4"],\n'
            f'  "prerequisites": {json.dumps(prereqs)},\n'
            '  "estimated_hours": 5,\n'
            f'  "difficulty": "{difficulty}"\n'
            "}"
        )

        for _ in range(3):
            if time.time() > deadline:
                logger.warning("Week %d timed out, using fallback.", week)
                break
            try:
                resp = llm.invoke(prompt)
                raw  = resp.content.strip().strip("```json").strip("```").strip()
                data = json.loads(repair_json(raw))
                data.setdefault("week",            week)
                data.setdefault("module_id",       module_id)
                data.setdefault("title",           title)
                data.setdefault("difficulty",      difficulty)
                data.setdefault("estimated_hours", 5)
                data.setdefault("prerequisites",   prereqs)
                if not data.get("description"):
                    data["description"] = f"Week {week} of your {domain} journey."
                if not data.get("concepts") or len(data["concepts"]) < 2:
                    data["concepts"] = [
                        f"{title} basics",
                        f"{title} techniques",
                        f"{title} applications",
                    ]
                else:
                    # Ensure every concept is a plain string (LLM sometimes returns dicts)
                    data["concepts"] = [
                        c if isinstance(c, str)
                        else str(c.get("concept") or c.get("name") or c.get("title")
                                 or next(iter(c.values()), title))
                        for c in data["concepts"]
                    ]
                data["resources"] = []   # populated later in enrichment phase
                return data
            except Exception:
                time.sleep(1)

        return self._fallback_module(domain, week, title, difficulty, prereqs)

    def _fallback_module(
        self,
        domain: str,
        week: int,
        title: str,
        difficulty: str,
        prereqs: List[str],
    ) -> Dict:
        """Return a valid complete module when all Ollama retries fail or time out."""
        module_id = title.lower().replace(" ", "_")[:30]
        return {
            "week":       week,
            "module_id":  module_id,
            "title":      title,
            "description": (
                f"Week {week} of your {domain} journey covers {title}. "
                f"This {difficulty.lower()} module builds on prior work "
                "and prepares you for the topics ahead."
            ),
            "concepts": [
                f"{title} fundamentals",
                f"{title} core techniques",
                f"{title} practical applications",
            ],
            "prerequisites":   prereqs,
            "estimated_hours": 5,
            "difficulty":      difficulty,
            "resources":       [],
        }

    # ------------------------------------------------------------------
    # Unchanged private helpers
    # ------------------------------------------------------------------

    def _get_titles(self, domain: str) -> List[str]:
        """Fetch 10 module titles in one fast call."""
        prompt = (
            f"List exactly 10 module titles for a {domain} learning course. "
            "Return ONLY a JSON array of 10 short title strings. "
            "No explanation. Example: [\"Introduction\", \"Core Concepts\", ...]"
        )
        for _ in range(3):
            try:
                resp   = self.llm.invoke(prompt)
                raw    = resp.content.strip().strip("```json").strip("```").strip()
                titles = json.loads(repair_json(raw))
                if isinstance(titles, list) and len(titles) >= 5:
                    while len(titles) < 10:
                        titles.append(f"{domain} Advanced Topic {len(titles) + 1}")
                    return titles[:10]
            except Exception:
                time.sleep(1)

        return [
            f"Introduction to {domain}",
            f"{domain} Fundamentals",
            "Core Concepts",
            "Intermediate Techniques",
            "Practical Applications",
            "Advanced Methods",
            "Real-World Projects",
            "Best Practices",
            "Capstone Integration",
            "Mastery & Beyond",
        ]

    def _get_resource(self, concept: str) -> List[Dict]:
        """Fetch one Wikipedia resource."""
        encoded = concept.replace(" ", "_")
        url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{encoded}"
        logger.debug("Wikipedia fetch — concept=%r url=%s", concept, url)
        try:
            r = requests.get(url, timeout=4, headers={"User-Agent": "SAESystem/1.0"})
            logger.debug(
                "Wikipedia response — concept=%r status=%d content_length=%d",
                concept, r.status_code, len(r.content),
            )
            if r.status_code == 200:
                d = r.json()
                title   = d.get("title", concept)
                extract = d.get("extract", "")
                page_url = d.get("content_urls", {}).get("desktop", {}).get("page", "")
                logger.info(
                    "Wikipedia OK — concept=%r title=%r extract_len=%d url=%s",
                    concept, title, len(extract), page_url,
                )
                return [{"title": title, "summary": extract[:250], "url": page_url}]
            else:
                logger.warning(
                    "Wikipedia non-200 — concept=%r status=%d body=%r",
                    concept, r.status_code, r.text[:200],
                )
        except Exception as exc:
            logger.warning(
                "Wikipedia fetch failed — concept=%r url=%s error=%s: %s",
                concept, url, type(exc).__name__, exc,
            )
        return []

    def _generate_module(
        self,
        domain: str,
        week: int,
        title: str,
        difficulty: str,
        prior_ids: List[str],
    ) -> Dict:
        """Legacy shim — kept so any external caller is not broken."""
        prereqs = prior_ids[-2:] if prior_ids else []
        module  = self._generate_module_content(domain, week, title, difficulty, prereqs)
        module["resources"] = self._get_resource(
            (module.get("concepts") or [""])[0]
        )
        return module
