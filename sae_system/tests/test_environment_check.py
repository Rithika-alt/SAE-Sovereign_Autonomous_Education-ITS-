"""Pytest tests for scripts.check_environment (Phase 10A).

Covers the checker's own logic — never hardcodes an expected model/URL,
always reads config.py, degrades optional-service checks to WARN not FAIL,
and never attempts an outbound call once sovereignty has already failed.
"""

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import pytest

from scripts.check_environment import (
    FAIL, PASS, WARN,
    CheckResult, run_all_checks,
    _check_python_version, _check_sovereignty, _check_optional_services,
)


def test_python_version_check_passes_on_current_interpreter():
    # This test suite itself only runs on Python 3.10+, so the check
    # running it must report PASS or WARN, never FAIL.
    result = _check_python_version()
    assert result.status in (PASS, WARN)


def test_sovereignty_check_reads_from_config_not_hardcoded(monkeypatch):
    import config
    monkeypatch.setattr(config, "OLLAMA_BASE_URL", "http://localhost:11434")
    assert _check_sovereignty().status == PASS

    monkeypatch.setattr(config, "OLLAMA_BASE_URL", "https://not-local.example.com")
    result = _check_sovereignty()
    assert result.status == FAIL
    assert "not-local.example.com" in result.detail


def test_optional_services_never_fail_only_warn_or_pass():
    """Postgres/Redis/Neo4j are all optional with working fallbacks — a
    missing one must never be reported as FAIL (that would make a perfectly
    valid, fully-functional deployment look broken).
    """
    for result in _check_optional_services():
        assert result.status in (PASS, WARN), f"{result.name} reported {result.status}, must be PASS or WARN"


def test_run_all_checks_returns_check_result_objects():
    # Full run against the real local environment — exercises every check
    # function end-to-end (mirrors what a real user running the script sees).
    results = run_all_checks()
    assert len(results) > 0
    for r in results:
        assert isinstance(r, CheckResult)
        assert r.status in (PASS, WARN, FAIL)
        assert r.name
        assert r.detail


def test_sovereignty_failure_skips_ollama_reachability_call(monkeypatch):
    """No outbound HTTP call should be attempted to a non-local endpoint,
    even a harmless reachability check with no student data — verified by
    monkeypatching requests.get to explode if called at all.
    """
    import config
    monkeypatch.setattr(config, "OLLAMA_BASE_URL", "https://not-local.example.com")

    def _explode(*_a, **_k):
        raise AssertionError("requests.get must not be called when sovereignty already failed")

    import requests
    monkeypatch.setattr(requests, "get", _explode)

    results = run_all_checks()
    sovereignty = next(r for r in results if r.name.startswith("Sovereignty"))
    ollama_reachable = next(r for r in results if r.name == "Ollama reachable")
    assert sovereignty.status == FAIL
    assert ollama_reachable.status == FAIL
    assert "skip" in ollama_reachable.detail.lower()


def test_check_result_messages_are_ascii_safe():
    """Every check's detail text must survive encoding to cp1252 (the
    default Windows console codepage) — a real UnicodeEncodeError crash
    was caught and fixed during Phase 10A when this wasn't true.
    """
    for result in run_all_checks():
        try:
            result.detail.encode("cp1252")
        except UnicodeEncodeError as exc:
            pytest.fail(f"{result.name}'s detail text is not cp1252-safe: {exc!r} in {result.detail!r}")
