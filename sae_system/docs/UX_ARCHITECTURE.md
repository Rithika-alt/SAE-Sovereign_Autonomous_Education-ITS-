# SAE UX Architecture

Written before Phase 6 implementation, per the phase's own instruction to
inspect the current app before changing it. Covers current state, the
proposed information architecture, reusable components, and state-management
constraints that later phases (7–13) need to respect.

## 1. Current navigation

`dashboard/app.py` is a single Streamlit script with a hand-rolled router at
the bottom (`_PAGES` dict + `current_page = ss.get("page", ...)`). There is
no URL routing — `page` is a plain session-state string, and every
navigation is `ss["page"] = X; st.rerun()` (the `_go()` helper at
`app.py:368`). Sub-pages live in their own module (`page_login.py`,
`page_friends.py`, `page_system_evaluation.py`) and are imported into
`app.py`; everything else is a `def page_*()` function inside `app.py`
itself.

Current page graph:
```
(unauthenticated) → page_login
        ↓ (login success)
page_domain_select  ←──────────────────────────┐
        ↓ (pick/type a domain)                 │
page_loading_roadmap → page_roadmap            │ "← Back to Roadmap"
        ↓ (pick a module)                      │
page_loading_lesson → page_lesson              │
        ↓ (finish lesson)                      │
page_loading_test → page_test                  │
        ↓ (submit test)                        │
page_results ───────────────────────────────────┘
        ↓ (all modules done)
page_certificate

Reachable from sidebar nav (only once ss["domain"] is set):
  roadmap · knowledge_graph · system_evaluation · friends · stress_relief
```

## 2. Current pain point (the one this phase fixes)

**A returning student with existing progress lands on `page_domain_select`
— a cold "pick a domain" grid — not on anything that reflects their actual
state.** `_SS_DEFAULTS["page"]` (`app.py:272`) is hardcoded to
`"domain_select"`, and `page_login.py::_apply_session` (`page_login.py:184`)
restores `ss["domain"]`/`modules_passed`/etc. from
`persistence.progress_store.load_progress` but never changes `ss["page"]`.
So even a student who's mastered 8 concepts sees the same "What do you want
to learn today?" grid as a brand-new student. There is no single place that
answers "what should I do next" — that data exists (`KnowledgeGraph`,
`XPEngine`, `event_log`, `system_evaluator`) but nothing surfaces it before
the student manually clicks into Roadmap or Knowledge Graph.

Secondary pain points (not fixed in this phase, noted for later phases):
- No persistent "ask anything" entry point (Phase 7).
- The tutor teaches the same way regardless of a student's prior mistakes on
  prerequisite concepts (Phase 8).
- The System Evaluation page's charts are single-shot metrics, not a live
  timeline a student would check daily (Phase 15).

## 3. Proposed information architecture

Add one new page, **`home`**, that becomes the post-login landing page
*only when the student has existing progress* (at least one entry from
`persistence.progress_store.get_enrolled_domains(student_id)`). A genuinely
new student — nothing enrolled yet — still lands on `page_domain_select`,
because a command center with zero data to show is worse than the existing
"pick a domain" grid; this is the same "intelligent empty state" principle
already used elsewhere (`system_evaluator`'s `insufficient_data` guards).

```
(unauthenticated) → page_login
        ↓ (login success)
   enrolled domains?
     ├─ no  → page_domain_select   (unchanged — first-time flow)
     └─ yes → page_home            (NEW — command center)
                  ↓
          [Continue learning] → page_roadmap (existing)
          [Fix this concept]  → page_lesson or page_test for that concept
          [Explore new domain] (new sidebar entry) → page_domain_select
```

`page_home` reuses existing pages for every action — it recommends and
routes, it does not duplicate lesson/test/roadmap rendering. This keeps the
new page small and avoids a second code path for lesson/test flows.

## 4. Reusable components identified

Already present and reused as-is (no changes needed):
- The colored-border metric-card `st.markdown` pattern (`page_knowledge_graph`,
  now also `page_system_evaluation._metric_card`) — reused for Home's
  mastery/streak/XP/level tiles.
- The Plotly gauge pattern (`test_interface.show_results`,
  `page_system_evaluation._render_learning_tab`) — reused for Home's overall
  mastery ring if needed.
- `evaluation.system_evaluator.evaluate_learning_outcomes` /
  `evaluate_engagement` — Home reads these directly rather than
  recomputing anything.

New in this phase, designed to be reused by later phases:
- `evaluation/recommendation_engine.py::recommend_next_actions()` — Phase 6.2.
  Phase 7 ("Ask SAE") and Phase 16 (notifications) are both expected to call
  this rather than re-deriving recommendations independently.
- A small `_action_card()` render helper in `page_home.py` (weak-concept /
  continue-lesson / recommendation cards) — Phase 10 ("visual learning
  system") should generalize this into a shared card module if/when more
  card types are needed, rather than each page inventing its own markup.

## 5. State management requirements

- `page_home` needs `student_id` and `domain` from `ss` — already present in
  `_SS_DEFAULTS`. No new session-state keys are required for Phase 6.
- Recommendation actions must route through the existing `_go()` helper and
  existing session-state keys (`ss["current_module_idx"]`, `ss["domain"]`,
  etc.) so navigating from a Home recommendation into `page_lesson`/`page_test`
  behaves identically to navigating there via the Roadmap page — no parallel
  state machine.
- `recommend_next_actions()` itself is stateless (pure read of
  `KnowledgeGraph`/`event_log`/`progress_store` + a returned list) — it does
  not touch `st.session_state`, so it's safely callable from a future CLI
  or notification job outside the dashboard process too.

## 6. What should NOT change in this phase

- `_PAGES` router mechanism, `_go()`, `_SS_DEFAULTS` shape — all sound and
  reused as-is.
- `page_domain_select`, `page_roadmap`, `page_lesson`, `page_test`,
  `page_results` — untouched; Home only links into them.
- `TestEngine`, `KnowledgeGraph`, `XPEngine`, `event_log`,
  `system_evaluator` — read-only consumers added, no API changes.
- Auth gate (`_is_authenticated`) — unchanged; Home sits behind it exactly
  like every other page.

## 7. Future migration considerations (if Streamlit becomes limiting)

Flagging for Phase 13 (Learning Canvas), not acted on now: Streamlit's
rerun-the-whole-script-on-every-interaction model (already worked around
once, for the XP double-award guard in `page_certificate`) makes fine-grained
node-drag/drop canvas interaction awkward — every drag event would trigger a
full-page Python rerun. A node-based canvas MVP is more likely to need a
small embedded custom component (`streamlit.components.v1` + a minimal JS
canvas library) than a change of framework. A full frontend migration is
very unlikely to be justified purely for the canvas; it should only be
reconsidered if Phase 13's MVP proves the interaction is unusable within
`components.v1`.
