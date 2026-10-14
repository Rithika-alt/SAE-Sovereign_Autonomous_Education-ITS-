"""Learning Canvas — Phase 10.

The interactive, spatial view of a student's knowledge graph: click a
concept to focus it, see its mastery/prerequisites/recommendation, and act
(Continue Lesson / Ask SAE / Adaptive Tutor) — all through Phase 6-9's
existing routing/recommendation/mastery systems, not a second one.

Interaction model: Plotly's native zoom/pan (built into any 2D scatter
figure) plus Streamlit's on_select="rerun" for click-to-select — no custom
JS component, no new dependency (see docs/VISUAL_LEARNING_ARCHITECTURE.md
Step 16's technology evaluation). Reuses the click-to-select pattern
already established in dashboard/app.py::page_knowledge_graph, adapted for
a 5-state status model (weak/developing/mastered/available/locked) instead
of that page's 3-color one, plus current-concept and recommended-path
highlighting that page doesn't have.
"""

from datetime import datetime

import streamlit as st

_STATUS_COLOR = {
    "mastered": "#4ade80",
    "developing": "#fbbf24",
    "weak": "#f87171",
    "available": "#7c6ef5",
    "locked": "#8888a3",
}
_STATUS_LABEL = {
    "mastered": "Mastered",
    "developing": "Developing",
    "weak": "Needs attention",
    "available": "Available",
    "locked": "Locked (prerequisite needed)",
}


def _metric_card(col, label: str, value: str, color: str) -> None:
    col.markdown(f"""
    <div style="background:rgba(255,255,255,0.045);backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px);border-radius:14px;padding:0.9rem;text-align:center;
                border:2px solid {color}22;box-shadow:0 2px 8px rgba(0,0,0,0.04);">
      <div style="font-size:1.4rem;font-weight:800;color:{color};">{value}</div>
      <div style="font-size:0.72rem;color:#a3a3bd;font-weight:600;margin-top:2px;">{label}</div>
    </div>
    """, unsafe_allow_html=True)


def _render_hero(ss, canvas: dict) -> None:
    """WHO / WHERE / HOW / WHAT / WHY — Phase 10 Step 3/4. Every number
    here comes from the same canvas view model the graph below renders,
    not a separate computation.
    """
    name = ss.get("student_name", "").split()[0] if ss.get("student_name") else "there"
    domain = canvas["domain"]
    current_id = canvas["current_concept_id"]
    nodes_by_id = {n["id"]: n for n in canvas["nodes"]}
    current_node = nodes_by_id.get(current_id) if current_id else None
    top_rec = canvas["top_recommendation"]

    st.markdown(f"""
    <div style="padding:0.4rem 0 0.8rem;">
      <div style="font-family:'Plus Jakarta Sans',sans-serif;font-size:1.6rem;font-weight:800;color:#f2f2f8;">
        Welcome back, {name}
      </div>
    </div>
    """, unsafe_allow_html=True)

    if current_node:
        mastery_pct = current_node["mastery"]
        status = current_node["status"]
        st.markdown(f"""
        <div style="background:linear-gradient(135deg,#7c6ef511,#38bdf811);border:2px solid rgba(124,110,245,0.20);
                    border-radius:18px;padding:1.1rem 1.4rem;margin-bottom:0.8rem;">
          <div style="font-size:0.75rem;color:#a3a3bd;font-weight:700;letter-spacing:0.5px;text-transform:uppercase;">
            You're currently learning
          </div>
          <div style="font-size:1.3rem;font-weight:800;color:#f2f2f8;margin-top:2px;">
            {current_node['label']} <span style="font-size:0.85rem;color:#a3a3bd;font-weight:600;">({domain})</span>
          </div>
          <div style="margin-top:6px;font-size:0.95rem;color:#c7c7de;">
            Mastery: <b style="color:{_STATUS_COLOR[status]}">{mastery_pct:.0%}</b> — {_STATUS_LABEL[status]}
          </div>
        </div>
        """, unsafe_allow_html=True)

    if top_rec:
        st.markdown(f"""
        <div style="background:rgba(255,255,255,0.045);backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px);border:2px solid rgba(251,191,36,0.27);border-radius:16px;
                    padding:1rem 1.3rem;margin-bottom:1rem;">
          <div style="font-size:0.75rem;color:#fbbf24;font-weight:700;letter-spacing:0.5px;text-transform:uppercase;">
            SAE recommends
          </div>
          <div style="font-size:1.05rem;font-weight:800;color:#f2f2f8;margin-top:2px;">
            {top_rec.get('concept_label') or 'Choose a domain'}
          </div>
          <div style="font-size:0.85rem;color:#a3a3bd;margin-top:3px;">{top_rec['reason']}</div>
        </div>
        """, unsafe_allow_html=True)


def _jump_to_lesson(ss, concept_id: str, domain: str) -> None:
    """Identical routing block to page_ask.py/page_tutor.py's — same
    established mechanism, not a new one.
    """
    roadmap = ss.get("roadmap")
    if roadmap and ss.get("domain") == domain:
        modules = roadmap.get("modules", [])
        match = next((i for i, m in enumerate(modules) if m["module_id"] == concept_id), None)
        if match is not None:
            from dashboard.state import make_session_defaults  # NOT dashboard.app: importing it re-runs the whole app
            _SS_DEFAULTS = make_session_defaults()
            ss["current_module_idx"] = match
            ss["current_concept_idx"] = 0
            ss["lesson_section"] = 0
            ss["lesson"] = None
            ss["video_path"] = ""
            ss["video_ready"] = False
            ss["questions"] = None
            ss["grade_result"] = None
            for k in ["test_phase", "test_answers", "test_q_index",
                       "test_grade_result", "test_terminated", "proctor"]:
                ss[k] = _SS_DEFAULTS[k]
            ss["page"] = "loading_lesson"
            st.rerun()
            return

    ss["domain"] = domain
    ss["session_start"] = datetime.now()
    ss["roadmap"] = None
    try:
        from persistence.progress_store import load_progress
        saved = load_progress(ss.get("student_id", ""), domain)
        ss["modules_passed"] = saved["modules_passed"]
        ss["modules_unlocked"] = saved["modules_unlocked"]
        ss["module_progress"] = saved["module_progress"]
    except Exception:
        ss["modules_passed"] = set()
        ss["modules_unlocked"] = set()
        ss["module_progress"] = {}
    ss["home_target_module_id"] = concept_id
    ss["page"] = "loading_roadmap"
    st.rerun()


def _go_to_ask_sae(ss, concept_id: str) -> None:
    roadmap = ss.get("roadmap")
    if roadmap:
        modules = roadmap.get("modules", [])
        match = next((i for i, m in enumerate(modules) if m["module_id"] == concept_id), None)
        if match is not None:
            ss["current_module_idx"] = match
    ss["page"] = "ask"
    st.rerun()


def _go_to_adaptive_tutor(ss, concept_id: str) -> None:
    ss["tutor_focus_concept_id"] = concept_id
    ss["page"] = "tutor"
    st.rerun()


def _render_graph(canvas: dict, key_suffix: str):
    """Renders the interactive Plotly network graph. Returns the selected
    node id, or None. Zoom/pan are native Plotly behavior (mouse wheel /
    drag) — no extra code needed for those two Step 6 interactions.
    """
    import networkx as nx
    import plotly.graph_objects as go

    nodes = canvas["nodes"]
    node_map = {n["id"]: n for n in nodes}

    G = nx.DiGraph()
    for n in nodes:
        G.add_node(n["id"])
    for e in canvas["edges"]:
        if e["source"] in G and e["target"] in G:
            G.add_edge(e["source"], e["target"])

    pos = nx.spring_layout(G, seed=42, k=2.5)

    recommended_path = set(canvas["recommended_path"])
    path_edges = set(zip(canvas["recommended_path"], canvas["recommended_path"][1:]))

    edge_x, edge_y, path_x, path_y = [], [], [], []
    for src, dst in G.edges():
        x0, y0 = pos[src]
        x1, y1 = pos[dst]
        if (src, dst) in path_edges or (dst, src) in path_edges:
            path_x += [x0, x1, None]
            path_y += [y0, y1, None]
        else:
            edge_x += [x0, x1, None]
            edge_y += [y0, y1, None]

    edge_trace = go.Scatter(x=edge_x, y=edge_y, mode="lines",
                             line=dict(width=1.2, color="rgba(255,255,255,0.10)"), hoverinfo="none")
    path_trace = go.Scatter(x=path_x, y=path_y, mode="lines",
                             line=dict(width=3, color="#fbbf24"), hoverinfo="none")

    node_x, node_y, node_text, node_color, node_size, node_line, node_hover, node_ids = (
        [], [], [], [], [], [], [], []
    )
    for nid in G.nodes():
        n = node_map[nid]
        x, y = pos[nid]
        is_current = n["is_current"]
        node_x.append(x)
        node_y.append(y)
        node_text.append(n["label"] if (n["is_primary"] or is_current) else "")
        node_color.append(_STATUS_COLOR[n["status"]])
        node_size.append(26 if is_current else (18 if n["is_primary"] else 10))
        node_line.append(dict(width=4, color="#f2f2f8") if is_current else dict(width=1.5, color="white"))
        node_hover.append(
            f"<b>{n['label']}</b>{'  (you are here)' if is_current else ''}<br>"
            f"Status: {_STATUS_LABEL[n['status']]}<br>"
            f"Mastery: {n['mastery']:.0%}"
        )
        node_ids.append(nid)

    # marker line color/width must be per-point via separate lists since
    # go.Scatter's marker.line doesn't accept a list of dicts directly
    node_line_width = [ld["width"] for ld in node_line]
    node_line_color = [ld["color"] for ld in node_line]

    node_trace = go.Scatter(
        x=node_x, y=node_y, mode="markers+text",
        marker=dict(size=node_size, color=node_color,
                    line=dict(width=node_line_width, color=node_line_color)),
        text=node_text, textposition="top center", textfont=dict(size=9, color="#f2f2f8"),
        hovertext=node_hover, hoverinfo="text", customdata=node_ids,
    )

    fig = go.Figure(
        data=[edge_trace, path_trace, node_trace],
        layout=go.Layout(
            paper_bgcolor="#0a0a0f", plot_bgcolor="#0a0a0f", showlegend=False,
            margin=dict(l=0, r=0, t=0, b=0), height=500,
            xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
            yaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
            clickmode="event+select",
        ),
    )

    selected = st.plotly_chart(
        fig, use_container_width=True,
        on_select="rerun", selection_mode="points", key=f"canvas_plot_{key_suffix}",
    )
    points = (selected or {}).get("selection", {}).get("points", [])
    return points[0].get("customdata") if points else None


def _render_concept_panel(ss, canvas: dict, concept_id: str) -> None:
    from evaluation.learning_canvas import get_concept_detail

    detail = get_concept_detail(canvas, concept_id)
    if detail is None:
        return

    status = detail["status"]
    st.markdown(f"""
    <div style="background:rgba(255,255,255,0.045);backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px);border-radius:16px;padding:1.2rem 1.4rem;
                border:2px solid {_STATUS_COLOR[status]}44;box-shadow:0 4px 16px rgba(0,0,0,0.06);
                margin-top:0.8rem;">
      <div style="font-size:1.15rem;font-weight:800;color:#f2f2f8;">{detail['label']}</div>
      <div style="margin-top:4px;">
        <span style="background:{_STATUS_COLOR[status]}22;color:{_STATUS_COLOR[status]};
                     font-size:0.72rem;font-weight:700;padding:2px 10px;border-radius:20px;">
          {_STATUS_LABEL[status]}
        </span>
        <span style="color:#a3a3bd;font-size:0.85rem;margin-left:8px;">Mastery: {detail['mastery']:.0%}</span>
      </div>
    </div>
    """, unsafe_allow_html=True)

    if detail["prerequisite_details"]:
        st.markdown("**Prerequisites**")
        for p in detail["prerequisite_details"]:
            mark = "OK" if p["status"] == "mastered" else "!"
            st.markdown(
                f"<div style='padding:3px 0;font-size:0.85rem;'>[{mark}] {p['label']} — {p['mastery']:.0%}</div>",
                unsafe_allow_html=True,
            )

    if detail["recommendation"]:
        st.info(f"SAE recommends: {detail['recommendation']['reason']}")

    domain = canvas["domain"]
    col1, col2, col3 = st.columns(3)
    with col1:
        if st.button("Continue Lesson", key=f"canvas_lesson_{concept_id}", use_container_width=True):
            _jump_to_lesson(ss, concept_id, domain)
    with col2:
        if st.button("Ask SAE", key=f"canvas_ask_{concept_id}", use_container_width=True):
            _go_to_ask_sae(ss, concept_id)
    with col3:
        if st.button("Adaptive Tutor", key=f"canvas_tutor_{concept_id}", use_container_width=True):
            _go_to_adaptive_tutor(ss, concept_id)


def page_canvas() -> None:
    ss = st.session_state
    student_id = ss.get("student_id", "")
    domain = ss.get("domain", "")

    if not domain:
        st.markdown("""
        <div style="text-align:center;padding:3rem 1rem;">
          <div style="font-size:1.6rem;font-weight:800;color:#f2f2f8;">Welcome to SAE</div>
          <p style="color:#a3a3bd;margin-top:0.5rem;">
            Your learning map will build as you learn. Choose a domain to get started.
          </p>
        </div>
        """, unsafe_allow_html=True)
        if st.button("Choose a domain", type="primary"):
            ss["page"] = "domain_select"
            st.rerun()
        return

    current_module_id = ""
    roadmap = ss.get("roadmap")
    if roadmap:
        idx = ss.get("current_module_idx", 0)
        modules = roadmap.get("modules", [])
        if 0 <= idx < len(modules):
            current_module_id = modules[idx].get("module_id", "")

    # Override from Phase 11's Activity/notification routing (mirrors the
    # tutor_focus_concept_id mechanism Phase 8 already established) — lets
    # a notification focus any graph node, not just the current roadmap module.
    focus_override = ss.pop("canvas_focus_concept_id", None)
    if focus_override:
        current_module_id = focus_override

    from evaluation.learning_canvas import build_learning_canvas
    canvas = build_learning_canvas(student_id, domain, current_module_id=current_module_id)

    if canvas["insufficient_data"]:
        st.markdown(f"""
        <div style="text-align:center;padding:3rem 1rem;">
          <div style="font-size:1.4rem;font-weight:800;color:#f2f2f8;">Your {domain} map is empty so far</div>
          <p style="color:#a3a3bd;margin-top:0.5rem;">It will build automatically as you complete lessons.</p>
        </div>
        """, unsafe_allow_html=True)
        if st.button("Go to Roadmap", type="primary"):
            ss["page"] = "roadmap"
            st.rerun()
        return

    _render_hero(ss, canvas)

    view = st.radio(
        "View", ["Current module", "Full domain"], horizontal=True,
        label_visibility="collapsed", key="canvas_view_filter",
    )
    if view == "Current module" and current_module_id:
        current_node = next((n for n in canvas["nodes"] if n["id"] == current_module_id), None)
        # Show the current concept plus its direct neighbors (its own
        # prerequisites, and concepts that list it as a prerequisite) —
        # a one-hop neighborhood, not a full graph traversal.
        neighbor_ids = set(current_node["prerequisites"]) if current_node else set()
        neighbor_ids |= {n["id"] for n in canvas["nodes"] if current_module_id in n["prerequisites"]}
        visible_ids = {current_module_id} | neighbor_ids

        filtered_nodes = [n for n in canvas["nodes"] if n["id"] in visible_ids] or canvas["nodes"]
        filtered_canvas = {**canvas, "nodes": filtered_nodes,
                            "edges": [e for e in canvas["edges"]
                                      if e["source"] in visible_ids and e["target"] in visible_ids]}
    else:
        filtered_canvas = canvas

    selected_id = _render_graph(filtered_canvas, key_suffix=view.replace(" ", "_"))

    st.markdown(f"""
    <div style="display:flex;gap:1.2rem;font-size:0.75rem;font-weight:600;color:#c7c7de;margin:0.5rem 0 1rem;flex-wrap:wrap;">
      <span><span style="color:{_STATUS_COLOR['mastered']}">●</span> Mastered</span>
      <span><span style="color:{_STATUS_COLOR['developing']}">●</span> Developing</span>
      <span><span style="color:{_STATUS_COLOR['weak']}">●</span> Needs attention</span>
      <span><span style="color:{_STATUS_COLOR['available']}">●</span> Available</span>
      <span><span style="color:{_STATUS_COLOR['locked']}">●</span> Locked</span>
      <span style="color:#8888a3;">Thick ring = you are here &nbsp;|&nbsp; Orange edge = recommended path</span>
    </div>
    """, unsafe_allow_html=True)

    if selected_id:
        _render_concept_panel(ss, canvas, selected_id)
    elif current_module_id:
        _render_concept_panel(ss, canvas, current_module_id)

    if st.button("Reset to current position"):
        st.rerun()
