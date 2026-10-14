# Deployment Architecture — Phase 10A

Written before/alongside implementation, per Step 1's dependency audit and
Step 2's requirement to document the actual runtime architecture before
changing anything. Two things were discovered during that audit that
changed the shape of this phase's work, described in Section 0.

## 0. What was already there (Step 1 finding — reuse, don't duplicate)

`bootstrap.ps1` / `bootstrap.sh` (repo root) and `docker-compose.yml` /
`Dockerfile` **already existed** before this phase and already implement
most of what a naive reading of "Phase 10A" would suggest building from
scratch: a Docker-based setup flow, Ollama detection, `.env` bootstrapping,
and platform-specific (Windows/Unix) launchers. `README.md` also already
documents **two deployment paths**: a "Quick Start (local, no Docker)"
native path, and an optional Docker path for Neo4j's visual graph browser.

This phase therefore did **not** create competing setup/launcher scripts.
It: (1) audited and fixed real gaps in the existing scripts/config, (2)
added the one genuinely missing piece — a proper preflight/diagnostic
checker (`scripts/check_environment.py`), since neither bootstrap script
did more than a shallow Ollama-only check, and (3) added a native-mode
equivalent launcher (`scripts/start.py`) alongside the existing
Docker-oriented ones, since no native launcher existed at all (every native
run in this project's history, including all of Phases 6-9's testing, used
a hand-typed `streamlit run dashboard/app.py`).

Two real, concrete bugs were found and fixed during the audit — not
hypothetical portability concerns:
1. **`docker-compose.yml` hardcoded `SEMANTIC_PASS_THRESHOLD: "0.45"`** —
   the old, pre-Phase-2 value. A Docker deployment would have silently
   graded worse than the validated native path (config.py's evidence-based
   0.60, re-validated in Phase 9's 98%-accuracy multi-signal benchmark).
   Fixed to `"0.60"`, plus added the missing `SEMANTIC_DIALOGUE_THRESHOLD`.
2. **`sae_system/.env` had `USE_NEO4J=true`** despite no Neo4j server
   running natively, while `.env.example` (and README.md's documented
   default) both say `false`. Every `KnowledgeGraph()` construction was
   silently wasting several seconds on a doomed TCP connect-then-fallback —
   directly observable throughout this project's own test logs
   ("Neo4j unavailable ... falling back to NetworkX"). Fixed `.env` to
   match the documented default; measured construction time afterward:
   0.001s (was several seconds).
3. **`bootstrap.ps1`/`bootstrap.sh` hardcoded `"llama3.2"`** as the model to
   check for, rather than reading the actually-configured `OLLAMA_MODEL`.
   Harmless today (they happen to match), but a real drift risk the moment
   someone changes the configured model. Fixed to read `OLLAMA_MODEL` from
   `.env`.
4. **`requirements.txt` was both incomplete and had dead weight**:
   `pandas` is a real runtime dependency (`page_knowledge_graph`'s detail
   table, `dashboard/app.py`) that was never declared — works today only
   because something else transitively installs it. `langchain`,
   `langchain-community`, and `Pillow` are declared but have zero imports
   anywhere in the codebase (confirmed by full AST-based import scanning,
   not just grep). Fixed: added `pandas`, removed the three unused
   packages, added `pdf2image` as an explicitly-optional line (it was
   already used, already gracefully degraded via try/except in
   `page_certificate()`, but was undeclared).

## 1. Runtime dependency map

```
SAE
│
├── Python runtime            REQUIRED  local   Python 3.10+ (3.11 tested/recommended,
│                                                matches Dockerfile's python:3.11-slim)
│
├── Application dependencies  REQUIRED  local   requirements.txt (19 packages after
│                                                Step 1's audit) — pip install -r requirements.txt
│
├── Ollama                    REQUIRED  local   config.OLLAMA_BASE_URL (default
│   └── Required model        REQUIRED  local   http://localhost:11434); config.OLLAMA_MODEL
│                                                (default "llama3.2", ~2.0GB on disk).
│                                                SovereigntyError blocks any non-local URL.
│
├── Curriculum data           GENERATED local   data/lessons, data/tests, data/roadmaps —
│                                                created on first use via Ollama; a fresh
│                                                install starts with these empty/absent.
│
├── Knowledge Graph           OPTIONAL/ local   data/knowledge_graphs/{student_id}.json
│   (default: NetworkX)       GENERATED        (NetworkX backend, USE_NEO4J=false default)
│   (optional: Neo4j)         OPTIONAL  local   bolt://localhost:7687 — only if USE_NEO4J=true;
│                                                falls back to NetworkX automatically on any
│                                                connection failure (memory/graph_engine.py)
│
├── Student progress          GENERATED local   data/progress/{student_id}.json
│
├── Authentication            OPTIONAL/ local   PostgreSQL (DATABASE_URL) if reachable, else
│   (default: local JSON)     GENERATED        auth/local_db.py -> data/users.json
│
├── Session cache             OPTIONAL  local   Redis (REDIS_URL) if reachable, else an
│   (default: in-memory)                        in-process dict (auth/cache.py)
│
├── Event telemetry           GENERATED local   data/events.jsonl (Phase 3)
│
├── ChromaDB                  OPTIONAL  local   ./chroma_db/ — only reachable via the CLI-only
│                                                SearcherAgent path (Phase 1 audit finding),
│                                                not the dashboard. Not required for normal use.
│
└── social_server             OPTIONAL  local   Separate service (own requirements.txt), only
                                                 for Friends/Chat. Never touches lesson/progress
                                                 data (documented in social_client.py's own
                                                 header comment). Out of scope for this phase.
```

**Bottom line: for a normal dashboard session, only Python + its
dependencies + Ollama are actually required.** Postgres, Redis, and Neo4j
are all optional with working, already-exercised local fallbacks — this
was true before Phase 10A, and is now correctly reflected in `.env`'s
default (Section 0, fix #2).

## 2. Python environment

- **Version**: 3.10 minimum (the codebase uses PEP 604 union syntax,
  `dict | None`, in `agents/tutor_agent.py`), 3.11 recommended — the
  version this project has been developed and tested against throughout
  every phase of this session, and what `Dockerfile` uses
  (`python:3.11-slim`).
- **Dependencies**: `requirements.txt` (repo root's `sae_system/`
  directory), no separate test-only dependency file — `pytest` is listed
  alongside runtime dependencies since the project doesn't currently
  separate them, and splitting it out wasn't judged worth the churn for
  one package.
- Not frozen to exact versions (no `==` pins in the original file, and none
  added) — preserves the project's existing looser-pinning convention
  rather than introducing a new constraint style as a side effect of this
  audit.

## 3. Ollama

- **Endpoint**: `config.OLLAMA_BASE_URL`, default `http://localhost:11434`.
  Every agent in the codebase (`TutorAgent`, `RoadmapAgent`,
  `SearcherAgent`, `AskSAEAgent`, `AdaptiveTutorAgent`, `LLMJudge`)
  independently raises `SovereigntyError` in its own `__init__` if this
  isn't `localhost`/`127.0.0.1` — verified in Phases 7-9's sovereignty
  tests and re-verified here (Section 6).
- **Model**: `config.OLLAMA_MODEL`, default `"llama3.2"`, measured at
  **2.0GB** on disk (`ollama list` on the development machine).
- **Installation**: not automated — Ollama has its own installer per OS
  (https://ollama.com/download); Phase 10A detects and reports its
  presence/absence/model rather than attempting to silently install
  system software requiring elevated privileges (explicitly out of scope
  per Step 11/21).

## 4. Data — source-controlled vs. generated vs. supplied

| Data | Category | Notes |
|---|---|---|
| `data/eval/grading_gold_set.json` | **Source-controlled** | Phase 2/9's hand-labeled benchmark — part of the application, not per-student data |
| `data/lessons/`, `data/tests/`, `data/roadmaps/` | **Generated** | Created on first Ollama call per concept/domain; empty on a fresh install |
| `data/knowledge_graphs/`, `data/progress/`, `data/events.jsonl` | **Generated** | Created as a student uses the app |
| `data/users.json` | **Generated** | Created by `auth/local_db.py` on first registration (or via `scripts/seed_demo.py`) when Postgres isn't configured/reachable |
| Neo4j / Postgres / Redis data volumes | **Supplied separately** | Only relevant if those optional services are used; `docker-compose.yml`'s named volumes persist them across container restarts |

No large generated artifacts were committed to source control to "solve"
portability — the measured `sae_system/data/` directory is **314KB**
(mostly small JSON files) precisely because it holds this session's actual
generated content, not because anything was pruned to look better.

## 5. Preflight checker (`scripts/check_environment.py`)

New in this phase — genuinely missing before it (Section 0). Checks, in
order: Python version, Python dependencies (all 19, by attempting the real
import), `config.py` loads, sovereignty (`OLLAMA_BASE_URL` is local),
Ollama installed (`shutil.which`), Ollama reachable (`GET /api/tags`),
configured model present, `data/` writable, lesson cache and knowledge
graph directories, and the three optional services (Postgres/Redis/Neo4j,
via a raw socket connect — WARN, never FAIL, since all three degrade
gracefully). Every value checked is read from the real `config.py` /
`.env` — nothing is a hardcoded guess (the exact gap Section 0 found in
the pre-existing bootstrap scripts). Exit code 0 unless something required
is actually missing.

A real bug was caught and fixed while building this: the initial version
used Unicode checkmarks (✓/✗) for status symbols, which crashed with
`UnicodeEncodeError` on this Windows machine's default `cp1252` console the
moment it was actually run — not a hypothetical, an actual crash on first
execution. Fixed to plain ASCII (`OK`/`??`/`XX`) throughout, including
em-dashes in every user-facing message string (comments/docstrings, never
printed, were left alone). This is exactly the class of "looks fine,
crashes on a real machine" issue Phase 10A's clean-environment testing
exists to catch.

## 6. Sovereignty preservation

No cloud/hosted-LLM fallback exists anywhere in this codebase to
accidentally wire up, and none was added. `check_environment.py`'s
sovereignty check reads `config.OLLAMA_BASE_URL` and reports FAIL (not
WARN) if it isn't local — this is the one check in the script that should
stop a deployment, since every agent will refuse to start anyway. The
preflight checker itself makes exactly one network call (`GET
{OLLAMA_BASE_URL}/api/tags`, to the already-configured local endpoint) and
sends no student data anywhere.

## 7. Recommended deployment model

**Native (Python + Ollama on the host) is the primary, recommended path**,
not Docker — this is an evidence-based conclusion, not a default
assumption:
- It's what `README.md` already documents as the "Quick Start."
- It's what every phase of this project (6 through 9) was actually
  developed and tested against, extensively — dozens of live Ollama runs,
  57+ passing tests, multiple headless dashboard boots, all native.
- Postgres/Redis/Neo4j are optional with working fallbacks, so the
  "minimal" native deployment genuinely only needs Python + Ollama, no
  other services to install or run.

**Docker Compose remains available and correctly configured** (after
Section 0's fixes) for anyone who wants persistent Postgres/Neo4j rather
than the file-based fallbacks, or who wants the Neo4j visual graph browser
specifically. It was not the subject of a from-scratch clean-machine test
in this phase (Section 9 explains why), but its configuration was audited
and its config-drift bug fixed.

A fully containerized stack including Ollama itself was **not** pursued —
Ollama benefits from direct GPU access on the host, and containerizing it
would add complexity (GPU passthrough configuration, larger images) without
a corresponding benefit for a single-student local deployment, which is
this project's actual use case.

## 8. Known limitations

- The Docker Compose path was audited and fixed but not run end-to-end in
  this phase (Section 9) — Docker wasn't available/exercised in this
  environment during this session. This is disclosed, not hidden.
- No automated Ollama installation exists for any OS — by design (Step 11
  explicitly prohibits silently installing software requiring elevated
  privileges).
- `requirements.txt` has no version pins — reproducible in the sense that
  the same packages install, not in the stricter sense of byte-identical
  dependency trees across time. Matches the project's pre-existing
  convention; introducing pins was judged out of scope for this phase.
