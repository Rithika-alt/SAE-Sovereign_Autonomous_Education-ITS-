"""Tests for evaluation/perf_trace.py and scripts/perf_report.py.

Telemetry must never change behaviour or crash the app, so most of these pin
the "boring" guarantees: no-op when disabled, exceptions pass through, writes
are thread-safe, and nothing here touches the real data/events.jsonl.
"""

import importlib.util
import json
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

import evaluation.event_log as event_log
from evaluation import perf_trace as pt


@pytest.fixture
def log(tmp_path, monkeypatch):
    """Redirect events.jsonl to a temp file and reset perf_trace's global state."""
    path = tmp_path / "events.jsonl"
    monkeypatch.setattr(event_log, "_LOG_PATH", path)
    monkeypatch.setattr(event_log, "_DATA_DIR", tmp_path)
    monkeypatch.setenv("SAE_PERF_TRACE", "1")
    pt._runs.clear()
    pt._current.update(id="", page="", student_id="system", session_id="")

    def read():
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

    return read


# ---------------------------------------------------------------- spans

def test_span_writes_event_with_expected_fields(log):
    pt.begin_rerun(page="home", student_id="s1")
    with pt.span("demo", a=1) as sp:
        sp["tier"] = "disk"
    (e,) = [r for r in log() if r["stage"] == "demo"]
    assert e["event_type"] == "perf_span"
    assert e["student_id"] == "s1"
    assert e["a"] == 1 and e["tier"] == "disk" and e["page"] == "home"
    assert e["duration_ms"] >= 0 and e["t_start_ms"] > 0 and e["run_id"]
    assert e["superseded"] is False


def test_disabled_is_a_complete_noop(log, monkeypatch):
    monkeypatch.setenv("SAE_PERF_TRACE", "0")
    assert pt.begin_rerun() == ""
    with pt.span("demo") as sp:
        sp["x"] = 1                       # body still runs, dict still usable
    pt.record("r", 5.0)
    pt.cache_event("lesson", "miss")
    assert pt.install_ollama_hook() is False
    assert log() == []


def test_exception_propagates_and_is_recorded(log):
    with pytest.raises(ValueError):
        with pt.span("boom"):
            raise ValueError("x")
    (e,) = log()
    assert e["stage"] == "boom" and e["exc"] == "ValueError"


def test_control_flow_baseexception_propagates(log):
    class Rerun(BaseException):
        pass

    with pytest.raises(Rerun):
        with pt.span("page"):
            raise Rerun()
    assert log()[0]["exc"] == "Rerun"


def test_explicit_page_field_overrides_context_but_not_structural_keys(log):
    pt.begin_rerun(page="home")
    with pt.span("rerun.page", page="login", thread="evil"):
        pass
    e = [r for r in log() if r["stage"] == "rerun.page"][0]
    assert e["page"] == "login"
    assert e["thread"] != "evil"


def test_non_json_fields_are_stringified_not_dropped(log):
    with pt.span("demo", path=Path("a/b"), obj=object()):
        pass
    e = log()[0]
    assert e["path"] == str(Path("a/b")) and isinstance(e["obj"], str)


def test_writes_are_thread_safe(log):
    def work():
        for i in range(50):
            with pt.span("t", i=i):
                pass

    threads = [threading.Thread(target=work) for _ in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    rows = log()                          # json.loads would raise on an interleaved line
    assert len(rows) == 400


def test_timed_decorator_preserves_behaviour(log):
    @pt.timed("fn.stage")
    def add(a, b=1):
        """doc"""
        return a + b

    assert add(2, b=3) == 5
    assert add.__name__ == "add" and add.__doc__ == "doc"
    assert log()[0]["stage"] == "fn.stage"


# ---------------------------------------------------------------- reruns

def test_superseded_flag_marks_work_that_outlives_its_rerun(log):
    pt.begin_rerun(page="a")
    with pt.span("orphan"):
        pt.begin_rerun(page="b")          # user clicked again mid-span
    with pt.span("fresh"):
        pass
    rows = {r["stage"]: r for r in log()}
    assert rows["orphan"]["superseded"] is True
    assert rows["fresh"]["superseded"] is False


def test_begin_rerun_closes_earlier_unfinished_runs(log):
    first = pt.begin_rerun(page="a")
    pt.begin_rerun(page="b")
    closed = [r for r in log() if r["stage"] == "rerun_total"]
    assert [r["run_id"] for r in closed] == [first]
    assert closed[0]["outcome"] == "ended_by_next_run"


def test_end_rerun_is_idempotent(log):
    rid = pt.begin_rerun()
    pt.end_rerun(rid, outcome="rendered")
    pt.end_rerun(rid, outcome="rendered")
    assert len([r for r in log() if r["stage"] == "rerun_total"]) == 1


def test_checkpoints_partition_the_run_timeline(log):
    pt.begin_rerun(started=time.perf_counter() - 0.10)    # script "started" 100 ms ago
    pt.checkpoint("startup")                               # measured from run start
    time.sleep(0.05)
    pt.checkpoint("next")                                  # measured from previous checkpoint
    segs = {r["stage"]: r["duration_ms"] for r in log()}
    assert segs["rerun.segment:startup"] >= 100
    assert 50 <= segs["rerun.segment:next"] < 90


def test_checkpoint_is_noop_without_active_run_or_when_disabled(log, monkeypatch):
    pt.checkpoint("orphan")                                # no begin_rerun yet
    assert log() == []
    pt.begin_rerun()
    monkeypatch.setenv("SAE_PERF_TRACE", "0")
    pt.checkpoint("disabled")
    assert log() == []


def test_rerun_total_includes_time_before_begin_when_started_given(log):
    t0 = time.perf_counter() - 0.2        # script "started" 200 ms ago (imports)
    rid = pt.begin_rerun(started=t0)
    pt.end_rerun(rid, outcome="rendered")
    assert log()[0]["duration_ms"] >= 200


# ---------------------------------------------------------------- ollama hook

def _fake_result(total_ns, load_ns, pe_ns, ev_ns, tokens=40):
    info = {"total_duration": total_ns, "load_duration": load_ns, "prompt_eval_duration": pe_ns,
            "eval_duration": ev_ns, "prompt_eval_count": 12, "eval_count": tokens}
    return SimpleNamespace(generations=[SimpleNamespace(generation_info=info)])


def test_ollama_wrapper_separates_queue_compute_and_overhead(log):
    ms = 1_000_000

    def orig(self, *a, **k):
        time.sleep(0.05)                  # client-side wall ~50 ms
        return _fake_result(total_ns=30 * ms, load_ns=2 * ms, pe_ns=3 * ms, ev_ns=10 * ms)

    wrapped = pt._make_timed_generate(orig)
    with pt.label("lesson.section", section="theory"):
        result = wrapped(SimpleNamespace(model="llama3.2"), ["msg"])
    assert result.generations                           # return value untouched
    (e,) = [r for r in log() if r["stage"] == "ollama.http"]
    assert e["purpose"] == "lesson.section" and e["section"] == "theory" and e["model"] == "llama3.2"
    assert e["compute_ms"] == 15.0                      # load + prompt_eval + eval
    assert e["server_queue_ms"] == 15.0                 # total (30) - compute (15): waited for the slot
    assert e["client_overhead_ms"] >= 15                # wall (~50) - total (30)
    assert e["tokens_per_s"] == 4000.0                  # 40 tokens / 10 ms
    assert e["inflight_at_start"] == 1


def test_ollama_wrapper_unlabelled_call_names_its_caller(log):
    wrapped = pt._make_timed_generate(lambda self, *a, **k: _fake_result(1, 0, 0, 1))
    wrapped(SimpleNamespace(model="m"), [])
    e = log()[0]
    assert e["purpose"] == "unlabelled" and "test_perf_trace" in e["caller"]


def test_ollama_wrapper_records_failure_and_reraises(log):
    def orig(self, *a, **k):
        raise ConnectionError("down")

    wrapped = pt._make_timed_generate(orig)
    with pytest.raises(ConnectionError):
        wrapped(SimpleNamespace(model="m"), [])
    e = log()[0]
    assert e["stage"] == "ollama.http" and e["exc"] == "ConnectionError"
    assert pt._inflight == 0                            # counter released on failure


def test_ollama_wrapper_tracks_concurrency(log):
    gate = threading.Barrier(3)

    def orig(self, *a, **k):
        gate.wait(timeout=5)              # all three are in flight together
        return _fake_result(1, 0, 0, 1)

    wrapped = pt._make_timed_generate(orig)
    ts = [threading.Thread(target=wrapped, args=(SimpleNamespace(model="m"), [])) for _ in range(3)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert max(r["inflight_at_start"] for r in log()) == 3
    assert pt._inflight == 0


def test_ollama_wrapper_when_disabled_just_calls_through(log, monkeypatch):
    monkeypatch.setenv("SAE_PERF_TRACE", "0")
    wrapped = pt._make_timed_generate(lambda self, *a, **k: "ok")
    assert wrapped(SimpleNamespace(model="m")) == "ok"
    assert log() == []


def test_install_hook_is_lazy_and_never_imports_langchain(log, monkeypatch):
    # Importing langchain_ollama costs 10-20 s on the dev machine; the hook must
    # never be what pays it (it would shift that cost onto app startup).
    monkeypatch.setattr(pt, "_hook_installed", False)
    monkeypatch.delitem(sys.modules, "langchain_ollama.chat_models", raising=False)
    assert pt.install_ollama_hook() is False
    assert pt.begin_rerun() != ""                     # begin_rerun retries it, still without importing
    assert "langchain_ollama.chat_models" not in sys.modules


def test_install_hook_wraps_chatollama_once_and_is_idempotent(log, monkeypatch):
    from langchain_ollama.chat_models import ChatOllama

    base = getattr(ChatOllama._generate, "__wrapped__", ChatOllama._generate)
    monkeypatch.setattr(ChatOllama, "_generate", base)   # start from the unwrapped method; restored on teardown
    monkeypatch.setattr(pt, "_hook_installed", False)
    assert pt.install_ollama_hook() is True
    wrapped = ChatOllama._generate
    assert getattr(wrapped, "_sae_perf_wrapped", False) and wrapped.__wrapped__ is base
    assert pt.install_ollama_hook() is True and ChatOllama._generate is wrapped   # not double-wrapped


def test_label_installs_the_hook_once_the_module_is_loaded(log, monkeypatch):
    import langchain_ollama.chat_models  # noqa: F401  (loaded -> hook may install)

    calls = []
    monkeypatch.setattr(pt, "install_ollama_hook", lambda: calls.append(1) or True)
    with pt.label("x"):
        pass
    assert calls, "label() must try to install the hook so the first call is traced"


def test_label_restores_previous_label(log):
    with pt.label("outer"):
        with pt.label("inner"):
            assert pt._tl.label[0] == "inner"
        assert pt._tl.label[0] == "outer"
    assert pt._tl.label is None


# ---------------------------------------------------------------- neo4j proxy

class _FakeSession:
    def __init__(self):
        self.closed = False
        self.queries = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.closed = True
        return False

    def run(self, query, **params):
        self.queries.append((query, params))
        return SimpleNamespace(single=lambda: {"cnt": 7})


class _FakeDriver:
    def __init__(self):
        self.session_obj = _FakeSession()
        self.closed = False

    def session(self, **kw):
        return self.session_obj

    def close(self):
        self.closed = True


def test_neo4j_proxy_times_queries_and_delegates_everything_else(log):
    driver = _FakeDriver()
    proxy = pt.wrap_neo4j_driver(driver)
    with proxy.session() as session:
        result = session.run("MATCH (c:Concept {student: $sid})\n   RETURN count(c) AS cnt", sid="s1")
        assert result.single()["cnt"] == 7              # real result object returned untouched
    assert driver.session_obj.closed                     # __exit__ delegated
    assert driver.session_obj.queries[0][1] == {"sid": "s1"}
    proxy.close()
    assert driver.closed                                 # unknown attributes pass through
    (e,) = log()
    assert e["stage"] == "neo4j.query" and "\n" not in e["cypher"] and e["cypher"].startswith("MATCH (c:Concept")


def test_neo4j_proxy_not_applied_when_disabled(log, monkeypatch):
    monkeypatch.setenv("SAE_PERF_TRACE", "0")
    driver = _FakeDriver()
    assert pt.wrap_neo4j_driver(driver) is driver


# ---------------------------------------------------------------- event_log integration

def test_read_events_unchanged_and_emits_read_cost_span(log):
    event_log.log_event("thing", student_id="s1", n=1)
    event_log.log_event("thing", student_id="s1", n=2)
    event_log.log_event("other", student_id="s2")
    got = event_log.read_events(student_id="s1", event_type="thing")
    assert [e["n"] for e in got] == [1, 2]
    (span,) = [r for r in log() if r.get("stage") == "events.read_all"]
    assert span["matched"] == 2 and span["file_bytes"] > 0 and span["filter_type"] == "thing"


def test_read_events_still_works_when_tracing_disabled(log, monkeypatch):
    monkeypatch.setenv("SAE_PERF_TRACE", "0")
    event_log.log_event("thing", student_id="s1")
    assert len(event_log.read_events(event_type="thing")) == 1
    assert [r for r in log() if r.get("stage")] == []


# ---------------------------------------------------------------- report script

def _load_report():
    path = Path(__file__).resolve().parent.parent / "scripts" / "perf_report.py"
    spec = importlib.util.spec_from_file_location("perf_report", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _span(stage, start, dur, run="r1", thread="MainThread", session="sess", **kw):
    return {"event_type": "perf_span", "stage": stage, "t_start_ms": start, "duration_ms": dur,
            "run_id": run, "thread": thread, "session_id": session, "page": "home",
            "superseded": False, "timestamp": "2026-10-07T10:00:00+00:00", **kw}


def test_report_breakdown_computes_unexplained_page_time():
    rp = _load_report()
    spans = [
        _span("rerun_total", 0, 2000, outcome="rendered"),
        _span("rerun.auth_gate", 10, 40),
        _span("rerun.sidebar", 60, 100),
        _span("rerun.page", 200, 1000, page="home"),
        _span("kg.init", 250, 300),          # inside the page, main thread
        _span("kg.load", 260, 100),          # nested inside kg.init: must not double count
        _span("ollama.http", 300, 500, thread="Worker-1"),   # other thread: ignored
    ]
    (run,) = rp.build_runs(spans)
    b = rp.breakdown(run)
    assert b["page"] == 1000 and b["page_instrumented"] == 300
    assert b["page_unexplained"] == 700
    assert b["auth"] == 40 and b["sidebar"] == 100
    assert b["other"] == 2000 - (40 + 100 + 0 + 1000)


def test_report_chains_reruns_into_one_click_and_splits_ollama_clicks():
    rp = _load_report()
    spans = [
        # click 1: two chained reruns (first ends with st.rerun), no Ollama
        _span("rerun_total", 0, 500, run="a", outcome="RerunException"),
        _span("rerun_total", 600, 400, run="b", outcome="rendered"),
        # click 2: much later, calls Ollama
        _span("rerun_total", 20_000, 900, run="c", outcome="rendered"),
        _span("ollama.http", 20_100, 800, run="c", purpose="lesson.section", compute_ms=700,
              server_queue_ms=0, client_overhead_ms=3, inflight_at_start=1),
    ]
    clicks = rp.build_clicks(rp.build_runs(spans))
    assert [len(c["runs"]) for c in clicks] == [2, 1]
    assert [bool(c["ollama"]) for c in clicks] == [False, True]
    assert clicks[0]["latency_ms"] == 1000


def test_report_flags_serialization_and_cross_run_queueing():
    rp = _load_report()
    spans = [_span("rerun_total", 0, 100, run="r1", outcome="rendered"),
             _span("rerun_total", 1000, 100, run="r2", outcome="rendered")]
    # r1's call is orphaned and still running when r2's call starts, so r2 queues behind it
    spans.append(_span("ollama.http", 10, 5000, run="r1", purpose="animation.extract", compute_ms=5000,
                       server_queue_ms=0, client_overhead_ms=0, inflight_at_start=1, superseded=True))
    spans.append(_span("ollama.http", 1010, 4000, run="r2", purpose="test.generate", compute_ms=1000,
                       server_queue_ms=3000, client_overhead_ms=0, inflight_at_start=2))
    text = rp.render(spans)
    assert "behind animation.extract (orphaned)" in text
    assert "ratio" in text and "Overlapping batches" in text


def test_report_names_slow_startup_segments_and_keeps_them_out_of_leaf_work():
    rp = _load_report()
    spans = [
        _span("rerun_total", 0, 10_000, outcome="rendered"),
        _span("rerun.segment:startup", 0, 9_000),
        _span("rerun.segment:css", 9_000, 50),
        _span("rerun.page", 9_500, 400, page="home"),
    ]
    (run,) = rp.build_runs(spans)
    b = rp.breakdown(run)
    assert b["segments"] == {"startup": 9_000, "css": 50}
    assert b["page_instrumented"] == 0               # segments are not leaf work inside the page
    text = rp.render(spans)
    assert "slowest startup segments (ms): startup 9000" in text
    assert "rerun.segment:startup" not in text.split("Stages ranked")[1]   # excluded from the stage table


def test_report_cli_handles_empty_log(tmp_path, capsys):
    rp = _load_report()
    assert rp.main(["--events", str(tmp_path / "nope.jsonl"), "--all"]) == 1
    assert "No perf_span events" in capsys.readouterr().out


def test_report_renders_all_sections_on_realistic_data(tmp_path, capsys):
    rp = _load_report()
    spans = [
        _span("rerun_total", 0, 3000, run="a", outcome="rendered"),
        _span("rerun.page", 100, 2800, run="a"),
        _span("kg.init", 120, 200, run="a", backend="networkx"),
        _span("events.read_all", 400, 900, run="a", file_bytes=20480, matched=5),
    ]
    p = tmp_path / "events.jsonl"
    p.write_text("\n".join(json.dumps(s) for s in spans), encoding="utf-8")
    assert rp.main(["--events", str(p), "--all"]) == 0
    out = capsys.readouterr().out
    for needle in ("A. PRIORITY", "UNEXPLAINED", "Hints for cached", "B. Clicks that called Ollama",
                   "C. Ollama calls", "D. Contention", "E. events.jsonl read cost"):
        assert needle in out
