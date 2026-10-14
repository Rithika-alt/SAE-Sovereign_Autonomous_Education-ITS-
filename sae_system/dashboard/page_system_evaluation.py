"""System Evaluation page — answers "how well is SAE performing" across four
independently-measured dimensions: learning outcomes, AI grading accuracy,
engagement, and reliability. See evaluation/system_evaluator.py for the
aggregation logic and SAE_ARCHITECTURE_AUDIT.md for the methodology.
"""

import streamlit as st


def _metric_card(col, label: str, value: str, color: str) -> None:
    """Same colored-border metric-card style used on the Knowledge Graph page."""
    col.markdown(f"""
    <div style="background:rgba(255,255,255,0.045);backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px);border-radius:14px;padding:1rem;text-align:center;
                border:2px solid {color}22;box-shadow:0 2px 8px rgba(0,0,0,0.04);">
      <div style="font-size:1.6rem;font-weight:800;color:{color};">{value}</div>
      <div style="font-size:0.75rem;color:#a3a3bd;font-weight:600;margin-top:2px;">{label}</div>
    </div>
    """, unsafe_allow_html=True)


def _insufficient_data_banner(unlock_hint: str) -> None:
    st.info(f"Not enough learning history yet. {unlock_hint}")


def _render_learning_tab(data: dict) -> None:
    import plotly.graph_objects as go

    total = data["total_concepts"]
    mastered = data["mastered"]
    overall_mastery_pct = round(mastered / total * 100, 1) if total else 0.0

    gauge_color = "#4ade80" if overall_mastery_pct >= 60 else "#fbbf24"
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=overall_mastery_pct,
        number={"suffix": "%", "font": {"size": 36, "color": "#f2f2f8"}},
        title={"text": "Overall Mastery", "font": {"size": 18, "color": "#f2f2f8"}},
        gauge={
            "axis": {"range": [0, 100], "tickcolor": "#a3a3bd"},
            "bar": {"color": gauge_color},
            "bgcolor": "rgba(255,255,255,0.05)",
            "bordercolor": "rgba(255,255,255,0.10)",
            "steps": [
                {"range": [0, 60], "color": "rgba(248,113,113,0.12)"},
                {"range": [60, 85], "color": "rgba(251,191,36,0.12)"},
                {"range": [85, 100], "color": "rgba(34,197,94,0.14)"},
            ],
        },
    ))
    fig.update_layout(
        paper_bgcolor="#0a0a0f", font={"color": "#f2f2f8"},
        height=240, margin=dict(l=30, r=30, t=40, b=10),
    )
    st.plotly_chart(fig, use_container_width=True)

    c1, c2, c3, c4 = st.columns(4)
    _metric_card(c1, "Total Concepts", str(total), "#7c6ef5")
    _metric_card(c2, "Mastered", str(mastered), "#4ade80")
    _metric_card(c3, "In Progress", str(data["in_progress"]), "#fbbf24")
    _metric_card(c4, "Not Started", str(data["not_started"]), "#8888a3")

    st.markdown("<div style='height:1rem'></div>", unsafe_allow_html=True)

    if data["insufficient_data"]:
        _insufficient_data_banner(
            f"Complete {3 - data['test_attempt_count']} more test(s) to unlock your pass-rate trend."
        )
    elif data["test_pass_rate"] is not None:
        st.metric("Test Pass Rate", f"{data['test_pass_rate']:.0%}", help=f"N={data['test_attempt_count']} attempts")
        if data["weekly_pass_rate"]:
            weeks = list(data["weekly_pass_rate"].keys())
            rates = [v["pass_rate"] * 100 for v in data["weekly_pass_rate"].values()]
            fig2 = go.Figure(go.Scatter(x=weeks, y=rates, mode="lines+markers", line=dict(color="#7c6ef5")))
            fig2.update_layout(
                title="Weekly Pass Rate", yaxis_range=[0, 100], height=250,
                paper_bgcolor="#0a0a0f", plot_bgcolor="#0a0a0f",
                font={"color": "#f2f2f8"}, margin=dict(l=30, r=30, t=40, b=10),
            )
            st.plotly_chart(fig2, use_container_width=True)

    col_w, col_s = st.columns(2)
    with col_w:
        st.markdown("**Weakest Concepts**")
        for c in data["weakest_concepts"]:
            st.markdown(
                f"<div style='border-left:3px solid #f87171;padding:4px 10px;margin-bottom:4px;'>"
                f"{c['concept_id'].replace('_', ' ').title()} — {c['mastery']:.0%}</div>",
                unsafe_allow_html=True,
            )
    with col_s:
        st.markdown("**Strongest Concepts**")
        for c in data["strongest_concepts"]:
            st.markdown(
                f"<div style='border-left:3px solid #4ade80;padding:4px 10px;margin-bottom:4px;'>"
                f"{c['concept_id'].replace('_', ' ').title()} — {c['mastery']:.0%}</div>",
                unsafe_allow_html=True,
            )

    retention = data["retention_proxy"]
    st.markdown("<div style='height:0.5rem'></div>", unsafe_allow_html=True)
    st.caption(f"ℹ️ {retention['note']}")
    if retention["at_risk_concepts"]:
        st.warning(
            "PROXY — concepts that may need review: " + ", ".join(
                f"{c['concept_id'].replace('_', ' ').title()} ({c['days_since_review']}d)"
                for c in retention["at_risk_concepts"]
            )
        )


def _render_grading_tab(data: dict) -> None:
    comparison = data["threshold_comparison"]
    t_a, t_b = comparison["threshold_a"], comparison["threshold_b"]

    st.caption(f"Measured against a {data['gold_set_size']}-item hand-labeled gold-standard set "
               f"(sae_system/data/eval/grading_gold_set.json). Current live threshold: "
               f"**{data['current_threshold']}**.")

    c1, c2, c3, c4 = st.columns(4)
    m = t_b["metrics"] if t_b["value"] == data["current_threshold"] else t_a["metrics"]
    _metric_card(c1, "Accuracy", f"{m['accuracy']:.0%}", "#7c6ef5")
    _metric_card(c2, "Precision", f"{m['precision']:.0%}", "#4ade80")
    _metric_card(c3, "Recall", f"{m['recall']:.0%}", "#fbbf24")
    _metric_card(c4, "F1", f"{m['f1']:.0%}", "#7c6ef5")
    st.caption(f"N={m['n']} · TP={m['tp']} FP={m['fp']} TN={m['tn']} FN={m['fn']}")

    st.markdown("<div style='height:1rem'></div>", unsafe_allow_html=True)
    st.warning(
        f"⚠️ {comparison['disagreement_count']} / {data['gold_set_size']} gold-set items "
        f"({comparison['disagreement_pct']}%) flip pass/fail depending on whether the threshold "
        f"is {t_a['value']} or {t_b['value']}. Semantic similarity alone cannot cleanly separate "
        "correct answers from confidently-wrong or negated ones — see SAE_ARCHITECTURE_AUDIT.md."
    )

    agreement = data["inter_method_agreement"]
    st.markdown("**Inter-method agreement** (test-grading path vs. auditor/dialogue path)")
    if agreement["insufficient_data"]:
        _insufficient_data_banner(
            "The auditor/dialogue path only runs via the CLI entry point (main.py), "
            "not the dashboard, so this needs data from that path to populate."
        )
    else:
        st.metric("Agreement Rate", f"{agreement['agreement_rate']:.0%}", help=f"N={agreement['n_compared']} compared")


def _render_engagement_tab(data: dict) -> None:
    xp = data["xp"]
    c1, c2, c3, c4 = st.columns(4)
    _metric_card(c1, "Level", xp["level"], "#7c6ef5")
    _metric_card(c2, "Total XP", str(xp["total_xp"]), "#4ade80")
    _metric_card(c3, "Streak (days)", str(xp["streak"]), "#fbbf24")
    _metric_card(c4, "XP to Next Level", str(xp["xp_to_next"]), "#8888a3")

    st.markdown("<div style='height:1rem'></div>", unsafe_allow_html=True)

    if data["insufficient_data"]:
        _insufficient_data_banner("Complete a few more sessions to unlock weekly activity trends.")
        return

    if data["tests_per_week"]:
        import plotly.graph_objects as go
        weeks = list(data["tests_per_week"].keys())
        counts = list(data["tests_per_week"].values())
        fig = go.Figure(go.Bar(x=weeks, y=counts, marker_color="#7c6ef5"))
        fig.update_layout(
            title="Tests per Week", height=250,
            paper_bgcolor="#0a0a0f", plot_bgcolor="#0a0a0f",
            font={"color": "#f2f2f8"}, margin=dict(l=30, r=30, t=40, b=10),
        )
        st.plotly_chart(fig, use_container_width=True)

    drop_off = data["drop_off"]
    if drop_off and drop_off["flagged"]:
        st.warning(
            f"Engagement drop-off detected — {drop_off['days_since_last_activity']:.0f} days "
            f"since last activity (typical gap: {drop_off['historical_median_gap_days']:.1f} days)."
        )


def _render_reliability_tab(data: dict) -> None:
    if data["insufficient_data"]:
        _insufficient_data_banner("Generate or take a few more tests to unlock reliability metrics.")
        return

    ollama = data["ollama"]
    c1, c2, c3 = st.columns(3)
    _metric_card(
        c1, "Ollama Success Rate",
        f"{ollama['success_rate']:.0%} (N={ollama['n_calls']})" if ollama["success_rate"] is not None else "—",
        "#4ade80",
    )
    _metric_card(
        c2, "Mean Latency",
        f"{ollama['latency_mean_s']:.2f}s" if ollama["latency_mean_s"] is not None else "—",
        "#7c6ef5",
    )
    p95_label = f"{ollama['latency_p95_s']:.2f}s" if ollama["latency_p95_s"] is not None else ollama["p95_note"]
    _metric_card(c3, "P95 Latency", p95_label, "#fbbf24")

    gen = data["test_generation"]
    st.markdown("<div style='height:1rem'></div>", unsafe_allow_html=True)
    if gen["cache_hit_rate"] is not None:
        st.metric("Test Generation Cache-Hit Rate", f"{gen['cache_hit_rate']:.0%}", help=f"N={gen['n_generations']}")

    errors = data["dashboard_errors"]
    if errors["count"]:
        st.markdown(f"**Dashboard Errors** ({errors['count']} total)")
        for e in errors["recent"]:
            st.markdown(
                f"<div style='border-left:3px solid #f87171;padding:4px 10px;margin-bottom:4px;"
                f"font-size:0.8rem;'>{e.get('context', e.get('page', '?'))}: {e.get('error', '')}</div>",
                unsafe_allow_html=True,
            )
    else:
        st.caption("No dashboard errors logged.")


def page_system_evaluation() -> None:
    ss = st.session_state
    student_id = ss.get("student_id", "default")

    st.markdown("""
    <div style="font-family:'Plus Jakarta Sans',sans-serif;font-size:1.6rem;
                font-weight:800;color:#f2f2f8;padding:0.5rem 0 1rem;">
      📊 System Evaluation
    </div>
    """, unsafe_allow_html=True)

    with st.spinner("Computing evaluation metrics…"):
        try:
            from evaluation.system_evaluator import evaluate_all
            report = evaluate_all(student_id)
        except Exception as exc:
            st.error(f"Could not compute system evaluation: {exc}")
            return

    tab_learning, tab_grading, tab_engagement, tab_reliability = st.tabs(
        ["🎓 Learning", "🧪 AI Grading", "🔥 Engagement", "⚙️ Reliability"]
    )
    with tab_learning:
        _render_learning_tab(report["learning_outcomes"])
    with tab_grading:
        _render_grading_tab(report["grading_accuracy"])
    with tab_engagement:
        _render_engagement_tab(report["engagement"])
    with tab_reliability:
        _render_reliability_tab(report["reliability"])

    st.caption(f"Generated at {report['generated_at']}")
