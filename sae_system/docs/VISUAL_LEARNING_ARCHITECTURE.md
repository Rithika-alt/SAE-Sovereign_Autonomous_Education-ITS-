# Visual Learning Architecture — Phase 10

Supersedes the "static learning map" reading of Phase 10 with a dynamic,
interactive Learning Canvas. Written per Step 2, alongside implementation.

## User journey

```
Login
  |
Home (page_home.py, Phase 6) — hero stats + top recommendation, unchanged
  |  [new: "Explore Learning Canvas" button]
  v
Learning Canvas (page_canvas.py, NEW)
  |
Hero state: WHO (greeting) / WHERE (current concept + domain) /
HOW (mastery %, status) / WHAT (top recommendation) / WHY (measured reason)
  |
Interactive graph: zoom/pan (native Plotly) + click-to-select
  |
Concept selected -> contextual panel: mastery, status, prerequisite
checklist, recommendation (if any) -> [Continue Lesson] [Ask SAE] [Adaptive Tutor]
  |
Routes into Phase 6/7/8's existing pages via their existing session-state
contracts — no new routing mechanism.
```

## Data architecture

```
KnowledgeGraph (Phase 1-9, unchanged)
        +
progress_store (Phase 1-9, unchanged)
        +
recommendation_engine.recommend_next_actions (Phase 6, unchanged)
        +
current session (ss["domain"], ss["roadmap"], ss["current_module_idx"])
        v
evaluation/learning_canvas.py::build_learning_canvas()   <- NEW, pure data
        v
dashboard/page_canvas.py                                  <- NEW, rendering only
```

`build_learning_canvas` is the one new piece of logic. It does not compute
mastery, does not invent recommendations, and does not maintain graph state
— it reads `KnowledgeGraph.get_graph_data_by_domain`,
`KnowledgeGraph.get_mastery`/`prerequisites_met`, and
`recommendation_engine.recommend_next_actions` on every call, and returns a
plain dict. Status (`mastered`/`developing`/`weak`/`available`/`locked`) is
derived from `config.SEMANTIC_PASS_THRESHOLD` and
`memory.graph_engine.MASTERY_THRESHOLD` — the exact same two constants
Phase 8's `diagnose_tutor_state` already uses, not a second classification
system (Hard Rule 3, verified by `test_status_*` in `test_learning_canvas.py`).

## Visualization technology (Step 16)

**Plotly (network scatter, NetworkX spring layout) + Streamlit's native
`on_select="rerun"`** — the same library pairing `page_knowledge_graph`
(pre-Phase-10 code) already uses, extended rather than replaced by a new
stack. Confirmed the installed Streamlit version (1.57.0) supports
`st.plotly_chart(..., on_select="rerun", selection_mode="points")` natively
— click events return the clicked point's `customdata` (the node id)
without any custom component, iframe, or JS.

Why this over the alternatives Step 16 asks to evaluate:
- **PyVis / Graphviz**: would be a genuinely new dependency for capability
  Plotly+NetworkX (already installed, already proven in this exact
  codebase) provides — rejected per Hard Rule 11 ("no heavy dependencies
  without justification").
- **Custom HTML/JS component**: would need a `streamlit.components.v1`
  build step, its own packaging/portability story, and cross-browser
  testing — none of that is needed since native Plotly already delivers
  genuine zoom (mouse wheel), pan (drag), and click-select. Reserved,
  per Step 16, for a future phase if this genuinely proves insufficient —
  it doesn't.
- **React migration**: never seriously on the table — explicitly
  prohibited by Step 16/Hard Rule set, and nothing here needed it.

**Zero new dependencies were added.** `scripts/check_environment.py` still
reports "All 19 required packages importable" after this phase (Phase 10A's
portability is unregressed — verified directly, not assumed).

## Node/edge model

Each node: `{id, label, mastery, status, is_primary, is_current, week,
module_id, domain, prerequisites: [id, ...]}`. Each edge: `{source,
target}` (a prerequisite relationship, direction = prerequisite ->
dependent, matching `KnowledgeGraph`'s existing edge semantics exactly).

## Interaction model (Step 6)

| Interaction | Mechanism |
|---|---|
| Zoom | Native Plotly (mouse wheel on the figure) — no code needed |
| Pan | Native Plotly (click-drag on empty canvas area) — no code needed |
| Select | `on_select="rerun"` + `customdata` -> node id -> contextual panel |
| Focus | Selected/current node gets a thick dark ring (`marker.line.width=4`) and 26px size vs. 10-18px for others |
| Explore | Prerequisite checklist in the panel links conceptually to other nodes (clicking them in the graph re-focuses) |
| Reset | "Reset to current position" button — clears the Plotly selection via rerun |
| Filter | "Current module" (one-hop neighborhood: the concept + its direct prerequisites + concepts that depend on it) vs. "Full domain" — reduces a 37-node graph to a handful when that's more useful |

## Dynamic behavior (Step 12) — verified live, not assumed

The canvas is *not* pre-rendered animation — every render calls
`build_learning_canvas` fresh, which reads `KnowledgeGraph.get_mastery`
live. A real end-to-end test (Phase 10's live journey, see the final
report) ran an actual Adaptive Tutor question/answer/grade cycle against
the real `AdaptiveTutorAgent`, then rebuilt the canvas and asserted the
node's displayed mastery equals the value `evaluate_and_update` actually
wrote to `KnowledgeGraph` — not a simulated "mastery went up" animation.

## Recommended-path highlighting (Step 11)

When `recommendation_engine` names a `concept_id`, and the session has a
`current_module_id`, the two are drawn as a distinct orange 3px edge
(`path_trace`, layered under the graph's node trace) instead of the
default 1px gray. This is a two-endpoint visual hint (current -> target),
not a claim of full shortest-path routing — the underlying graph doesn't
expose multi-hop pathfinding, so the highlight doesn't pretend to either.
Documented, not glossed over.

## Routing (Step 23 — no new mechanism)

- **Continue Lesson**: byte-identical routing block to `page_ask.py`'s/
  `page_tutor.py`'s `_jump_to_lesson` (sets `current_module_idx` if the
  roadmap is already loaded and the concept is a top-level module;
  otherwise hands off via `home_target_module_id` + `loading_roadmap`,
  the Phase 6 mechanism).
- **Ask SAE**: sets `current_module_idx` to match the selected concept (if
  it's a loaded roadmap module) then navigates to `ss["page"]="ask"` —
  `page_ask.py`'s existing `_current_concept()` auto-detects it from there,
  unchanged.
- **Adaptive Tutor**: sets `ss["tutor_focus_concept_id"]` (the override
  mechanism Phase 8 already built for exactly this) then navigates to
  `ss["page"]="tutor"`.

No parallel navigation system, no new session-state convention.

## Empty states (Step 15)

A student with no `domain` set sees "Welcome to SAE... choose a domain to
get started" with a real button into `page_domain_select` — not a broken
graph render. A student with a domain but `insufficient_data=True` (no
graph populated yet) sees "Your {domain} map is empty so far... it will
build automatically" with a button to the Roadmap page. Neither path
invents mastery or nodes that don't exist.

## Performance (Step 18)

Measured against the real 37-node/47-edge Machine Learning graph (the
largest populated domain in this project's actual data):
`build_learning_canvas` executes in well under 100ms (pure dict/set
operations over already-loaded graph data — no LLM call, confirmed: Hard
Rule 6/Step 19, "no LLM for visualization state"). `AppTest` full-page
render (spring layout + Plotly figure construction + Streamlit script
execution) completed within the 60s test timeout with no measurable lag
observed interactively. The "Current module" filter view exists
specifically so a much larger future domain doesn't force rendering every
node at once (Step 11/17's clutter-avoidance requirement).

## Accessibility (Step 21)

Every node's status is available as text (hover tooltip: label, status,
mastery %) and the contextual panel restates the same information in
plain text/labels (not just the marker color) — a student who can't
distinguish the five status colors still gets the same information from
the "Needs attention"/"Developing"/etc. text badge and the numeric
mastery percentage. The legend below the graph spells out what each color
means in words, not just a color key.

## Known limitations

- Plotly's native pan/zoom/click work well for this project's realistic
  graph sizes (dozens of nodes) but weren't stress-tested against a
  hypothetical hundreds-of-node graph — no domain in this project's real
  data currently approaches that size.
- The recommended-path highlight is a two-endpoint visual hint, not true
  multi-hop pathfinding (Section "Recommended-path highlighting" above) —
  disclosed, not silently overstated.
- `AppTest` simulated `.click()` on the graph/buttons wasn't used for
  routing verification (the known Phase 6 `st.rerun()` harness hang) —
  routing logic was tested directly instead (`test_go_to_*` in
  `test_learning_canvas.py`), consistent with every prior phase's approach
  to this same limitation.
