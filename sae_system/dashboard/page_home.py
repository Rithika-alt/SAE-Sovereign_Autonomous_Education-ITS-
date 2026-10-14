"""Home / Learning Command Center — Phase 6.1.

The post-login landing page for a returning student (one with at least one
enrolled domain). Answers "what should I do next?" using real data from
KnowledgeGraph, XPEngine, and evaluation.recommendation_engine — never
fabricated. A brand-new student with no progress still lands on
page_domain_select (see app.py's login routing) since there is nothing
meaningful to show here yet.
"""

from datetime import datetime

import streamlit as st


def _metric_card(col, label: str, value: str, color: str) -> None:
    col.markdown(f"""
    <div style="background:rgba(255,255,255,0.045);backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px);border-radius:14px;padding:1rem;text-align:center;
                border:2px solid {color}22;box-shadow:0 2px 8px rgba(0,0,0,0.04);">
      <div style="font-size:1.6rem;font-weight:800;color:{color};">{value}</div>
      <div style="font-size:0.75rem;color:#a3a3bd;font-weight:600;margin-top:2px;">{label}</div>
    </div>
    """, unsafe_allow_html=True)


def _greeting() -> str:
    hour = datetime.now().hour
    if hour < 12:
        return "Good morning"
    if hour < 18:
        return "Good afternoon"
    return "Good evening"


def _go_to_recommendation(ss, rec: dict) -> None:
    """Route a recommendation card's action button through the existing
    domain-select → loading_roadmap flow, reusing the exact state-population
    logic page_domain_select's "Start" button uses (see app.py).
    """
    if rec["action"] == "start_domain":
        ss["page"] = "domain_select"
        st.rerun()
        return

    domain = rec["domain"]
    ss["domain"] = domain
    ss["session_start"] = datetime.now()
    ss["roadmap"] = None
    try:
        from persistence.progress_store import load_progress
        saved = load_progress(ss.get("student_id", ""), domain)
        ss["modules_passed"]   = saved["modules_passed"]
        ss["modules_unlocked"] = saved["modules_unlocked"]
        ss["module_progress"]  = saved["module_progress"]
    except Exception:
        ss["modules_passed"]   = set()
        ss["modules_unlocked"] = set()
        ss["module_progress"]  = {}

    if rec.get("concept_id"):
        ss["home_target_module_id"] = rec["concept_id"]

    ss["page"] = "loading_roadmap"
    st.rerun()


def _render_recommendation_card(ss, rec: dict) -> None:
    priority_color = {"high": "#f87171", "medium": "#fbbf24", "low": "#8888a3"}.get(
        rec["priority"], "#8888a3"
    )
    label = rec.get("concept_label") or "Get started"
    st.markdown(f"""
    <div style="background:rgba(255,255,255,0.045);backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px);border:2px solid {priority_color}33;border-radius:16px;
                padding:1rem 1.2rem;margin-bottom:0.6rem;">
      <div style="display:flex;justify-content:space-between;align-items:center;">
        <div style="font-weight:800;font-size:1.05rem;color:#f2f2f8;">{label}</div>
        <span style="background:{priority_color}22;color:{priority_color};font-size:0.7rem;
                     font-weight:700;padding:2px 10px;border-radius:20px;text-transform:uppercase;">
          {rec['priority']}
        </span>
      </div>
      <div style="color:#a3a3bd;font-size:0.85rem;margin-top:4px;">{rec['reason']}</div>
    </div>
    """, unsafe_allow_html=True)
    if st.button(rec["cta_label"], key=f"rec_{rec['action']}_{rec.get('concept_id')}", use_container_width=True):
        _go_to_recommendation(ss, rec)


def _repair_missing_enrolment(ss) -> None:
    """A student who chose a domain before enrolment was saved at roadmap load has a
    domain (and usually a roadmap) in session state but no saved record, so Home
    would say "You haven't started a learning domain yet". Write the record from the
    session. Never overwrites an existing one; does nothing if no domain is chosen.
    """
    student_id, domain = ss.get("student_id", ""), ss.get("domain", "")
    if not (student_id and domain):
        return
    unlocked = set(ss.get("modules_unlocked") or ())
    roadmap = ss.get("roadmap") or {}
    if not unlocked and roadmap.get("modules") and (roadmap.get("domain") or "").lower() == domain.lower():
        unlocked = {roadmap["modules"][0]["module_id"]}        # same rule loading_roadmap applies
        ss["modules_unlocked"] = set(unlocked)
    try:
        from persistence.progress_store import ensure_enrolled
        ensure_enrolled(student_id, domain, ss.get("modules_passed") or (), unlocked, ss.get("module_progress") or {})
    except Exception:
        pass


def page_home() -> None:
    ss = st.session_state
    student_id = ss.get("student_id", "")
    _repair_missing_enrolment(ss)
    name = ss.get("student_name", "").split()[0] if ss.get("student_name") else "there"

    st.markdown(f"""
    <div style="padding:0.5rem 0 1rem;">
      <div style="font-family:'Plus Jakarta Sans',sans-serif;font-size:1.8rem;
                  font-weight:800;color:#f2f2f8;">
        {_greeting()}, {name} 👋
      </div>
    </div>
    """, unsafe_allow_html=True)

    with st.spinner("Loading your learning status…"):
        try:
            from evaluation.system_evaluator import evaluate_learning_outcomes, evaluate_engagement
            learning = evaluate_learning_outcomes(student_id)
            engagement = evaluate_engagement(student_id)
            from evaluation.recommendation_engine import recommend_next_actions
            recommendations = recommend_next_actions(student_id, max_recommendations=3)
        except Exception as exc:
            st.error(f"Could not load your learning status: {exc}")
            return

    total = learning["total_concepts"]
    mastery_pct = round(learning["mastered"] / total * 100) if total else 0
    xp = engagement["xp"]

    st.markdown("**Your Learning Status**")
    c1, c2, c3, c4 = st.columns(4)
    _metric_card(c1, "Mastery", f"{mastery_pct}%", "#7c6ef5")
    _metric_card(c2, "Streak", f"{xp['streak']}d", "#fbbf24")
    _metric_card(c3, "Level", xp["level"], "#4ade80")
    _metric_card(c4, "XP", str(xp["total_xp"]), "#7c6ef5")

    st.markdown("<div style='height:1.2rem'></div>", unsafe_allow_html=True)

    st.markdown("### Recommended for you")
    if not recommendations:
        st.info("No recommendations right now — you're all caught up! Check the Roadmap to keep going.")
    else:
        for rec in recommendations:
            _render_recommendation_card(ss, rec)

    st.markdown("<div style='height:1rem'></div>", unsafe_allow_html=True)

    domain = ss.get("domain", "")
    try:
        from evaluation.activity_feed import build_activity_timeline
        recent = build_activity_timeline(student_id, domain or None, limit=3)
    except Exception:
        recent = []
    if recent:
        st.markdown("**Recent activity**")
        for e in recent:
            st.markdown(
                f"<div style='padding:3px 0;font-size:0.85rem;color:#c7c7de;'>"
                f"{e['icon']} {e['title']}{' — ' + e['detail'] if e['detail'] else ''}</div>",
                unsafe_allow_html=True,
            )
        st.markdown("<div style='height:1rem'></div>", unsafe_allow_html=True)

    col_w, col_s = st.columns(2)
    with col_w:
        st.markdown("**Needs attention**")
        if learning["weakest_concepts"]:
            for c in learning["weakest_concepts"]:
                st.markdown(
                    f"<div style='border-left:3px solid #f87171;padding:4px 10px;margin-bottom:4px;'>"
                    f"{c['concept_id'].replace('_', ' ').title()} — {c['mastery']:.0%}</div>",
                    unsafe_allow_html=True,
                )
        else:
            st.caption("Not enough data yet.")
    with col_s:
        st.markdown("**Strengths**")
        if learning["strongest_concepts"]:
            for c in learning["strongest_concepts"]:
                st.markdown(
                    f"<div style='border-left:3px solid #4ade80;padding:4px 10px;margin-bottom:4px;'>"
                    f"{c['concept_id'].replace('_', ' ').title()} — {c['mastery']:.0%}</div>",
                    unsafe_allow_html=True,
                )
        else:
            st.caption("Not enough data yet.")

    st.markdown("<div style='height:1rem'></div>", unsafe_allow_html=True)
    col_a, col_b, col_c = st.columns(3)
    with col_a:
        if st.button("🧠 Explore Knowledge Graph", use_container_width=True):
            ss["page"] = "knowledge_graph"
            st.rerun()
    with col_b:
        if st.button("💬 Ask a question", use_container_width=True):
            ss["page"] = "tutor"          # the question box lives on the Adaptive Tutor page
            st.rerun()
    with col_c:
        if st.button("🌍 Explore a new domain", use_container_width=True):
            ss["page"] = "domain_select"
            st.rerun()
