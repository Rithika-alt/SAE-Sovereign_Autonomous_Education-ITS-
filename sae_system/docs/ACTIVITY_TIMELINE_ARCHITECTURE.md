# Activity Timeline + Notifications Architecture — Phase 11

## Event source

`evaluation/event_log.py`'s `data/events.jsonl` (Phase 3) is the sole
source of history — no second log/history store was created. Inspection
(Step 1) found two real gaps this phase had to fix before the feature
could work as specified, not just build on top of what already existed:

1. **Three event-type constants were defined but never logged anywhere**:
   `EVT_XP_AWARDED`, `EVT_MASTERY_UPDATE`, `EVT_CONCEPT_MASTERED` (confirmed
   via a repo-wide `log_event(` search — zero call sites for any of the
   three). Not fixed by adding call sites for them — `EVT_KNOWLEDGE_GRAPH_UPDATE`
   (which *is* logged, by every path that calls
   `KnowledgeGraph.update_mastery`, with `mastery_before`/`mastery_after`/
   `delta`) already carries everything needed to derive both "mastery
   improved" and "concept mastered" activity deterministically. Adding the
   three unused constants as new call sites would have been a second,
   redundant way to say the same thing — this module derives from the one
   source that already exists and already fires on every mastery-affecting
   path (test grading, Adaptive Tutor).
2. **Ask SAE logged nothing at all.** The phase spec explicitly asks for
   "Ask SAE activity" in the timeline, so this was a real, necessary gap to
   close: `agents/ask_sae_agent.py::AskSAEAgent.ask()` now logs one
   `EVT_AGENT_EXECUTION` event (`agent="ask_sae"`) per successful answer —
   reusing the existing generic event type and the same
   `agent=`-tagging convention `roadmap_agent.py`/`searcher_agent.py`
   already use, not a new event constant.

## Activity model

`evaluation/activity_feed.py::build_activity_timeline(student_id, domain,
limit)` reads raw events, normalizes the ones that mean something to a
student (`session_start`, `test_attempt`, `dialogue_attempt`,
`knowledge_graph_update`, `domain_completed`, and `ask_sae`-tagged
`agent_execution`) into `{timestamp, icon, title, detail, concept_id,
domain}`, and drops everything else (`ollama_call`, `test_generation`,
`dashboard_error`, other `agent_execution`s) — real telemetry that exists
for Phase 3/9's system-evaluation purposes but means nothing to a student
reading their own activity feed.

`knowledge_graph_update` events don't carry a `domain` field at all
(`memory/graph_engine.py::update_mastery` is never passed one) — a second
real gap found during inspection. Rather than change that method's
signature (used by every mastery-writing path in the app), domain is
resolved via a `concept_id -> domain` map built once per call from the
real `KnowledgeGraph.get_graph_data()` — reuse, not a new field threaded
through unrelated call sites.

Small mastery nudges (< 3 percentage points) are filtered out of both the
timeline and notifications (`_NOTABLE_DELTA = 0.03`) so the feed isn't
dominated by the low-stakes blend-weighted adjustments the Adaptive Tutor
makes on every single question.

## Notification rules

Two sources, cleanly divided by what each is actually good at:

- **Backward-looking** (`_milestone_notifications`, new logic in this
  module): did a recent `knowledge_graph_update` cross `MASTERY_THRESHOLD`
  (imported from `memory.graph_engine`, not redefined), or move mastery
  notably? This needs event *history*, which `recommendation_engine`
  doesn't consume — the one genuinely new detection capability this phase adds.
- **Forward-looking** (`build_notifications`'s second half): weak
  concepts, stale review, prerequisite/continue nudges — all produced by
  calling `evaluation.recommendation_engine.recommend_next_actions()`
  exactly as Phase 6 built it, just reformatted into the notification
  shape. Verified by a direct cross-check test
  (`test_weak_concept_notifications_come_from_recommendation_engine`) that
  every forward-looking notification's `(type, concept_id)` also appears
  in `recommend_next_actions`'s own output — not a second algorithm.

No LLM is called anywhere in this module — every rule is a plain
comparison against a real stored/logged number.

## Deduplication (no notification spam)

Two layers:
1. **Structural**: notifications are deduplicated by `(type, concept_id)`
   within a single `build_notifications()` call — the same concept can't
   produce two "weak concept" entries, etc. Verified by
   `test_notifications_are_deduplicated_by_type_and_concept`.
2. **Session-level dismissal**: `page_activity.py` keeps a
   `ss["dismissed_notifications"]` set (session-state only — resets on
   next login, no new persistent store) so clicking "Dismiss" hides that
   specific notification for the rest of the session without needing a
   database.

## Routing

Every notification/timeline action button reuses an existing mechanism,
no new one:
- **Canvas**: a new `ss["canvas_focus_concept_id"]` override, added to
  `page_canvas.py` this phase — but it's a direct copy of the pattern
  Phase 8 already established for the Adaptive Tutor
  (`tutor_focus_concept_id`), not a new mechanism.
- **Lesson**: the byte-identical routing block used by
  `page_ask.py`/`page_tutor.py`/`page_canvas.py` since Phase 6.
- **Ask SAE**: sets `current_module_idx` if the concept is a loaded
  roadmap module, same as Phase 10's Canvas page does.
- **Adaptive Tutor**: `ss["tutor_focus_concept_id"]`, Phase 8's existing override.

## Privacy / isolation

`read_events(student_id=...)` already filters by student — `activity_feed.py`
never reads another student's events. Domain filtering (Section "Activity
model") further scopes the feed to the domain the caller asks for, so a
student viewing one domain's Activity page doesn't see unrelated-domain
noise mixed in.

## Home integration

`page_home.py` gained one small section: the 3 most recent timeline
entries plus a "View Activity" button into the full page — not the full
timeline, not the full notification list, matching the phase's explicit
"only a small preview" instruction.

## Known limitations

- Session-scoped dismissal means a dismissed notification reappears after
  logging back in — acceptable given the alternative (a new persistent
  "seen" store) would be exactly the kind of second history/state system
  the Hard Rules prohibit for a first version of this feature.
- `dialogue_attempt` events come from two different code paths with
  different field names for the outcome (`AdaptiveTutorAgent` sets
  `label`, the CLI-only `AuditorAgent` sets `phase`) — `_normalize_event`
  checks both, but a future unification of those two paths (flagged since
  Phase 1's audit, still not undertaken) would let this be simplified.
- Milestone detection only looks at the *most recent* `knowledge_graph_update`
  per concept (to avoid re-notifying the same historical crossing forever)
  — a concept that crosses the mastered threshold, drops back down, and
  crosses again would only surface its latest crossing, not the full history.
