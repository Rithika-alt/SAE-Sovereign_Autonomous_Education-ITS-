"""Activity Timeline + Notifications — Phase 11.

Full view of evaluation/activity_feed.py's output. Notifications route into
Canvas/Lesson/Ask SAE/Adaptive Tutor via the exact same session-state
mechanisms page_canvas.py already established (Phase 10) — no new routing.
"""

from datetime import datetime

import streamlit as st

_PRIORITY_COLOR = {"high": "#f87171", "medium": "#fbbf24", "low": "#8888a3"}


def _jump_to_lesson(ss, concept_id: str, domain: str) -> None:
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


def _go_to_canvas(ss, concept_id: str) -> None:
    ss["canvas_focus_concept_id"] = concept_id
    ss["page"] = "canvas"
    st.rerun()


def _render_notification(ss, note: dict) -> None:
    color = _PRIORITY_COLOR.get(note["priority"], "#8888a3")
    dismissed = ss.setdefault("dismissed_notifications", set())
    key = f"{note['type']}::{note['concept_id']}"
    if key in dismissed:
        return

    st.markdown(f"""
    <div style="background:rgba(255,255,255,0.045);backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px);border:2px solid {color}33;border-radius:14px;
                padding:0.9rem 1.1rem;margin-bottom:0.6rem;">
      <div style="font-weight:700;color:#f2f2f8;">{note['title']}</div>
      <div style="color:#a3a3bd;font-size:0.85rem;margin-top:2px;">{note['message']}</div>
    </div>
    """, unsafe_allow_html=True)

    domain = note.get("domain") or ss.get("domain", "")
    concept_id = note["concept_id"]
    cols = st.columns(5)
    with cols[0]:
        if st.button("Canvas", key=f"note_canvas_{key}", use_container_width=True):
            _go_to_canvas(ss, concept_id)
    with cols[1]:
        if st.button("Lesson", key=f"note_lesson_{key}", use_container_width=True):
            _jump_to_lesson(ss, concept_id, domain)
    with cols[2]:
        if st.button("Ask SAE", key=f"note_ask_{key}", use_container_width=True):
            _go_to_ask_sae(ss, concept_id)
    with cols[3]:
        if st.button("Tutor", key=f"note_tutor_{key}", use_container_width=True):
            _go_to_adaptive_tutor(ss, concept_id)
    with cols[4]:
        if st.button("Dismiss", key=f"note_dismiss_{key}", use_container_width=True):
            dismissed.add(key)
            st.rerun()


def page_activity() -> None:
    ss = st.session_state
    student_id = ss.get("student_id", "")
    domain = ss.get("domain", "")

    st.markdown("""
    <div style="padding:0.5rem 0 0.8rem;">
      <div style="font-family:'Plus Jakarta Sans',sans-serif;font-size:1.6rem;font-weight:800;color:#f2f2f8;">
        📅 Activity & Notifications
      </div>
    </div>
    """, unsafe_allow_html=True)

    try:
        from evaluation.activity_feed import build_activity_timeline, build_notifications
        notifications = build_notifications(student_id, domain or None)
        timeline = build_activity_timeline(student_id, domain or None, limit=50)
    except Exception as exc:
        st.error(f"Could not load activity: {exc}")
        return

    tab_notify, tab_timeline = st.tabs(["🔔 Notifications", "🕒 Timeline"])

    with tab_notify:
        if not notifications:
            st.info("Nothing needs your attention right now.")
        else:
            for note in notifications:
                _render_notification(ss, note)

    with tab_timeline:
        if not timeline:
            st.info("No activity recorded yet — it will appear here as you learn.")
        else:
            for e in timeline:
                ts = e["timestamp"][:19].replace("T", " ")
                st.markdown(
                    f"<div style='padding:6px 0;border-bottom:1px solid rgba(255,255,255,0.10);'>"
                    f"<span style='color:#8888a3;font-size:0.75rem;'>{ts}</span><br>"
                    f"{e['icon']} <b>{e['title']}</b>"
                    f"{' — ' + e['detail'] if e['detail'] else ''}</div>",
                    unsafe_allow_html=True,
                )
