"""Login and registration page for the SAE System."""

import streamlit as st


def page_login() -> None:
    ss = st.session_state

    st.markdown("""
    <style>
    /* ── Force dark visible labels on every input on this page ── */
    .stTextInput label p,
    .stTextInput label {
        color: #1a1a2e !important;
        font-weight: 600 !important;
        font-size: 0.88rem !important;
    }

    /* ── Input box border styling ── */
    .stTextInput input {
        border: 1.5px solid #d1d5db !important;
        border-radius: 10px !important;
        padding: 0.55rem 0.75rem !important;
        font-size: 0.95rem !important;
        color: #1a1a2e !important;
        background: #fafafa !important;
    }
    .stTextInput input:focus {
        border-color: #667eea !important;
        box-shadow: 0 0 0 3px rgba(102,126,234,0.15) !important;
        background: #ffffff !important;
    }

    /* ── Tab styling ── */
    .stTabs [data-baseweb="tab"] {
        font-weight: 600;
        font-size: 0.9rem;
    }

    /* ── Button ── */
    .stButton > button[kind="primary"] {
        background: linear-gradient(135deg, #667eea, #764ba2) !important;
        border: none !important;
        border-radius: 10px !important;
        font-weight: 700 !important;
        font-size: 0.95rem !important;
        padding: 0.6rem !important;
        margin-top: 0.4rem;
    }
    </style>
    """, unsafe_allow_html=True)

    # ── Logo ────────────────────────────────────────────────────────────────
    st.markdown("""
    <div style="text-align:center;padding:2.5rem 0 1.5rem;">
      <div style="font-size:3rem;margin-bottom:0.5rem;">🎓</div>
      <div style="font-family:'Plus Jakarta Sans',sans-serif;font-size:2rem;font-weight:800;
                  background:linear-gradient(135deg,#667eea,#764ba2);
                  -webkit-background-clip:text;-webkit-text-fill-color:transparent;">
        SAE System
      </div>
      <div style="font-size:0.75rem;color:#9ca3af;letter-spacing:2px;margin-top:4px;">
        SOVEREIGN LEARNING
      </div>
    </div>
    """, unsafe_allow_html=True)

    # ── Tabs ─────────────────────────────────────────────────────────────────
    col_l, col_mid, col_r = st.columns([1, 2, 1])
    with col_mid:
        tab_login, tab_register = st.tabs(["🔑  Log In", "✨  Create Account"])

        # ── LOGIN TAB ────────────────────────────────────────────────────────
        with tab_login:
            st.markdown("<div style='height:0.6rem'></div>", unsafe_allow_html=True)

            st.markdown("**Email address**")
            email_in = st.text_input(
                "Email address",
                placeholder="you@example.com",
                key="li_email",
                label_visibility="collapsed",
            )

            st.markdown("**Password**")
            password_in = st.text_input(
                "Password",
                placeholder="Enter your password",
                type="password",
                key="li_password",
                label_visibility="collapsed",
            )

            st.markdown("<div style='height:0.4rem'></div>", unsafe_allow_html=True)

            if st.button("Log In", use_container_width=True, type="primary", key="btn_login"):
                if not email_in or not password_in:
                    st.error("Please enter both your email and password.")
                else:
                    with st.spinner("Checking credentials…"):
                        from auth.auth import login
                        ok, msg, student = login(email_in, password_in)
                    if ok:
                        _apply_session(ss, student)
                        st.success(msg)
                        st.rerun()
                    else:
                        st.error(msg)

            st.markdown("""
            <div style="text-align:center;margin-top:1rem;font-size:0.8rem;color:#9ca3af;">
              Don't have an account? Switch to the <strong>Create Account</strong> tab above.
            </div>
            """, unsafe_allow_html=True)

        # ── REGISTER TAB ─────────────────────────────────────────────────────
        with tab_register:
            st.markdown("<div style='height:0.6rem'></div>", unsafe_allow_html=True)

            st.markdown("**Full Name**")
            r_name = st.text_input(
                "Full Name",
                placeholder="e.g. Jane Smith",
                key="rg_name",
                label_visibility="collapsed",
            )

            st.markdown("**Username**")
            r_username = st.text_input(
                "Username",
                placeholder="e.g. janesmith  (letters, numbers, _ and - only)",
                key="rg_username",
                label_visibility="collapsed",
            )

            st.markdown("**Email address**")
            r_email = st.text_input(
                "Email address",
                placeholder="e.g. jane@example.com",
                key="rg_email",
                label_visibility="collapsed",
            )

            st.markdown("**Password**")
            r_password = st.text_input(
                "Password",
                placeholder="Minimum 8 characters",
                type="password",
                key="rg_password",
                label_visibility="collapsed",
            )

            st.markdown("**Confirm Password**")
            r_confirm = st.text_input(
                "Confirm Password",
                placeholder="Repeat your password",
                type="password",
                key="rg_confirm",
                label_visibility="collapsed",
            )

            st.markdown("<div style='height:0.4rem'></div>", unsafe_allow_html=True)

            if st.button("Create Account", use_container_width=True, type="primary", key="btn_register"):
                with st.spinner("Creating your account…"):
                    from auth.auth import register
                    ok, msg = register(r_name, r_username, r_email, r_password, r_confirm)
                if ok:
                    st.success(msg + "  Switch to the Log In tab.")
                else:
                    st.error(msg)

            st.markdown("""
            <div style="text-align:center;margin-top:1rem;font-size:0.8rem;color:#9ca3af;">
              Already have an account? Switch to the <strong>Log In</strong> tab above.
            </div>
            """, unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _apply_session(ss, student: dict) -> None:
    ss["auth_token"]       = student["token"]
    ss["student_id"]       = student["student_id"]
    ss["student_name"]     = student["name"]
    ss["student_email"]    = student["email"]
    ss["student_username"] = student["username"]
    # Restore last saved domain + progress so the student continues where they left off
    try:
        from persistence.progress_store import load_progress
        sid    = student["student_id"]
        domain = student.get("domain", "")
        if domain:
            saved = load_progress(sid, domain)
            ss["domain"]           = domain
            ss["modules_passed"]   = saved["modules_passed"]
            ss["modules_unlocked"] = saved["modules_unlocked"]
            ss["module_progress"]  = saved["module_progress"]
        elif not ss.get("domain"):
            ss["domain"] = ""
    except Exception:
        if student.get("domain") and not ss.get("domain"):
            ss["domain"] = student["domain"]
