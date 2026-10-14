"""Session-state defaults for the dashboard — no Streamlit import, no side effects.

Lives in its own module on purpose. Streamlit runs ``dashboard/app.py`` as the
main script, NOT as the module ``dashboard.app``; a page doing
``from dashboard.app import _SS_DEFAULTS`` therefore executes the whole app a
second time inside the same run (sidebar included), which raised
``StreamlitDuplicateElementKey: nav_home``. Pages import from here instead.

It is a FACTORY, not a constant, deliberately: the defaults contain mutable
objects (``set()``, ``{}``) and a timestamp. ``app.py`` rebuilds them on every
rerun, so each session gets its own objects and a fresh ``question_start_time``.
A module-level dict would share one set/dict across every session (one
student's progress leaking into another's) and freeze the timestamp at
server start.
"""

import time
from typing import Any, Dict


def make_session_defaults() -> Dict[str, Any]:
    """Return a fresh dict of session-state defaults (new mutable objects each call)."""
    return {
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
        "social_token": "",
        "social_id": "",
        "social_display_name": "",
    }
