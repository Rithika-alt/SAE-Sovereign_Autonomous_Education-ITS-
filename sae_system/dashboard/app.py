"""Streamlit dashboard for the Sovereign Autonomous Education (SAE) System.

Page flow:
  domain_select → loading_roadmap → roadmap → lesson → test → results → certificate
  Any page → stress_relief (Recharge) → back
"""

import os
import sys
import time
import warnings
from datetime import datetime
from html import escape as _esc  # LLM-written text goes into HTML: always escape it
from pathlib import Path

_PERF_T0 = time.perf_counter()  # start of this script run — see evaluation/perf_trace.py

# Suppress noisy __path__ deprecation warnings from transformers' lazy-loader
warnings.filterwarnings("ignore", message=r"Accessing `__path__`", category=UserWarning)
from typing import Optional

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from evaluation import perf_trace as _perf

_PERF_RUN = _perf.begin_rerun(started=_PERF_T0)

import streamlit as st
from dotenv import load_dotenv

load_dotenv()

st.set_page_config(
    page_title="SAE System",
    page_icon="🎓",
    layout="wide",
    initial_sidebar_state="expanded",
)
_perf.checkpoint("startup")  # script start -> here: imports, dotenv, set_page_config

# ---------------------------------------------------------------------------
# Global CSS — dark theme (glassmorphism + gradient accents)
# ---------------------------------------------------------------------------
#
# Centralizes the palette other pages should reference (see dashboard/theme.py
# for the same constants as Python values, used by pages that build their own
# inline-styled HTML rather than these shared classes). Streamlit's own
# widgets (buttons, inputs, sidebar, tabs) are themed once here and inherit
# everywhere automatically since every page renders inside this one script.

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap');

:root {
  --font-body:      'Inter', sans-serif;
  --font-heading:   'Plus Jakarta Sans', sans-serif;

  --bg-void:        #0a0a0f;   /* deep background */
  --bg-surface:     rgba(255,255,255,0.045);   /* glass card fill */
  --bg-surface-hi:  rgba(255,255,255,0.08);    /* hovered/elevated glass */
  --border-glass:   rgba(255,255,255,0.10);
  --border-glass-hi:rgba(255,255,255,0.20);

  --text-primary:   #f2f2f8;
  --text-secondary: #a3a3bd;
  --text-muted:     #6f6f8c;

  --accent-1:       #7c6ef5;   /* purple */
  --accent-2:       #38bdf8;   /* cyan/blue */
  --gradient-1:     linear-gradient(135deg, #7c6ef5 0%, #38bdf8 100%);
  --glow-1:         rgba(124,110,245,0.45);

  --fw-base:        500;
}

/* Global reset — every element inherits base type */
.stApp,
.stApp * {
  font-family: var(--font-body) !important;
  font-weight: var(--fw-base) !important;
  -webkit-font-smoothing: antialiased;
}

/* Default text colour. An element that sets its OWN colour inline (status dots, mastery
   labels, difficulty badges, ...) must keep it: a stylesheet !important beats an inline
   style, so the old unconditional `color: ... !important` painted all of them white.
   `[style*="color"]` also exempts gradient text (-webkit-text-fill-color), which is fine. */
.stApp,
.stApp *:not([style*="color"]) {
  color: var(--text-primary) !important;
}

.stApp h1, .stApp h2, .stApp h3,
.stApp h4, .stApp h5, .stApp h6 {
  font-family: var(--font-heading) !important;
  font-weight: 800 !important;
  color: var(--text-primary) !important;
}

.stApp p, .stApp li, .stApp span,
.stMarkdown p, .stMarkdown li, .stMarkdown span {
  font-family: var(--font-body) !important;
  font-weight: var(--fw-base) !important;
  line-height: 1.7 !important;
}
.stApp p:not([style*="color"]), .stApp li:not([style*="color"]), .stApp span:not([style*="color"]),
.stMarkdown p:not([style*="color"]), .stMarkdown li:not([style*="color"]), .stMarkdown span:not([style*="color"]) {
  color: var(--text-primary) !important;
}

.stApp small, .stCaption, .stCaption * {
  color: var(--text-secondary) !important;
  font-weight: 500 !important;
}

.stApp code {
  font-family: 'JetBrains Mono', 'Fira Code', monospace !important;
  font-weight: 500 !important;
  color: #d8b4fe !important;
  background: rgba(124,110,245,0.15) !important;
  padding: 1px 4px !important;
  border-radius: 4px !important;
}

.stApp pre,
.stMarkdown pre,
div[data-testid="stMarkdownContainer"] pre {
  background: #05050a !important;
  border: 1px solid var(--border-glass) !important;
  border-radius: 10px !important;
  padding: 16px !important;
}
.stApp pre code,
.stMarkdown pre code,
div[data-testid="stMarkdownContainer"] pre code {
  font-family: 'JetBrains Mono', 'Fira Code', monospace !important;
  font-weight: 400 !important;
  color: #cdd6f4 !important;
  background: transparent !important;
  padding: 0 !important;
  font-size: 0.88rem !important;
  line-height: 1.6 !important;
}

/* ═══ Deep dark background + slow-drifting gradient mesh (pure CSS, no JS/
   particle library — zero new dependency, browser-rendered so no console-
   encoding concerns) ═══ */
.stApp {
  background: var(--bg-void) !important;
  position: relative;
}
.stApp::before {
  content: "";
  position: fixed;
  inset: 0;
  z-index: 0;
  pointer-events: none;
  background:
    radial-gradient(ellipse 900px 600px at 15% 10%, rgba(124,110,245,0.16), transparent 60%),
    radial-gradient(ellipse 900px 700px at 85% 25%, rgba(56,189,248,0.14), transparent 60%),
    radial-gradient(ellipse 800px 800px at 50% 95%, rgba(124,110,245,0.10), transparent 60%);
  background-repeat: no-repeat;
  animation: mesh-drift 22s ease-in-out infinite alternate;
}
@keyframes mesh-drift {
  0%   { background-position: 0% 0%, 100% 0%, 50% 100%; }
  100% { background-position: 8% 6%, 92% 10%, 55% 92%; }
}
.stApp > * { position: relative; z-index: 1; }

[data-testid="stHeader"] { background: transparent !important; }

section[data-testid="stSidebar"] {
  background: linear-gradient(180deg, #0d0d16 0%, #0a0a0f 100%) !important;
  border-right: 1px solid var(--border-glass) !important;
}
section[data-testid="stSidebar"] *:not([style*="color"]) {
  color: var(--text-primary) !important;
}

::-webkit-scrollbar { width: 10px; height: 10px; }
::-webkit-scrollbar-track { background: var(--bg-void); }
::-webkit-scrollbar-thumb { background: var(--border-glass-hi); border-radius: 10px; }
::-webkit-scrollbar-thumb:hover { background: var(--accent-1); }

.sae-card {
  background: var(--bg-surface); border-radius: 16px; padding: 1.5rem; margin: 0.6rem 0;
  border: 1px solid var(--border-glass); backdrop-filter: blur(14px);
  -webkit-backdrop-filter: blur(14px);
  box-shadow: 0 4px 24px rgba(0,0,0,0.35);
  transition: box-shadow 0.25s, transform 0.25s, border-color 0.25s;
}
.sae-card:hover {
  box-shadow: 0 10px 32px var(--glow-1); transform: translateY(-2px);
  border-color: var(--border-glass-hi);
}
.card-purple {
  background: var(--gradient-1);
  color: white; border-radius: 16px; padding: 1.5rem; border: none;
  box-shadow: 0 8px 28px var(--glow-1);
}

.badge { display:inline-block; padding:3px 12px; border-radius:20px;
  font-size:0.72rem; font-weight:600; letter-spacing:0.3px; }
.badge-beginner     { background:rgba(34,197,94,0.18); color:#4ade80; }
.badge-intermediate { background:rgba(56,189,248,0.18); color:#7dd3fc; }
.badge-advanced     { background:rgba(244,114,182,0.18); color:#f9a8d4; }
.badge-purple       { background:rgba(124,110,245,0.18); color:#c4b5fd; }

.progress-wrap {
  background: rgba(255,255,255,0.06); border-radius:99px; height:10px; overflow:hidden; margin:6px 0;
}
.progress-fill {
  height:100%; border-radius:99px;
  background: var(--gradient-1);
  box-shadow: 0 0 12px var(--glow-1);
  transition:width 0.6s cubic-bezier(0.4,0,0.2,1);
}

.timeline-dot {
  width:44px; height:44px; border-radius:50%; display:flex;
  align-items:center; justify-content:center; font-weight:700;
  font-size:0.85rem; flex-shrink:0;
}
.dot-done    { background:rgba(34,197,94,0.18); color:#4ade80; }
.dot-active  { background: var(--gradient-1); color:white;
               box-shadow:0 4px 18px var(--glow-1); }
.dot-locked  { background: rgba(255,255,255,0.06); color: var(--text-muted); }

.concept-tag {
  display:inline-block; background:rgba(124,110,245,0.16); color:#c4b5fd;
  padding:3px 10px; border-radius:12px; font-size:0.72rem; font-weight:500; margin:2px;
  border: 1px solid rgba(124,110,245,0.25);
}

.metric-card {
  background: var(--bg-surface); border-radius:14px; padding:1.2rem; text-align:center;
  border: 1px solid var(--border-glass); backdrop-filter: blur(14px);
  -webkit-backdrop-filter: blur(14px);
  box-shadow: 0 4px 20px rgba(0,0,0,0.3);
  transition: box-shadow 0.25s, transform 0.25s;
}
.metric-card:hover { box-shadow: 0 8px 28px var(--glow-1); transform: translateY(-2px); }
.metric-value {
  font-size:2rem; font-weight:700; font-family:'Plus Jakarta Sans',sans-serif;
  color: var(--text-primary);
  text-shadow: 0 0 18px var(--glow-1);
}
.metric-label { font-size:0.78rem; color: var(--text-secondary); margin-top:4px; font-weight:500; }

.warning-banner {
  background: rgba(248,113,113,0.12); border:2px solid rgba(248,113,113,0.5); border-radius:12px;
  padding:1rem 1.2rem; color:#fca5a5; font-weight:600; text-align:center;
  animation:pulse-warning 2s ease-in-out infinite;
}
@keyframes pulse-warning {
  0%,100% { box-shadow:0 0 0 0 rgba(248,113,113,0.4); }
  50%      { box-shadow:0 0 0 8px rgba(248,113,113,0); }
}

.stButton > button {
  background: var(--gradient-1) !important;
  color: white !important; border: 1px solid rgba(255,255,255,0.15) !important;
  border-radius: 12px !important;
  font-family: 'Plus Jakarta Sans', sans-serif !important; font-weight: 600 !important;
  font-size: 0.85rem !important; padding: 0.5rem 1.2rem !important;
  transition: all 0.25s !important;
  box-shadow: 0 4px 16px var(--glow-1) !important;
}
.stButton > button:hover {
  transform: translateY(-2px) !important;
  box-shadow: 0 8px 28px var(--glow-1), 0 0 0 1px rgba(255,255,255,0.2) inset !important;
  filter: brightness(1.1) !important;
}
.stButton > button:active { transform: translateY(0) !important; }
.stButton > button p { color: white !important; }

.stTextInput > div > div > input,
.stTextArea > div > div > textarea {
  border-radius: 12px !important; border: 1px solid var(--border-glass) !important;
  background: rgba(255,255,255,0.04) !important; font-family: var(--font-body) !important;
  font-size: 0.9rem !important; font-weight: 500 !important;
  color: var(--text-primary) !important; transition: border-color 0.25s, box-shadow 0.25s !important;
}
.stTextInput > div > div > input:focus,
.stTextArea > div > div > textarea:focus {
  border-color: var(--accent-1) !important;
  box-shadow: 0 0 0 3px var(--glow-1) !important;
}
.stSelectbox > div > div {
  border-radius:12px !important; border:1px solid var(--border-glass) !important;
  background: rgba(255,255,255,0.04) !important;
}

.stRadio > div { gap: 0.5rem !important; }
.stRadio > div > label {
  background: var(--bg-surface) !important;
  border: 1px solid var(--border-glass) !important;
  border-radius: 12px !important;
  padding: 0.65rem 1.1rem !important;
  transition: all 0.25s !important;
  cursor: pointer !important;
}
.stRadio > div > label,
.stRadio > div > label p,
.stRadio > div > label span {
  color: var(--text-primary) !important;
  font-weight: 600 !important;
  font-size: 0.93rem !important;
}
.stRadio > div > label:hover {
  border-color: var(--accent-1) !important;
  background: rgba(124,110,245,0.12) !important;
  box-shadow: 0 0 16px var(--glow-1) !important;
}
.stRadio > div > label:hover,
.stRadio > div > label:hover p,
.stRadio > div > label:hover span {
  color: #d8d2fe !important;
}

hr { border:none !important; border-top:1px solid var(--border-glass) !important; margin:1.5rem 0 !important; }

.stTabs [data-baseweb="tab-list"] {
  background: var(--bg-surface) !important; border-radius:12px !important;
  padding:4px !important; border:1px solid var(--border-glass) !important;
}
.stTabs [data-baseweb="tab"] {
  border-radius:8px !important; font-weight:600 !important; color: var(--text-secondary) !important;
  transition: all 0.25s !important;
}
.stTabs [aria-selected="true"] {
  background: var(--gradient-1) !important; color:white !important;
  box-shadow: 0 2px 12px var(--glow-1) !important;
}
.streamlit-expanderHeader {
  background: var(--bg-surface) !important; border-radius:12px !important;
  border:1px solid var(--border-glass) !important; font-weight:600 !important;
}
div[data-testid="stExpander"] {
  background: var(--bg-surface) !important; border:1px solid var(--border-glass) !important;
  border-radius: 12px !important;
}

/* Metrics, dataframes, sliders, checkboxes — dark-ified so nothing renders a
   stray white panel inside an otherwise dark page. */
div[data-testid="stMetric"] {
  background: var(--bg-surface) !important; border: 1px solid var(--border-glass) !important;
  border-radius: 14px !important; padding: 0.8rem 1rem !important;
  backdrop-filter: blur(14px) !important;
}
div[data-testid="stMetricValue"] { color: var(--text-primary) !important; text-shadow: 0 0 14px var(--glow-1); }
div[data-testid="stMetricLabel"] { color: var(--text-secondary) !important; }
div[data-testid="stDataFrame"] { background: var(--bg-surface) !important; border-radius: 12px !important; }
.stSlider [data-baseweb="slider"] > div { background: rgba(255,255,255,0.1) !important; }
.stProgress > div > div { background: var(--gradient-1) !important; }

/* Smooth transitions on every interactive element site-wide. */
button, input, textarea, select, [role="button"], [role="tab"], a {
  transition: all 0.25s cubic-bezier(0.4,0,0.2,1) !important;
}
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Session-state defaults
# ---------------------------------------------------------------------------

from dashboard.state import make_session_defaults

# Rebuilt on every rerun (fresh set()/{} per session) — see dashboard/state.py.
_SS_DEFAULTS = make_session_defaults()

for key, default in _SS_DEFAULTS.items():
    if key not in st.session_state:
        st.session_state[key] = default

ss = st.session_state

# ---------------------------------------------------------------------------
# Hidden pages — removed from the sidebar and the router, code kept
# ---------------------------------------------------------------------------
# To bring one back: (1) move its tuple into `nav` in render_sidebar(), (2) re-add
# its import and its `_PAGES` entry in the Router section at the bottom of this
# file, (3) delete it from this list. The page modules themselves, and the
# backing code (evaluation/activity_feed.py, learning_canvas.py,
# system_evaluator.py, dashboard/social_client.py, stress_*), are untouched; Home
# still uses activity_feed and system_evaluator directly.
_HIDDEN_NAV = [
    ("💬", "Ask SAE",           "ask",               "page_ask (its question box now lives on the Adaptive Tutor page)"),
    ("🗺️", "Learning Canvas",   "canvas",            "page_canvas"),
    ("📅", "Activity",          "activity",          "page_activity"),
    ("📊", "System Evaluation", "system_evaluation", "page_system_evaluation"),
    ("👥", "Friends",           "friends",           "page_friends"),
    ("🧘", "Recharge",          "stress_relief",     "page_stress_relief (defined in this file)"),
]
_HIDDEN_PAGE_IDS = {entry[2] for entry in _HIDDEN_NAV}

# A session saved/open from before the pages were hidden may still hold one of
# these ids; send it Home instead of silently falling through to the domain picker.
if ss.get("page") in _HIDDEN_PAGE_IDS:
    ss["page"] = "tutor" if ss.get("page") == "ask" else "home"      # Ask SAE moved into the tutor page

_perf.set_context(page=ss.get("page", "domain_select"), student_id=ss.get("student_id") or "system")
_perf.checkpoint("css_and_state_defaults")

# ---------------------------------------------------------------------------
# Auth gate — show login page if no valid session
# ---------------------------------------------------------------------------

def _is_authenticated() -> bool:
    """True if the session token is still live in Redis, or student_id is set."""
    if ss.get("student_id"):
        # Re-validate token with Redis if available
        token = ss.get("auth_token", "")
        if token:
            try:
                from auth.cache import get_session
                data = get_session(token)
                if data:
                    return True
                # Token expired — clear and force re-login
                ss["student_id"] = ""
                ss["auth_token"] = ""
                return False
            except Exception:
                pass  # Redis unavailable — trust session_state
        return True
    return False


with _perf.span("rerun.auth_gate"):
    _authenticated = _is_authenticated()
if not _authenticated:
    from dashboard.page_login import page_login
    with _perf.span("rerun.page", page="login"):
        page_login()
    _perf.end_rerun(_PERF_RUN, outcome="login")
    st.stop()
_perf.checkpoint("auth_gate")

# ---------------------------------------------------------------------------
# Singleton helpers
# ---------------------------------------------------------------------------

@st.cache_resource
def get_roadmap_agent():
    from agents.roadmap_agent import RoadmapAgent
    return RoadmapAgent()


@st.cache_resource
def get_tutor_agent():
    from agents.tutor_agent import TutorAgent
    return TutorAgent()


@st.cache_resource
def get_animation_generator():
    from media.video_generator import AnimatedLessonGenerator
    return AnimatedLessonGenerator()


# ---------------------------------------------------------------------------
# Navigation helper
# ---------------------------------------------------------------------------

def _go(page: str) -> None:
    if ss.get("page") != "stress_relief":
        ss["prev_page"] = ss.get("page", "domain_select")
    ss["page"] = page
    st.rerun()


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

def render_sidebar() -> None:
    with st.sidebar:
        st.markdown("""
        <div style="padding:1rem 0 0.5rem;text-align:center;">
          <div style="font-family:'Plus Jakarta Sans',sans-serif;font-size:1.3rem;
                      font-weight:800;background:linear-gradient(135deg,#7c6ef5,#38bdf8);
                      -webkit-background-clip:text;-webkit-text-fill-color:transparent;">
            SAE System
          </div>
          <div style="font-size:0.72rem;color:#8888a3;letter-spacing:1px;margin-top:2px;">
            SOVEREIGN LEARNING
          </div>
        </div>
        """, unsafe_allow_html=True)
        st.markdown("---")

        name = ss.get("student_name", "")
        if name:
            initials = "".join(w[0].upper() for w in name.split()[:2])
            st.markdown(f"""
            <div style="display:flex;align-items:center;gap:10px;padding:0.8rem;
                        background:rgba(255,255,255,0.04);backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px);border-radius:14px;margin-bottom:1rem;">
              <div style="width:40px;height:40px;border-radius:50%;
                          background:linear-gradient(135deg,#7c6ef5,#38bdf8);
                          display:flex;align-items:center;justify-content:center;
                          font-weight:700;color:white;font-size:0.9rem;flex-shrink:0;">
                {initials}
              </div>
              <div>
                <div style="font-weight:600;font-size:0.9rem;color:#f2f2f8;">
                  {name}
                </div>
                <div style="font-size:0.72rem;color:#8888a3;">
                  {ss.get("domain") or "No domain yet"}
                </div>
              </div>
            </div>
            """, unsafe_allow_html=True)

        # Only globally safe nav targets — never mid-flow pages like lesson/test
        if ss.get("domain"):
            nav = [
                ("Home",            "home"),
                ("Roadmap",         "roadmap"),
                ("Adaptive Tutor",  "tutor"),
                ("Knowledge Graph", "knowledge_graph"),
            ]
            for label, page in nav:
                active = ss["page"] == page
                if st.button(
                    label,
                    key=f"nav_{page}",
                    use_container_width=True,
                    type="primary" if active else "secondary",
                ):
                    if page == "stress_relief" and ss["page"] != "stress_relief":
                        ss["prev_page"] = ss["page"]
                    ss["page"] = page
                    st.rerun()

            if ss.get("page") == "stress_relief":
                if st.button("← Back", use_container_width=True):
                    _go(ss.get("prev_page", "domain_select"))

        if ss.get("session_start"):
            elapsed = int(
                (datetime.now() - ss["session_start"]).total_seconds() / 60
            )
            color = (
                "#f87171" if elapsed >= 90 else
                "#fbbf24" if elapsed >= 60 else
                "#4ade80"
            )
            st.markdown(f"""
            <div style="text-align:center;padding:0.5rem;font-size:0.75rem;
                        color:{color};background:rgba(255,255,255,0.04);backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px);border-radius:8px;margin-top:0.5rem;">
              ⏱ {elapsed} min studied today
            </div>
            """, unsafe_allow_html=True)

        st.markdown("---")
        if st.button("Log Out", use_container_width=True, key="nav_logout"):
            # Save progress before clearing session
            try:
                from persistence.progress_store import save_progress as _sp
                _sp(
                    ss.get("student_id", ""),
                    ss.get("domain", ""),
                    ss.get("modules_passed", set()),
                    ss.get("modules_unlocked", set()),
                    ss.get("module_progress", {}),
                )
            except Exception:
                pass
            try:
                from auth.auth import logout as _logout
                _logout(ss.get("auth_token", ""))
            except Exception:
                pass
            for k in list(ss.keys()):
                del ss[k]
            st.rerun()


_perf.checkpoint("defs_before_sidebar")
with _perf.span("rerun.sidebar"):
    render_sidebar()
_perf.checkpoint("sidebar")

# ---------------------------------------------------------------------------
# Domain constants
# ---------------------------------------------------------------------------

DOMAINS = [
    ("🤖", "Machine Learning",   "Intermediate", 4.8, 850),
    ("🌐", "Web Development",    "Beginner",      4.6, 1240),
    ("📊", "Data Science",       "Intermediate", 4.7, 920),
    ("🔐", "Cybersecurity",      "Advanced",      4.5, 610),
    ("☁️", "Cloud Computing",    "Intermediate", 4.4, 780),
    ("⛓️", "Blockchain",         "Advanced",      4.3, 420),
    ("📱", "Mobile Dev",         "Beginner",      4.5, 1050),
    ("🔧", "DevOps",             "Intermediate", 4.4, 690),
    ("📈", "Digital Marketing",  "Beginner",      4.2, 1180),
    ("🎨", "UI/UX Design",       "Beginner",      4.6, 970),
]

# ---------------------------------------------------------------------------
# Page: domain_select
# ---------------------------------------------------------------------------

def page_domain_select() -> None:
    st.markdown("""
    <div style="text-align:center;padding:2rem 0 1.5rem;">
      <div style="font-family:'Plus Jakarta Sans',sans-serif;font-size:2.2rem;
                  font-weight:800;color:#f2f2f8;line-height:1.2;margin-bottom:0.5rem;">
        What do you want to<br>
        <span style="background:linear-gradient(135deg,#7c6ef5,#38bdf8);
                     -webkit-background-clip:text;-webkit-text-fill-color:transparent;">
          learn today?
        </span>
      </div>
      <p style="color:#a3a3bd;font-size:1rem;max-width:480px;margin:0 auto;">
        Choose a domain below. Your AI professor will build a personalised
        10-week roadmap just for you.
      </p>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("""
    <div style="text-align:center;margin:1rem 0 0.5rem;">
      <span style="font-size:0.8rem;font-weight:600;color:#8888a3;
                   letter-spacing:1.5px;text-transform:uppercase;">
        Choose your domain
      </span>
    </div>
    """, unsafe_allow_html=True)

    cols = st.columns(5)
    for i, (icon, domain, diff, rating, learners) in enumerate(DOMAINS):
        badge_cls = {
            "Beginner": "badge-beginner",
            "Intermediate": "badge-intermediate",
            "Advanced": "badge-advanced",
        }.get(diff, "badge-beginner")
        stars = "★" * int(rating) + "☆" * (5 - int(rating))
        with cols[i % 5]:
            st.markdown(f"""
            <div style="background:rgba(255,255,255,0.045);backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px);border:2px solid rgba(255,255,255,0.10);border-radius:20px;
                        padding:1.2rem 0.8rem;text-align:center;min-height:150px;">
              <div style="font-size:2.2rem;margin-bottom:4px;">{icon}</div>
              <div style="font-family:'Plus Jakarta Sans',sans-serif;font-weight:700;
                          font-size:0.82rem;color:#f2f2f8;margin-bottom:4px;">{domain}</div>
              <span class="badge {badge_cls}">{diff}</span><br>
              <div style="font-size:0.7rem;color:#fbbf24;margin:2px 0;">{stars}</div>
              <div style="font-size:0.65rem;color:#8888a3;">{learners:,} learners</div>
            </div>
            """, unsafe_allow_html=True)
            if st.button("Start →", key=f"dom_{i}", use_container_width=True):
                ss["domain"] = domain
                ss["session_start"] = datetime.now()
                ss["roadmap"] = None
                ss["domain_xp_awarded"] = False
                from evaluation.event_log import log_event, EVT_SESSION_START
                log_event(EVT_SESSION_START, student_id=ss.get("student_id", ""), domain=domain)
                # Restore saved progress for this domain (empty sets if first time)
                try:
                    from persistence.progress_store import load_progress as _lp
                    _saved = _lp(ss.get("student_id", ""), domain)
                    ss["modules_passed"]   = _saved["modules_passed"]
                    ss["modules_unlocked"] = _saved["modules_unlocked"]
                    ss["module_progress"]  = _saved["module_progress"]
                except Exception:
                    ss["modules_passed"]   = set()
                    ss["modules_unlocked"] = set()
                    ss["module_progress"]  = {}
                _go("loading_roadmap")

    st.markdown("<br>", unsafe_allow_html=True)
    c1, c2, c3 = st.columns([1, 2, 1])
    with c2:
        st.markdown("""
        <div style="text-align:center;margin-bottom:8px;font-size:0.85rem;color:#8888a3;">
          — or type your own —
        </div>
        """, unsafe_allow_html=True)
        custom = st.text_input(
            "custom domain",
            placeholder="e.g. Quantum Computing, Game Design…",
            label_visibility="collapsed",
            key="custom_domain",
        )
        if st.button("Generate Custom Roadmap 🚀", use_container_width=True) and custom:
            ss["domain"] = custom.strip()
            ss["session_start"] = datetime.now()
            ss["roadmap"] = None
            ss["domain_xp_awarded"] = False
            from evaluation.event_log import log_event, EVT_SESSION_START
            log_event(EVT_SESSION_START, student_id=ss.get("student_id", ""), domain=custom.strip())
            try:
                from persistence.progress_store import load_progress as _lp
                _saved = _lp(ss.get("student_id", ""), custom.strip())
                ss["modules_passed"]   = _saved["modules_passed"]
                ss["modules_unlocked"] = _saved["modules_unlocked"]
                ss["module_progress"]  = _saved["module_progress"]
            except Exception:
                ss["modules_passed"]   = set()
                ss["modules_unlocked"] = set()
                ss["module_progress"]  = {}
            _go("loading_roadmap")


# ---------------------------------------------------------------------------
# Page: loading_roadmap  (progressive module-by-module rendering)
# ---------------------------------------------------------------------------

def page_loading_roadmap() -> None:
    domain = ss.get("domain", "")
    st.markdown(f"""
    <div style="text-align:center;padding:1.5rem 0 1rem;">
      <div style="font-family:'Plus Jakarta Sans',sans-serif;font-size:1.6rem;
                  font-weight:800;color:#f2f2f8;">
        Building your {domain} roadmap
      </div>
      <p style="color:#a3a3bd;margin-top:0.4rem;">
        Generating each week individually for complete content…
      </p>
    </div>
    """, unsafe_allow_html=True)

    progress_bar = st.progress(0)
    status_text  = st.empty()
    modules_container = st.container()

    generated_modules = []

    def on_module_done(week: int, module: dict) -> None:
        generated_modules.append(module)
        progress_bar.progress(week / 10)
        status_text.markdown(f"✅ Week {week} — **{module['title']}** generated")
        diff = module.get("difficulty", "Beginner")
        badge_cls = {
            "Beginner": "badge-beginner",
            "Intermediate": "badge-intermediate",
            "Advanced": "badge-advanced",
        }.get(diff, "badge-beginner")
        concepts_html = "".join(
            f'<span class="concept-tag">{_esc(str(c))}</span>'
            for c in module.get("concepts", [])[:4]
        )
        with modules_container:
            st.markdown(f"""
            <div class="sae-card" style="margin:4px 0;">
              <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap;">
                <div style="background:linear-gradient(135deg,#7c6ef5,#38bdf8);color:white;
                            width:36px;height:36px;border-radius:50%;display:flex;
                            align-items:center;justify-content:center;font-weight:700;
                            font-size:0.85rem;flex-shrink:0;">{week}</div>
                <div style="flex:1;min-width:0;">
                  <div style="font-weight:700;font-size:0.95rem;color:#f2f2f8;">
                    {_esc(str(module["title"]))}
                  </div>
                  <div style="font-size:0.8rem;color:#a3a3bd;margin-top:2px;">
                    {_esc(str(module.get("description", ""))[:100])}…
                  </div>
                </div>
                <span class="badge {badge_cls}">{diff}</span>
              </div>
              <div style="margin-top:8px;">{concepts_html}</div>
            </div>
            """, unsafe_allow_html=True)

    try:
        agent   = get_roadmap_agent()
        roadmap = agent.generate_roadmap(
            domain,
            progress_callback=on_module_done,
            student_id=ss.get("student_id", "default"),
        )
        ss["roadmap"] = roadmap
        # Unlock first module (add to unlocked, NOT passed — it hasn't been completed yet)
        if roadmap["modules"]:
            ss["modules_unlocked"].add(roadmap["modules"][0]["module_id"])
        # Record the enrolment now. Progress used to be written only on Log Out or after
        # passing a test, so a student who had picked a domain and generated a roadmap
        # looked "not started" to Home's recommendations, the login redirect and the evaluator.
        try:
            from persistence.progress_store import save_progress as _sp
            _sp(ss.get("student_id", ""), domain, ss["modules_passed"], ss["modules_unlocked"], ss["module_progress"])
        except Exception as exc:
            from evaluation.event_log import log_event, EVT_DASHBOARD_ERROR
            log_event(EVT_DASHBOARD_ERROR, student_id=ss.get("student_id", ""), page="loading_roadmap",
                      context="save_progress", error=f"{type(exc).__name__}: {exc}")
        progress_bar.progress(1.0)
        status_text.success("✅ All 10 weeks generated!")
        time.sleep(0.6)

        # One-click jump from a Home recommendation straight into its lesson,
        # instead of always landing on the roadmap grid. Falls back to the
        # roadmap page if the recommended concept isn't a top-level module
        # (e.g. it's a secondary concept tag, not a module_id).
        target_id = ss.pop("home_target_module_id", None)
        if target_id:
            modules = roadmap.get("modules", [])
            match = next((i for i, m in enumerate(modules) if m["module_id"] == target_id), None)
            if match is not None:
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
                _go("loading_lesson")
        _go("roadmap")
    except Exception as exc:
        st.error(f"Roadmap generation failed: {exc}. Check Ollama is running.")
        if st.button("← Try Again"):
            _go("domain_select")


# ---------------------------------------------------------------------------
# Page: roadmap
# ---------------------------------------------------------------------------

def page_roadmap() -> None:
    roadmap = ss.get("roadmap")
    if not roadmap:
        _go("domain_select")
        return

    passed = ss["modules_passed"]
    modules = roadmap["modules"]
    total  = len(modules)
    pct    = int(len(passed) / total * 100) if total else 0

    try:
        from memory.graph_engine import KnowledgeGraph
        _graph = KnowledgeGraph(student_id=ss.get("student_id", "default"))
    except Exception:
        _graph = None

    st.markdown(f"""
    <div style="padding:1rem 0 0.5rem;">
      <div style="font-family:'Plus Jakarta Sans',sans-serif;font-size:1.8rem;
                  font-weight:800;color:#f2f2f8;">
        {roadmap["domain"]} Learning Path
      </div>
      <div style="color:#a3a3bd;font-size:0.9rem;margin-top:4px;">
        Your personalised 10-week mission
      </div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown(f"""
    <div style="background:rgba(255,255,255,0.045);backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px);border-radius:14px;padding:1rem 1.2rem;
                border:1px solid rgba(255,255,255,0.10);margin:0.5rem 0 1rem;
                box-shadow:0 2px 8px rgba(0,0,0,0.04);">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
        <span style="font-weight:700;font-size:0.9rem;color:#f2f2f8;">Mission Progress</span>
        <span style="font-size:0.85rem;font-weight:700;color:#7c6ef5;">
          {len(passed)}/{total} modules · {pct}%
        </span>
      </div>
      <div class="progress-wrap" style="height:14px;">
        <div class="progress-fill" style="width:{pct}%;height:14px;"></div>
      </div>
    </div>
    """, unsafe_allow_html=True)

    for i, mod in enumerate(modules):
        is_done   = mod["module_id"] in passed
        is_locked = (
            i > 0
            and mod["module_id"] not in ss["modules_unlocked"]
            and not is_done
        )
        diff = mod.get("difficulty", "Beginner")
        badge_cls = {
            "Beginner": "badge-beginner",
            "Intermediate": "badge-intermediate",
            "Advanced": "badge-advanced",
        }.get(diff, "badge-beginner")

        dot_cls  = "dot-done" if is_done else ("dot-locked" if is_locked else "dot-active")
        dot_icon = "✓" if is_done else ("🔒" if is_locked else str(mod["week"]))
        card_opacity = "0.55" if is_locked else "1"
        concepts_html = "".join(
            f'<span class="concept-tag">{_esc(str(c))}</span>'
            for c in mod.get("concepts", [])[:5]
        )
        resources = mod.get("resources", [])
        res_html = ""
        if resources and resources[0].get("url"):
            res_html = (
                f'<a href="{_esc(str(resources[0]["url"]), quote=True)}" target="_blank" '
                f'style="font-size:0.75rem;color:#7c6ef5;text-decoration:none;font-weight:500;">'
                f'📚 {_esc(str(resources[0].get("title", "")))} →</a>'
            )

        mastery_html = ""
        if _graph and mod.get("concepts"):
            cid = mod["concepts"][0].lower().replace(" ", "_")[:50]
            m   = _graph.get_mastery(cid)
            if m >= 0.85:
                bar_color, bar_label = "#4ade80", "Mastered"
            elif m > 0.0:
                bar_color, bar_label = "#fbbf24", f"In progress {m:.0%}"
            else:
                bar_color, bar_label = "rgba(255,255,255,0.10)", "Not started"
            mastery_html = (
                f'<div style="margin-top:8px;">'
                f'  <div style="display:flex;justify-content:space-between;'
                f'              font-size:0.7rem;color:#a3a3bd;margin-bottom:3px;">'
                f'    <span>Mastery</span>'
                f'    <span style="color:{bar_color};font-weight:700;">{bar_label}</span>'
                f'  </div>'
                f'  <div style="background:rgba(255,255,255,0.06);border-radius:99px;height:6px;overflow:hidden;">'
                f'    <div style="width:{m*100:.0f}%;height:6px;background:{bar_color};'
                f'                border-radius:99px;transition:width 0.4s;"></div>'
                f'  </div>'
                f'</div>'
            )

        col_dot, col_content = st.columns([1, 11])
        with col_dot:
            line_html = (
                "<div style='width:2px;background:rgba(255,255,255,0.10);margin:0 21px;min-height:20px;'></div>"
                if i < total - 1 else ""
            )
            st.markdown(f"""
            <div style="display:flex;flex-direction:column;align-items:center;padding-top:8px;">
              <div class="timeline-dot {dot_cls}">{dot_icon}</div>
              {line_html}
            </div>
            """, unsafe_allow_html=True)
        with col_content:
            # Built as ONE string with no newlines or indentation. The old triple-quoted
            # template put {res_html} on its own line; when a module had no resource link
            # that left a blank line, which ends Markdown's HTML block, and the indented
            # {mastery_html} below it was then rendered as a code block (raw <div> text).
            # Here no blank line can occur whichever parts are empty. The description is
            # clamped to 3 lines so cards keep a consistent height.
            card_html = "".join([
                f'<div class="sae-card" style="opacity:{card_opacity};margin-bottom:4px;">',
                '<div style="display:flex;align-items:flex-start;justify-content:space-between;flex-wrap:wrap;gap:8px;">',
                '<div style="min-width:0;flex:1 1 320px;">',
                f'<div style="font-weight:700;font-size:1rem;color:#f2f2f8;margin-bottom:3px;">'
                f'Week {_esc(str(mod["week"]))} — {_esc(str(mod["title"]))}</div>',
                '<div style="font-size:0.82rem;color:#a3a3bd;margin-bottom:6px;line-height:1.5;'
                'display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden;">'
                f'{_esc(str(mod.get("description", "")))}</div>',
                f'<div style="margin-bottom:6px;">{concepts_html}</div>',
                res_html,
                mastery_html,
                '</div>',
                '<div style="text-align:right;flex-shrink:0;">',
                f'<span class="badge {badge_cls}">{_esc(str(diff))}</span>',
                f'<div style="font-size:0.72rem;color:#8888a3;margin-top:4px;">⏱ {_esc(str(mod.get("estimated_hours", 5)))}h</div>',
                '</div>',
                '</div>',
                '</div>',
            ])
            st.markdown(card_html, unsafe_allow_html=True)

            if not is_locked and not is_done:
                prog = ss["module_progress"].get(mod["module_id"], 0.0)
                if prog >= 50.0:
                    st.markdown(
                        "<div style='font-size:0.8rem;color:#fbbf24;font-weight:600;padding:2px 0;'>"
                        "📖 In Progress</div>",
                        unsafe_allow_html=True,
                    )
                btn_label = f"▶ Continue Week {mod['week']}" if prog >= 50.0 else f"▶ Start Week {mod['week']}"
                if st.button(btn_label, key=f"start_{i}"):
                    ss["current_module_idx"]  = i
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
                    _go("loading_lesson")
            elif is_done:
                st.markdown(
                    "<div style='font-size:0.8rem;color:#4ade80;font-weight:600;padding:4px 0;'>"
                    "✅ Completed</div>",
                    unsafe_allow_html=True,
                )


# ---------------------------------------------------------------------------
# Page: lesson  (loading + display)
# ---------------------------------------------------------------------------

LESSON_SECTIONS = [
    ("introduction",    "🎯", "Introduction & Motivation"),
    ("theory",          "📐", "Core Theory"),
    ("example",         "🔢", "Worked Example"),
    ("misconceptions",  "⚠️",  "Common Misconceptions"),
    ("applications",    "🌍", "Real-World Applications"),
    ("summary",         "✅", "Key Takeaways"),
]


def page_loading_lesson() -> None:
    """Load and display a full lesson when user clicks a topic."""
    roadmap = ss.get("roadmap", {})
    mod_idx = ss.get("current_module_idx", 0)

    if not roadmap or not roadmap.get("modules"):
        st.error("No roadmap loaded. Please go back and select a domain.")
        if st.button("← Back"):
            _go("domain_select")
        return

    module   = roadmap["modules"][mod_idx]
    concepts = module.get("concepts", [module.get("title", "Topic")])
    con_idx  = ss.get("current_concept_idx", 0)
    concept  = concepts[min(con_idx, len(concepts) - 1)]
    domain   = roadmap.get("domain", "this subject")

    st.markdown(f"""
    <div style="text-align:center;padding:1.5rem 0 1rem;">
      <div style="font-size:2.5rem;margin-bottom:0.8rem;">📖</div>
      <div style="font-family:'Plus Jakarta Sans',sans-serif;
                  font-size:1.3rem;font-weight:700;color:#f2f2f8;">
        Generating your lesson on
      </div>
      <div style="font-size:1.7rem;font-weight:800;margin-top:6px;
                  background:linear-gradient(135deg,#7c6ef5,#38bdf8);
                  -webkit-background-clip:text;-webkit-text-fill-color:transparent;">
        {concept}
      </div>
      <div style="color:#8888a3;font-size:0.85rem;margin-top:8px;">
        Week {module.get('week', mod_idx + 1)} — {module.get('title', '')}
      </div>
    </div>
    """, unsafe_allow_html=True)

    cols         = st.columns(3)
    placeholders = {}
    for i, (key, icon, label) in enumerate(LESSON_SECTIONS):
        with cols[i % 3]:
            placeholders[key] = st.empty()
            placeholders[key].markdown(f"""
            <div style="background:rgba(255,255,255,0.04);backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px);border-radius:12px;padding:10px 8px;
                        text-align:center;border:2px solid rgba(255,255,255,0.10);margin:3px 0;">
              <div style="font-size:1.2rem;">{icon}</div>
              <div style="font-size:0.78rem;font-weight:600;color:#8888a3;margin-top:3px;">
                {label}
              </div>
              <div style="font-size:0.68rem;color:#8888a3;margin-top:2px;">Waiting...</div>
            </div>
            """, unsafe_allow_html=True)

    # Mark all 6 cards as "generating" immediately — they all fire at once
    for key, icon, label in LESSON_SECTIONS:
        placeholders[key].markdown(f"""
        <div style="background:rgba(251,191,36,0.10);border-radius:12px;padding:10px 8px;
                    text-align:center;border:2px solid rgba(251,191,36,0.4);margin:3px 0;">
          <div style="font-size:1.2rem;">{icon}</div>
          <div style="font-size:0.78rem;font-weight:600;color:#fbbf24;margin-top:3px;">
            {label}
          </div>
          <div style="font-size:0.68rem;color:#fbbf24;margin-top:2px;">Generating…</div>
        </div>
        """, unsafe_allow_html=True)

    # Build icon/label lookup for use inside the callback
    _section_meta = {key: (icon, label) for key, icon, label in LESSON_SECTIONS}

    status = st.empty()
    status.info("Connecting to Professor SAE via Ollama…")

    try:
        tutor = get_tutor_agent()

        def _on_section_done(key: str, content: str, ok: bool) -> None:
            """Flip a card to green/red the moment its section arrives."""
            icon, label = _section_meta[key]
            placeholders[key].markdown(f"""
            <div style="background:{'rgba(34,197,94,0.12)' if ok else 'rgba(248,113,113,0.10)'};border-radius:12px;
                        padding:10px 8px;text-align:center;margin:3px 0;
                        border:2px solid {'rgba(74,222,128,0.4)' if ok else '#fca5a5'};">
              <div style="font-size:1.2rem;">{icon}</div>
              <div style="font-size:0.78rem;font-weight:600;margin-top:3px;
                          color:{'#4ade80' if ok else '#f87171'};">{label}</div>
              <div style="font-size:0.68rem;margin-top:2px;
                          color:{'#4ade80' if ok else '#f87171'};">
                {'Ready' if ok else 'Incomplete'}
              </div>
            </div>
            """, unsafe_allow_html=True)

        lesson = tutor.teach_concept_parallel(concept, domain, _on_section_done)

        ss["lesson"]         = lesson
        ss["lesson_section"] = 0
        ss["video_path"]     = ""
        ss["video_ready"]    = False

        # Generate animation in background
        try:
            import threading
            gen = get_animation_generator()
            concept_id_safe = module.get("module_id", concept)

            _anim_run_id = _perf.current_run_id()

            def _gen_anim() -> None:
                with _perf.span("animation.thread", run_id=_anim_run_id, concept=concept_id_safe):
                    path = gen.generate_lesson_animation(
                        concept_id_safe,
                        lesson.get("introduction", ""),
                        domain,
                        module.get("concepts", []),
                    )
                ss["video_path"]  = path
                ss["video_ready"] = bool(path)

            threading.Thread(target=_gen_anim, daemon=True).start()
        except Exception:
            pass

        status.success("Lesson ready! Loading…")
        time.sleep(0.8)
        _go("lesson")

    except Exception as err:
        status.error(
            f"Error: {err}\n\n"
            "Make sure Ollama is running: open a terminal and run `ollama serve`"
        )
        if st.button("Try again"):
            st.rerun()
        if st.button("← Back to roadmap"):
            _go("roadmap")


def page_lesson() -> None:
    """Display the full professor-style lesson."""
    lesson = ss.get("lesson")

    if not lesson:
        st.warning("No lesson loaded.")
        if st.button("← Back to roadmap"):
            _go("roadmap")
        return

    concept_id  = lesson.get("concept_id", "Topic")
    domain      = lesson.get("domain", "")

    # Mark as in-progress (50%) the moment the student opens the lesson
    if concept_id not in ss["modules_passed"]:
        ss["module_progress"][concept_id] = max(
            ss["module_progress"].get(concept_id, 0), 50.0
        )

    section_idx = ss.get("lesson_section", 0)
    total       = len(LESSON_SECTIONS)

    section_idx = max(0, min(section_idx, total - 1))
    ss["lesson_section"] = section_idx

    # By the third section the student is clearly working through the lesson: begin preparing the
    # test in the background so it is (usually) ready by the time they click "Take test".
    if section_idx >= 2:
        _prefetch_test()

    st.markdown(f"""
    <div style="padding:0.5rem 0 1rem;">
      <div style="font-family:'Plus Jakarta Sans',sans-serif;font-size:1.6rem;
                  font-weight:800;color:#f2f2f8;">{concept_id}</div>
      <div style="font-size:0.82rem;color:#8888a3;margin-top:2px;">
        {domain} · Section {section_idx + 1} of {total}
      </div>
    </div>
    """, unsafe_allow_html=True)

    # Section pills
    pills = ""
    for j, (k, icon, label) in enumerate(LESSON_SECTIONS):
        if j < section_idx:
            cls = "background:rgba(34,197,94,0.18);color:#4ade80;border:2px solid rgba(74,222,128,0.4);"
        elif j == section_idx:
            cls = "background:linear-gradient(135deg,#7c6ef5,#38bdf8);color:white;border:none;"
        else:
            cls = "background:rgba(255,255,255,0.04);backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px);color:#8888a3;border:2px solid rgba(255,255,255,0.10);"
        pills += (
            f'<span style="display:inline-block;padding:4px 12px;border-radius:20px;'
            f'font-size:0.72rem;font-weight:600;margin:2px;{cls}">{icon} {label}</span>'
        )
    st.markdown(f'<div style="margin-bottom:1.2rem;">{pills}</div>', unsafe_allow_html=True)

    # Two-column layout
    col_main, col_side = st.columns([6, 4])

    with col_main:
        key  = LESSON_SECTIONS[section_idx][0]
        icon = LESSON_SECTIONS[section_idx][1]
        lbl  = LESSON_SECTIONS[section_idx][2]
        text = lesson.get(key, "")

        if not text or len(text) < 20:
            st.error(
                f"Section '{lbl}' has no content.\n\n"
                f"Key '{key}' returned: '{text[:60]}'\n\n"
                f"Available keys: {list(lesson.keys())}"
            )
            if st.button("Regenerate lesson"):
                ss["lesson"] = None
                _go("loading_lesson")
        else:
            st.markdown(f"""
            <div style="background:rgba(255,255,255,0.045);backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px);border-radius:16px;padding:1.8rem;
                        border:1px solid rgba(255,255,255,0.10);
                        box-shadow:0 2px 12px rgba(0,0,0,0.05);min-height:400px;">
              <div style="display:flex;align-items:center;gap:10px;margin-bottom:1.2rem;
                          padding-bottom:1rem;border-bottom:2px solid rgba(255,255,255,0.06);">
                <span style="font-size:1.6rem;">{icon}</span>
                <div>
                  <div style="font-family:'Plus Jakarta Sans',sans-serif;font-weight:700;
                              font-size:1.05rem;color:#f2f2f8;">{lbl}</div>
                  <div style="font-size:0.72rem;color:#8888a3;">{concept_id} · {domain}</div>
                </div>
              </div>
              <div style="color:#f2f2f8;line-height:1.95;font-size:0.93rem;
                          white-space:pre-wrap;">{text}</div>
            </div>
            """, unsafe_allow_html=True)

        st.markdown("<div style='margin-top:1rem;'>", unsafe_allow_html=True)
        c1, c2, c3 = st.columns([2, 3, 2])
        with c1:
            if section_idx > 0:
                if st.button("← Previous", use_container_width=True):
                    ss["lesson_section"] -= 1
                    st.rerun()
        with c2:
            dots = "".join(
                f'<span style="display:inline-block;width:10px;height:10px;border-radius:50%;'
                f'margin:0 3px;background:{"#7c6ef5" if j == section_idx else "rgba(255,255,255,0.10)"}'
                f'"></span>'
                for j in range(total)
            )
            st.markdown(
                f'<div style="text-align:center;padding-top:8px;">{dots}</div>',
                unsafe_allow_html=True,
            )
        with c3:
            if section_idx < total - 1:
                if st.button("Next →", use_container_width=True):
                    ss["lesson_section"] += 1
                    st.rerun()
            else:
                if st.button("Take the Test →", use_container_width=True):
                    ss["questions"] = None
                    for k in ["test_phase", "test_answers", "test_q_index",
                               "test_grade_result", "test_terminated"]:
                        ss[k] = _SS_DEFAULTS[k]
                    _go("test")
        st.markdown("</div>", unsafe_allow_html=True)

    with col_side:
        # Module info card
        try:
            roadmap     = ss.get("roadmap", {})
            mod_idx     = ss.get("current_module_idx", 0)
            module_info = roadmap["modules"][mod_idx]
            module_title = module_info.get("title", "")
        except Exception:
            module_title = ""

        st.markdown(f"""
        <div style="background:rgba(255,255,255,0.045);backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px);border-radius:16px;padding:1.2rem;
                    border:1px solid rgba(255,255,255,0.10);box-shadow:0 2px 8px rgba(0,0,0,0.04);
                    margin-bottom:0.8rem;">
          <div style="font-weight:700;font-size:0.85rem;color:#f2f2f8;margin-bottom:0.8rem;">
            About this lesson
          </div>
          <div style="font-size:0.8rem;color:#a3a3bd;line-height:1.6;">
            <div style="margin-bottom:6px;">
              <strong style="color:#f2f2f8;">Topic:</strong> {concept_id}
            </div>
            <div style="margin-bottom:6px;">
              <strong style="color:#f2f2f8;">Domain:</strong> {domain}
            </div>
            <div>
              <strong style="color:#f2f2f8;">Module:</strong> {module_title}
            </div>
          </div>
        </div>
        """, unsafe_allow_html=True)

        # Section list
        st.markdown("""
        <div style="background:rgba(255,255,255,0.045);backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px);border-radius:16px;padding:1.2rem;
                    border:1px solid rgba(255,255,255,0.10);box-shadow:0 2px 8px rgba(0,0,0,0.04);">
          <div style="font-weight:700;font-size:0.85rem;color:#f2f2f8;margin-bottom:0.8rem;">
            Lesson contents
          </div>
        """, unsafe_allow_html=True)

        for j, (k, icon, lbl) in enumerate(LESSON_SECTIONS):
            has    = len(lesson.get(k, "")) > 20
            active = j == section_idx
            bg     = "rgba(124,110,245,0.12)" if active else "rgba(255,255,255,0.04)"
            border = "2px solid #7c6ef5" if active else "1px solid rgba(255,255,255,0.10)"
            col    = "#c4b5fd" if active else "#c7c7de"
            weight = "700" if active else "500"
            dot    = "🟢" if has else "🔴"
            st.markdown(f"""
            <div style="background:{bg};border:{border};border-radius:8px;
                        padding:7px 10px;margin-bottom:5px;
                        display:flex;align-items:center;gap:8px;">
              <span style="font-size:1rem;">{icon}</span>
              <span style="font-size:0.78rem;font-weight:{weight};color:{col};flex:1;">
                {lbl}
              </span>
              <span style="font-size:0.6rem;">{dot}</span>
            </div>
            """, unsafe_allow_html=True)

        st.markdown("</div>", unsafe_allow_html=True)

        # Animation panel
        anim = ss.get("video_path", "")
        if anim and anim.endswith(".html") and Path(anim).exists():
            try:
                html = Path(anim).read_text(encoding="utf-8")
                st.markdown("""
                <div style="margin-top:0.8rem;font-weight:700;
                            font-size:0.85rem;color:#f2f2f8;">
                  Lesson animation
                </div>
                """, unsafe_allow_html=True)
                st.html(html)
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Page: test
# ---------------------------------------------------------------------------

def _current_test_inputs():
    """(module, concept_id, domain, lesson_content) for the module being studied, or None.

    Used by BOTH the test page and the early "prepare the test while reading" call in the lesson
    page, so they always ask the generator for exactly the same test.
    """
    roadmap = ss.get("roadmap")
    if not roadmap or not roadmap.get("modules"):
        return None
    module = roadmap["modules"][ss.get("current_module_idx", 0)]
    lesson_dict = ss.get("lesson") or {}
    lesson_content = "\n\n".join(
        str(lesson_dict.get(k, ""))
        for k in ["introduction", "theory", "example", "misconceptions", "applications", "summary"]
        if lesson_dict.get(k)
    )[:3000]
    return module, module.get("module_id", "unknown"), ss.get("domain", "general"), lesson_content


def _prefetch_test() -> None:
    """Start generating this module's test in the background (no-op if already running or cached).

    Called while the student reads the lesson, so the test is usually ready by "Take test".
    Never allowed to break the lesson page.
    """
    try:
        inputs = _current_test_inputs()
        if inputs and ss.get("questions") is None:
            from evaluation.generation_jobs import start_or_get
            _, concept_id, domain, lesson_content = inputs
            start_or_get(concept_id, domain, lesson_content)
    except Exception:
        pass


def page_test() -> None:
    inputs = _current_test_inputs()
    if inputs is None:
        _go("roadmap")
        return

    module, concept_id, domain, lesson_content = inputs
    student_id = ss.get("student_id", "student")

    st.markdown(f"""
    <div style="font-family:'Plus Jakarta Sans',sans-serif;font-size:1.5rem;
                font-weight:800;color:#f2f2f8;padding:0.5rem 0;">
      📝 Test: {module.get("title", concept_id)}
    </div>
    """, unsafe_allow_html=True)

    if ss.get("questions") is None:
        # Generation runs in ONE background job per test (evaluation/generation_jobs.py). It used to
        # run inline here, so every rerun started another generation that queued behind the first.
        from evaluation.generation_jobs import start_or_get

        job = start_or_get(concept_id, domain, lesson_content)
        if job.state == "done":
            ss["questions"] = job.questions
            st.rerun()
        elif job.state == "error":
            st.error(f"Test generation failed: {job.error}")
            if st.button("Try again", type="primary", key="test_generation_retry"):
                start_or_get(concept_id, domain, lesson_content, retry=True)
                st.rerun()
            return
        else:
            from dashboard.test_progress import render_generation_progress
            render_generation_progress(job)
            return

    from dashboard.test_interface import run_test_interface
    result = run_test_interface(ss["questions"], student_id, concept_id)

    if result is not None:
        from evaluation.event_log import log_event, EVT_TEST_ATTEMPT, EVT_DASHBOARD_ERROR
        ss["grade_result"] = result
        log_event(
            EVT_TEST_ATTEMPT,
            student_id=ss.get("student_id", ""), concept_id=concept_id, domain=domain,
            percentage=result.get("percentage", 0.0), grade=result.get("grade", ""),
            passed=result["passed"],
        )
        if result["passed"]:
            ss["modules_passed"].add(concept_id)
            ss["module_progress"][concept_id] = 100.0
            _unlock_next_module(concept_id)
            from integrity.xp_engine import XPEngine
            xp_engine = XPEngine(ss.get("student_id", ""))
            xp_engine.award("test_passed", metadata={"concept_id": concept_id})
            if result.get("percentage", 0.0) >= 95:
                xp_engine.award("perfect_score", metadata={"concept_id": concept_id})
            # Persist progress so it survives logout/login
            try:
                from persistence.progress_store import save_progress as _sp
                _sp(
                    ss.get("student_id", ""),
                    ss.get("domain", ""),
                    ss["modules_passed"],
                    ss["modules_unlocked"],
                    ss["module_progress"],
                )
            except Exception as exc:
                log_event(
                    EVT_DASHBOARD_ERROR, student_id=ss.get("student_id", ""),
                    page="test", context="save_progress", error=f"{type(exc).__name__}: {exc}",
                )
            try:
                from memory.graph_engine import KnowledgeGraph
                graph = KnowledgeGraph(student_id=ss.get("student_id", "default"))
                lesson_dict = ss.get("lesson") or {}
                raw_concept = lesson_dict.get("concept_id") or concept_id
                clean_id = raw_concept.lower().replace(" ", "_")[:50]
                score = result.get("percentage", 0.0) / 100.0
                mastery_before = graph.get_mastery(clean_id)
                graph.update_mastery(clean_id, score)
                from memory.graph_engine import MASTERY_THRESHOLD
                if mastery_before < MASTERY_THRESHOLD <= score:
                    xp_engine.award("concept_mastered", metadata={"concept_id": clean_id})
            except Exception as exc:
                log_event(
                    EVT_DASHBOARD_ERROR, student_id=ss.get("student_id", ""),
                    page="test", context="update_mastery", error=f"{type(exc).__name__}: {exc}",
                )
        _go("results")


def _unlock_next_module(current_id: str) -> None:
    roadmap = ss.get("roadmap")
    if not roadmap:
        return
    modules = roadmap.get("modules", [])
    for i, m in enumerate(modules):
        if m["module_id"] == current_id and i + 1 < len(modules):
            ss["modules_unlocked"].add(modules[i + 1]["module_id"])
            break


# ---------------------------------------------------------------------------
# Page: results
# ---------------------------------------------------------------------------

def page_results() -> None:
    result    = ss.get("grade_result")
    questions = ss.get("questions", [])
    if result is None:
        _go("roadmap")
        return

    from dashboard.test_interface import show_results
    show_results(result, questions)

    st.divider()
    roadmap = ss.get("roadmap")
    idx     = ss.get("current_module_idx", 0)
    module  = (roadmap["modules"][idx] if roadmap and idx < len(roadmap["modules"]) else {})
    concept_id = module.get("module_id", "")

    col1, col2, col3 = st.columns(3)
    with col1:
        if st.button("← Back to Roadmap", use_container_width=True):
            _go("roadmap")
    with col2:
        if not result["passed"]:
            if st.button("🔄 Retry Lesson", use_container_width=True):
                ss["lesson"]         = None
                ss["lesson_section"] = 0
                ss["questions"]      = None
                ss["grade_result"]   = None
                for k in ["test_phase", "test_answers", "test_q_index",
                           "test_grade_result", "test_terminated", "proctor"]:
                    ss[k] = _SS_DEFAULTS[k]
                _go("lesson")
    with col3:
        if roadmap:
            all_ids = {m["module_id"] for m in roadmap.get("modules", [])}
            if all_ids.issubset(ss["modules_passed"]):
                if st.button("🎓 Get Certificate!", type="primary", use_container_width=True):
                    _go("certificate")


# ---------------------------------------------------------------------------
# Page: certificate
# ---------------------------------------------------------------------------

def page_certificate() -> None:
    roadmap = ss.get("roadmap")
    if not roadmap:
        _go("domain_select")
        return

    st.markdown("""
    <div style="font-family:'Plus Jakarta Sans',sans-serif;font-size:1.8rem;
                font-weight:800;color:#f2f2f8;text-align:center;padding:0.5rem 0;">
      🎓 Congratulations!
    </div>
    """, unsafe_allow_html=True)
    st.balloons()

    student_name = ss.get("student_name") or ss.get("student_id", "Student")
    domain       = roadmap.get("domain", ss.get("domain", "Learning"))
    modules      = roadmap.get("modules", [])
    completed    = len(ss["modules_passed"])
    today        = datetime.now().date().isoformat()

    scores   = [v for v in ss["module_progress"].values() if v > 0]
    avg_score = sum(scores) / len(scores) if scores else 100.0

    from integrity.proof_of_learning import generate_hash
    import uuid
    proof_hash = generate_hash(student_name, domain, str(uuid.uuid4()), avg_score / 100)

    # Streamlit reruns this whole function on every interaction, so guard the
    # one-time domain-completion XP award with a session-state flag.
    if not ss.get("domain_xp_awarded"):
        from evaluation.event_log import log_event, EVT_DOMAIN_COMPLETED
        from integrity.xp_engine import XPEngine
        XPEngine(ss.get("student_id", "")).award("domain_completed", metadata={"domain": domain})
        log_event(
            EVT_DOMAIN_COMPLETED, student_id=ss.get("student_id", ""),
            domain=domain, modules_completed=completed, avg_score=avg_score,
        )
        ss["domain_xp_awarded"] = True

    if not ss.get("certificate_path"):
        with st.spinner("Generating your certificate…"):
            try:
                from integrity.certificate_generator import CertificateGenerator
                gen = CertificateGenerator()
                ss["certificate_path"] = gen.generate_certificate(
                    student_name=student_name,
                    domain=domain,
                    completion_date=today,
                    modules_completed=completed,
                    final_score=avg_score,
                    proof_hash=proof_hash,
                    student_id=student_name,
                )
            except Exception as exc:
                st.error(f"Certificate generation failed: {exc}")

    cert_path = ss.get("certificate_path", "")
    if cert_path and Path(cert_path).exists():
        try:
            from pdf2image import convert_from_path
            images = convert_from_path(cert_path, first_page=1, last_page=1, dpi=120)
            if images:
                st.image(images[0], use_container_width=True, caption="Certificate Preview")
        except Exception:
            st.info("📄 Certificate generated. Install poppler for a preview.")

        with open(cert_path, "rb") as f:
            cert_bytes = f.read()
        st.download_button(
            "⬇️ Download Certificate 🎓",
            data=cert_bytes,
            file_name=Path(cert_path).name,
            mime="application/pdf",
            type="primary",
            use_container_width=True,
        )

    st.divider()
    col1, col2, col3 = st.columns(3)
    col1.markdown(
        f'<div class="metric-card"><div class="metric-value">{completed}/10</div>'
        f'<div class="metric-label">Modules</div></div>', unsafe_allow_html=True)
    col2.markdown(
        f'<div class="metric-card"><div class="metric-value">{avg_score:.0f}%</div>'
        f'<div class="metric-label">Avg Score</div></div>', unsafe_allow_html=True)
    col3.markdown(
        f'<div class="metric-card"><div class="metric-value">{today}</div>'
        f'<div class="metric-label">Completed</div></div>', unsafe_allow_html=True)

    st.markdown("**🔐 Verification Hash**")
    st.code(proof_hash, language="text")


# ---------------------------------------------------------------------------
# Page: stress_relief
# ---------------------------------------------------------------------------

def page_stress_relief() -> None:
    from dashboard.stress_relief_ui import render_stress_relief_page
    domain  = ss.get("domain", "Learning")
    roadmap = ss.get("roadmap")
    idx     = ss.get("current_module_idx", 0)
    module  = (roadmap["modules"][idx]
               if roadmap and roadmap["modules"] and idx < len(roadmap["modules"])
               else {})
    concept = module.get("title", "the current topic")
    render_stress_relief_page(domain=domain, concept=concept)


# ---------------------------------------------------------------------------
# Page: knowledge graph
# ---------------------------------------------------------------------------

def page_knowledge_graph() -> None:
    student_id = ss.get("student_id", "default")
    domain     = ss.get("domain", "")

    st.markdown("""
    <div style="font-family:'Plus Jakarta Sans',sans-serif;font-size:1.6rem;
                font-weight:800;color:#f2f2f8;padding:0.5rem 0 1rem;">
      🧠 Knowledge Graph
    </div>
    """, unsafe_allow_html=True)

    try:
        from memory.graph_engine import KnowledgeGraph, MASTERY_THRESHOLD
        graph = KnowledgeGraph(student_id=student_id)
        # Filter to current domain so Machine Learning graph doesn't bleed into Web Dev etc.
        data  = graph.get_graph_data_by_domain(domain) if domain else graph.get_graph_data()
    except Exception as exc:
        st.error(f"Could not load knowledge graph: {exc}")
        return

    nodes = data.get("nodes", [])
    edges = data.get("edges", [])

    # Auto-recover: if graph is empty but roadmap is in session, populate now.
    # Handles the case where _populate_graph failed silently during roadmap generation,
    # or where Neo4j was restarted after the roadmap was generated.
    if not nodes and domain and ss.get("roadmap"):
        roadmap_cached = ss["roadmap"]
        if (roadmap_cached.get("domain") or "").lower() == domain.lower():
            with st.spinner("Syncing concepts to knowledge graph…"):
                try:
                    graph.populate_from_roadmap(roadmap_cached)
                    graph.create_rich_schema(roadmap_cached, student_name=student_id)
                    data  = graph.get_graph_data_by_domain(domain)
                    nodes = data.get("nodes", [])
                    edges = data.get("edges", [])
                except Exception as exc:
                    st.warning(f"Could not auto-sync graph: {exc}")

    if not nodes:
        st.info(f"No concepts in your {domain} graph yet. Generate a roadmap first to populate it.")
        if st.button("← Go to Roadmap"):
            _go("roadmap")
        return

    # ── Progress summary cards — computed from filtered domain nodes ───────
    total     = len(nodes)
    mastered  = sum(1 for n in nodes if (n.get("mastery") or 0.0) >= MASTERY_THRESHOLD)
    in_prog   = sum(1 for n in nodes if 0.0 < (n.get("mastery") or 0.0) < MASTERY_THRESHOLD)
    not_start = total - mastered - in_prog

    c1, c2, c3, c4 = st.columns(4)
    for col, label, val, color in [
        (c1, "Total Concepts", total,     "#7c6ef5"),
        (c2, "Mastered",       mastered,  "#4ade80"),
        (c3, "In Progress",    in_prog,   "#fbbf24"),
        (c4, "Not Started",    not_start, "#8888a3"),
    ]:
        col.markdown(f"""
        <div style="background:rgba(255,255,255,0.045);backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px);border-radius:14px;padding:1rem;text-align:center;
                    border:2px solid {color}22;box-shadow:0 2px 8px rgba(0,0,0,0.04);">
          <div style="font-size:1.8rem;font-weight:800;color:{color};">{val}</div>
          <div style="font-size:0.75rem;color:#a3a3bd;font-weight:600;margin-top:2px;">{label}</div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("<div style='height:1rem'></div>", unsafe_allow_html=True)

    # ── Plotly network graph ──────────────────────────────────────────────
    import plotly.graph_objects as go
    import networkx as nx

    G = nx.DiGraph()
    node_map = {n["id"]: n for n in nodes}
    for n in nodes:
        G.add_node(n["id"])
    for e in edges:
        if e["source"] in G and e["target"] in G:
            G.add_edge(e["source"], e["target"])

    # Use spring layout for positioning
    pos = nx.spring_layout(G, seed=42, k=2.5)

    # Edge traces
    edge_x, edge_y = [], []
    for src, dst in G.edges():
        x0, y0 = pos[src]
        x1, y1 = pos[dst]
        edge_x += [x0, x1, None]
        edge_y += [y0, y1, None]

    edge_trace = go.Scatter(
        x=edge_x, y=edge_y,
        mode="lines",
        line=dict(width=1.2, color="rgba(255,255,255,0.10)"),
        hoverinfo="none",
    )

    # Node traces — colour by mastery
    node_x, node_y, node_text, node_color, node_size, node_hover = [], [], [], [], [], []
    for nid in G.nodes():
        n      = node_map.get(nid, {})
        m      = n.get("mastery", 0.0)
        x, y   = pos[nid]
        label  = nid.replace("_", " ").title()
        week   = n.get("week", 0)
        is_pri = n.get("is_primary", False)

        if m >= 0.85:
            color = "#4ade80"
        elif m > 0.0:
            color = "#fbbf24"
        else:
            color = "#8888a3"

        node_x.append(x)
        node_y.append(y)
        node_text.append(label if is_pri else "")
        node_color.append(color)
        node_size.append(18 if is_pri else 10)
        node_hover.append(
            f"<b>{label}</b><br>"
            f"Week {week} · {'Primary' if is_pri else 'Secondary'}<br>"
            f"Mastery: {m:.0%}"
        )

    # Store node ids in customdata so click events can identify the node
    node_ids = list(G.nodes())

    node_trace = go.Scatter(
        x=node_x, y=node_y,
        mode="markers+text",
        marker=dict(size=node_size, color=node_color, line=dict(width=1.5, color="white")),
        text=node_text,
        textposition="top center",
        textfont=dict(size=9, color="#f2f2f8"),
        hovertext=node_hover,
        hoverinfo="text",
        customdata=node_ids,
    )

    fig = go.Figure(
        data=[edge_trace, node_trace],
        layout=go.Layout(
            paper_bgcolor="#0a0a0f",
            plot_bgcolor="#0a0a0f",
            showlegend=False,
            margin=dict(l=0, r=0, t=0, b=0),
            height=480,
            xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
            yaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
            clickmode="event+select",
        ),
    )

    # Capture node clicks — Streamlit 1.35+ on_select API
    selected = st.plotly_chart(
        fig, use_container_width=True,
        on_select="rerun", selection_mode="points", key="kg_plot",
    )

    # ── Node detail panel (shown when a node is clicked) ─────────────────
    clicked_pts = (selected or {}).get("selection", {}).get("points", [])
    if clicked_pts:
        pt       = clicked_pts[0]
        nid      = pt.get("customdata")
        node_data = node_map.get(nid, {})
        if node_data:
            label   = nid.replace("_", " ").title()
            mastery = node_data.get("mastery") or 0.0
            week    = node_data.get("week", "—")
            mod_id  = node_data.get("module_id", "—")
            is_pri  = node_data.get("is_primary", False)
            status  = "✅ Mastered" if mastery >= MASTERY_THRESHOLD else ("🟡 In Progress" if mastery > 0 else "⬜ Not Started")

            prereqs = graph.get_prerequisites(nid)
            prereq_str = ", ".join(p.replace("_", " ").title() for p in prereqs) if prereqs else "None"

            st.markdown(
                f"<div style='background:rgba(255,255,255,0.045);backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px);border-radius:14px;padding:1.2rem 1.4rem;"
                f"border:2px solid rgba(124,110,245,0.20);box-shadow:0 4px 16px rgba(0,0,0,0.06);"
                f"margin-bottom:1rem;'>"
                f"<div style='font-size:1.1rem;font-weight:800;color:#f2f2f8;margin-bottom:0.6rem;'>"
                f"🔍 {label}</div></div>",
                unsafe_allow_html=True,
            )
            detail_rows = {
                "Concept ID":      nid,
                "Domain":          node_data.get("domain", domain),
                "Week":            week,
                "Module":          mod_id.replace("_", " ").title() if mod_id else "—",
                "Type":            "Primary concept" if is_pri else "Supporting concept",
                "Mastery Score":   f"{mastery:.0%}",
                "Status":          status,
                "Prerequisites":   prereq_str,
                "Last Reviewed":   (node_data.get("last_reviewed") or "Not yet reviewed")[:19].replace("T", " "),
            }
            import pandas as pd
            df = pd.DataFrame(list(detail_rows.items()), columns=["Field", "Value"])
            st.dataframe(df, use_container_width=True, hide_index=True)

    # ── Legend ───────────────────────────────────────────────────────────
    st.markdown("""
    <div style="display:flex;gap:1.5rem;font-size:0.78rem;font-weight:600;
                color:#c7c7de;margin-bottom:1rem;">
      <span><span style="color:#4ade80">●</span> Mastered (≥ 85%)</span>
      <span><span style="color:#fbbf24">●</span> In Progress</span>
      <span><span style="color:#8888a3">●</span> Not Started</span>
      <span style="color:#8888a3">Large nodes = primary lesson concepts</span>
    </div>
    """, unsafe_allow_html=True)

    # ── Weakest / Strongest — derived from domain-filtered nodes ─────────
    sorted_nodes = sorted(nodes, key=lambda n: n.get("mastery") or 0.0)
    weakest  = sorted_nodes[:5]
    strongest = [n for n in reversed(sorted_nodes[-5:]) if (n.get("mastery") or 0.0) > 0]

    col_w, col_s = st.columns(2)
    with col_w:
        st.markdown("**Weakest concepts (focus here)**")
        for n in weakest:
            m_pct = f"{(n.get('mastery') or 0.0):.0%}"
            st.markdown(
                f"<div style='background:rgba(248,113,113,0.12);border-left:4px solid #f87171;"
                f"padding:6px 10px;border-radius:6px;margin-bottom:4px;"
                f"font-size:0.83rem;font-weight:600;color:#f2f2f8;'>"
                f"{n['id'].replace('_',' ').title()} "
                f"<span style='color:#a3a3bd;font-weight:500;'>— {m_pct}</span></div>",
                unsafe_allow_html=True,
            )
    with col_s:
        st.markdown("**Strongest concepts**")
        if strongest:
            for n in strongest:
                m_pct = f"{(n.get('mastery') or 0.0):.0%}"
                st.markdown(
                    f"<div style='background:rgba(34,197,94,0.12);border-left:4px solid #4ade80;"
                    f"padding:6px 10px;border-radius:6px;margin-bottom:4px;"
                    f"font-size:0.83rem;font-weight:600;color:#f2f2f8;'>"
                    f"{n['id'].replace('_',' ').title()} "
                    f"<span style='color:#a3a3bd;font-weight:500;'>— {m_pct}</span></div>",
                    unsafe_allow_html=True,
                )
        else:
            st.info("Complete module tests to build mastery scores.")

    # ── Proof of Learning Log ─────────────────────────────────────────────
    st.markdown("<div style='height:1rem'></div>", unsafe_allow_html=True)
    with st.expander("📋 Proof of Learning Log", expanded=False):
        try:
            from integrity.proof_of_learning import read_log
            entries = read_log(student_id)
            if not entries:
                st.info("No verified learning events yet. Complete a module test to generate proof entries.")
            else:
                st.caption(f"{len(entries)} verified learning event(s) on record for this account.")
                for e in reversed(entries):
                    ts = e.get("timestamp", "")[:19].replace("T", " ")
                    concept = e.get("concept_id", "—").replace("_", " ").title()
                    score   = f"{e.get('composite_score', 0):.1%}"
                    h       = e.get("hash", "")
                    short_h = f"{h[:16]}…{h[-8:]}" if len(h) >= 24 else h
                    st.markdown(
                        f"<div style='background:rgba(255,255,255,0.04);backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px);border:1px solid rgba(255,255,255,0.10);"
                        f"border-radius:8px;padding:8px 12px;margin-bottom:6px;"
                        f"font-size:0.82rem;color:#f2f2f8;'>"
                        f"<b>{concept}</b> &nbsp;·&nbsp; Score: <b>{score}</b>"
                        f"&nbsp;·&nbsp; {ts} UTC<br>"
                        f"<span style='font-family:monospace;color:#7c6ef5;font-size:0.75rem;'>"
                        f"SHA-256: {short_h}</span></div>",
                        unsafe_allow_html=True,
                    )
        except Exception as exc:
            st.warning(f"Could not load proof log: {exc}")


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

_perf_t_imports = time.perf_counter()
from dashboard.page_home import page_home
from dashboard.page_tutor import page_tutor
# Hidden (see _HIDDEN_NAV near the top): page_ask, page_friends, page_system_evaluation,
# page_canvas, page_activity — their modules still exist, they are just not imported/routed.
_perf.record("rerun.import_pages", (time.perf_counter() - _perf_t_imports) * 1000)
_perf.checkpoint("page_defs_and_imports")

_PAGES = {
    "home":              page_home,
    "tutor":             page_tutor,
    "domain_select":     page_domain_select,
    "loading_roadmap":   page_loading_roadmap,
    "roadmap":           page_roadmap,
    "loading_lesson":    page_loading_lesson,
    "lesson":            page_lesson,
    "loading_test":      page_test,
    "test":              page_test,
    "results":           page_results,
    "certificate":       page_certificate,
    "knowledge_graph":   page_knowledge_graph,
}

current_page = ss.get("page", "domain_select")
_perf_outcome = "rendered"
try:
    with _perf.span("rerun.page", page=current_page):
        _PAGES.get(current_page, page_domain_select)()
except Exception as exc:
    _perf_outcome = type(exc).__name__
    from evaluation.event_log import log_event, EVT_DASHBOARD_ERROR
    log_event(
        EVT_DASHBOARD_ERROR, student_id=ss.get("student_id", ""),
        page=current_page, error=f"{type(exc).__name__}: {exc}",
    )
    raise
except BaseException as exc:  # Streamlit control flow: st.rerun() / st.stop()
    _perf_outcome = type(exc).__name__
    raise
finally:
    _perf.end_rerun(_PERF_RUN, outcome=_perf_outcome)
