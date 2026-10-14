#!/usr/bin/env python3
"""SAE environment preflight checker  -  Phase 10A.

Run standalone before starting the dashboard on a new machine:

    python scripts/check_environment.py

Or via the bootstrap scripts, which call this for the Ollama/model checks
instead of duplicating that logic in shell (Phase 10A Step 12: don't
duplicate configuration between scripts and config.py). Reads every
threshold/URL/model name from the actual sae_system/config.py  -  nothing
here is a hardcoded guess at what the project is configured to use.

Exit code: 0 if nothing FAILed (WARNs are fine  -  they're all things the
app already gracefully degrades from), 1 if anything FAILed.
"""

from __future__ import annotations

import importlib
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

PASS, WARN, FAIL = "PASS", "WARN", "FAIL"
# Plain ASCII, not Unicode glyphs (OK/FAIL)  -  this script must run correctly in
# a default Windows console (cp1252), which is exactly the kind of thing a
# preflight checker is supposed to survive. Caught by actually running this
# script during Phase 10A, not assumed.
_SYMBOL = {PASS: "OK", WARN: "??", FAIL: "XX"}


@dataclass
class CheckResult:
    name: str
    status: str
    detail: str


def _check_python_version() -> CheckResult:
    v = sys.version_info
    if v < (3, 10):
        return CheckResult(
            "Python version", FAIL,
            f"Python {v.major}.{v.minor} found  -  SAE uses PEP 604 union "
            f"type hints (e.g. `dict | None` in agents/tutor_agent.py), "
            f"which require Python 3.10+. Install 3.10 or newer (3.11, the "
            f"version this project is developed and tested against, is "
            f"recommended  -  matches Dockerfile's python:3.11-slim base).",
        )
    detail = f"Python {v.major}.{v.minor}.{v.micro}"
    if v >= (3, 11):
        return CheckResult("Python version", PASS, detail + " (matches recommended 3.11)")
    return CheckResult("Python version", WARN, detail + " (3.10 is the floor; 3.11 is recommended/tested)")


def _check_dependencies() -> CheckResult:
    # (requirements.txt name, importable module name)  -  the two differ for
    # several packages (e.g. pip name "langchain-ollama" -> import "langchain_ollama").
    required = [
        ("langgraph", "langgraph"),
        ("langchain-ollama", "langchain_ollama"),
        ("chromadb", "chromadb"),
        ("networkx", "networkx"),
        ("sentence-transformers", "sentence_transformers"),
        ("streamlit", "streamlit"),
        ("plotly", "plotly"),
        ("pandas", "pandas"),
        ("pytest", "pytest"),
        ("python-dotenv", "dotenv"),
        ("neo4j", "neo4j"),
        ("opencv-python", "cv2"),
        ("reportlab", "reportlab"),
        ("requests", "requests"),
        ("json_repair", "json_repair"),
        ("psycopg2-binary", "psycopg2"),
        ("redis", "redis"),
        ("numpy", "numpy"),
        ("streamlit-autorefresh", "streamlit_autorefresh"),
    ]
    optional = [("pdf2image", "pdf2image")]

    missing = []
    for pip_name, import_name in required:
        try:
            importlib.import_module(import_name)
        except ImportError:
            missing.append(pip_name)

    missing_optional = []
    for pip_name, import_name in optional:
        try:
            importlib.import_module(import_name)
        except ImportError:
            missing_optional.append(pip_name)

    if missing:
        return CheckResult(
            "Python dependencies", FAIL,
            f"Missing: {', '.join(missing)}. Run: pip install -r requirements.txt",
        )
    if missing_optional:
        return CheckResult(
            "Python dependencies", WARN,
            f"All required packages present. Optional missing: {', '.join(missing_optional)} "
            f"(certificate PDF preview only  -  also needs the system 'poppler' package).",
        )
    return CheckResult("Python dependencies", PASS, f"All {len(required)} required packages importable")


def _check_config() -> CheckResult:
    try:
        import config
    except Exception as exc:
        return CheckResult("Configuration (config.py)", FAIL, f"Could not import config.py: {exc}")
    return CheckResult(
        "Configuration (config.py)", PASS,
        f"OLLAMA_BASE_URL={config.OLLAMA_BASE_URL} OLLAMA_MODEL={config.OLLAMA_MODEL} "
        f"SEMANTIC_PASS_THRESHOLD={config.SEMANTIC_PASS_THRESHOLD}",
    )


def _check_sovereignty() -> CheckResult:
    try:
        import config
    except Exception as exc:
        return CheckResult("Sovereignty (local-only endpoint)", FAIL, f"Could not read config.py: {exc}")
    url = config.OLLAMA_BASE_URL
    if url.startswith("http://localhost") or url.startswith("http://127.0.0.1"):
        return CheckResult("Sovereignty (local-only endpoint)", PASS, f"OLLAMA_BASE_URL={url} is local")
    return CheckResult(
        "Sovereignty (local-only endpoint)", FAIL,
        f"OLLAMA_BASE_URL='{url}' is NOT localhost/127.0.0.1  -  every agent in this "
        f"codebase (TutorAgent, RoadmapAgent, SearcherAgent, AskSAEAgent, "
        f"AdaptiveTutorAgent, LLMJudge) will refuse to start and raise "
        f"SovereigntyError. This is intentional  -  SAE never falls back to a "
        f"hosted provider. Fix OLLAMA_BASE_URL in .env.",
    )


def _check_ollama_installed() -> CheckResult:
    path = shutil.which("ollama")
    if path:
        return CheckResult("Ollama installed", PASS, path)
    return CheckResult(
        "Ollama installed", WARN,
        "'ollama' not found on PATH. Install from https://ollama.com/download "
        "(only a WARN, not FAIL, here  -  Ollama may be running as a service/"
        "container reachable at OLLAMA_BASE_URL without the CLI on this machine's PATH).",
    )


def _check_ollama_reachable_and_model() -> List[CheckResult]:
    try:
        import config
    except Exception as exc:
        return [CheckResult("Ollama reachable", FAIL, f"Could not read config.py: {exc}")]

    try:
        import requests
    except ImportError:
        return [CheckResult("Ollama reachable", FAIL, "requests package missing  -  see Python dependencies check")]

    try:
        resp = requests.get(f"{config.OLLAMA_BASE_URL}/api/tags", timeout=5)
        resp.raise_for_status()
    except Exception as exc:
        return [
            CheckResult(
                "Ollama reachable", FAIL,
                f"Could not reach {config.OLLAMA_BASE_URL}: {exc}. "
                f"Start Ollama (run `ollama serve` or launch the Ollama app) before starting SAE.",
            ),
        ]

    reachable = CheckResult("Ollama reachable", PASS, config.OLLAMA_BASE_URL)

    try:
        models = [m.get("name", "") for m in resp.json().get("models", [])]
    except Exception:
        models = []

    configured = config.OLLAMA_MODEL
    # Ollama model names may carry a ":tag" suffix (e.g. "llama3.2:latest")
    # even when the configured name doesn't  -  match on the base name.
    have = any(m == configured or m.split(":")[0] == configured.split(":")[0] for m in models)
    if have:
        model_check = CheckResult("Required model available", PASS, configured)
    else:
        model_check = CheckResult(
            "Required model available", FAIL,
            f"Model '{configured}' (from config.OLLAMA_MODEL) not found. "
            f"Installed models: {models or '(none)'}. "
            f"Suggested action: ollama pull {configured}",
        )
    return [reachable, model_check]


def _check_writable_data_dir() -> CheckResult:
    data_dir = _ROOT / "data"
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        probe = data_dir / ".write_check"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except Exception as exc:
        return CheckResult("Storage (data/ writable)", FAIL, f"Cannot write to {data_dir}: {exc}")
    return CheckResult("Storage (data/ writable)", PASS, str(data_dir))


def _check_lesson_and_graph_dirs() -> List[CheckResult]:
    results = []
    for label, sub in [("Lesson cache", "lessons"), ("Knowledge Graph storage", "knowledge_graphs")]:
        d = _ROOT / "data" / sub
        if d.exists() and any(d.iterdir()):
            results.append(CheckResult(label, PASS, f"{d} ({sum(1 for _ in d.iterdir())} file(s))"))
        else:
            results.append(CheckResult(
                label, WARN,
                f"{d} is empty or doesn't exist yet  -  normal on a fresh install; "
                f"populated automatically as the student uses the app "
                f"(or run scripts/seed_demo.py for a working example immediately).",
            ))
    return results


def _check_optional_services() -> List[CheckResult]:
    """Postgres/Redis/Neo4j are all optional  -  every one has a working
    local fallback (auth/local_db.py JSON store, in-memory cache,
    NetworkX/JSON graph respectively). These are WARN, never FAIL.
    """
    import socket

    results = []
    for label, host, port, fallback in [
        ("PostgreSQL (optional)", "localhost", 5432, "falls back to auth/local_db.py JSON store"),
        ("Redis (optional)", "localhost", 6379, "falls back to in-memory session cache"),
        ("Neo4j (optional)", "localhost", 7687, "falls back to NetworkX + JSON knowledge graph files"),
    ]:
        try:
            with socket.create_connection((host, port), timeout=1.5):
                results.append(CheckResult(label, PASS, f"{host}:{port} reachable"))
        except OSError:
            results.append(CheckResult(label, WARN, f"{host}:{port} not reachable  -  {fallback}"))
    return results


def run_all_checks() -> List[CheckResult]:
    checks = [
        _check_python_version(),
        _check_dependencies(),
        _check_config(),
        _check_sovereignty(),
        _check_ollama_installed(),
    ]

    # Skip the reachability/model check entirely if sovereignty already
    # failed — no outbound call should be attempted at all to a non-local
    # endpoint, even a harmless reachability GET with no student data.
    if checks[3].status != FAIL:
        checks.extend(_check_ollama_reachable_and_model())
    else:
        checks.append(CheckResult(
            "Ollama reachable", FAIL,
            "Skipped — sovereignty check failed above; not attempting any "
            "outbound call to a non-local endpoint.",
        ))

    checks.append(_check_writable_data_dir())
    checks.extend(_check_lesson_and_graph_dirs())
    checks.extend(_check_optional_services())
    return checks


def main() -> int:
    print("=" * 60)
    print("SAE Environment Check")
    print("=" * 60)

    results = run_all_checks()
    any_fail = False
    for r in results:
        symbol = _SYMBOL[r.status]
        print(f"[{symbol}] {r.name}: {r.detail}")
        if r.status == FAIL:
            any_fail = True

    print("=" * 60)
    if any_fail:
        print("FAIL  -  one or more required components are missing. See above for suggested fixes.")
        return 1
    print("PASS  -  SAE is ready to start. Any [!] items above are optional/degraded-mode notices.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
