"""Lightweight timing spans, written to data/events.jsonl as ``perf_span`` events.

Purpose: find where per-click latency goes in the Streamlit app WITHOUT
changing behaviour. Everything here is observational — every public helper is
a no-op when disabled, never raises, and never alters a return value.

Disable with ``SAE_PERF_TRACE=0`` (default: on while we investigate latency).

Event shape (one JSON line each, ``event_type == "perf_span"``)::

    stage        what was timed, e.g. "rerun_total", "ollama.http", "cache.lesson"
    duration_ms  wall time of the span
    t_start_ms   epoch ms when it started (lets you rebuild a timeline)
    run_id       the Streamlit script run (rerun) it belongs to
    page, session_id, thread
    superseded   True if a NEWER rerun had already started when this span ended
                 (i.e. work nobody is waiting for any more — orphaned threads)
    ...          stage-specific fields (tier, purpose, compute_ms, ...)

Ollama calls (``stage == "ollama.http"``) additionally carry, from Ollama's own
timings (``total_duration`` already INCLUDES time queued behind other requests):

    compute_ms         load + prompt_eval + eval  (work actually done)
    server_queue_ms    total - compute            (waited for the server's slot)
    client_overhead_ms wall  - total              (connect / HTTP; ~2 s was the
                                                   localhost->::1 fallback bug)
    inflight_at_start  concurrent Ollama calls from this process incl. this one

Limitations: ``run_id`` for spans created in worker threads comes from a
process-global "current rerun" (worker threads have no Streamlit script
context). That is exact for one user at a time, which is how this app runs
locally; with several simultaneous sessions spans may be attributed to
whichever rerun started last.
"""

from __future__ import annotations

import contextlib
import functools
import os
import sys
import threading
import time
import uuid
from typing import Any, Callable, Dict, Iterator, Optional

# --------------------------------------------------------------------------
# State
# --------------------------------------------------------------------------

_state_lock = threading.Lock()
_current: Dict[str, Any] = {"id": "", "page": "", "student_id": "system", "session_id": ""}
_runs: Dict[str, Dict[str, Any]] = {}       # run_id -> {"t0": perf_counter, "page": ...}

_tl = threading.local()                      # per-thread Ollama "purpose" label
_inflight_lock = threading.Lock()
_inflight = 0
_hook_lock = threading.Lock()
_hook_installed = False


def enabled() -> bool:
    return os.getenv("SAE_PERF_TRACE", "1").strip().lower() not in ("0", "false", "off", "no")


def _epoch_ms() -> float:
    return time.time() * 1000.0


def _clean(value: Any) -> Any:
    """JSON-safe: keep primitives, stringify everything else."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    return str(value)


def _emit(stage: str, duration_ms: float, start_ms: float, run_id: str, fields: Dict[str, Any]) -> None:
    """Write one perf_span event. Never raises."""
    try:
        from evaluation.event_log import EVT_PERF_SPAN, log_event

        with _state_lock:
            page = _current["page"]
            student_id = _current["student_id"]
            session_id = _current["session_id"]
            current_id = _current["id"]
        record = {
            "stage": stage,
            "duration_ms": round(duration_ms, 1),
            "t_start_ms": round(start_ms, 1),
            "run_id": run_id,
            "page": page,
            "session_id": session_id,
            "thread": threading.current_thread().name,
            # a newer rerun began before this span finished -> nobody is waiting on it
            "superseded": bool(run_id and current_id and run_id != current_id),
        }
        for k, v in fields.items():
            # explicit fields win over the run-level context (e.g. page="login"),
            # but never over the structural keys above
            if v is not None and (k not in record or k == "page"):
                record[k] = _clean(v)
        log_event(EVT_PERF_SPAN, student_id=student_id, **record)
    except Exception:
        pass


# --------------------------------------------------------------------------
# Rerun lifecycle (called from dashboard/app.py)
# --------------------------------------------------------------------------

def _streamlit_session_id() -> str:
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx

        ctx = get_script_run_ctx()
        return ctx.session_id if ctx else ""
    except Exception:
        return ""


def begin_rerun(started: Optional[float] = None, page: str = "", student_id: str = "system") -> str:
    """Mark the start of one Streamlit script run and return its run_id.

    ``started`` is a ``time.perf_counter()`` taken on the script's first line,
    so import time before this call is included in ``rerun_total``.
    """
    if not enabled():
        return ""
    install_ollama_hook()
    run_id = uuid.uuid4().hex[:8]
    t0 = started if started is not None else time.perf_counter()
    now = time.perf_counter()
    with _state_lock:
        # A script that ends via st.rerun()/st.stop() raises out of wherever it
        # happens to be (often before any "end" code runs). Close every earlier
        # unfinished run here: the next run starts immediately after, so this
        # is a close approximation of when it actually stopped.
        stale = list(_runs.items())
        _runs.clear()
        _runs[run_id] = {"t0": t0}
        _current.update(id=run_id, page=page, student_id=student_id or "system",
                        session_id=_streamlit_session_id())
    for old_id, old in stale:
        dur = (now - old["t0"]) * 1000.0
        _emit("rerun_total", dur, _epoch_ms() - dur, old_id, {"outcome": "ended_by_next_run"})
    return run_id


def set_context(page: Optional[str] = None, student_id: Optional[str] = None) -> None:
    if not enabled():
        return
    with _state_lock:
        if page is not None:
            _current["page"] = page
        if student_id:
            _current["student_id"] = student_id


def current_run_id() -> str:
    return _current["id"]


def checkpoint(name: str) -> None:
    """Emit ``rerun.segment:<name>``: the time since the previous checkpoint of
    this run (or since the run started). Called at a few points in the
    top-level script so that startup time outside any span is attributed to a
    named stretch of code instead of an anonymous "other".
    """
    if not enabled():
        return
    now = time.perf_counter()
    with _state_lock:
        run = _runs.get(_current["id"])
        if run is None:
            return
        last = run.get("last", run["t0"])
        run["last"] = now
        rid = _current["id"]
    dur = (now - last) * 1000.0
    _emit(f"rerun.segment:{name}", dur, _epoch_ms() - dur, rid, {})


def end_rerun(run_id: str, outcome: str = "") -> None:
    """Emit ``rerun_total`` for this run (idempotent). ``outcome`` is e.g.
    "rendered", "login", or the control-flow exception that ended the script
    ("RerunException" means the script asked for another run — one click is
    usually a chain of reruns).
    """
    if not run_id or not enabled():
        return
    with _state_lock:
        run = _runs.pop(run_id, None)
    if run is None:
        return
    dur = (time.perf_counter() - run["t0"]) * 1000.0
    _emit("rerun_total", dur, _epoch_ms() - dur, run_id, {"outcome": outcome})


# --------------------------------------------------------------------------
# Spans
# --------------------------------------------------------------------------

@contextlib.contextmanager
def span(stage: str, run_id: Optional[str] = None, **fields: Any) -> Iterator[Dict[str, Any]]:
    """Time a block. The yielded dict may be filled in with extra fields
    (e.g. ``sp["tier"] = "disk"``) and is merged into the event. Exceptions —
    including Streamlit's control-flow ones — propagate unchanged and are
    recorded in ``exc``.
    """
    if not enabled():
        yield {}
        return
    extra: Dict[str, Any] = {}
    rid = run_id if run_id is not None else _current["id"]
    start_ms = _epoch_ms()
    t0 = time.perf_counter()
    try:
        yield extra
    except BaseException as exc:
        extra.setdefault("exc", type(exc).__name__)
        raise
    finally:
        _emit(stage, (time.perf_counter() - t0) * 1000.0, start_ms, rid, {**fields, **extra})


def record(stage: str, duration_ms: float, **fields: Any) -> None:
    """Record a duration measured elsewhere (ending now)."""
    if not enabled():
        return
    _emit(stage, duration_ms, _epoch_ms() - duration_ms, _current["id"], fields)


def timed(stage: str, **fields: Any) -> Callable:
    """Decorator form of :func:`span` — no re-indentation of the wrapped body."""
    def deco(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            with span(stage, **fields):
                return fn(*args, **kwargs)
        return wrapper
    return deco


def cache_event(kind: str, tier: str, duration_ms: float = 0.0, **fields: Any) -> None:
    """``cache.<kind>`` with tier = memory | disk | miss."""
    record(f"cache.{kind}", duration_ms, tier=tier, **fields)


# --------------------------------------------------------------------------
# Ollama: one span per HTTP request
# --------------------------------------------------------------------------

@contextlib.contextmanager
def label(purpose: str, **detail: Any) -> Iterator[None]:
    """Name the Ollama call(s) made inside this block (thread-local), e.g.
    ``with label("lesson.section", section="theory"): llm.invoke(...)``.
    Unlabelled calls fall back to the calling module/function name.
    """
    if not enabled():
        yield
        return
    install_ollama_hook()  # cheap; by now the agent module (and langchain_ollama) is imported
    prev = getattr(_tl, "label", None)
    _tl.label = (purpose, detail)
    try:
        yield
    finally:
        _tl.label = prev


def _caller() -> str:
    """First frame outside langchain / this module = the real call site."""
    try:
        f = sys._getframe(2)
        for _ in range(30):
            if f is None:
                break
            mod = f.f_globals.get("__name__", "")
            if not (mod.startswith(("langchain", "pydantic")) or mod == __name__):
                return f"{mod}.{f.f_code.co_name}"
            f = f.f_back
    except Exception:
        pass
    return "unknown"


def _ollama_fields(result: Any, wall_ms: float) -> Dict[str, Any]:
    """Derive queue/compute/overhead from Ollama's own durations (ns)."""
    try:
        info = dict(result.generations[0].generation_info or {})
    except Exception:
        return {}

    def ms(key: str) -> Optional[float]:
        v = info.get(key)
        return round(v / 1e6, 1) if isinstance(v, (int, float)) else None

    total, load, pe, ev = ms("total_duration"), ms("load_duration"), ms("prompt_eval_duration"), ms("eval_duration")
    if total is None:
        return {}
    compute = (load or 0.0) + (pe or 0.0) + (ev or 0.0)
    out: Dict[str, Any] = {
        "server_total_ms": total,
        "load_ms": load,
        "prompt_eval_ms": pe,
        "eval_ms": ev,
        "compute_ms": round(compute, 1),
        # total_duration includes time queued behind other requests
        "server_queue_ms": round(max(0.0, total - compute), 1),
        "client_overhead_ms": round(max(0.0, wall_ms - total), 1),
        "prompt_tokens": info.get("prompt_eval_count"),
        "eval_tokens": info.get("eval_count"),
    }
    if ev and info.get("eval_count"):
        out["tokens_per_s"] = round(info["eval_count"] / (ev / 1000.0), 2)
    return out


def _make_timed_generate(orig: Callable) -> Callable:
    @functools.wraps(orig)
    def timed_generate(self: Any, *args: Any, **kwargs: Any) -> Any:
        if not enabled():
            return orig(self, *args, **kwargs)
        global _inflight
        lab = getattr(_tl, "label", None)
        purpose, detail = lab if lab else (None, {})
        caller = _caller()
        with _inflight_lock:
            _inflight += 1
            inflight_at_start = _inflight
        start_ms = _epoch_ms()
        t0 = time.perf_counter()
        result = None
        exc_name = None
        try:
            result = orig(self, *args, **kwargs)
            return result
        except BaseException as exc:
            exc_name = type(exc).__name__
            raise
        finally:
            with _inflight_lock:
                _inflight -= 1
            wall_ms = (time.perf_counter() - t0) * 1000.0
            fields: Dict[str, Any] = {
                "purpose": purpose or "unlabelled",
                "caller": caller,
                "model": getattr(self, "model", None),
                "inflight_at_start": inflight_at_start,
                "exc": exc_name,
                **detail,
            }
            fields.update(_ollama_fields(result, wall_ms))
            _emit("ollama.http", wall_ms, start_ms, _current["id"], fields)

    timed_generate._sae_perf_wrapped = True  # type: ignore[attr-defined]
    return timed_generate


def install_ollama_hook() -> bool:
    """Wrap ``ChatOllama._generate`` once so EVERY ``invoke`` (one invoke = one
    HTTP request to Ollama, retries included) emits an ``ollama.http`` span.
    Idempotent; returns True if the hook is active.

    Deliberately LAZY: importing langchain_ollama costs 10-20 s on the dev
    machine, so this never imports it — it only hooks the class once something
    else has. ``begin_rerun`` and ``label`` retry it, so the hook is in place
    before the first call without shifting that import cost onto app startup.
    """
    global _hook_installed
    if not enabled():
        return False
    if _hook_installed:
        return True
    if "langchain_ollama.chat_models" not in sys.modules:
        return False
    with _hook_lock:
        if _hook_installed:
            return True
        try:
            from langchain_ollama.chat_models import ChatOllama
        except Exception:
            return False
        orig = ChatOllama._generate
        if getattr(orig, "_sae_perf_wrapped", False):
            _hook_installed = True
            return True
        try:
            ChatOllama._generate = _make_timed_generate(orig)  # type: ignore[method-assign]
        except Exception:
            return False
        _hook_installed = True
        return True


# --------------------------------------------------------------------------
# Neo4j: time each query without touching call sites
# --------------------------------------------------------------------------

class _TimedSession:
    """Delegating proxy: only ``run`` is timed; everything else passes through."""

    def __init__(self, session: Any) -> None:
        self._s = session

    def __enter__(self) -> "_TimedSession":
        self._s.__enter__()
        return self

    def __exit__(self, *exc: Any) -> Any:
        return self._s.__exit__(*exc)

    def run(self, query: Any, *args: Any, **kwargs: Any) -> Any:
        with span("neo4j.query", cypher=" ".join(str(query).split())[:60]):
            return self._s.run(query, *args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._s, name)


class _TimedDriver:
    def __init__(self, driver: Any) -> None:
        self._d = driver

    def session(self, *args: Any, **kwargs: Any) -> _TimedSession:
        return _TimedSession(self._d.session(*args, **kwargs))

    def __getattr__(self, name: str) -> Any:
        return getattr(self._d, name)


def wrap_neo4j_driver(driver: Any) -> Any:
    """Return a timing proxy around a neo4j driver (or the driver itself if disabled)."""
    return _TimedDriver(driver) if enabled() else driver
