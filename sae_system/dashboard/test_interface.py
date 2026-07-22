"""Proctored test-taking interface for the SAE System dashboard."""

import base64
import time
from typing import Dict, List, Optional, Tuple

import plotly.graph_objects as go
import streamlit as st

from evaluation.semantic_auditor import grade_response
from integrity.camera_proctor import CameraProctor

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MAX_WARNINGS = 5
_FACE_CHECK_INTERVAL_S = 5          # seconds between proctor checks
_LOCK_DURATION_H = 24               # hours a terminated test is locked

# Minimal base64-encoded 1-second 440 Hz beep (WAV, 8kHz, mono)
# Generated offline: a pure-tone warning beep for face-not-detected alerts.
_BEEP_B64 = (
    "UklGRiQAAABXQVZFZm10IBAAAAABAAEARKwAAIhYAQACABAAZGF0YQAAAAA="
)


# ---------------------------------------------------------------------------
# Lock helpers (stored in ./test_locks/)
# ---------------------------------------------------------------------------

import json
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path

_LOCK_DIR = Path(__file__).resolve().parent.parent / "test_locks"


def _lock_path(student_id: str, concept_id: str) -> Path:
    """Return the lock file path for a student+concept pair."""
    _LOCK_DIR.mkdir(parents=True, exist_ok=True)
    safe = f"{student_id}_{concept_id}".replace(" ", "_")
    return _LOCK_DIR / f"{safe}.json"


def is_test_locked(student_id: str, concept_id: str) -> Tuple[bool, str]:
    """Return (is_locked, unlock_time_str) for this student/concept combination."""
    p = _lock_path(student_id, concept_id)
    if not p.exists():
        return False, ""
    with p.open() as fh:
        data = json.load(fh)
    locked_at = datetime.fromisoformat(data["locked_at"])
    unlock_at = locked_at + timedelta(hours=_LOCK_DURATION_H)
    now = datetime.now(timezone.utc)
    if now < unlock_at:
        return True, unlock_at.strftime("%Y-%m-%d %H:%M UTC")
    p.unlink(missing_ok=True)
    return False, ""


def write_test_lock(student_id: str, concept_id: str) -> None:
    """Write a lock file marking this test as terminated."""
    p = _lock_path(student_id, concept_id)
    with p.open("w") as fh:
        json.dump({"locked_at": datetime.now(timezone.utc).isoformat()}, fh)


# ---------------------------------------------------------------------------
# Camera setup screen
# ---------------------------------------------------------------------------

def show_camera_setup(proctor: CameraProctor) -> bool:
    """Render the mandatory identity verification screen before the test begins.

    Returns True only when a valid face is detected and the student clicks Start.
    Camera verification is required — there is no skip option.
    """
    st.subheader("📷 Identity Verification Required")
    st.info(
        "**Test Rules:**\n"
        "- You must verify your identity with a clear face photo before starting.\n"
        "- Your face must be close to the camera and clearly visible (no hats, masks, or glasses covering the face).\n"
        "- Looking away or covering your face during the test will trigger a warning.\n"
        "- 5 warnings = test terminated and locked for 24 hours.\n\n"
        "**Identity verification is mandatory. The test cannot begin without it.**"
    )

    # Step 1 instruction — shown before the photo is taken
    st.markdown(
        """
        <div style='background:#1e3a5f;border:2px solid #3b82f6;border-radius:10px;
                    padding:14px 18px;margin-bottom:12px;'>
          <div style='color:#93c5fd;font-size:1rem;font-weight:700;margin-bottom:4px;'>
            📌 Step 1 — Take your photo
          </div>
          <div style='color:#dbeafe;font-size:0.9rem;'>
            Look directly at the camera, then click the
            <strong style='color:#facc15;'>⬤ white circle button</strong>
            at the bottom-centre of the camera box below.
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    img_data = st.camera_input(
        "👇 Click the ⬤ button at the bottom of this box to take your photo",
        key="setup_cam",
    )
    face_ok = False

    if img_data is not None:
        face_ok = proctor.detect_face_in_image_bytes(img_data.getvalue())
        if face_ok:
            st.success("✅ Face verified — click **Start Test** below to begin.")
        else:
            st.error(
                "⛔ No valid face detected. Make sure your face is close to the camera, "
                "well-lit, and fully visible, then click the ⬤ button again to retake."
            )

    if face_ok:
        st.markdown(
            """
            <div style='background:#14532d;border:2px solid #22c55e;border-radius:10px;
                        padding:12px 18px;margin:10px 0;'>
              <div style='color:#86efac;font-size:0.95rem;font-weight:700;'>
                ✅ Identity confirmed. You may now start the test.
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if st.button("▶ Start Test", type="primary", use_container_width=True):
            return True
    else:
        if img_data is None:
            st.warning("📸 No photo taken yet — click the ⬤ white circle button inside the camera box above.")
        # Start button disabled (greyed out) so the user can see it exists but knows why it's locked
        st.button("🔒 Start Test (take photo first)", disabled=True, use_container_width=True)

    return False


# ---------------------------------------------------------------------------
# Warning banner + beep
# ---------------------------------------------------------------------------

def _show_warning_banner(count: int) -> None:
    """Display a red warning banner and play an audio beep."""
    st.markdown(
        f"<div style='background:#7f1d1d;border:2px solid #ef4444;border-radius:8px;"
        f"padding:14px;text-align:center;font-size:1.1rem;font-weight:700;color:#fca5a5'>"
        f"⚠️ WARNING {count}/{_MAX_WARNINGS}: Face not detected! Please face the camera."
        f"</div>",
        unsafe_allow_html=True,
    )
    # Play base64-encoded beep
    try:
        beep_bytes = base64.b64decode(_BEEP_B64)
        st.audio(beep_bytes, format="audio/wav")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Single-question renderer
# ---------------------------------------------------------------------------

def _render_question(question: Dict, q_index: int, total: int) -> Optional[str]:
    """Render one test question and return the student's answer (or None).

    Args:
        question: Question dict with keys: question, type, options, etc.
        q_index: 0-based question index.
        total: Total number of questions.

    Returns:
        Student's answer string, or None if unanswered.
    """
    # Progress bar
    st.progress((q_index) / total, text=f"Question {q_index + 1} of {total}")

    # Timer
    elapsed = int(time.time() - st.session_state.get("question_start_time", time.time()))
    st.caption(f"⏱ Time on this question: {elapsed}s")

    # Difficulty chip
    diff_col = {"easy": "#22c55e", "medium": "#f59e0b", "hard": "#ef4444"}.get(
        question.get("difficulty", "medium"), "#6b7280"
    )
    st.markdown(
        f"<span style='background:{diff_col}22;color:{diff_col};padding:2px 8px;"
        f"border-radius:6px;font-size:0.78rem'>{question.get('difficulty','medium').upper()}</span> "
        f"<span style='color:#64748b;font-size:0.78rem'>·  {question.get('marks',2)} marks</span>",
        unsafe_allow_html=True,
    )

    st.markdown(
        f"<div style='font-size:1.1rem;font-weight:600;color:#e2e8f0;margin:10px 0'>"
        f"{question['question']}</div>",
        unsafe_allow_html=True,
    )

    q_type = question.get("type", "mcq")
    key = f"ans_{question['question_id']}"

    answer: Optional[str] = None

    if q_type == "mcq":
        options = question.get("options", ["A", "B", "C", "D"])
        choice = st.radio("Select your answer:", options, key=key, index=None)
        answer = choice

    elif q_type == "true_false":
        choice = st.radio("True or False?", ["True", "False"], key=key, index=None)
        answer = choice

    elif q_type == "short_answer":
        answer = st.text_area(
            "Your answer (write in full sentences):",
            key=key,
            height=130,
            placeholder="Explain your understanding clearly…",
        )
        answer = answer.strip() if answer else None

    return answer


# ---------------------------------------------------------------------------
# Results display
# ---------------------------------------------------------------------------

def show_results(
    grade_result: Dict,
    questions: List[Dict],
) -> None:
    """Render the full test results page.

    Shows a gauge chart, per-question breakdown, and pass/fail status.

    Args:
        grade_result: Dict from TestEngine.grade_test().
        questions: Original question list (for ordering).
    """
    pct = grade_result["percentage"]
    grade = grade_result["grade"]
    passed = grade_result["passed"]

    # ── Gauge chart — light theme ────────────────────────────────────────
    gauge_color = "#16a34a" if passed else "#dc2626"
    fig = go.Figure(go.Indicator(
        mode="gauge+number+delta",
        value=pct,
        number={"suffix": "%", "font": {"size": 40, "color": "#111827"}},
        title={"text": f"Grade: {grade}", "font": {"size": 22, "color": "#111827"}},
        gauge={
            "axis": {"range": [0, 100], "tickcolor": "#6b7280"},
            "bar": {"color": gauge_color},
            "bgcolor": "#f3f4f6",
            "bordercolor": "#e5e7eb",
            "steps": [
                {"range": [0,  60], "color": "#fee2e2"},
                {"range": [60, 85], "color": "#fef9c3"},
                {"range": [85, 100], "color": "#dcfce7"},
            ],
            "threshold": {
                "line": {"color": "#7c3aed", "width": 3},
                "thickness": 0.8,
                "value": 60,
            },
        },
    ))
    fig.update_layout(
        paper_bgcolor="#ffffff",
        font={"color": "#111827"},
        height=280,
        margin=dict(l=30, r=30, t=40, b=10),
    )
    st.plotly_chart(fig, use_container_width=True)

    # ── Score summary ────────────────────────────────────────────────────
    col1, col2, col3 = st.columns(3)
    col1.metric("Score", f"{grade_result['earned_marks']}/{grade_result['total_marks']}")
    col2.metric("Percentage", f"{pct:.1f}%")
    col3.metric("Grade", grade)

    if passed:
        st.success("✅ Module Passed — next module unlocked!")
    else:
        st.error("❌ Please review the material and retake the test.")

    st.divider()

    # ── Per-question breakdown ────────────────────────────────────────────
    # Light-theme cards: white background, dark text throughout.
    # Border and tint colour signals correct (green) vs wrong (red).
    st.subheader("Question Review")
    for r in grade_result.get("results", []):
        is_correct   = r["is_correct"]
        icon         = "✅" if is_correct else "❌"
        border_color = "#16a34a" if is_correct else "#dc2626"
        bg_color     = "#f0fdf4" if is_correct else "#fff1f2"
        label_color  = "#15803d" if is_correct else "#b91c1c"
        marks_color  = "#7c3aed"

        similarity_text = (
            f" &nbsp;·&nbsp; Similarity: {r['similarity_score']:.0%}"
            if r["type"] == "short_answer" else ""
        )

        st.markdown(
            f"""
            <div style="
                border-left: 5px solid {border_color};
                background: {bg_color};
                border-radius: 10px;
                padding: 14px 18px;
                margin-bottom: 10px;
            ">
              <div style="font-weight:700;font-size:0.97rem;color:#111827;margin-bottom:8px;">
                {icon} {r['question']}
              </div>
              <div style="font-size:0.88rem;margin-bottom:4px;">
                <span style="color:#374151;font-weight:600;">Your answer:&nbsp;</span>
                <span style="color:#111827;font-weight:600;background:#e5e7eb;
                             padding:2px 8px;border-radius:5px;">
                  {r['student_answer'] or '(no answer)'}
                </span>
              </div>
              <div style="font-size:0.88rem;margin-bottom:6px;">
                <span style="color:{label_color};font-weight:600;">Correct answer:&nbsp;</span>
                <span style="color:#111827;font-weight:600;background:#e5e7eb;
                             padding:2px 8px;border-radius:5px;">
                  {r['correct_answer']}
                </span>
              </div>
              <div style="font-size:0.83rem;color:#374151;font-weight:500;
                          margin-bottom:6px;font-style:italic;">
                {r['explanation']}
              </div>
              <div style="font-size:0.82rem;font-weight:700;color:{marks_color};">
                Marks: {r['marks_awarded']}/{r['marks_possible']}{similarity_text}
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )


# ---------------------------------------------------------------------------
# Main test interface orchestrator
# ---------------------------------------------------------------------------

def run_test_interface(
    questions: List[Dict],
    student_id: str,
    concept_id: str,
) -> Optional[Dict]:
    """Full proctored test flow: setup → questions → results.

    Manages state entirely via st.session_state.  Call this function on
    every Streamlit re-run while the test is in progress.

    Args:
        questions: List of question dicts from TestEngine.generate_test().
        student_id: Learner identifier (used for lock files).
        concept_id: Concept being tested (used for lock files).

    Returns:
        Grade result dict from TestEngine.grade_test() once the test is
        submitted, or None while still in progress.
    """
    from evaluation.test_engine import TestEngine

    ss = st.session_state

    # Check test lock
    locked, unlock_time = is_test_locked(student_id, concept_id)
    if locked:
        st.error(
            f"🚫 This test was terminated. It will unlock at **{unlock_time}**."
        )
        return None

    # Initialise session keys on first run (also re-init when value is None/falsy)
    if not ss.get("proctor"):
        ss["proctor"] = CameraProctor()
    if not ss.get("test_phase"):
        ss["test_phase"] = "setup"          # setup | questions | submitted
    if ss.get("test_answers") is None:
        ss["test_answers"] = {}
    if ss.get("test_q_index") is None:
        ss["test_q_index"] = 0
    if not ss.get("question_start_time"):
        ss["question_start_time"] = time.time()
    if "test_grade_result" not in ss:
        ss["test_grade_result"] = None
    if "test_terminated" not in ss:
        ss["test_terminated"] = False

    proctor: CameraProctor = ss["proctor"]
    total = len(questions)

    # ── Phase: setup ───────────────────────────────────────────────────
    if ss["test_phase"] == "setup":
        if show_camera_setup(proctor):
            ss["test_phase"] = "questions"
            ss["question_start_time"] = time.time()
            st.rerun()
        return None

    # ── Phase: terminated ─────────────────────────────────────────────
    if ss.get("test_terminated"):
        st.error("🚫 TEST TERMINATED — Maximum warnings reached. This attempt has been recorded.")
        return None

    # ── Phase: questions ──────────────────────────────────────────────
    if ss["test_phase"] == "questions":
        q_index = ss["test_q_index"]

        if q_index >= total:
            ss["test_phase"] = "submitted"
            st.rerun()
            return None

        # Affective pacing — check cognitive load after at least 2 answers
        if q_index >= 2:
            try:
                from integrity.affective_pacing import compute_cognitive_load, should_deescalate
                short_answers = [
                    v for v in ss.get("test_answers", {}).values()
                    if isinstance(v, str) and len(v) > 20
                ]
                if short_answers:
                    load = compute_cognitive_load(short_answers)
                    if should_deescalate(load):
                        st.info(
                            "💡 **Heads up:** Your response patterns suggest high cognitive load. "
                            "Consider taking a 2-minute break before continuing — "
                            "it will help you retain what you've learned."
                        )
            except Exception:
                pass

        question = questions[q_index]

        # Camera proctoring check
        cam_col, q_col = st.columns([1, 3])
        with cam_col:
            st.caption("📷 Live Proctoring")
            cam_snap = st.camera_input("", key=f"proctor_cam_{q_index}", label_visibility="collapsed")
            if cam_snap is not None:
                face_found = proctor.detect_face_in_image_bytes(cam_snap.getvalue())
                # Check if enough time has passed since last warning
                if not face_found:
                    if proctor.seconds_since_last_check() >= _FACE_CHECK_INTERVAL_S:
                        count = proctor.increment_warning()
                        if count >= _MAX_WARNINGS:
                            ss["test_terminated"] = True
                            write_test_lock(student_id, concept_id)
                            st.rerun()
                        else:
                            _show_warning_banner(count)
                face_status = "✅ Face OK" if face_found else "⚠️ No face"
                st.caption(face_status)
                st.caption(f"Warnings: {proctor.get_warning_count()}/{_MAX_WARNINGS}")

        with q_col:
            answer = _render_question(question, q_index, total)

            is_last = (q_index == total - 1)
            btn_label = "Submit Test ✅" if is_last else "Next Question →"
            btn_type = "primary" if is_last else "secondary"

            if st.button(btn_label, type=btn_type, use_container_width=True):
                if answer:
                    ss["test_answers"][question["question_id"]] = answer
                ss["test_q_index"] += 1
                ss["question_start_time"] = time.time()
                if is_last:
                    ss["test_phase"] = "submitted"
                st.rerun()

        return None

    # ── Phase: submitted ──────────────────────────────────────────────
    if ss["test_phase"] == "submitted":
        if ss["test_grade_result"] is None:
            engine = TestEngine()
            ss["test_grade_result"] = engine.grade_test(questions, ss["test_answers"])

        show_results(ss["test_grade_result"], questions)
        return ss["test_grade_result"]

    return None
