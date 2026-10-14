"""Background, single-flight test generation (evaluation/generation_jobs.py) and its pages.

The regression: generation ran inside the Streamlit script run, so every rerun started another
one that queued behind the first on the single-threaded Ollama server (two full generations for
one test in the real log; 10-20 minute waits). These tests simulate reruns, concurrent callers and
failures with a controllable fake generator — no model is involved.
"""

import threading
import time
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import evaluation.event_log as event_log
import evaluation.generation_jobs as gj
import evaluation.test_engine as te

APP = str(Path(__file__).resolve().parent.parent / "dashboard" / "app.py")
CONCEPT, DOMAIN = "intro_module", "Digital Marketing"


def ten_questions(tag="x"):
    qs = te._build_fallback_questions(CONCEPT, DOMAIN)
    for i, q in enumerate(qs):
        q["question"] = f"{tag} question number {i + 1} about marketing"
    return qs


class FakeGenerator:
    """Stands in for TestEngine.generate_test: counts calls, can block until released, can fail."""

    def __init__(self, monkeypatch, block=False, fail=None):
        self.calls, self.release, self.fail = 0, threading.Event(), fail
        if not block:
            self.release.set()
        outer = self

        def generate_test(engine_self, concept_id, domain, lesson_content, progress=None):
            outer.calls += 1
            outer.release.wait(timeout=30)
            if outer.fail:
                raise outer.fail
            for t, n in (("mcq", 4), ("true_false", 3), ("short_answer", 3)):
                if progress:
                    progress(t, n)
            return ten_questions()

        monkeypatch.setattr(te.TestEngine, "generate_test", generate_test)
        monkeypatch.setattr(te.TestEngine, "_load_cache", lambda self, c, d: [])


@pytest.fixture(autouse=True)
def clean_jobs(tmp_path, monkeypatch):
    gj._JOBS.clear()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(event_log, "_LOG_PATH", tmp_path / "events.jsonl")
    monkeypatch.setattr(event_log, "_DATA_DIR", tmp_path)
    yield
    gj._JOBS.clear()


def wait_done(job, timeout=10):
    end = time.time() + timeout
    while job.state == "running" and time.time() < end:
        time.sleep(0.02)
    return job


# ---------------------------------------------------------------- the manager

def test_many_callers_at_once_start_exactly_one_generation(monkeypatch):
    gen = FakeGenerator(monkeypatch, block=True)
    jobs, barrier = [], threading.Barrier(12)

    def caller():
        barrier.wait(timeout=5)
        jobs.append(gj.start_or_get(CONCEPT, DOMAIN, "lesson"))

    threads = [threading.Thread(target=caller) for _ in range(12)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    time.sleep(0.2)
    assert gen.calls == 1                                   # the whole point: no second generation queued behind the first
    assert len({id(j) for j in jobs}) == 1 and jobs[0].state == "running"
    gen.release.set()
    assert wait_done(jobs[0]).state == "done" and len(jobs[0].questions) == 10


def test_rerunning_while_generating_does_not_start_another(monkeypatch):
    gen = FakeGenerator(monkeypatch, block=True)
    first = gj.start_or_get(CONCEPT, DOMAIN, "lesson")
    for _ in range(25):                                     # 25 simulated reruns / clicks
        assert gj.start_or_get(CONCEPT, DOMAIN, "lesson") is first
    time.sleep(0.1)
    assert gen.calls == 1
    gen.release.set()
    wait_done(first)


def test_different_tests_get_independent_jobs(monkeypatch):
    gen = FakeGenerator(monkeypatch, block=True)
    a, b = gj.start_or_get("module_a", DOMAIN, "x"), gj.start_or_get("module_b", DOMAIN, "x")
    assert a is not b
    gen.release.set()
    wait_done(a), wait_done(b)
    assert gen.calls == 2


def test_progress_is_recorded_per_question_type(monkeypatch):
    FakeGenerator(monkeypatch)
    job = wait_done(gj.start_or_get(CONCEPT, DOMAIN, "lesson"))
    assert [(t, n) for t, n, _ in job.completed] == [("mcq", 4), ("true_false", 3), ("short_answer", 3)]
    assert job.elapsed() >= 0 and job.finished_at >= job.started_at


def test_a_finished_job_is_reused_not_regenerated(monkeypatch):
    gen = FakeGenerator(monkeypatch)
    job = wait_done(gj.start_or_get(CONCEPT, DOMAIN, "lesson"))
    assert gj.start_or_get(CONCEPT, DOMAIN, "lesson") is job and gen.calls == 1


def test_a_test_already_cached_on_disk_is_returned_instantly_without_generating(monkeypatch):
    gen = FakeGenerator(monkeypatch)
    cached = ten_questions("cached")
    monkeypatch.setattr(te.TestEngine, "_load_cache", lambda self, c, d: cached)
    job = gj.start_or_get(CONCEPT, DOMAIN, "lesson")
    assert job.state == "done" and job.questions == cached and gen.calls == 0


def test_a_failure_is_captured_and_only_a_retry_starts_a_new_generation(monkeypatch):
    gen = FakeGenerator(monkeypatch, fail=RuntimeError("model unreachable"))
    job = wait_done(gj.start_or_get(CONCEPT, DOMAIN, "lesson"))
    assert job.state == "error" and "model unreachable" in job.error
    assert gj.start_or_get(CONCEPT, DOMAIN, "lesson") is job and gen.calls == 1     # not retried behind the user's back
    gen.fail = None
    retried = wait_done(gj.start_or_get(CONCEPT, DOMAIN, "lesson", retry=True))
    assert retried is not job and retried.state == "done" and gen.calls == 2


def test_discard_only_removes_finished_jobs(monkeypatch):
    gen = FakeGenerator(monkeypatch, block=True)
    job = gj.start_or_get(CONCEPT, DOMAIN, "lesson")
    gj.discard(CONCEPT, DOMAIN)
    assert gj.get(CONCEPT, DOMAIN) is job                   # still running: kept
    gen.release.set()
    wait_done(job)
    gj.discard(CONCEPT, DOMAIN)
    assert gj.get(CONCEPT, DOMAIN) is None


# ---------------------------------------------------------------- the pages

ROADMAP = {"domain": DOMAIN, "modules": [{"week": 1, "module_id": CONCEPT, "title": "Intro Module",
                                           "concepts": ["Customer Journey"], "prerequisites": []}]}
LESSON = {k: "marketing text " * 10 for k in ("introduction", "theory", "example", "misconceptions", "applications", "summary")}


def page(name, **state):
    at = AppTest.from_file(APP, default_timeout=120)
    base = dict(student_id="job-test", student_name="Job Test", domain=DOMAIN, roadmap=ROADMAP, lesson=dict(LESSON, concept_id="Customer Journey", domain=DOMAIN),
                modules_unlocked={CONCEPT}, current_module_idx=0, page=name)
    for k, v in {**base, **state}.items():
        at.session_state[k] = v
    return at.run()


def text(at):
    return " ".join(m.value for m in at.markdown) + " " + " ".join(str(c.value) for c in at.caption)


def test_test_page_shows_progress_and_reruns_never_start_a_second_generation(monkeypatch):
    gen = FakeGenerator(monkeypatch, block=True)
    at = page("test")
    assert not at.exception, [str(e.value) for e in at.exception]
    assert "Preparing your test" in text(at) and "background" in text(at)
    assert at.session_state["questions"] is None
    for _ in range(4):                                      # the reruns that used to pile up generations
        at.run()
        assert not at.exception
    time.sleep(0.2)
    assert gen.calls == 1
    gen.release.set()
    wait_done(gj.get(CONCEPT, DOMAIN))
    at.run()
    assert not at.exception, [str(e.value) for e in at.exception]
    assert at.session_state["questions"] is not None and len(at.session_state["questions"]) == 10
    assert gen.calls == 1


def test_a_failed_generation_shows_the_error_and_a_working_try_again_button(monkeypatch):
    gen = FakeGenerator(monkeypatch, fail=RuntimeError("model unreachable"))
    at = page("test")
    wait_done(gj.get(CONCEPT, DOMAIN))
    at.run()
    assert [e for e in at.error if "model unreachable" in e.value]
    retry = [b for b in at.button if b.label == "Try again"]
    assert len(retry) == 1
    gen.fail = None
    retry[0].click().run()
    wait_done(gj.get(CONCEPT, DOMAIN))
    at.run()
    assert gen.calls == 2 and at.session_state["questions"] is not None


def test_a_cached_test_opens_immediately_with_no_generation(monkeypatch):
    gen = FakeGenerator(monkeypatch)
    monkeypatch.setattr(te.TestEngine, "_load_cache", lambda self, c, d: ten_questions("cached"))
    at = page("test")
    assert not at.exception, [str(e.value) for e in at.exception]
    assert at.session_state["questions"] is not None and gen.calls == 0


@pytest.mark.parametrize("section,expected_calls", [(0, 0), (1, 0), (2, 1), (4, 1)])
def test_the_lesson_page_starts_the_test_early_once_the_student_is_into_the_lesson(monkeypatch, section, expected_calls):
    gen = FakeGenerator(monkeypatch, block=True)
    at = page("lesson", lesson_section=section)
    assert not at.exception, [str(e.value) for e in at.exception]
    at.run()                                                # a second render must not start another
    time.sleep(0.2)
    assert gen.calls == expected_calls
    gen.release.set()
    if gj.get(CONCEPT, DOMAIN):
        wait_done(gj.get(CONCEPT, DOMAIN))


def test_a_test_prepared_during_the_lesson_is_ready_the_moment_the_student_opens_it(monkeypatch):
    gen = FakeGenerator(monkeypatch)
    page("lesson", lesson_section=3)
    wait_done(gj.get(CONCEPT, DOMAIN))
    at = page("test")
    assert at.session_state["questions"] is not None and gen.calls == 1      # no new generation, no waiting


def test_prefetch_never_breaks_the_lesson_page_if_the_generator_cannot_start(monkeypatch):
    monkeypatch.setattr(gj, "start_or_get", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    at = page("lesson", lesson_section=3)
    assert not at.exception, [str(e.value) for e in at.exception]
