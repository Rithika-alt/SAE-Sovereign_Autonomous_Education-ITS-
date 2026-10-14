# SAE System — Technical Status Report (Final Draft)

Date: 2026-10-07 · Branch: `main` · Scope: current working tree (uncommitted changes included)

**How to read this.** Every finding is tagged:
- **[Verified]** — I read the code that causes it, and/or reproduced it (tests, git).
- **[Likely]** — the cause is evident from the code and the screenshot, but I did not reproduce it in a browser.
- **[Not checked]** — flagged for you to look at; I did not open the code.

This report supersedes the stale parts of `SAE_ARCHITECTURE_AUDIT.md` (written before Ask SAE, Adaptive Tutor, Canvas, Activity, Friends and System Evaluation existed).

---

## 1. Executive summary

| Area | Status |
|---|---|
| Core learning loop (roadmap → lesson → test → mastery → certificate) | Works end-to-end on local Ollama |
| Test suite (Python 3.11) | **150 passed, 2 failed** (see §6) |
| Crash bugs in the UI | **2 confirmed** (duplicate Streamlit keys) — both reproducible from your screenshots |
| Rendering bugs | **3** (lesson body blank, roadmap card shows raw HTML, expander icon text) |
| AI grading quality | Weak: 61% accuracy / 58% F1 on the 49-item gold set |
| Security / secrets | **Needs action before any push**: `.env` and `users.json` are tracked in git, no `.gitignore` |
| Architecture | Two parallel execution paths that do not share code (unchanged from the earlier audit) |

The three things I would do first, in order: (1) rotate/secure the Neo4j Aura credential and stop tracking `.env` (§5.1), (2) fix the `dashboard.app` re-import that causes the `nav_home` crash (§4.1), (3) stop injecting LLM text into HTML (§4.3–4.4) — this one change fixes two of the three rendering bugs.

---

## 2. How the system works, from a cold start

### 2.1 What has to exist before anything runs ("staging")

| Component | Required? | Role | Fallback if missing |
|---|---|---|---|
| Python 3.11 + `requirements.txt` | Yes | Runtime. Your tracebacks show 3.11; the default `python` on PATH is 3.14 and has no `pytest` — see §5.4 | — |
| Ollama (`localhost:11434`) + model (`OLLAMA_MODEL`) | Yes | All lesson, roadmap, test and tutor generation | None — generation falls back to canned text |
| `sae_system/.env` | Yes | Thresholds, Ollama URL, DB URLs | Defaults in `config.py` |
| Redis | No | Session tokens, cache | In-memory (`auth/cache.py`) |
| Postgres | No | User accounts | JSON file `data/users.json` (`auth/local_db.py`) |
| Neo4j | No (`USE_NEO4J=false` default) | Knowledge graph | NetworkX + JSON in `data/knowledge_graphs/` |
| `social_server` (FastAPI, port 8000) | No | Friends/chat | Friends page shows connection error |
| ChromaDB | No | Reference material for Ask SAE / Searcher | Ask SAE answers ungrounded |

Entry points: `python scripts/start.py` (env check, then Streamlit), `streamlit run dashboard/app.py`, `bootstrap.ps1` / `docker-compose up -d` (Postgres + Redis + Neo4j + dashboard; Ollama stays on the host by design).

**Sovereignty guard:** `TutorAgent` raises `SovereigntyError` if `OLLAMA_BASE_URL` is not local. The design promise is "no data leaves the machine" — keep this in mind for §5.2.

### 2.2 Startup sequence of `dashboard/app.py`

1. Streamlit executes `app.py` top to bottom **on every interaction** (this matters for every bug in §4).
2. `st.set_page_config`, then one global CSS block (dark glassmorphism theme).
3. `_SS_DEFAULTS` seeded into `st.session_state`.
4. **Auth gate** (`_is_authenticated`): if a `student_id` exists, validate `auth_token` against Redis; if Redis is down, *trust session state* (so token expiry is not enforced without Redis). Otherwise render `page_login` and `st.stop()`.
5. Singletons via `@st.cache_resource`: `RoadmapAgent`, `TutorAgent`, `AnimatedLessonGenerator`.
6. `render_sidebar()` runs **at module level, before the page** — it draws the nav buttons with keys `nav_<page>`.
7. Page router: `_PAGES[ss["page"]]()` wrapped in try/except that logs a `dashboard_error` event and re-raises.

### 2.3 The student journey (dashboard path — what users actually see)

```
login ─► domain_select ─► loading_roadmap ─► roadmap ─► loading_lesson ─► lesson ─► test ─► results ─► certificate
                              │                              │              │         │         │
                        RoadmapAgent                    TutorAgent     6 sections  TestEngine  progress_store
                        (Ollama, parallel               (6 sections,   (intro,     (10 Qs,     + KnowledgeGraph
                        module gen, cached              cached JSON,   theory,     cached,     .update_mastery
                        data/roadmaps/*.json)           fallback text) example…)   proctored)  + XPEngine.award
```

- **Roadmap:** `RoadmapAgent.generate_roadmap` returns a cached 10-week plan or generates modules in parallel via Ollama, enriches each with a resource link, and seeds the `KnowledgeGraph` with concept nodes and prerequisite edges.
- **Lesson:** `TutorAgent.teach_concept_parallel` generates six sections (`introduction, theory, example, misconceptions, applications, summary`) in parallel, caches to `data/lessons/{domain}_{concept}.json`, falls back to template text per section on failure. An optional animation is produced by `media/video_generator.py`.
- **Test:** `TestEngine.generate_test` builds 10 questions (MCQ / true-false / short answer), cached in `data/tests/`. `test_interface.py` adds camera proctoring (`integrity/camera_proctor.py`) and affective pacing.
- **Grading** (`TestEngine.grade_test`): MCQ and T/F by normalised exact match; short answer by sentence-embedding cosine similarity ≥ `SEMANTIC_PASS_THRESHOLD` (0.60). Pass = ≥ 60%.
- **On pass:** `progress_store` writes `data/progress/{student}.json`; `KnowledgeGraph.update_mastery(percentage/100)`; `XPEngine.award` (guarded against Streamlit reruns by a session flag); certificate PDF on domain completion.

### 2.4 Pages added after the first audit

| Page | Mechanism |
|---|---|
| Home | Recommendation-driven landing, built on `evaluation/recommendation_engine.py` |
| Adaptive Tutor | `diagnose_tutor_state` → `choose_teaching_strategy` → explain + one question → `evaluate_and_update` using **multi-signal grading** (coverage + embedding + optional LLM judge); mastery is *blended*, not overwritten |
| Ask SAE | `gather_context` (cached lesson + ChromaDB + mastery) → Ollama; response flagged `grounded` or "general knowledge" |
| Learning Canvas, Activity, Knowledge Graph | Visualisations over `KnowledgeGraph` and `data/events.jsonl` |
| System Evaluation | `system_evaluator.evaluate_all` — learning, AI grading, engagement, reliability tabs |
| Friends | `dashboard/social_client.py` → separate FastAPI `social_server` over HTTP |
| Recharge | Breathing/heroes HTML scenes (`static/`) |

### 2.5 The second path (CLI only)

`python main.py` → LangGraph `orchestration/state_graph.py`: Tutor → `AuditorAgent` (semantic 0.7 + logic 0.3 composite, Socratic clarification, proof-of-learning hash) → `SearcherAgent` (ChromaDB) → loop. **Nothing in the dashboard calls it.** Editing `auditor_agent.py`, `searcher_agent.py`, or `state_graph.py` does not change what a student sees. This is why the System Evaluation page shows "Not enough learning history yet" for inter-method agreement (screenshot 4): the data source for that metric can only be produced by a path the dashboard never runs.

### 2.6 Data stores (all under `sae_system/data/` unless noted)

`users.json` · `roadmaps/` · `lessons/` · `tests/` · `progress/` · `knowledge_graphs/` · `events.jsonl` (telemetry) · `eval/grading_gold_set.json` · `{student}_xp.json` · `certificates/` · `media/` (animations, videos, SVG text renders).

---

## 3. Bug register (summary)

| # | Bug | Severity | Confidence | Where |
|---|---|---|---|---|
| B1 | `StreamlitDuplicateElementKey: nav_home` after "Continue this lesson" | **High (crash)** | Verified | `page_tutor.py:71`, `page_ask.py:41`, `app.py:530` |
| B2 | `StreamlitDuplicateElementKey: ask_sae_continue_lesson` with ≥2 answers in history | **High (crash)** | Verified | `page_ask.py:99,160-167` |
| B3 | Lesson "Worked Example" shows only first sentence; table/steps missing | High (content lost) | Likely | `app.py` `page_lesson` card (~line 1210) |
| B4 | Roadmap card renders raw HTML as a code block | Medium | Verified (cause) | `app.py:938-943` |
| B5 | Expander icon shows literal text `arrow_down` / `arrow_right`, overlapping label | Low (cosmetic) | Likely | `app.py:72-76` global CSS |
| B6 | AI grading accuracy 61%, 14.3% of items flip with threshold | High (product quality) | Verified (measured) | `test_engine.py:610`, `semantic_auditor.py` |
| B7 | Secrets and user data tracked in git; Aura credential exposed in a screenshot | **High (security)** | Verified | `sae_system/.env`, `data/users.json` |
| B8 | Three different grading methods for the same kind of answer | Medium | Verified | §4.6 |
| B9 | System Evaluation "inter-method agreement" can never populate from the dashboard | Medium | Verified | §2.5 |
| B10 | 2 failing tests | Low–Med | Verified | §6 |

---

## 4. Bug details and fixes

### B1 — `nav_home` duplicate key (crash on "Continue this lesson") [Verified]

**Symptom (screenshot 6):** after answering in Adaptive Tutor, clicking "Continue this lesson" raises `StreamlitDuplicateElementKey: key='nav_home'`. Traceback runs `app.py:1918 → page_tutor.py:250 → _render_next_actions`.

**Root cause:** `_jump_to_lesson` (`page_tutor.py:71`, copy at `page_ask.py:41`) does `from dashboard.app import _SS_DEFAULTS`. Streamlit runs `app.py` as the main script, not as the module `dashboard.app`, so Python has never imported it under that name — the import **executes all of `app.py` a second time inside the same run**. That second execution calls `render_sidebar()` again, so the key `nav_home` (built as `f"nav_{page}"` at `app.py:530`) is registered twice. The 2nd run would also re-execute `set_page_config`, the CSS, and the page router.

**Why it looks intermittent:** it only fires on the first click that triggers the lazy import in a given server process. It works in the test suite because the tests `import dashboard.app` deliberately.

**Fix:** move `_SS_DEFAULTS` (and `_go`) into a small module with no Streamlit side effects, e.g. `dashboard/state.py`, and import from there in `app.py`, `page_tutor.py`, `page_ask.py`, `page_canvas.py`, `page_activity.py`. Also de-duplicate `_jump_to_lesson` — it is copy-pasted in `page_ask.py` and `page_tutor.py` (the Canvas and Activity pages have the same `_SS_DEFAULTS` import at lines 110 and 21, so they have the same latent crash).

### B2 — `ask_sae_continue_lesson` duplicate key [Verified]

**Root cause:** `_render_answer` (`page_ask.py:99`) uses the hardcoded key `"ask_sae_continue_lesson"` and is called once for the latest answer **and again for every entry in "Earlier questions"** (`page_ask.py:160-167`). Any two answers that both have a `suggested_action` collide. Screenshot 7 is the 2nd-question case.

**Fix:** pass a unique suffix: `_render_answer(ss, result, key_suffix=f"{item['timestamp']}_{i}")` and use `key=f"ask_sae_continue_lesson_{key_suffix}"`. Same pattern should be applied to any widget rendered inside a loop — grep for fixed `key=` strings inside `for` loops across `dashboard/`.

### B3 — Lesson "Worked Example" blank after first sentence [Likely]

**Symptom (screenshot 2):** only "Let's consider a simple example… age and income:" is shown, then an empty card.

**What I confirmed:** the cached lesson `data/lessons/machine_learning_clustering.json` has, right after that sentence, `\n\n| Customer ID | Age | Income |…` — a markdown table separated by blank lines. `page_lesson` interpolates that raw text into an HTML `<div style="white-space:pre-wrap">{text}</div>` and renders it with `unsafe_allow_html=True`. In Markdown, a blank line ends an HTML block, so everything after the first paragraph is re-parsed as Markdown *outside* the styled card, and the surrounding closing tags are orphaned. I did not confirm in a browser exactly how the leftover is hidden, but the root cause is unambiguous in the code.

**Fix:** render the card frame and the body separately — `st.container(border=True)` for the frame and `st.markdown(text)` for the body — so LLM Markdown (tables, bold, code, lists) is rendered by Streamlit's Markdown engine. Do not interpolate model output into HTML. If any HTML must stay, `html.escape()` it. The same pattern appears in `page_ask.py` (`{result['answer']}`), and roadmap titles/descriptions.

### B4 — Roadmap card shows raw HTML in a code block [Verified cause]

**Symptom (screenshot 3):** a dark code block under "Week 1 — Introduction to ML" containing literal `<div style=…>` and the mastery bar markup.

**Root cause:** the card template at `app.py:935-952` places `{res_html}` and `{mastery_html}` on their own lines. When `res_html` is empty (no resource URL) the line is whitespace-only → a blank line → the HTML block ends → the next lines are indented ≥ 4 spaces, which Markdown treats as an **indented code block**. This depends on data (module has no resource, or graph unavailable), so some cards render fine and others don't.

**Fix:** build the card as a single dedented string with no blank lines (`textwrap.dedent` + remove empty interpolations), or better, drop the 12-space indentation inside the triple-quoted strings across `app.py` — this is a systemic hazard (every `st.markdown(f"""\n    <div…""")` in the file). A tiny helper `html(s) -> st.markdown(re.sub(r"\n\s*\n", "\n", dedent(s)), unsafe_allow_html=True)` fixes all of them.

### B5 — Expander icon text overlaps label [Likely]

**Symptom (screenshots 5 and 7):** "arrow_down", "arrow_right" printed over "Discoverability…" and "Earlier questions…".

**Root cause:** `app.py:72-76` sets `.stApp * { font-family: var(--font-body) !important; }`. Streamlit draws expander chevrons as a ligature in the *Material Symbols* icon font; forcing the body font onto every element makes the browser show the ligature's name as plain text.

**Fix:** exclude icon elements from the universal rule, e.g. `.stApp *:not([data-testid="stIconMaterial"]):not([class*="material"])`, or add after it `[data-testid="stIconMaterial"]{font-family:"Material Symbols Rounded"!important}`. Also drop the blanket `color` and `font-weight` `!important` on `*` — it is the same class of problem and will keep producing odd rendering.

### B6 — AI grading quality [Verified, measured]

Screenshot 4 (System Evaluation, 49-item gold set, threshold 0.6): **accuracy 61%, precision 54%, recall 62%, F1 58%** (TP 13, FP 11, TN 17, FN 8). 7 of 49 items (14.3%) flip between thresholds 0.45 and 0.60.

- The earlier audit measured 67.5% / F1 64.9% on a 40-item set. The sets differ, so this is **not a regression**, but it confirms the audit's conclusion: **cosine similarity alone cannot separate correct answers from confidently-wrong, negated, or keyword-stuffed ones.** 11 false positives out of 24 passes means ~46% of "passed" short answers were wrong.
- `grade_test` (`test_engine.py:610-640`) uses *only* embedding similarity for short answers. The better signals already exist (`multi_signal_grader.grade_multi_signal`: coverage + similarity + LLM judge, and the auditor's `logic_score`) but are used only by the Adaptive Tutor and the CLI path respectively.

**Improvement:** route `grade_test` short answers through `grade_multi_signal` (with the LLM judge as tie-breaker for the 0.45–0.75 band), re-run `python -m evaluation.grading_evaluator` against the gold set to prove the gain, and add a negation/contradiction check. Short answers are the only place this matters; MCQ/TF are exact-match and fine.

### B7 — Secrets and data in version control [Verified]

- `git ls-files` shows **`sae_system/.env` and `sae_system/data/users.json` are tracked**; there is **no `.gitignore`**; `origin` is a GitHub repo. Compiled `.pyc` files and ~40 partial Manim render files under `media/videos/tmp*/` are tracked too.
- Screenshot 1 shows a one-time Neo4j **Aura Free** password in plain view. Treat it as exposed: the screenshot is now in this conversation's context and (if shared elsewhere) in chat history. If you have not yet used it, the cleaner move is to reset it in the Aura console. Do **not** paste the real value into `sae_system/.env` while `.env` is tracked — it would be committed on the next `git add -A`.
- I did not open `users.json` (the tool call was declined), so I cannot say what it contains; its schema is `hash:salt` PBKDF2 per `auth/auth.py`, i.e. real student records and password hashes.

**Fix:** add `.gitignore` (`.env`, `data/`, `__pycache__/`, `*.pyc`, `media/videos/`, `certificates/`, `outputs/`), then `git rm -r --cached` those paths. Keep `.env.example` as the template. If the repo was ever pushed with `.env`, the history still holds it — rotate every value in it (Postgres/Redis/Neo4j passwords) rather than only deleting the file.

---

## 5. Other technical findings

### 5.1 Neo4j Aura vs. the "sovereign" design
- `graph_engine.py:76-80` reads `NEO4J_URI/USER/PASSWORD` and calls `GraphDatabase.driver(uri, auth=…)`, so an Aura URI (`neo4j+s://…`) will work with no code change. Aura issues a username like the one in your screenshot, **not** `neo4j`, so set `NEO4J_USER` too.
- The earlier audit's password mismatch still applies locally: the code default is `saesystem`, `docker-compose.yml` provisions `saesystem`, but `.env` carries a different value, so a local Neo4j silently falls back to NetworkX. Pick one authority.
- Product decision: Aura is a **hosted third-party service**. Student mastery data would leave the machine, which contradicts the README's "SAE will never call a hosted provider" stance (that rule is enforced only for the LLM). Either document Aura as an opt-in exception or keep Neo4j local in Docker.
- A failed Neo4j connection is retried and logged as a warning on every `KnowledgeGraph()` construction; with `USE_NEO4J=true` and an unreachable DB this multiplies latency on each page load.

### 5.2 Streamlit-specific structural risks
- **Rerun model + module-level side effects.** `app.py` is a 1,925-line script with side effects at import time (sidebar, auth gate, CSS). Any `import dashboard.app` re-runs them. Splitting into `state.py` / `theme.py` (already partly started) / `pages/` removes this class of bug.
- **Widgets in loops need unique keys** (B2). A one-line lint (`grep -n 'key="' dashboard/ | inside for-loops`) would have caught it.
- **Token validation depends on Redis.** If Redis is down, `_is_authenticated` trusts `student_id` in session state — fine for local use, wrong for any shared deployment.
- **Logout** swallows errors from `save_progress` with a bare `except: pass` (`app.py` logout block), so a failed save is silent *and* the session is cleared right after — progress can be lost without any message.

### 5.3 Unescaped HTML from untrusted text [Not checked beyond three sites]
Model output (`page_lesson`, `page_ask`), roadmap fields, and user display names are interpolated into HTML with `unsafe_allow_html=True`. For local Ollama output this is mostly a correctness problem (B3), but **Friends chat messages come from other users** — check `page_friends.py` for the same pattern; if present it is stored HTML injection.

### 5.4 Environment and hygiene
- Two Pythons: default `python` is 3.14 (no `pytest`, likely no `streamlit`); the app and tests ran under 3.11. Pin it: add `.python-version`/`pyproject` and have `scripts/start.py` print the interpreter.
- `requirements.txt` still lists unused `langchain-community` and `Pillow` (from the earlier audit).
- Repo clutter: tracked caches (`.pyc`, Manim temp renders), and two test JSONs deleted in the working tree (`D` in `git status`: `devops_devops_fundamentals.json`, `web_development_html_fundamentals.json`) that should be committed or restored deliberately. The earlier audit's inventory of 41 swallowed `except Exception:` sites has not been re-counted.

---

## 6. Test status (measured today)

Result: **2 failed, 150 passed in 122 s** on Python 3.11. This is the figure from a full `pytest tests` run that included `test_ollama_generation.py`: my first command (with `--ignore` flags) exited non-zero, which triggered a fallback re-run of the whole suite, and only that second run's output was captured. I did not separately record the count without the Ollama tests.

| Failing test | Cause | Status |
|---|---|---|
| `test_test_engine.py::TestNormaliseQuestion::test_empty_correct_answer_gets_fallback_mcq` | Fixture uses bare-letter options `["A","B","C","D"]`; the `_LETTER_PLACEHOLDER_RE` filter strips them as junk, so the fallback text replaces them and the assertion `== "A"` fails | Pre-existing, documented in the old audit; needs a decision on which side is correct |
| `test_ollama_generation.py::test_generate_test_empty_lesson_warns_but_still_returns_10` | Needs a live Ollama; I did not investigate why it failed | Open — look at this first if test generation has been flaky |

**Coverage gaps worth closing:** there is no test that clicks through the Streamlit pages, which is exactly where B1–B5 live. Streamlit's `streamlit.testing.v1.AppTest` can render `page_ask` with 2 history items (catches B2) and run `_jump_to_lesson` (catches B1) in a few lines each.

---

## 7. Recommended order of work

**Now (hours)**
1. Add `.gitignore`, untrack `.env`/`users.json`/caches; reset/secure the Aura password. (B7)
2. Extract `_SS_DEFAULTS`/`_jump_to_lesson` out of `app.py`. (B1)
3. Unique keys in `_render_answer`. (B2)
4. Render lesson body with `st.markdown`, not interpolated HTML. (B3)
5. Fix the icon-font CSS rule. (B5)

**Next (days)**
6. HTML helper that strips blank lines/indent; apply across `app.py`. (B4)
7. Route short-answer grading through `grade_multi_signal`; re-measure on the gold set; target F1 > 75%. (B6, B8)
8. `AppTest` smoke tests for every page, with the two crash cases as regressions. (§6)
9. Decide Neo4j: local Docker (consistent with "sovereign") or Aura (opt-in, documented); fix the password mismatch either way.

**Later (architecture)**
10. Decide whether to **retire or unify** the LangGraph/CLI path with the dashboard — this also fixes the System Evaluation "inter-method agreement" gap (B9) and the three-way grading split.
11. Break `app.py` (1,925 lines) into `pages/` modules with no import-time side effects.
12. Real session validation without Redis (signed token with expiry) if this is ever shared beyond one machine.

---

## 8. What I did not do
- Did not open `.env` values or `users.json`.
- Did not reproduce B3/B5 in a browser; the causes are from code and screenshots.
- Did not run the Docker stack, the social server, or the CLI path.
- Did not change any source code — this is analysis only.
