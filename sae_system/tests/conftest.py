"""Shared pytest configuration."""

import os

# evaluation/perf_trace.py writes timing spans to the REAL data/events.jsonl
# (the same file the app reads for the Activity and System Evaluation pages).
# Many existing tests exercise instrumented code paths — and some import
# dashboard.app, which starts a "rerun" — so without this they would pollute
# production telemetry with hundreds of spans per run. Tracing is therefore
# off for the whole test session; tests/test_perf_trace.py turns it on
# explicitly, against a temp log file.
os.environ.setdefault("SAE_PERF_TRACE", "0")


import pytest


@pytest.fixture(autouse=True)
def _isolate_progress_store(tmp_path, monkeypatch):
    """Never let a test read or write the real data/progress/ directory.

    Home now repairs a missing enrolment record and the roadmap loader saves one, so
    any test that renders those pages with a domain would otherwise leave a
    <student>.json in production data (one did: card-test.json). Tests that need a
    populated store override this by monkeypatching persistence.progress_store._DIR
    themselves, as tests/test_enrolment_persistence.py does.
    """
    import persistence.progress_store as progress_store

    monkeypatch.setattr(progress_store, "_DIR", tmp_path / "_progress_isolated")
