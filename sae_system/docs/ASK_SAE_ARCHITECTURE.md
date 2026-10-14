# Ask SAE — Architecture Finding

Written before implementation, per Phase 7 Step 2. Answers the nine
questions the phase asks, grounded in what actually exists in the repo
today (not aspirational architecture).

## Inspection summary

**LLM infrastructure**: All local generation goes through `langchain_ollama.ChatOllama`
pointed at `OLLAMA_BASE_URL`/`OLLAMA_MODEL`, now centralized in `config.py`
(Phase 2). Three existing agents (`agents/tutor_agent.py::TutorAgent`,
`agents/roadmap_agent.py::RoadmapAgent`, `agents/searcher_agent.py::SearcherAgent`)
each independently implement the same sovereignty guard in `__init__`: refuse
to construct if `OLLAMA_BASE_URL` doesn't start with `http://localhost` or
`http://127.0.0.1`, raising `SovereigntyError` (defined once, in
`agents/tutor_agent.py`, imported by the other two). There is **no existing
chat/Q&A capability** — `AuditorAgent`'s Socratic "clarification" dialogue
(`evaluation/semantic_auditor.generate_socratic_probe`) is the closest
analog, but it grades a specific expected answer, it doesn't answer an
open-ended student question, and per the Phase 1 audit it's only reachable
via the CLI (`main.py`), never the dashboard.

**Knowledge infrastructure**: Two candidate context sources exist:
1. **Lesson cache** (`data/lessons/{domain}_{concept}.json`, written by
   `TutorAgent.teach_concept`/`teach_concept_parallel`) — real,
   already-generated 6-section curriculum content for every concept a
   student has actually opened a lesson for. This is populated on the
   normal dashboard path.
2. **ChromaDB** (`memory/chroma_store.py`) — per the Phase 1 audit, only
   ever populated by `SearcherAgent._generate_chunks`, which only runs on
   the CLI-only LangGraph path. On the dashboard path, `collection_exists()`
   will be `False` for essentially every concept.

Given this, the lesson cache is the *primary* dashboard-reachable grounding
source; ChromaDB is queried as a secondary, best-effort source (reusing
existing infra per the phase's "reuse before creating" rule) but is expected
to usually return nothing on the dashboard path — that's an honest reflection
of current system state, not a bug to fix in this phase.

**Student context**: `memory/graph_engine.py::KnowledgeGraph.get_mastery(concept_id)`
gives a single concept's mastery in O(1) without loading the whole graph.
`st.session_state` (`ss`) already carries `domain`, `roadmap`,
`current_module_idx` — the same fields Phase 6's Home page and the existing
Roadmap/Lesson pages already read.

**Dashboard conventions**: `dashboard/app.py`'s `_PAGES` dict + `ss["page"]`
router (Phase 6 already added to this once for `page_home`). Pages are
plain `def page_x() -> None` functions using `st.session_state` directly.
Metric-card and gauge-chart render patterns are established
(`page_knowledge_graph`, `page_system_evaluation`, `page_home`).

## Answers

1. **What existing component should answer the question?** None exists —
   this phase adds a new, narrow component (`agents/ask_sae_agent.py::AskSAEAgent`),
   deliberately mirroring the existing agent shape (sovereignty check +
   `ChatOllama` in `__init__`, per `TutorAgent`/`RoadmapAgent`/`SearcherAgent`)
   rather than inventing a new pattern.
2. **What existing retrieval mechanism should provide context?** The lesson
   cache (direct file read, same path convention as `TutorAgent._cache_file`,
   without invoking `TutorAgent`'s generation fallback — a context *lookup*
   should never itself trigger a full 6-section Ollama generation). ChromaDB
   (`memory.chroma_store.query_documents`) as a secondary, best-effort source.
3. **What student-progress context is safe/useful to inject?** Only the
   focus concept's single mastery value (`KnowledgeGraph.get_mastery`), not
   the full graph or full event history — directly per the phase's "keep
   context focused" instruction.
4. **What existing local model interface should be used?** `ChatOllama` via
   `config.OLLAMA_BASE_URL`/`config.OLLAMA_MODEL`, with the same
   `SovereigntyError` guard the other three agents use (imported, not
   redefined).
5. **What happens when retrieval finds nothing?** The response's `grounded`
   field is `False` and `sources` is empty; the system prompt instructs the
   model to answer from general knowledge while being explicit that it isn't
   grounded in the student's curriculum, and the UI surfaces this plainly
   (see Step 5/9 below) rather than silently presenting an ungrounded answer
   as if it were sourced.
6. **What happens when Ollama is unavailable?** The `llm.invoke()` call is
   wrapped; on failure, the response contains an `error` field and no
   `answer` — the UI shows a clear message. No fallback to any hosted
   provider is implemented or possible in this codebase.
7. **How will sovereignty be guaranteed?** Same mechanism as every other
   agent: constructing `AskSAEAgent` itself raises `SovereigntyError` if
   `OLLAMA_BASE_URL` isn't localhost/127.0.0.1 — enforced before any network
   call is attempted, not as an afterthought.
8. **Where should the Ask SAE page live?** `dashboard/page_ask.py`, following
   the `page_home.py`/`page_friends.py` convention (own module, imported and
   registered in `app.py`'s `_PAGES` + sidebar `nav`).
9. **How should Ask SAE connect back to lessons/modules?** Reuses the exact
   state-population block `page_roadmap`'s "Start/Continue Week" button and
   Phase 6's `page_home`/`app.py` jump-to-lesson logic already use
   (`current_module_idx`, `lesson`, `questions`, etc. reset, then
   `_go("loading_lesson")` if the roadmap is already loaded, or the
   `home_target_module_id` hand-off Phase 6 added if it isn't) — no new
   navigation mechanism.

## Scope note

This phase's own instructions explicitly scope it down from the broader
"route any request to any agent" vision floated earlier: *"The goal of this
phase is NOT to build a sophisticated autonomous agent system... Establish
this core loop: Student Question → Context/Retrieval → Local Answer →
Evidence/Explanation → Optional Lesson Routing."* Accordingly, `AskSAEAgent`
does **not** do intent detection or route to `TutorAgent`/`AuditorAgent`/
`RoadmapAgent`/`SearcherAgent` — it answers the question directly and offers
one concrete next action (continue the current lesson, if one is identified).
Multi-capability routing ("test me", "make me a study plan") is out of scope
here and would be a future phase's decision, not something to half-build now.

## Limits established (Step 9)

No existing max-question-length constant was found anywhere in the repo.
This phase establishes `MAX_QUESTION_CHARS = 2000` in `agents/ask_sae_agent.py`
— generous enough for a real question, conservative enough to bound prompt
size and Ollama latency. Documented here as the source of truth for that
number.
