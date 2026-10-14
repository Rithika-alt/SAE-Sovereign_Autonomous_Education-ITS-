# Adaptive Tutor — Architecture Finding

Written before implementation, per Phase 8 Step 2. Grounded in the actual
repository state inspected in Step 1 (TutorAgent, TestEngine,
semantic_auditor, KnowledgeGraph, progress_store, event_log,
recommendation_engine, AskSAEAgent) — not aspirational architecture.

## Flow

```
Student State (KnowledgeGraph + progress_store + event_log)
      v
diagnose_tutor_state() -> TutorState        [pure read, no LLM]
      v
choose_teaching_strategy(TutorState)         [pure rule, no LLM]
      v
AdaptiveTutorAgent.explain()                 [reuses TutorAgent's cached lesson,
                                               slices by depth — usually zero new
                                               Ollama calls]
      v
AdaptiveTutorAgent.generate_question()       [one new, focused Ollama call]
      v
Student answers
      v
AdaptiveTutorAgent.evaluate_and_update()     [reuses semantic_auditor.grade_response
                                               + KnowledgeGraph.update_mastery]
      v
diagnose_tutor_state() again (re-diagnosis) -> next strategy
```

## 1. Existing components reused

- **`agents/tutor_agent.py::TutorAgent`** — `teach_concept()` for grounded lesson
  content (cached at `data/lessons/{domain}_{concept}.json`). Not
  reimplemented; `AdaptiveTutorAgent` composes a `TutorAgent` instance
  internally and calls it, per Step 7's "extend or wrap, don't duplicate."
- **`agents/tutor_agent.py::SovereigntyError`** — imported, not redefined,
  same as Phase 7's `AskSAEAgent`.
- **`config.py::SEMANTIC_PASS_THRESHOLD` (0.60), `OLLAMA_BASE_URL`,
  `OLLAMA_MODEL`** — the same centralized values Phase 2 established.
- **`evaluation/semantic_auditor.py::grade_response`** — the same local
  cosine-similarity grader `TestEngine.grade_test` and `AuditorAgent` use.
  No second grading algorithm.
- **`memory/graph_engine.py::KnowledgeGraph`** — `get_mastery`,
  `update_mastery`, `get_prerequisites`, `get_next_recommended_nodes`,
  `MASTERY_THRESHOLD` (0.85). `update_mastery` already logs
  `EVT_KNOWLEDGE_GRAPH_UPDATE` internally (Phase 3 instrumentation) — the
  adaptive tutor gets mastery-change telemetry for free, no new logging code
  needed for that part.
- **`evaluation/event_log.py`** — `EVT_DIALOGUE_ATTEMPT` (already defined,
  already consumed by `system_evaluator.evaluate_grading_accuracy`'s
  inter-method-agreement calculation for the CLI-only auditor path). The
  adaptive tutor emits the same event type with a compatible shape
  (`concept_id`, `semantic_score`, `phase`) so its interactions
  automatically feed that existing metric rather than requiring a new one.
- **`json_repair.repair_json`** — already a project dependency, used by
  `roadmap_agent.py`/`test_engine.py` to parse LLM-returned JSON
  defensively; reused for the question-generation call's JSON parsing.

## 2. Student-state sources

- Mastery: `KnowledgeGraph.get_mastery(concept_id)` — single concept, O(1),
  not the whole graph (mirrors the "keep context focused" discipline from
  Phase 7).
- Recent performance/failure: `event_log.read_events(student_id,
  event_type=EVT_TEST_ATTEMPT)` filtered to the concept, most recent 3 —
  same event stream `recommendation_engine.py`'s `_last_failed_attempt`
  already reads, same field names (`passed`, `percentage`, `timestamp`).
- Prerequisites: `KnowledgeGraph.get_prerequisites(concept_id)` +
  `get_mastery` on each — only ever a real graph edge, never inferred.
- Domain/enrollment: `persistence/progress_store.py` (`get_enrolled_domains`,
  `load_progress`) — same as Phase 6/7.

## 3. Curriculum/lesson sources

The cached lesson (`TutorAgent.teach_concept`) is the grounding source for
the "explain" step. **No new lesson-generation prompt was created.** Instead,
`AdaptiveTutorAgent.explain()` selects which of the 6 existing cached
sections (`introduction, theory, example, misconceptions, applications,
summary`) to surface, based on the chosen strategy's `explanation_depth`:
scaffolded shows `introduction` + `example`; standard shows `introduction` +
`theory` + `example`; concise shows `theory` + `applications`. This means
the *content itself* stays identical to what `page_lesson` already shows
(same cache file, same grounding) — adaptation changes which parts are
surfaced and in what framing, not the underlying facts. This was the
deciding factor in Step 7's "can the existing agent be reused" question: yes,
for content; a new focused call was only justified for question generation,
where nothing existing produces a single question at a specified difficulty
(`TestEngine` only generates a fixed 10-question batch, cached per
domain+concept without a difficulty axis — reusing it for one adaptive
question would mean discarding 9 of its 10 generated questions each time,
which is worse than one small dedicated prompt).

## 4. Evaluation mechanism

`evaluation/semantic_auditor.grade_response(student_answer, reference_answer)`
— identical grader used elsewhere. `passed = similarity >=
config.SEMANTIC_PASS_THRESHOLD` — identical threshold used elsewhere. No new
evaluator, no LLM-judged pass/fail, no fabricated confidence.

## 5. How adaptation decisions are made

Deterministic, three real signals, zero invented thresholds beyond one
documented blend weight (see Section 6):

- **Mode band** — reuses two thresholds that already exist elsewhere in this
  exact codebase, rather than inventing new ones:
  - `mastery < SEMANTIC_PASS_THRESHOLD (0.60)` -> **struggling**
  - `SEMANTIC_PASS_THRESHOLD <= mastery < MASTERY_THRESHOLD (0.60-0.85)` -> **developing**
  - `mastery >= MASTERY_THRESHOLD (0.85)` -> **strong**, or **mastered_retention**
    if `days_since_last_reviewed > STALE_REVIEW_DAYS`. `STALE_REVIEW_DAYS = 14`
    is not a new invented value — it mirrors the identical constant already
    used for the identical purpose in `evaluation/system_evaluator.py` and
    `evaluation/recommendation_engine.py`'s retention-proxy logic.
- **Recent failure** — if the concept's most recent `EVT_TEST_ATTEMPT` failed,
  the mode is pulled toward `struggling` regardless of the raw mastery band
  (a student who just failed shouldn't immediately get a "challenge"
  question even if their historical mastery number is still high).
- **Weak prerequisite** — if any real prerequisite edge has mastery below
  `SEMANTIC_PASS_THRESHOLD`, it's surfaced as a *recommendation*
  (`weak_prerequisite` field), never an automatic reroute — the student
  clicks a button to go review it; nothing happens silently (Step 12).

Every `TutorState.reasons` entry names the actual measured value (e.g.
`"Mastery is 43%, below the 60% pass threshold"`), not an inferred
personality trait.

## 6. How mastery changes are persisted

`AdaptiveTutorAgent.evaluate_and_update()` does **not** let the LLM assign a
mastery value, and does **not** hard-overwrite mastery the way the full
10-question test flow does (`dashboard/app.py`'s `page_test`: mastery =
this test's percentage, full replace). A single tutor question is a much
lower-stakes, single-sample signal than a 10-question test, so a hard
overwrite would let one lucky guess or one careless slip swing mastery
wildly. Instead, this phase introduces one new, small, disclosed constant:

```
MASTERY_BLEND_WEIGHT_NEW = 0.3
new_mastery = (1 - 0.3) * old_mastery + 0.3 * similarity_score
```

70% weight stays with the student's existing measured mastery; 30% comes
from this question's real `grade_response` similarity score. This is then
passed to the *existing, unmodified* `KnowledgeGraph.update_mastery()` —
the blending happens in `AdaptiveTutorAgent`, not inside `graph_engine.py`,
so the core mastery-write API is untouched. This is a genuine Phase 8 design
decision (not something already established elsewhere in the repo) and is
called out as such rather than presented as a pre-existing rule.

## 7. Sovereignty

`AdaptiveTutorAgent.__init__` performs the identical guard
`TutorAgent`/`RoadmapAgent`/`SearcherAgent`/`AskSAEAgent` all use: refuses to
construct (raises the shared `SovereigntyError`) unless `OLLAMA_BASE_URL`
starts with `http://localhost` or `http://127.0.0.1`. Constructing the
internal `TutorAgent()` performs the same check a second time (belt-and-
suspenders, not a weaker path). No hosted-provider fallback exists anywhere
in this code to be triggered.

## 8. What remains intentionally outside Phase 8

- No ML-based or reinforcement-learned personalization — three deterministic
  mode bands plus two boolean modifiers (recent failure, weak prerequisite).
- No multi-turn autonomous dialogue planner — one question per teaching
  step, evaluated, then re-diagnosed; the student always sees and clicks the
  next action.
- No new grading algorithm — `grade_response` + `SEMANTIC_PASS_THRESHOLD`,
  unchanged.
- No automatic roadmap/prerequisite rerouting — recommendations only,
  student-initiated.
- No persistent tutor "personality" or long-term memory beyond what
  `KnowledgeGraph`/`event_log` already persist.
