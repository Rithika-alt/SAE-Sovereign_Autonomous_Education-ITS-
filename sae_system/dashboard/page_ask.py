"""Ask SAE page — Phase 7.

A grounded Q&A box: student asks a question, SAE answers using cached
curriculum content for the current lesson (if any) plus a best-effort
ChromaDB lookup, and is honest when it has no grounding. See
docs/ASK_SAE_ARCHITECTURE.md for the full design rationale.
"""

from datetime import datetime

import streamlit as st

from agents.ask_sae_agent import MAX_QUESTION_CHARS


def _current_concept(ss):
    """Best-effort: derive (concept_id, domain) from the student's active
    roadmap module, mirroring how page_test/page_lesson read the same state.
    Returns ("", "") if no roadmap/module is currently selected.
    """
    roadmap = ss.get("roadmap")
    domain = ss.get("domain", "")
    if not roadmap or not domain:
        return "", ""
    idx = ss.get("current_module_idx", 0)
    modules = roadmap.get("modules", [])
    if 0 <= idx < len(modules):
        return modules[idx].get("module_id", ""), domain
    return "", domain


def _jump_to_lesson(ss, concept_id: str, domain: str) -> None:
    """Reuses the exact routing Phase 6 added (page_home._go_to_recommendation /
    app.py's home_target_module_id hand-off) rather than inventing a new path.
    """
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

    # Roadmap not loaded (or a different domain) — hand off via the Phase 6 mechanism.
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


def _render_answer(ss, result: dict, key_suffix: str = "", key_prefix: str = "ask_sae",
                   show_action: bool = True) -> None:
    """Render one answer. ``key_suffix`` must be unique per rendered answer on the page:
    the latest answer and every entry of "Earlier questions" are all rendered in one run,
    and Streamlit raises StreamlitDuplicateElementKey if two buttons share a key.
    """
    if result.get("error"):
        st.error(result["error"])
        return

    st.markdown(f"""
    <div style="background:rgba(255,255,255,0.045);backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px);border:2px solid rgba(124,110,245,0.13);border-radius:16px;
                padding:1.2rem;margin-top:0.8rem;">
      <div style="font-size:0.95rem;color:#f2f2f8;line-height:1.6;white-space:pre-wrap;">{result['answer']}</div>
    </div>
    """, unsafe_allow_html=True)

    if result["grounded"]:
        st.caption("✅ Grounded in: " + "; ".join(result["sources"]))
    else:
        st.caption("⚠️ General knowledge answer — not grounded in your curriculum "
                   "(no cached lesson or reference material found for this topic).")

    if result.get("mastery") is not None:
        st.caption(f"Your current mastery of this concept: {result['mastery']:.0%}")

    action = result.get("suggested_action")
    if action and show_action:
        if st.button(f"➡️ {action['label']}", key=f"{key_prefix}_continue_lesson_{key_suffix}"):
            _jump_to_lesson(ss, action["concept_id"], action["domain"])


def render_ask_panel(ss, concept_id: str, domain: str, key_prefix: str = "ask_sae", show_action: bool = True) -> None:
    """The question box and answers. Used by the Ask SAE page and embedded in the Adaptive Tutor page.

    ``key_prefix`` namespaces every widget key (two panels on one page must not collide) and
    ``show_action`` hides the "Continue this lesson" button where the host page already has one.
    """
    if concept_id:
        st.caption(f"Currently grounded in: **{concept_id.replace('_', ' ').title()}** ({domain})")

    question = st.text_area(
        "Your question",
        placeholder="e.g. \"I don't understand recursion\" or \"Why is my answer wrong?\"",
        max_chars=MAX_QUESTION_CHARS,
        label_visibility="collapsed",
        key=f"{key_prefix}_question_input",
    )

    if st.button("Ask", type="primary", key=f"{key_prefix}_submit"):
        if not question or not question.strip():
            st.warning("Please enter a question first.")
        else:
            with st.spinner("Thinking…"):
                try:
                    from agents.ask_sae_agent import AskSAEAgent
                    agent = AskSAEAgent()
                    result = agent.ask(
                        question,
                        student_id=ss.get("student_id", ""),
                        concept_id=concept_id,
                        domain=domain,
                    )
                except Exception as exc:
                    result = {"error": f"Ask SAE is unavailable: {exc}"}

            ss.setdefault("ask_sae_history", [])
            ss["ask_sae_history"].insert(0, {
                "question": question,
                "result": result,
                "timestamp": datetime.now().strftime("%H:%M"),
            })
            ss["ask_sae_history"] = ss["ask_sae_history"][:10]

    history = ss.get("ask_sae_history", [])
    if history:
        latest = history[0]
        st.markdown(f"**You asked:** {latest['question']}")
        _render_answer(ss, latest["result"], key_suffix="latest", key_prefix=key_prefix, show_action=show_action)

        if len(history) > 1:
            with st.expander(f"Earlier questions this session ({len(history) - 1})"):
                for i, item in enumerate(history[1:], start=1):
                    st.markdown(f"**{item['timestamp']} — {item['question']}**")
                    _render_answer(ss, item["result"], key_suffix=f"h{i}", key_prefix=key_prefix, show_action=show_action)
                    st.markdown("---")


def page_ask() -> None:
    ss = st.session_state

    st.markdown("""
    <div style="padding:0.5rem 0 0.3rem;">
      <div style="font-family:'Plus Jakarta Sans',sans-serif;font-size:1.6rem;
                  font-weight:800;color:#f2f2f8;">
        💬 Ask SAE
      </div>
      <p style="color:#a3a3bd;font-size:0.9rem;margin-top:2px;">
        Ask questions about what you're learning. SAE uses your curriculum and
        learning context to give grounded explanations — and tells you plainly
        when it can't.
      </p>
    </div>
    """, unsafe_allow_html=True)

    concept_id, domain = _current_concept(ss)
    render_ask_panel(ss, concept_id, domain)
