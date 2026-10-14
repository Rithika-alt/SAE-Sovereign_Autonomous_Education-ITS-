"""Single-flight background generation of tests.

Why this exists: the test page used to generate the test INSIDE the Streamlit script run. Any
rerun (a click, a refresh, a reconnect) abandons that run but not the worker threads already
talking to Ollama, and the new run started a second generation. Ollama here serves one request
at a time, so the second generation queued behind the first: two full generations for one test
(seen in the real event log), and "loading" for 10-20 minutes.

Now there is at most ONE generation per (domain, concept), running in a daemon thread that no
rerun can orphan or duplicate. The page only polls its status; leaving the page does not cancel
it; and it can be started early (while the student is still reading the lesson) so the test is
usually ready by the time they click "Take test".
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_LOCK = threading.Lock()
_JOBS: Dict[Tuple[str, str], "GenerationJob"] = {}
_KEEP_DONE_S = 300          # a finished job's result is reused for this long (it is also in the disk cache)


@dataclass
class GenerationJob:
    concept_id: str
    domain: str
    state: str = "running"                       # running | done | error
    questions: Optional[List[Dict]] = None
    error: str = ""
    started_at: float = field(default_factory=time.time)
    finished_at: float = 0.0
    completed: List[Tuple[str, int, float]] = field(default_factory=list)   # (question type, count, finished-at)

    def elapsed(self) -> float:
        return (self.finished_at or time.time()) - self.started_at

    def on_progress(self, q_type: str, n: int) -> None:
        self.completed.append((q_type, n, time.time()))


def _key(concept_id: str, domain: str) -> Tuple[str, str]:
    return (domain.strip().lower(), concept_id)


def _run(job: GenerationJob, lesson_content: str) -> None:
    try:
        from evaluation.test_engine import TestEngine

        questions = TestEngine().generate_test(
            job.concept_id, job.domain, lesson_content, progress=job.on_progress,
        )
        job.questions, job.state = questions, "done"
    except Exception as exc:                      # surfaced to the page; never raised in the thread
        logger.exception("Background test generation failed for %s/%s", job.domain, job.concept_id)
        job.error, job.state = f"{type(exc).__name__}: {exc}", "error"
    finally:
        job.finished_at = time.time()


def start_or_get(concept_id: str, domain: str, lesson_content: str, retry: bool = False) -> GenerationJob:
    """Return the job for this test, starting one only if none is running or usable.

    Safe to call from every rerun and from several threads at once: at most one generation is
    ever in flight per (domain, concept). A cached test comes back as an already-finished job.
    ``retry=True`` replaces a job that ended in an error.
    """
    key = _key(concept_id, domain)
    with _LOCK:
        job = _JOBS.get(key)
        if job is not None:
            if job.state == "running":
                return job
            if job.state == "done" and time.time() - job.finished_at < _KEEP_DONE_S:
                return job
            if job.state == "error" and not retry:
                return job

        # a test already on disk needs no generation (the engine also validates it)
        try:
            from evaluation.test_engine import TestEngine

            cached = TestEngine()._load_cache(concept_id, domain)
        except Exception:
            cached = []
        if cached:
            job = GenerationJob(concept_id, domain, state="done", questions=cached)
            job.finished_at = time.time()
            _JOBS[key] = job
            return job

        job = GenerationJob(concept_id, domain)
        _JOBS[key] = job
        threading.Thread(
            target=_run, args=(job, lesson_content), daemon=True, name=f"testgen-{concept_id[:24]}",
        ).start()
        return job


def get(concept_id: str, domain: str) -> Optional[GenerationJob]:
    with _LOCK:
        return _JOBS.get(_key(concept_id, domain))


def discard(concept_id: str, domain: str) -> None:
    """Forget a finished/failed job (does not stop a running thread — its output is token-capped)."""
    with _LOCK:
        job = _JOBS.get(_key(concept_id, domain))
        if job is not None and job.state != "running":
            _JOBS.pop(_key(concept_id, domain), None)
