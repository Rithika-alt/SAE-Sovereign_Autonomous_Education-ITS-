"""Stress relief / Recharge page for the SAE System dashboard."""

from pathlib import Path
from typing import Optional
import time

import plotly.graph_objects as go
import streamlit as st

from dashboard.stress_manager import StressReliefManager

_STATIC = Path(__file__).parent / "static"
_HEROES_HTML  = _STATIC / "heroes_scene.html"
_BREATHE_HTML = _STATIC / "breathing_animation.html"

_POMODORO_WORK  = 25 * 60   # seconds
_POMODORO_SHORT =  5 * 60
_POMODORO_LONG  = 15 * 60

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read_html(path: Path) -> str:
    if path.exists():
        return path.read_text(encoding="utf-8")
    return "<p style='color:#ef4444'>Scene file not found.</p>"


def _fmt_seconds(s: int) -> str:
    m, sec = divmod(max(0, s), 60)
    return f"{m:02d}:{sec:02d}"


def _session_gauge(elapsed_min: float, work_min: int = 25) -> go.Figure:
    pct = min(100.0, elapsed_min / work_min * 100)
    color = "#22c55e" if pct < 60 else ("#f59e0b" if pct < 90 else "#ef4444")
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=round(pct, 1),
        number={"suffix": "%", "font": {"size": 28, "color": "#e2e8f0"}},
        title={"text": "Focus Session Used", "font": {"size": 13, "color": "#94a3b8"}},
        gauge={
            "axis": {"range": [0, 100], "tickcolor": "#334155"},
            "bar": {"color": color},
            "bgcolor": "#1e293b",
            "bordercolor": "#334155",
            "steps": [
                {"range": [0, 60],  "color": "#052e16"},
                {"range": [60, 90], "color": "#431407"},
                {"range": [90, 100],"color": "#450a0a"},
            ],
        },
    ))
    fig.update_layout(
        paper_bgcolor="#0f172a",
        height=200,
        margin=dict(l=20, r=20, t=30, b=10),
    )
    return fig


# ---------------------------------------------------------------------------
# Curiosity card
# ---------------------------------------------------------------------------

def _render_curiosity_card(domain: str, concept: str) -> None:
    ss = st.session_state

    if "shown_facts" not in ss:
        ss["shown_facts"] = []
    if "current_fact" not in ss:
        ss["current_fact"] = ""

    st.markdown("### 💡 Curiosity Card")

    if st.button("✨ Give me a fun fact!", use_container_width=True, type="primary"):
        mgr: Optional[StressReliefManager] = ss.get("stress_mgr")
        if mgr is None:
            try:
                mgr = StressReliefManager()
                ss["stress_mgr"] = mgr
            except Exception as exc:
                st.error(f"Could not load StressReliefManager: {exc}")
                return
        with st.spinner("Fetching curiosity…"):
            fact = mgr.get_curiosity_card(domain, concept, ss["shown_facts"])
        ss["current_fact"] = fact
        ss["shown_facts"].append(fact)

    if ss.get("current_fact"):
        st.markdown(
            f"""
            <div style='
                background: linear-gradient(135deg,#1e293b,#0f172a);
                border: 1.5px solid #7c3aed;
                border-radius: 14px;
                padding: 20px 22px;
                margin-top: 10px;
                font-size: 0.97rem;
                color: #e2e8f0;
                line-height: 1.6;
                box-shadow: 0 4px 24px rgba(124,58,237,0.18);
            '>
            🔮 {ss["current_fact"]}
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.caption(f"Facts shown this session: {len(ss['shown_facts'])}")


# ---------------------------------------------------------------------------
# Pomodoro timer
# ---------------------------------------------------------------------------

def _render_pomodoro() -> None:
    ss = st.session_state

    if "pomo_mode" not in ss:
        ss["pomo_mode"] = "work"
    if "pomo_start" not in ss:
        ss["pomo_start"] = None
    if "pomo_paused_at" not in ss:
        ss["pomo_paused_at"] = None
    if "pomo_elapsed" not in ss:
        ss["pomo_elapsed"] = 0

    mode_durations = {
        "work":  _POMODORO_WORK,
        "short": _POMODORO_SHORT,
        "long":  _POMODORO_LONG,
    }
    duration = mode_durations[ss["pomo_mode"]]

    # Compute remaining
    if ss["pomo_start"] is not None:
        running_elapsed = time.time() - ss["pomo_start"] + ss["pomo_elapsed"]
    else:
        running_elapsed = ss["pomo_elapsed"]

    remaining = max(0, duration - running_elapsed)
    is_running = ss["pomo_start"] is not None

    # Auto-refresh every second while timer is running so the countdown updates live
    if is_running:
        from streamlit_autorefresh import st_autorefresh
        st_autorefresh(interval=1000, limit=None, key="pomodoro_tick")

    st.markdown("### ⏱ Pomodoro Timer")

    # Mode selector
    mode_col1, mode_col2, mode_col3 = st.columns(3)
    with mode_col1:
        if st.button("🎯 Focus (25m)", use_container_width=True,
                     type="primary" if ss["pomo_mode"] == "work" else "secondary"):
            ss["pomo_mode"]    = "work"
            ss["pomo_start"]   = None
            ss["pomo_elapsed"] = 0
    with mode_col2:
        if st.button("☕ Short (5m)", use_container_width=True,
                     type="primary" if ss["pomo_mode"] == "short" else "secondary"):
            ss["pomo_mode"]    = "short"
            ss["pomo_start"]   = None
            ss["pomo_elapsed"] = 0
    with mode_col3:
        if st.button("🧘 Long (15m)", use_container_width=True,
                     type="primary" if ss["pomo_mode"] == "long" else "secondary"):
            ss["pomo_mode"]    = "long"
            ss["pomo_start"]   = None
            ss["pomo_elapsed"] = 0

    # Big timer display
    pct = (1 - remaining / duration) * 100 if duration > 0 else 0
    timer_color = "#22c55e" if ss["pomo_mode"] == "work" else "#f59e0b"
    st.markdown(
        f"""
        <div style='text-align:center;padding:24px 0'>
            <div style='font-size:3.2rem;font-weight:800;color:{timer_color};
                        font-variant-numeric:tabular-nums;letter-spacing:0.05em'>
                {_fmt_seconds(int(remaining))}
            </div>
            <div style='color:#64748b;font-size:0.8rem;margin-top:4px'>
                {"Focus time" if ss["pomo_mode"]=="work" else "Break time"}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.progress(pct / 100)

    ctrl1, ctrl2 = st.columns(2)
    with ctrl1:
        if is_running:
            if st.button("⏸ Pause", use_container_width=True):
                ss["pomo_elapsed"] += time.time() - ss["pomo_start"]
                ss["pomo_start"]   = None
        else:
            if st.button("▶ Start", use_container_width=True, type="primary"):
                ss["pomo_start"] = time.time()
    with ctrl2:
        if st.button("↺ Reset", use_container_width=True):
            ss["pomo_start"]   = None
            ss["pomo_elapsed"] = 0

    if remaining == 0 and (is_running or ss["pomo_elapsed"] > 0):
        st.success("✅ Timer complete! Time to switch modes.")

    return running_elapsed / 60  # elapsed minutes (for gauge)


# ---------------------------------------------------------------------------
# Public page
# ---------------------------------------------------------------------------

def render_stress_relief_page(domain: str = "Learning", concept: str = "the current topic") -> None:
    """Render the full Recharge / stress-relief page.

    Args:
        domain:  Current study domain (passed from main app session state).
        concept: Current concept being studied.
    """
    st.markdown(
        "<h2 style='color:#7c3aed'>🧘 Recharge Station</h2>",
        unsafe_allow_html=True,
    )
    st.caption("Take a mindful break. Your brain will thank you.")

    # ── Heroes scene ────────────────────────────────────────────────────────
    with st.expander("🦸 Study Buddies (click anywhere on the scene!)", expanded=True):
        heroes_html = _read_html(_HEROES_HTML)
        st.html(heroes_html)

    st.divider()

    # ── Two-column layout ────────────────────────────────────────────────────
    left, right = st.columns([1, 1], gap="large")

    with left:
        elapsed_min = _render_pomodoro()
        st.divider()
        st.plotly_chart(_session_gauge(elapsed_min), use_container_width=True)

    with right:
        # Breathing animation
        st.markdown("### 🫁 Box Breathing (4-4-4-2)")
        breathe_html = _read_html(_BREATHE_HTML)
        st.html(breathe_html)

    st.divider()

    # ── Curiosity card ───────────────────────────────────────────────────────
    _render_curiosity_card(domain, concept)
