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
from pathlib import Path

# Suppress noisy __path__ deprecation warnings from transformers' lazy-loader
warnings.filterwarnings("ignore", message=r"Accessing `__path__`", category=UserWarning)
from typing import Optional

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import streamlit as st
from dotenv import load_dotenv

load_dotenv()

st.set_page_config(
    page_title="SAE System",
    page_icon="🎓",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Global CSS — light theme
# ---------------------------------------------------------------------------

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap');

/* ═══════════════════════════════════════════════════════
   BASE TYPOGRAPHY — applied to every element site-wide.
   Override per-component only when intentionally different.
   ═══════════════════════════════════════════════════════ */
:root {
  --font-body:    'Inter', sans-serif;
  --font-heading: 'Plus Jakarta Sans', sans-serif;
  --color-text:   #111827;   /* near-black — base for all body copy */
  --color-muted:  #6b7280;   /* secondary / caption text */
  --color-bg:     #f5f6fa;
  --fw-base:      600;       /* semi-bold throughout */
}

/* Global reset — every element inherits base type */
.stApp,
.stApp * {
  font-family: var(--font-body) !important;
  color: var(--color-text) !important;
  font-weight: var(--fw-base) !important;
  -webkit-font-smoothing: antialiased;
}

/* Headings — heavier and distinct face */
.stApp h1, .stApp h2, .stApp h3,
.stApp h4, .stApp h5, .stApp h6 {
  font-family: var(--font-heading) !important;
  font-weight: 800 !important;
  color: var(--color-text) !important;
}

/* Markdown body paragraphs */
.stApp p, .stApp li, .stApp span,
.stMarkdown p, .stMarkdown li, .stMarkdown span {
  font-family: var(--font-body) !important;
  font-weight: var(--fw-base) !important;
  color: var(--color-text) !important;
  line-height: 1.7 !important;
}

/* Captions / small helper text */
.stApp small, .stCaption, .stCaption * {
  color: var(--color-muted) !important;
  font-weight: 500 !important;
}

/* Inline code — dark text on light bg */
.stApp code {
  font-family: 'JetBrains Mono', 'Fira Code', monospace !important;
  font-weight: 500 !important;
  color: #c7254e !important;
  background: #f9f2f4 !important;
  padding: 1px 4px !important;
  border-radius: 4px !important;
}

/* Code blocks (pre) — light text on dark bg */
.stApp pre,
.stMarkdown pre,
div[data-testid="stMarkdownContainer"] pre {
  background: #1e1e2e !important;
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

.stApp {
  background: var(--color-bg) !important;
}

section[data-testid="stSidebar"] {
  background: #ffffff !important;
  border-right: 1px solid #e8eaf0 !important;
  box-shadow: 2px 0 12px rgba(0,0,0,0.05) !important;
}
section[data-testid="stSidebar"] * {
  color: var(--color-text) !important;
}

.sae-card {
  background: white; border-radius: 16px; padding: 1.5rem; margin: 0.6rem 0;
  border: 1px solid #e8eaf0; box-shadow: 0 2px 12px rgba(0,0,0,0.05);
  transition: box-shadow 0.2s, transform 0.2s;
}
.sae-card:hover {
  box-shadow: 0 8px 24px rgba(79,70,229,0.12); transform: translateY(-2px);
}
.card-purple {
  background: linear-gradient(135deg,#667eea 0%,#764ba2 100%);
  color: white; border-radius: 16px; padding: 1.5rem; border: none;
  box-shadow: 0 8px 24px rgba(102,126,234,0.3);
}

.badge { display:inline-block; padding:3px 12px; border-radius:20px;
  font-size:0.72rem; font-weight:600; letter-spacing:0.3px; }
.badge-beginner     { background:#d1fae5; color:#065f46; }
.badge-intermediate { background:#dbeafe; color:#1e40af; }
.badge-advanced     { background:#fce7f3; color:#9d174d; }
.badge-purple       { background:#ede9fe; color:#4c1d95; }

.progress-wrap {
  background:#f1f3f9; border-radius:99px; height:10px; overflow:hidden; margin:6px 0;
}
.progress-fill {
  height:100%; border-radius:99px;
  background:linear-gradient(90deg,#667eea,#764ba2);
  transition:width 0.6s cubic-bezier(0.4,0,0.2,1);
}

.timeline-dot {
  width:44px; height:44px; border-radius:50%; display:flex;
  align-items:center; justify-content:center; font-weight:700;
  font-size:0.85rem; flex-shrink:0;
}
.dot-done    { background:#d1fae5; color:#065f46; }
.dot-active  { background:linear-gradient(135deg,#667eea,#764ba2); color:white;
               box-shadow:0 4px 15px rgba(102,126,234,0.4); }
.dot-locked  { background:#f1f3f9; color:#9ca3af; }

.concept-tag {
  display:inline-block; background:#ede9fe; color:#4c1d95;
  padding:3px 10px; border-radius:12px; font-size:0.72rem; font-weight:500; margin:2px;
}

.metric-card {
  background:white; border-radius:14px; padding:1.2rem; text-align:center;
  border:1px solid #e8eaf0; box-shadow:0 2px 8px rgba(0,0,0,0.04);
}
.metric-value {
  font-size:2rem; font-weight:700; font-family:'Plus Jakarta Sans',sans-serif; color:#1a1a2e;
}
.metric-label { font-size:0.78rem; color:#6b7280; margin-top:4px; font-weight:500; }

.warning-banner {
  background:#fef2f2; border:2px solid #fca5a5; border-radius:12px;
  padding:1rem 1.2rem; color:#991b1b; font-weight:600; text-align:center;
  animation:pulse-warning 2s ease-in-out infinite;
}
@keyframes pulse-warning {
  0%,100% { box-shadow:0 0 0 0 rgba(252,165,165,0.4); }
  50%      { box-shadow:0 0 0 8px rgba(252,165,165,0); }
}

.stButton > button {
  background: linear-gradient(135deg,#667eea,#764ba2) !important;
  color: white !important; border: none !important; border-radius: 12px !important;
  font-family: 'Plus Jakarta Sans', sans-serif !important; font-weight: 600 !important;
  font-size: 0.85rem !important; padding: 0.5rem 1.2rem !important;
  transition: all 0.2s !important;
  box-shadow: 0 4px 12px rgba(102,126,234,0.25) !important;
}
.stButton > button:hover {
  transform: translateY(-1px) !important;
  box-shadow: 0 6px 20px rgba(102,126,234,0.4) !important;
}

.stTextInput > div > div > input,
.stTextArea > div > div > textarea {
  border-radius: 12px !important; border: 2px solid #d1d5db !important;
  background: white !important; font-family: var(--font-body) !important;
  font-size: 0.9rem !important; font-weight: 600 !important;
  color: #111827 !important; transition: border-color 0.2s !important;
}
.stTextInput > div > div > input:focus,
.stTextArea > div > div > textarea:focus {
  border-color: #667eea !important;
  box-shadow: 0 0 0 3px rgba(102,126,234,0.15) !important;
}
.stSelectbox > div > div { border-radius:12px !important; border:2px solid #e8eaf0 !important; }

.stRadio > div { gap: 0.5rem !important; }
.stRadio > div > label {
  background: #f0f0f5 !important;
  border: 2px solid #d1d5db !important;
  border-radius: 12px !important;
  padding: 0.65rem 1.1rem !important;
  transition: all 0.2s !important;
  cursor: pointer !important;
}
.stRadio > div > label,
.stRadio > div > label p,
.stRadio > div > label span {
  color: #111827 !important;
  font-weight: 600 !important;
  font-size: 0.93rem !important;
}
.stRadio > div > label:hover {
  border-color: #667eea !important;
  background: #ede9fe !important;
}
.stRadio > div > label:hover,
.stRadio > div > label:hover p,
.stRadio > div > label:hover span {
  color: #4c1d95 !important;
}

hr { border:none !important; border-top:2px solid #f1f3f9 !important; margin:1.5rem 0 !important; }

.stTabs [data-baseweb="tab-list"] {
  background:white !important; border-radius:12px !important;
  padding:4px !important; border:1px solid #e8eaf0 !important;
}
.stTabs [data-baseweb="tab"] {
  border-radius:8px !important; font-weight:600 !important; color:#6b7280 !important;
}
.stTabs [aria-selected="true"] {
  background:linear-gradient(135deg,#667eea,#764ba2) !important; color:white !important;
}
.streamlit-expanderHeader {
  background:white !important; border-radius:12px !important;
  border:1px solid #e8eaf0 !important; font-weight:600 !important;
}
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Session-state defaults
# ---------------------------------------------------------------------------

_SS_DEFAULTS = {
    "page": "domain_select",
    "prev_page": "domain_select",
    "auth_token": "",
    "student_id": "",
    "student_name": "",
    "student_email": "",
    "student_username": "",
    "domain": "",
    "session_start": None,
    "roadmap": None,
    "current_module_idx": 0,
    "current_concept_idx": 0,
    "lesson": None,
    "lesson_section": 0,
    "video_path": "",
    "video_ready": False,
    "questions": None,
    "grade_result": None,
    "modules_passed": set(),
    "modules_unlocked": set(),
    "module_progress": {},
    "test_phase": None,
    "test_answers": {},
    "test_q_index": 0,
    "question_start_time": time.time(),
    "test_grade_result": None,
    "test_terminated": False,
    "proctor": None,
    "certificate_path": "",
}

for key, default in _SS_DEFAULTS.items():
    if key not in st.session_state:
        st.session_state[key] = default

ss = st.session_state

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


if not _is_authenticated():
    from dashboard.page_login import page_login
    page_login()
    st.stop()

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
# Hero scene helper
# ---------------------------------------------------------------------------

def render_hero_scene() -> None:
    heroes_path = Path(__file__).parent / "static" / "heroes_scene.html"
    if heroes_path.exists():
        html = heroes_path.read_text(encoding="utf-8")
        with st.expander("🦸 Your Study Buddies", expanded=False):
            st.html(html)


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

def render_sidebar() -> None:
    with st.sidebar:
        st.markdown("""
        <div style="padding:1rem 0 0.5rem;text-align:center;">
          <div style="font-family:'Plus Jakarta Sans',sans-serif;font-size:1.3rem;
                      font-weight:800;background:linear-gradient(135deg,#667eea,#764ba2);
                      -webkit-background-clip:text;-webkit-text-fill-color:transparent;">
            SAE System
          </div>
          <div style="font-size:0.72rem;color:#9ca3af;letter-spacing:1px;margin-top:2px;">
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
                        background:#f8f9ff;border-radius:14px;margin-bottom:1rem;">
              <div style="width:40px;height:40px;border-radius:50%;
                          background:linear-gradient(135deg,#667eea,#764ba2);
                          display:flex;align-items:center;justify-content:center;
                          font-weight:700;color:white;font-size:0.9rem;flex-shrink:0;">
                {initials}
              </div>
              <div>
                <div style="font-weight:600;font-size:0.9rem;color:#1a1a2e;">
                  {name}
                </div>
                <div style="font-size:0.72rem;color:#9ca3af;">
                  {ss.get("domain") or "No domain yet"}
                </div>
              </div>
            </div>
            """, unsafe_allow_html=True)

        # Only globally safe nav targets — never mid-flow pages like lesson/test
        if ss.get("domain"):
            nav = [
                ("🌍", "Roadmap",         "roadmap"),
                ("🧠", "Knowledge Graph", "knowledge_graph"),
                ("🧘", "Recharge",        "stress_relief"),
            ]
            for icon, label, page in nav:
                active = ss["page"] == page
                if st.button(
                    f"{icon}  {label}",
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
                "#ef4444" if elapsed >= 90 else
                "#f59e0b" if elapsed >= 60 else
                "#10b981"
            )
            st.markdown(f"""
            <div style="text-align:center;padding:0.5rem;font-size:0.75rem;
                        color:{color};background:#f9fafb;border-radius:8px;margin-top:0.5rem;">
              ⏱ {elapsed} min studied today
            </div>
            """, unsafe_allow_html=True)

        st.markdown("---")
        if st.button("🚪  Log Out", use_container_width=True, key="nav_logout"):
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


render_sidebar()

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
    render_hero_scene()

    st.markdown("""
    <div style="text-align:center;padding:2rem 0 1.5rem;">
      <div style="font-family:'Plus Jakarta Sans',sans-serif;font-size:2.2rem;
                  font-weight:800;color:#1a1a2e;line-height:1.2;margin-bottom:0.5rem;">
        What do you want to<br>
        <span style="background:linear-gradient(135deg,#667eea,#764ba2);
                     -webkit-background-clip:text;-webkit-text-fill-color:transparent;">
          learn today?
        </span>
      </div>
      <p style="color:#6b7280;font-size:1rem;max-width:480px;margin:0 auto;">
        Choose a domain below. Your AI professor will build a personalised
        10-week roadmap just for you.
      </p>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("""
    <div style="text-align:center;margin:1rem 0 0.5rem;">
      <span style="font-size:0.8rem;font-weight:600;color:#9ca3af;
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
            <div style="background:white;border:2px solid #e8eaf0;border-radius:20px;
                        padding:1.2rem 0.8rem;text-align:center;min-height:150px;">
              <div style="font-size:2.2rem;margin-bottom:4px;">{icon}</div>
              <div style="font-family:'Plus Jakarta Sans',sans-serif;font-weight:700;
                          font-size:0.82rem;color:#1a1a2e;margin-bottom:4px;">{domain}</div>
              <span class="badge {badge_cls}">{diff}</span><br>
              <div style="font-size:0.7rem;color:#f59e0b;margin:2px 0;">{stars}</div>
              <div style="font-size:0.65rem;color:#9ca3af;">{learners:,} learners</div>
            </div>
            """, unsafe_allow_html=True)
            if st.button("Start →", key=f"dom_{i}", use_container_width=True):
                ss["domain"] = domain
                ss["session_start"] = datetime.now()
                ss["roadmap"] = None
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
        <div style="text-align:center;margin-bottom:8px;font-size:0.85rem;color:#9ca3af;">
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
                  font-weight:800;color:#1a1a2e;">
        Building your {domain} roadmap
      </div>
      <p style="color:#6b7280;margin-top:0.4rem;">
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
            f'<span class="concept-tag">{c}</span>'
            for c in module.get("concepts", [])[:4]
        )
        with modules_container:
            st.markdown(f"""
            <div class="sae-card" style="margin:4px 0;">
              <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap;">
                <div style="background:linear-gradient(135deg,#667eea,#764ba2);color:white;
                            width:36px;height:36px;border-radius:50%;display:flex;
                            align-items:center;justify-content:center;font-weight:700;
                            font-size:0.85rem;flex-shrink:0;">{week}</div>
                <div style="flex:1;min-width:0;">
                  <div style="font-weight:700;font-size:0.95rem;color:#1a1a2e;">
                    {module["title"]}
                  </div>
                  <div style="font-size:0.8rem;color:#6b7280;margin-top:2px;">
                    {module.get("description", "")[:100]}…
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
        progress_bar.progress(1.0)
        status_text.success("✅ All 10 weeks generated!")
        time.sleep(0.6)
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

    render_hero_scene()

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
                  font-weight:800;color:#1a1a2e;">
        {roadmap["domain"]} Learning Path
      </div>
      <div style="color:#6b7280;font-size:0.9rem;margin-top:4px;">
        Your personalised 10-week mission
      </div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown(f"""
    <div style="background:white;border-radius:14px;padding:1rem 1.2rem;
                border:1px solid #e8eaf0;margin:0.5rem 0 1rem;
                box-shadow:0 2px 8px rgba(0,0,0,0.04);">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
        <span style="font-weight:700;font-size:0.9rem;color:#1a1a2e;">Mission Progress</span>
        <span style="font-size:0.85rem;font-weight:700;color:#667eea;">
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
            f'<span class="concept-tag">{c}</span>'
            for c in mod.get("concepts", [])[:5]
        )
        resources = mod.get("resources", [])
        res_html = ""
        if resources and resources[0].get("url"):
            res_html = (
                f'<a href="{resources[0]["url"]}" target="_blank" '
                f'style="font-size:0.75rem;color:#667eea;text-decoration:none;font-weight:500;">'
                f'📚 {resources[0]["title"]} →</a>'
            )

        mastery_html = ""
        if _graph and mod.get("concepts"):
            cid = mod["concepts"][0].lower().replace(" ", "_")[:50]
            m   = _graph.get_mastery(cid)
            if m >= 0.85:
                bar_color, bar_label = "#16a34a", "Mastered"
            elif m > 0.0:
                bar_color, bar_label = "#f59e0b", f"In progress {m:.0%}"
            else:
                bar_color, bar_label = "#d1d5db", "Not started"
            mastery_html = (
                f'<div style="margin-top:8px;">'
                f'  <div style="display:flex;justify-content:space-between;'
                f'              font-size:0.7rem;color:#6b7280;margin-bottom:3px;">'
                f'    <span>Mastery</span>'
                f'    <span style="color:{bar_color};font-weight:700;">{bar_label}</span>'
                f'  </div>'
                f'  <div style="background:#f1f3f9;border-radius:99px;height:6px;overflow:hidden;">'
                f'    <div style="width:{m*100:.0f}%;height:6px;background:{bar_color};'
                f'                border-radius:99px;transition:width 0.4s;"></div>'
                f'  </div>'
                f'</div>'
            )

        col_dot, col_content = st.columns([1, 11])
        with col_dot:
            line_html = (
                "<div style='width:2px;background:#e8eaf0;margin:0 21px;min-height:20px;'></div>"
                if i < total - 1 else ""
            )
            st.markdown(f"""
            <div style="display:flex;flex-direction:column;align-items:center;padding-top:8px;">
              <div class="timeline-dot {dot_cls}">{dot_icon}</div>
              {line_html}
            </div>
            """, unsafe_allow_html=True)
        with col_content:
            st.markdown(f"""
            <div class="sae-card" style="opacity:{card_opacity};margin-bottom:4px;">
              <div style="display:flex;align-items:flex-start;justify-content:space-between;
                          flex-wrap:wrap;gap:8px;">
                <div>
                  <div style="font-weight:700;font-size:1rem;color:#1a1a2e;margin-bottom:3px;">
                    Week {mod["week"]} — {mod["title"]}
                  </div>
                  <div style="font-size:0.82rem;color:#6b7280;margin-bottom:6px;line-height:1.5;">
                    {mod.get("description", "")}
                  </div>
                  <div style="margin-bottom:6px;">{concepts_html}</div>
                  {res_html}
                  {mastery_html}
                </div>
                <div style="text-align:right;flex-shrink:0;">
                  <span class="badge {badge_cls}">{diff}</span>
                  <div style="font-size:0.72rem;color:#9ca3af;margin-top:4px;">
                    ⏱ {mod.get("estimated_hours", 5)}h
                  </div>
                </div>
              </div>
            </div>
            """, unsafe_allow_html=True)

            if not is_locked and not is_done:
                prog = ss["module_progress"].get(mod["module_id"], 0.0)
                if prog >= 50.0:
                    st.markdown(
                        "<div style='font-size:0.8rem;color:#b45309;font-weight:600;padding:2px 0;'>"
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
                    "<div style='font-size:0.8rem;color:#065f46;font-weight:600;padding:4px 0;'>"
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
    render_hero_scene()

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
                  font-size:1.3rem;font-weight:700;color:#1a1a2e;">
        Generating your lesson on
      </div>
      <div style="font-size:1.7rem;font-weight:800;margin-top:6px;
                  background:linear-gradient(135deg,#667eea,#764ba2);
                  -webkit-background-clip:text;-webkit-text-fill-color:transparent;">
        {concept}
      </div>
      <div style="color:#9ca3af;font-size:0.85rem;margin-top:8px;">
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
            <div style="background:#f9fafb;border-radius:12px;padding:10px 8px;
                        text-align:center;border:2px solid #e8eaf0;margin:3px 0;">
              <div style="font-size:1.2rem;">{icon}</div>
              <div style="font-size:0.78rem;font-weight:600;color:#9ca3af;margin-top:3px;">
                {label}
              </div>
              <div style="font-size:0.68rem;color:#d1d5db;margin-top:2px;">Waiting...</div>
            </div>
            """, unsafe_allow_html=True)

    # Mark all 6 cards as "generating" immediately — they all fire at once
    for key, icon, label in LESSON_SECTIONS:
        placeholders[key].markdown(f"""
        <div style="background:#fffbeb;border-radius:12px;padding:10px 8px;
                    text-align:center;border:2px solid #fde68a;margin:3px 0;">
          <div style="font-size:1.2rem;">{icon}</div>
          <div style="font-size:0.78rem;font-weight:600;color:#92400e;margin-top:3px;">
            {label}
          </div>
          <div style="font-size:0.68rem;color:#d97706;margin-top:2px;">Generating…</div>
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
            <div style="background:{'#f0fdf4' if ok else '#fef2f2'};border-radius:12px;
                        padding:10px 8px;text-align:center;margin:3px 0;
                        border:2px solid {'#a7f3d0' if ok else '#fca5a5'};">
              <div style="font-size:1.2rem;">{icon}</div>
              <div style="font-size:0.78rem;font-weight:600;margin-top:3px;
                          color:{'#065f46' if ok else '#991b1b'};">{label}</div>
              <div style="font-size:0.68rem;margin-top:2px;
                          color:{'#10b981' if ok else '#ef4444'};">
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

            def _gen_anim() -> None:
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

    render_hero_scene()

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

    st.markdown(f"""
    <div style="padding:0.5rem 0 1rem;">
      <div style="font-family:'Plus Jakarta Sans',sans-serif;font-size:1.6rem;
                  font-weight:800;color:#1a1a2e;">{concept_id}</div>
      <div style="font-size:0.82rem;color:#9ca3af;margin-top:2px;">
        {domain} · Section {section_idx + 1} of {total}
      </div>
    </div>
    """, unsafe_allow_html=True)

    # Section pills
    pills = ""
    for j, (k, icon, label) in enumerate(LESSON_SECTIONS):
        if j < section_idx:
            cls = "background:#d1fae5;color:#065f46;border:2px solid #a7f3d0;"
        elif j == section_idx:
            cls = "background:linear-gradient(135deg,#667eea,#764ba2);color:white;border:none;"
        else:
            cls = "background:#f9fafb;color:#9ca3af;border:2px solid #e8eaf0;"
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
            <div style="background:white;border-radius:16px;padding:1.8rem;
                        border:1px solid #e8eaf0;
                        box-shadow:0 2px 12px rgba(0,0,0,0.05);min-height:400px;">
              <div style="display:flex;align-items:center;gap:10px;margin-bottom:1.2rem;
                          padding-bottom:1rem;border-bottom:2px solid #f1f3f9;">
                <span style="font-size:1.6rem;">{icon}</span>
                <div>
                  <div style="font-family:'Plus Jakarta Sans',sans-serif;font-weight:700;
                              font-size:1.05rem;color:#1a1a2e;">{lbl}</div>
                  <div style="font-size:0.72rem;color:#9ca3af;">{concept_id} · {domain}</div>
                </div>
              </div>
              <div style="color:#1f2937;line-height:1.95;font-size:0.93rem;
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
                f'margin:0 3px;background:{"#667eea" if j == section_idx else "#d1d5db"}'
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
        <div style="background:white;border-radius:16px;padding:1.2rem;
                    border:1px solid #e8eaf0;box-shadow:0 2px 8px rgba(0,0,0,0.04);
                    margin-bottom:0.8rem;">
          <div style="font-weight:700;font-size:0.85rem;color:#1a1a2e;margin-bottom:0.8rem;">
            About this lesson
          </div>
          <div style="font-size:0.8rem;color:#6b7280;line-height:1.6;">
            <div style="margin-bottom:6px;">
              <strong style="color:#1a1a2e;">Topic:</strong> {concept_id}
            </div>
            <div style="margin-bottom:6px;">
              <strong style="color:#1a1a2e;">Domain:</strong> {domain}
            </div>
            <div>
              <strong style="color:#1a1a2e;">Module:</strong> {module_title}
            </div>
          </div>
        </div>
        """, unsafe_allow_html=True)

        # Section list
        st.markdown("""
        <div style="background:white;border-radius:16px;padding:1.2rem;
                    border:1px solid #e8eaf0;box-shadow:0 2px 8px rgba(0,0,0,0.04);">
          <div style="font-weight:700;font-size:0.85rem;color:#1a1a2e;margin-bottom:0.8rem;">
            Lesson contents
          </div>
        """, unsafe_allow_html=True)

        for j, (k, icon, lbl) in enumerate(LESSON_SECTIONS):
            has    = len(lesson.get(k, "")) > 20
            active = j == section_idx
            bg     = "#f5f3ff" if active else "#f9fafb"
            border = "2px solid #667eea" if active else "1px solid #e8eaf0"
            col    = "#4c1d95" if active else "#374151"
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
                            font-size:0.85rem;color:#1a1a2e;">
                  Lesson animation
                </div>
                """, unsafe_allow_html=True)
                st.html(html)
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Page: test
# ---------------------------------------------------------------------------

def page_test() -> None:
    render_hero_scene()

    roadmap = ss.get("roadmap")
    if not roadmap:
        _go("roadmap")
        return

    idx    = ss.get("current_module_idx", 0)
    module = roadmap["modules"][idx]
    concept_id   = module.get("module_id", "unknown")
    domain       = ss.get("domain", "general")
    student_id   = ss.get("student_id", "student")
    lesson_dict = ss.get("lesson") or {}
    lesson_content = "\n\n".join(
        str(lesson_dict.get(k, ""))
        for k in ["introduction", "theory", "example", "misconceptions", "applications", "summary"]
        if lesson_dict.get(k)
    )[:3000]

    st.markdown(f"""
    <div style="font-family:'Plus Jakarta Sans',sans-serif;font-size:1.5rem;
                font-weight:800;color:#1a1a2e;padding:0.5rem 0;">
      📝 Test: {module.get("title", concept_id)}
    </div>
    """, unsafe_allow_html=True)

    if ss.get("questions") is None:
        with st.spinner("Generating your 10-question test…"):
            try:
                from evaluation.test_engine import TestEngine
                engine = TestEngine()
                ss["questions"] = engine.generate_test(concept_id, domain, lesson_content)
            except Exception as exc:
                st.error(f"Test generation failed: {exc}")
                return
        st.rerun()

    from dashboard.test_interface import run_test_interface
    result = run_test_interface(ss["questions"], student_id, concept_id)

    if result is not None:
        ss["grade_result"] = result
        if result["passed"]:
            ss["modules_passed"].add(concept_id)
            ss["module_progress"][concept_id] = 100.0
            _unlock_next_module(concept_id)
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
            except Exception:
                pass
            try:
                from memory.graph_engine import KnowledgeGraph
                graph = KnowledgeGraph(student_id=ss.get("student_id", "default"))
                lesson_dict = ss.get("lesson") or {}
                raw_concept = lesson_dict.get("concept_id") or concept_id
                clean_id = raw_concept.lower().replace(" ", "_")[:50]
                score = result.get("percentage", 0.0) / 100.0
                graph.update_mastery(clean_id, score)
            except Exception:
                pass
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
    render_hero_scene()

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
    render_hero_scene()

    roadmap = ss.get("roadmap")
    if not roadmap:
        _go("domain_select")
        return

    st.markdown("""
    <div style="font-family:'Plus Jakarta Sans',sans-serif;font-size:1.8rem;
                font-weight:800;color:#1a1a2e;text-align:center;padding:0.5rem 0;">
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
    render_hero_scene()

    student_id = ss.get("student_id", "default")
    domain     = ss.get("domain", "")

    st.markdown("""
    <div style="font-family:'Plus Jakarta Sans',sans-serif;font-size:1.6rem;
                font-weight:800;color:#1a1a2e;padding:0.5rem 0 1rem;">
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
        (c1, "Total Concepts", total,     "#667eea"),
        (c2, "Mastered",       mastered,  "#16a34a"),
        (c3, "In Progress",    in_prog,   "#f59e0b"),
        (c4, "Not Started",    not_start, "#9ca3af"),
    ]:
        col.markdown(f"""
        <div style="background:white;border-radius:14px;padding:1rem;text-align:center;
                    border:2px solid {color}22;box-shadow:0 2px 8px rgba(0,0,0,0.04);">
          <div style="font-size:1.8rem;font-weight:800;color:{color};">{val}</div>
          <div style="font-size:0.75rem;color:#6b7280;font-weight:600;margin-top:2px;">{label}</div>
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
        line=dict(width=1.2, color="#d1d5db"),
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
            color = "#16a34a"
        elif m > 0.0:
            color = "#f59e0b"
        else:
            color = "#94a3b8"

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
        textfont=dict(size=9, color="#1a1a2e"),
        hovertext=node_hover,
        hoverinfo="text",
        customdata=node_ids,
    )

    fig = go.Figure(
        data=[edge_trace, node_trace],
        layout=go.Layout(
            paper_bgcolor="#f5f6fa",
            plot_bgcolor="#f5f6fa",
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
                f"<div style='background:white;border-radius:14px;padding:1.2rem 1.4rem;"
                f"border:2px solid #667eea33;box-shadow:0 4px 16px rgba(0,0,0,0.06);"
                f"margin-bottom:1rem;'>"
                f"<div style='font-size:1.1rem;font-weight:800;color:#1a1a2e;margin-bottom:0.6rem;'>"
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
                color:#374151;margin-bottom:1rem;">
      <span><span style="color:#16a34a">●</span> Mastered (≥ 85%)</span>
      <span><span style="color:#f59e0b">●</span> In Progress</span>
      <span><span style="color:#94a3b8">●</span> Not Started</span>
      <span style="color:#9ca3af">Large nodes = primary lesson concepts</span>
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
                f"<div style='background:#fff1f2;border-left:4px solid #ef4444;"
                f"padding:6px 10px;border-radius:6px;margin-bottom:4px;"
                f"font-size:0.83rem;font-weight:600;color:#111827;'>"
                f"{n['id'].replace('_',' ').title()} "
                f"<span style='color:#6b7280;font-weight:500;'>— {m_pct}</span></div>",
                unsafe_allow_html=True,
            )
    with col_s:
        st.markdown("**Strongest concepts**")
        if strongest:
            for n in strongest:
                m_pct = f"{(n.get('mastery') or 0.0):.0%}"
                st.markdown(
                    f"<div style='background:#f0fdf4;border-left:4px solid #16a34a;"
                    f"padding:6px 10px;border-radius:6px;margin-bottom:4px;"
                    f"font-size:0.83rem;font-weight:600;color:#111827;'>"
                    f"{n['id'].replace('_',' ').title()} "
                    f"<span style='color:#6b7280;font-weight:500;'>— {m_pct}</span></div>",
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
                        f"<div style='background:#f8fafc;border:1px solid #e2e8f0;"
                        f"border-radius:8px;padding:8px 12px;margin-bottom:6px;"
                        f"font-size:0.82rem;color:#1a1a2e;'>"
                        f"<b>{concept}</b> &nbsp;·&nbsp; Score: <b>{score}</b>"
                        f"&nbsp;·&nbsp; {ts} UTC<br>"
                        f"<span style='font-family:monospace;color:#667eea;font-size:0.75rem;'>"
                        f"SHA-256: {short_h}</span></div>",
                        unsafe_allow_html=True,
                    )
        except Exception as exc:
            st.warning(f"Could not load proof log: {exc}")


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

_PAGES = {
    "domain_select":   page_domain_select,
    "loading_roadmap": page_loading_roadmap,
    "roadmap":         page_roadmap,
    "loading_lesson":  page_loading_lesson,
    "lesson":          page_lesson,
    "loading_test":    page_test,
    "test":            page_test,
    "results":         page_results,
    "certificate":     page_certificate,
    "stress_relief":   page_stress_relief,
    "knowledge_graph": page_knowledge_graph,
}

current_page = ss.get("page", "domain_select")
_PAGES.get(current_page, page_domain_select)()
