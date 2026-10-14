"""Adaptive Tutor page — Phase 8.

"Teach me based on what you know about my current understanding," as
distinct from Phase 7's Ask SAE ("answer my question"). See
docs/ADAPTIVE_TUTOR_ARCHITECTURE.md for the full design rationale.
"""

from datetime import datetime

import streamlit as st

from agents.adaptive_tutor_agent import (
    MODE_MASTERED_RETENTION,
    MODE_STRONG,
)


@st.cache_resource
def _get_adaptive_tutor():
    from agents.adaptive_tutor_agent import AdaptiveTutorAgent
    return AdaptiveTutorAgent()


def _focus_concept(ss):
    """Session-state override (set by "review prerequisite"/"next concept"
    buttons) takes priority; otherwise falls back to the current roadmap
    module — same convention page_ask.py's _current_concept uses.
    """
    override = ss.get("tutor_focus_concept_id")
    domain = ss.get("domain", "")
    if override and domain:
        return override, domain

    roadmap = ss.get("roadmap")
    if not roadmap or not domain:
        return "", ""
    idx = ss.get("current_module_idx", 0)
    modules = roadmap.get("modules", [])
    if 0 <= idx < len(modules):
        return modules[idx].get("module_id", ""), domain
    return "", domain


def _load_step(ss, concept_id: str, domain: str) -> None:
    """Run diagnosis -> strategy -> explanation -> question once per
    concept focus (not on every rerun/keystroke).
    """
    agent = _get_adaptive_tutor()
    from agents.adaptive_tutor_agent import diagnose_tutor_state, choose_teaching_strategy

    state = diagnose_tutor_state(ss.get("student_id", ""), concept_id, domain)
    strategy = choose_teaching_strategy(state)
    explanation = agent.explain(concept_id, domain, strategy)
    question = agent.generate_question(concept_id, domain, strategy)

    ss["tutor_state"] = state
    ss["tutor_strategy"] = strategy
    ss["tutor_explanation"] = explanation
    ss["tutor_question"] = question
    ss["tutor_feedback"] = None
    ss["tutor_loaded_for"] = (concept_id, domain)


def _jump_to_lesson(ss, concept_id: str, domain: str) -> None:
    """Reuses the exact routing Phase 6/7 established rather than a new mechanism."""
    roadmap = ss.get("roadmap")
    if roadmap and ss.get("domain") == domain:
        modules = roadmap.get("modules", [])
        match = next((i for i, m in enumerate(modules) if m["module_id"] == concept_id), None)
        if match is not None:
            from dashboard.state import make_session_defaults  # NOT dashboard.app: importing it re-runs the whole app
            _SS_DEFAULTS = make_session_defaults()
            ss["current_module_idx"]  = match
            ss["current_concept_idx"] = 0
            ss["lesson_section"]      = 0
            ss["lesson"]              = None
            ss["video_path"]          = ""
            ss["video_ready"]         = False
            ss["questions"]           = None
            ss["grade_result"]        = None
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
        ss["modules_passed"]   = saved["modules_passed"]
        ss["modules_unlocked"] = saved["modules_unlocked"]
        ss["module_progress"]  = saved["module_progress"]
    except Exception:
        ss["modules_passed"]   = set()
        ss["modules_unlocked"] = set()
        ss["module_progress"]  = {}
    ss["home_target_module_id"] = concept_id
    ss["page"] = "loading_roadmap"
    st.rerun()


def _render_explanation(explanation: dict) -> None:
    st.markdown(f"""
    <div style="background:rgba(255,255,255,0.045);backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px);border:2px solid rgba(124,110,245,0.13);border-radius:16px;
                padding:1.2rem;margin:0.6rem 0;">
      <div style="font-size:0.92rem;color:#f2f2f8;line-height:1.6;white-space:pre-wrap;">{explanation['content']}</div>
    </div>
    """, unsafe_allow_html=True)


def _render_feedback(ss, feedback: dict, concept_id: str, domain: str) -> None:
    label = feedback.get("label", "correct" if feedback["passed"] else "incorrect")
    if label == "correct":
        st.success(f"✅ Correct — {feedback['reason']}")
    elif label == "partial":
        st.warning(f"◐ Partially correct — {feedback['reason']}")
    else:
        st.error(f"✗ Needs improvement — {feedback['reason']}")

    st.caption(
        f"Mastery: {feedback['mastery_before']:.0%} → {feedback['mastery_after']:.0%} "
        f"(blended from this question's result, not a full overwrite)."
    )

    new_state_diag_button = st.button("🔁 Re-diagnose and continue", key="tutor_rediagnose")
    if new_state_diag_button:
        _load_step(ss, concept_id, domain)
        st.rerun()


def _render_next_actions(ss, state, concept_id: str, domain: str) -> None:
    cols = st.columns(3)
    with cols[0]:
        if st.button("🔄 Try another question", use_container_width=True, key="tutor_new_question"):
            _load_step(ss, concept_id, domain)
            st.rerun()

    with cols[1]:
        if state.weak_prerequisite:
            if st.button(
                f"⬅️ Review {state.weak_prerequisite.replace('_', ' ').title()}",
                use_container_width=True, key="tutor_review_prereq",
            ):
                ss["tutor_focus_concept_id"] = state.weak_prerequisite
                ss["tutor_state"] = None
                st.rerun()

    with cols[2]:
        if st.button("📖 Continue this lesson", use_container_width=True, key="tutor_continue_lesson"):
            _jump_to_lesson(ss, concept_id, domain)

    if state.mode in (MODE_STRONG, MODE_MASTERED_RETENTION):
        try:
            from memory.graph_engine import KnowledgeGraph
            graph = KnowledgeGraph(student_id=ss.get("student_id", ""))
            next_nodes = graph.get_next_recommended_nodes(concept_id)
        except Exception:
            next_nodes = []
        if next_nodes:
            next_id = next_nodes[0]
            if st.button(
                f"➡️ Move to next concept: {next_id.replace('_', ' ').title()}",
                key="tutor_next_concept",
            ):
                ss["tutor_focus_concept_id"] = next_id
                ss["tutor_state"] = None
                st.rerun()


def page_tutor() -> None:
    ss = st.session_state

    st.markdown("""
    <div style="padding:0.5rem 0 0.3rem;">
      <div style="font-family:'Plus Jakarta Sans',sans-serif;font-size:1.6rem;
                  font-weight:800;color:#f2f2f8;">
        🎓 Adaptive Tutor
      </div>
    </div>
    """, unsafe_allow_html=True)

    concept_id, domain = _focus_concept(ss)
    if not concept_id or not domain:
        st.info("Select a domain and start a roadmap module first — the Adaptive "
                "Tutor teaches whatever concept you're currently on.")
        if st.button("🌍 Go to Roadmap"):
            ss["page"] = "roadmap" if ss.get("roadmap") else "domain_select"
            st.rerun()
        return

    if ss.get("tutor_loaded_for") != (concept_id, domain) or ss.get("tutor_state") is None:
        with st.spinner("Diagnosing your current understanding…"):
            try:
                _load_step(ss, concept_id, domain)
            except Exception as exc:
                st.error(f"Adaptive Tutor is unavailable: {exc}")
                return

    state = ss["tutor_state"]
    strategy = ss["tutor_strategy"]
    explanation = ss["tutor_explanation"]
    question = ss["tutor_question"]

    st.markdown(f"""
    <div style="display:flex;justify-content:space-between;align-items:center;
                margin-bottom:0.4rem;">
      <div style="font-weight:800;font-size:1.1rem;color:#f2f2f8;">
        {concept_id.replace('_', ' ').title()}
      </div>
      <span style="background:rgba(124,110,245,0.13);color:#7c6ef5;font-size:0.75rem;font-weight:700;
                   padding:3px 12px;border-radius:20px;">
        {strategy.mode_label}
      </span>
    </div>
    """, unsafe_allow_html=True)
    st.caption(strategy.objective)

    if state.weak_prerequisite:
        prereq_reason = next((r for r in state.reasons if "Prerequisite" in r), None)
        if prereq_reason:
            st.info(f"💡 {prereq_reason}")

    _render_explanation(explanation)

    st.markdown(f"**Question:** {question['question']}")
    if strategy.hints_enabled:
        st.caption("💡 Hints are available — take your time and think it through step by step.")

    answer = st.text_area("Your answer", key="tutor_answer_input", label_visibility="collapsed")

    if st.button("Submit Answer", type="primary", key="tutor_submit_answer"):
        if not answer or not answer.strip():
            st.warning("Please enter an answer first.")
        else:
            with st.spinner("Evaluating…"):
                agent = _get_adaptive_tutor()
                feedback = agent.evaluate_and_update(
                    ss.get("student_id", ""), concept_id, domain,
                    question["question"], question["correct_answer"], answer,
                )
            ss["tutor_feedback"] = feedback

    if ss.get("tutor_feedback"):
        _render_feedback(ss, ss["tutor_feedback"], concept_id, domain)

    st.markdown("<div style='height:0.8rem'></div>", unsafe_allow_html=True)
    _render_next_actions(ss, state, concept_id, domain)

    # Ask a question: the former Ask SAE page now lives here, beneath the tutor, grounded in this
    # same concept. Its own "Continue this lesson" button is hidden (the row above already has one),
    # and its widget keys are namespaced so they never collide with the tutor's.
    from dashboard.page_ask import render_ask_panel

    st.markdown("<div style='height:1.4rem'></div>", unsafe_allow_html=True)
    st.markdown("---")
    st.markdown("#### Ask a question")
    st.caption("Stuck on something? Ask here — answers come from this lesson's material, and SAE says so "
               "when it has to answer from general knowledge.")
    render_ask_panel(ss, concept_id, domain, key_prefix="tutor_ask", show_action=False)
