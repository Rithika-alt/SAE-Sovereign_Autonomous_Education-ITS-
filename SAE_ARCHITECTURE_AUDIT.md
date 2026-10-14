# SAE Architecture Audit

Produced as Phase 1 of a five-phase stabilization pass (audit → stabilize →
observability → evaluation → XP integration). Sections 1–8 are the audit
proper; Section 9 records what Phases 2–5 actually changed as a result;
Section 10 is the roadmap for the larger product vision (new UX, agentic
tutor, learning canvas) that was explicitly **not** built in this pass.

## 1. Architecture overview

SAE has **two separate, parallel execution paths** that don't share code and,
until this pass, didn't share a config source either:

**Dashboard path (what actually runs when a student uses the app):**
`dashboard/app.py` (Streamlit) → `agents/tutor_agent.py::TutorAgent` (lesson
generation) → `evaluation/test_engine.py::TestEngine` (10-question test
generation + grading, exact-match for MCQ/T-F, semantic similarity for
short-answer) → `memory/graph_engine.py::KnowledgeGraph` (mastery tracking,
NetworkX/JSON by default, Neo4j if reachable) → `persistence/progress_store.py`
(per-domain module completion) → `integrity/certificate_generator.py`.

**LangGraph/CLI path (only reachable via `python main.py`, never from the
dashboard):** `orchestration/state_graph.py::sae_graph` wires
`agents/tutor_agent.py::TutorAgent.run` → `agents/auditor_agent.py::AuditorAgent`
(semantic + logic composite scoring, Socratic clarification dialogue) →
`agents/searcher_agent.py::SearcherAgent` (ChromaDB-backed supplementary
content) → back to tutor, or `next_lesson`. `integrity/anti_malpractice.py`
and `memory/chroma_store.py` are only reachable through this path.

**This split is the single biggest architectural fact to know before making
changes here**: editing `auditor_agent.py`, `searcher_agent.py`, or
`state_graph.py` has zero effect on what a student sees in the dashboard.
Any future work unifying these two paths (or deciding to retire one) should
be a deliberate decision, not a byproduct of an unrelated change.

## 2. Data flow summary

- **Test attempt**: `TestEngine.generate_test()` (cached at
  `data/tests/{domain}_{concept}.json`) → `TestEngine.grade_test()` → on pass,
  `dashboard/app.py` writes `modules_passed`/`module_progress` to
  `persistence/progress_store.py` (`data/progress/{student_id}.json`) and
  calls `KnowledgeGraph.update_mastery()` with `percentage/100`.
- **Dialogue attempt** (CLI-only): `AuditorAgent.run()` computes
  `composite = semantic*0.7 + logic*0.3`; on gate pass, writes a proof hash to
  `mastery_log.jsonl` (`integrity/proof_of_learning.py`) and separately calls
  `KnowledgeGraph.update_mastery()` with the composite score.
- **Both paths write the same `KnowledgeGraph.mastery` field per concept, via
  different formulas, and only the dialogue path ever wrote to
  `mastery_log.jsonl`** — which is why that file had exactly one line before
  this pass (see Section 9 for the new `data/events.jsonl` that now captures
  both paths' outcomes without touching `mastery_log.jsonl`'s narrow
  proof-of-learning purpose).
- **XP**: `integrity/xp_engine.py::XPEngine` was fully implemented (XP table,
  levels, streaks, its own per-student event list at
  `data/{student_id}_xp.json`) but had **zero callers anywhere in the
  codebase** before this pass — confirmed by repo-wide grep.

## 3. The SEMANTIC_PASS_THRESHOLD inconsistency (found and fixed)

Before this pass, three files read the same env var with two different
hardcoded fallback defaults:
- `evaluation/test_engine.py:592` — `os.getenv("SEMANTIC_PASS_THRESHOLD", "0.45")`
- `agents/auditor_agent.py:8` and `orchestration/state_graph.py:15` —
  `os.getenv("SEMANTIC_PASS_THRESHOLD", "0.85")`

`.env` set the var to `0.45`, so all three happened to resolve to the same
value at runtime — but removing that one line, or deploying to an environment
that didn't set it, would have silently split the test-grading path onto a
stricter threshold than the dialogue path with no error or warning.

**Fix**: `sae_system/config.py` is now the single source of truth for this
and three related thresholds (`LOGIC_GATE_THRESHOLD`,
`SEMANTIC_DIALOGUE_THRESHOLD`, plus `OLLAMA_BASE_URL`/`OLLAMA_MODEL`). All
three original call sites now import from `config.py` instead of calling
`os.getenv` directly.

**The default itself was also wrong, and this was measured, not guessed.**
`evaluation/grading_evaluator.py` runs the actual semantic grader
(`evaluation/semantic_auditor.grade_response`) against a 40-item hand-labeled
gold-standard set (`data/eval/grading_gold_set.json`) covering correct,
paraphrased, partial, irrelevant, confidently-wrong, negated, empty,
keyword-only, semantically-similar-but-factually-wrong, ambiguous, and
overly-verbose answers. Results:

| Threshold | Accuracy | Precision | Recall | F1 |
|---|---|---|---|---|
| 0.45 (old test-path default) | 62.5% | 48.1% | 92.9% | 63.4% |
| 0.85 (old auditor-path default) | 65.0% | 50.0% | 14.3% | 22.2% |
| **0.60 (new default, sweep-selected)** | **67.5%** | 52.2% | 85.7% | **64.9%** |

A full sweep from 0.30–0.90 (2% steps) found the best accuracy/F1 balance at
0.58–0.60. **Neither old default was good, and the new one isn't either —
this is the more important finding.** At 0.45, the grader rubber-stamps
confidently-wrong, negated, and keyword-only answers as "pass" (14 false
positives out of 40 items) because their topic overlap with the reference
answer produces high cosine similarity regardless of correctness. At 0.85, it
rejects genuinely correct paraphrased answers (12 false negatives) because
paraphrasing lowers surface similarity even when the meaning is preserved.
**No single global threshold on cosine similarity alone can cleanly separate
"correct" from "confidently wrong but on-topic" or "negated" answers** — this
is a structural limitation of similarity-only grading, not a tuning problem.
The auditor path's `logic_score` (via `anti_malpractice.verify_reasoning`)
exists specifically to catch this category but is only applied on the
CLI-only dialogue path, never on the dashboard's test-grading path — a
concrete, evidence-backed argument for eventually sharing that check between
both paths (left for a future phase; out of scope here per the fix being
"raise the threshold quality," not "redesign the grader").

Moving `SEMANTIC_PASS_THRESHOLD` from 0.45 to 0.60 also collapsed
`SEMANTIC_DIALOGUE_THRESHOLD` (was 0.60) to a zero-width clarification band —
fixed by lowering `SEMANTIC_DIALOGUE_THRESHOLD` to 0.45 so the auditor path's
"offer a Socratic clarification" phase still has room to trigger.

Re-run `python -m evaluation.grading_evaluator` after any change to the gold
set or the embedding model to re-validate this default.

## 4. Swallowed-exception inventory

41 occurrences of `except Exception:` across 16 files. Top concentrations:
`dashboard/app.py` (12), `agents/tutor_agent.py` (7), `agents/roadmap_agent.py`
(4), `auth/cache.py` (3). Classification:

**Fixed in this pass** (were silently hiding real failures a student would
otherwise never learn about): the progress-save and knowledge-graph-update
blocks in `dashboard/app.py`'s test-completion flow (~line 1265–1310) now log
a `dashboard_error` event with the exception type/message instead of a bare
`pass`, while still not crashing the page (the point of the try/except is
preserved — visibility was the only thing missing).

**Left as-is** (genuine, intentional fallback behavior, confirmed by reading
each site): `tutor_agent.py`'s 7 sites are all cache-read-fails-so-regenerate
or Ollama-retry-loop patterns where the fallback path is itself correct
behavior, not a hidden bug. `roadmap_agent.py`'s 4 sites are the same
retry/fallback shape (2 more sites in that file already log via
`logger.warning`, not bare). `auth/cache.py`'s 3 sites are the
documented Redis-unavailable → in-memory-fallback pattern. Changing these to
loud failures would be net-negative — they exist specifically so a missing
Redis/Ollama/cache-file doesn't take down the app.

## 5. Confirmed dead/orphaned code

- **`integrity/xp_engine.py::XPEngine`** — fully built, zero callers before
  this pass. **Fixed**: wired into `dashboard/app.py`'s test-pass,
  concept-mastered, and domain-completed flows (Section 9).
- **`integrity/p2p_handshake.py`** — explicitly self-documented as a Phase 2
  stub ("P2P knowledge-gap broadcast stub"). Confirmed orphaned by repo-wide
  grep. Left alone; it's honest about being unfinished, not a silent bug.
- **`orchestration/state_schema.py::GraphState` dead fields**:
  `cognitive_load_score` (computed by `integrity/affective_pacing.py` but fed
  from `dashboard/test_interface.py`, never from `GraphState` — the two are
  disconnected), `response_history` (initialized, never appended to or read),
  `mastery_level` (never set anywhere — actual mastery lives in
  `KnowledgeGraph`, not this field), `error_message` (only ever set to `""`,
  so `main.py`'s `if result.get("error_message")` branch is unreachable dead
  code). None of these were touched — they're only meaningful if/when the
  LangGraph path is unified with the dashboard path (Section 10).
- **`requirements.txt`**: `langchain-community` and `Pillow` are listed but
  have zero imports anywhere in the codebase. Not removed in this pass
  (low-risk but out of scope for a stabilization-only change; flagging for a
  future dependency-cleanup pass).

## 6. Bugs found and fixed

- **`memory/chroma_store.py`** used `Path(__file__)` in `_get_client()` but
  never imported `pathlib.Path` — a guaranteed `NameError` on first call.
  Since `chroma_store.py` is only reached via the CLI-only `SearcherAgent`
  (Section 1), this would only surface when running `python main.py` and
  hitting the `"retry"` → `"searcher"` graph edge, which likely explains why
  it went unnoticed. **Fixed**: added the missing import.

## 7. Bugs found, documented, NOT fixed (behavior-changing, needs a decision)

- **Neo4j password mismatch**: `.env` sets `NEO4J_PASSWORD=<redacted>` (a value different from docker-compose's) while
  `docker-compose.yml` provisions the Neo4j container with
  `NEO4J_AUTH: neo4j/saesystem` (and separately sets the *dashboard
  container's* env to the matching `saesystem`). Running Neo4j via
  `docker compose up` and the app locally (reading `.env` directly, not the
  containerized dashboard) means every `KnowledgeGraph()` construction fails
  Neo4j auth and silently falls back to NetworkX/JSON — confirmed live during
  this pass's own testing (`Neo4j unavailable ... falling back to NetworkX`).
  **Not changed**: fixing the password would change live behavior (Neo4j
  would actually start getting used instead of the NetworkX fallback) in a
  way this pass's scope (grading/telemetry/XP) didn't call for, and it's not
  known whether the fallback is currently relied upon. Flagging for the
  user to decide which value is authoritative.
- **Pre-existing test failure**: `tests/test_test_engine.py::TestNormaliseQuestion::test_empty_correct_answer_gets_fallback_mcq`
  fails both before and after this pass's changes (confirmed by re-running
  the fast test subset post-change — no new failures introduced). The test
  fixture uses bare-letter options (`["A","B","C","D"]`) which
  `_normalise_question`'s `_LETTER_PLACEHOLDER_RE` filter (designed to catch
  literal LLM output like `"A."`/`"B)"`) strips as placeholder junk, so all 4
  options get replaced by the generic fallback text before the "use first
  option" logic runs. The test's fixture doesn't reflect realistic LLM
  output and collides with a filter meant for a different scenario. Left
  unfixed — untangling which side (test fixture or filter behavior) is
  "correct" needs a product decision outside this pass's scope.

## 8. Test coverage

`python -m pytest tests/ -v` (fresh run for this audit, Ollama reachable):
**49 passed, 1 failed** (the pre-existing failure in Section 7).
`tests/test_semantic_auditor.py` (3 tests) and `tests/test_test_engine.py`
(32 tests) are real, fast, no-Ollama-required unit tests. `tests/test_ollama_generation.py`
(7 tests) requires a live Ollama server and is explicitly diagnostic in
style. `tests/diagnose_test_generation.py` is a standalone script, not a
pytest file (correctly excluded from collection). Re-running the fast subset
(`test_semantic_auditor.py` + `test_test_engine.py`) after this pass's
changes reproduces the exact same 1 pre-existing failure and no new ones.

## 9. What Phases 2–5 actually changed

- **`sae_system/config.py`** (new) — single source of truth for
  `SEMANTIC_PASS_THRESHOLD` (now 0.60, evidence-based per Section 3),
  `LOGIC_GATE_THRESHOLD`, `SEMANTIC_DIALOGUE_THRESHOLD` (now 0.45),
  `OLLAMA_BASE_URL`, `OLLAMA_MODEL`. `.env`/`.env.example` updated to match
  and documented inline.
- **`sae_system/evaluation/event_log.py`** (new) — generic JSONL telemetry
  logger at `data/events.jsonl`, deliberately separate from
  `mastery_log.jsonl`'s narrow proof-of-learning purpose. Event types:
  `session_start`, `test_generation`, `test_attempt`, `dialogue_attempt`,
  `ollama_call`, `xp_awarded`, `mastery_update`, `concept_mastered`,
  `domain_completed`, `dashboard_error`, `agent_execution`,
  `search_execution`, `knowledge_graph_update`.
- **Instrumentation** added to: `evaluation/test_engine.py` (Ollama call
  success/latency, test-generation cache hits), `agents/auditor_agent.py`
  (dialogue attempt outcomes), `memory/graph_engine.py::update_mastery`
  (mastery before/after/delta, covers both dashboard and dialogue paths
  since both call this one method), `agents/roadmap_agent.py` and
  `agents/searcher_agent.py` (light-touch entry-point execution logging),
  `dashboard/app.py` (session starts, test attempts, a top-level page-router
  error wrapper).
- **`sae_system/data/eval/grading_gold_set.json`** and
  **`sae_system/evaluation/grading_evaluator.py`** (new) — the gold-standard
  set and evaluator behind Section 3's threshold decision. Runnable
  standalone: `python -m evaluation.grading_evaluator`.
- **`sae_system/evaluation/system_evaluator.py`** (new) — `evaluate_all(student_id)`
  aggregates all four dimensions (learning outcomes, grading accuracy,
  engagement, reliability) from `KnowledgeGraph`, `progress_store`,
  `XPEngine`, and `event_log`, each with an `insufficient_data` guard.
- **`sae_system/dashboard/page_system_evaluation.py`** (new) — four-tab
  dashboard page (Learning / AI Grading / Engagement / Reliability),
  registered in `app.py`'s nav and `_PAGES` router.
- **XP integration**: `XPEngine.award()` now actually gets called — from
  `dashboard/app.py` on `test_passed`, `perfect_score` (≥95%), and
  `concept_mastered` (mastery crossing `MASTERY_THRESHOLD`), and on
  `domain_completed` in `page_certificate()` (guarded by a session-state flag
  so Streamlit's rerun-on-every-interaction behavior doesn't double-award).
- **`memory/chroma_store.py`** — missing `Path` import fixed (Section 6).

## 10. Roadmap — NOT built in this pass

The original request described a much larger product transformation beyond
stabilization: a new recommendation-driven home screen, a persistent "Ask
SAE" command interface, a more agentic tutor (autonomous mini learning-paths
triggered by "I don't understand X"), richer visualization (skill tree,
mastery heatmap, activity timeline, progress rings), and a node-based
"Learning Canvas" workspace. These were deliberately scoped out of this pass
because:

- They touch nearly every part of the app (dashboard UX, tutor orchestration,
  new dependencies for a canvas/node editor) at once, which is exactly the
  kind of large, unreviewable, high-blast-radius change the stabilization
  work in this pass was trying to protect against.
- Several depend on product decisions this audit surfaced but didn't resolve:
  whether to unify the dashboard and LangGraph paths (Section 1) before
  building a more agentic tutor on top of one of them; whether a canvas
  editor warrants a frontend framework beyond Streamlit; whether the
  Neo4j-vs-NetworkX question (Section 7) should be settled first, since a
  richer knowledge-graph visualization (skill tree) would be built
  differently depending on the answer.
- They're better served by their own dedicated planning session with the
  Plan-mode workflow this pass already used, rather than being designed
  as an afterthought here.

Recommended order for a future pass: (1) decide the dashboard/LangGraph
unification question, since the agentic-tutor and Ask-SAE work both assume
one coherent orchestration path; (2) build the recommendation-driven home
screen and richer visualizations on top of `system_evaluator.py`'s metrics,
since that data now exists; (3) tackle the Learning Canvas last, since it's
the highest-risk, most novel piece and benefits from the other two being
settled first.
