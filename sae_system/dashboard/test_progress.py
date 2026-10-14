"""Progress view shown while a test is being prepared in the background.

Polls the job (evaluation/generation_jobs.py) every few seconds in a Streamlit fragment, so the
page stays responsive and — unlike the old blocking spinner — a rerun can never start a second
generation. The student can also leave and come back; the job keeps going.
"""

import time

import streamlit as st

_STEPS = [
    ("mcq", "Multiple-choice questions", 100.0),
    ("true_false", "True / False statements", 50.0),
    ("short_answer", "Short-answer questions", 60.0),
]


def _fraction(job) -> float:
    done = {t for t, _, _ in job.completed}
    finished = sum(1 for t, _, _ in _STEPS if t in done)
    last = max((ts for _, _, ts in job.completed), default=job.started_at)
    typical = next((s for t, _, s in _STEPS if t not in done), 60.0)
    partial = min(0.9, (time.time() - last) / typical) if finished < len(_STEPS) else 0.0
    return min(0.97, (finished + partial) / len(_STEPS))


def render_generation_progress(job) -> None:
    st.markdown(
        "<div style='font-size:1.05rem;font-weight:600;color:#f2f2f8;padding:0.4rem 0;'>"
        "Preparing your test from this lesson…</div>",
        unsafe_allow_html=True,
    )

    @st.fragment(run_every=3)
    def _poll() -> None:
        if job.state != "running":
            st.rerun()                                   # whole app: picks up the finished (or failed) job
        mins, secs = divmod(int(job.elapsed()), 60)
        st.progress(_fraction(job), text=f"About {int(_fraction(job) * 100)}% — {mins}:{secs:02d} elapsed")
        done = {t: n for t, n, _ in job.completed}
        for key, label, _ in _STEPS:
            st.markdown(f"{'✅' if key in done else '⏳'} {label}")
        st.caption(
            "Usually 2–4 minutes on this computer. You can leave this page — the test keeps "
            "preparing in the background and will be ready when you come back."
        )

    _poll()
