"""Friends & chat page — talks only to social_server (see social_client.py).

No lesson content, AI interaction, progress, or knowledge-graph data is
ever sent here. The only academic-looking data that can leave the machine
is what a student explicitly opts into via the "Discoverable" toggle below
(current domain + current module — nothing else).
"""

import streamlit as st

from dashboard import social_client
from dashboard.social_client import SocialClientError


def _connect_panel(ss) -> None:
    """Shown when this browser session has no social_server session yet."""
    st.markdown("""
    <div style="text-align:center;padding:1.5rem 0 1rem;">
      <div style="font-family:'Plus Jakarta Sans',sans-serif;font-size:1.8rem;
                  font-weight:800;color:#f2f2f8;">
        👋 Connect with other students
      </div>
      <p style="color:#a3a3bd;font-size:0.95rem;max-width:480px;margin:0.4rem auto;">
        Friends and chat run through a small separate service — your lessons,
        tests, and progress never touch it. Log in or create a social profile
        to get started.
      </p>
    </div>
    """, unsafe_allow_html=True)

    col_l, col_mid, col_r = st.columns([1, 2, 1])
    with col_mid:
        tab_login, tab_register = st.tabs(["🔑  Log In", "✨  Create Profile"])

        with tab_login:
            email = st.text_input("Email", key="social_li_email")
            password = st.text_input("Password", type="password", key="social_li_password")
            if st.button("Log In", type="primary", use_container_width=True, key="social_li_btn"):
                try:
                    result = social_client.login(email, password)
                    _apply_social_session(ss, result)
                    st.rerun()
                except SocialClientError as exc:
                    st.error(str(exc))

        with tab_register:
            name = st.text_input("Display name", key="social_rg_name")
            r_email = st.text_input("Email", key="social_rg_email")
            r_password = st.text_input("Password (min 8 characters)", type="password", key="social_rg_password")
            if st.button("Create Profile", type="primary", use_container_width=True, key="social_rg_btn"):
                try:
                    result = social_client.register(r_email, name, r_password)
                    _apply_social_session(ss, result)
                    st.rerun()
                except SocialClientError as exc:
                    st.error(str(exc))


def _apply_social_session(ss, auth_result: dict) -> None:
    ss["social_token"] = auth_result["token"]
    ss["social_id"] = auth_result["social_id"]
    ss["social_display_name"] = auth_result["display_name"]
    ss["_chat_since"] = {}


def _discoverability_panel(ss) -> None:
    try:
        me = social_client.get_me(ss["social_token"])
    except SocialClientError as exc:
        st.warning(f"Couldn't load your social profile: {exc}")
        return

    with st.expander("🔎 Discoverability — let other students studying the same thing find you"):
        current_domain = ss.get("domain", "")
        st.caption(
            f"Your current course in this app: **{current_domain or 'none selected yet'}**. "
            "Turning this on shares only that domain + module — never lesson content, "
            "test results, or anything else."
        )
        new_state = st.toggle("Make me discoverable", value=me["discoverable"], key="social_discoverable_toggle")
        if new_state != me["discoverable"]:
            try:
                idx = ss.get("current_module_idx", 0)
                roadmap = ss.get("roadmap") or {}
                modules = roadmap.get("modules", [])
                module_title = modules[idx]["title"] if idx < len(modules) else ""
                social_client.update_me(
                    ss["social_token"],
                    discoverable=new_state,
                    current_domain=current_domain,
                    current_module=module_title,
                )
                st.rerun()
            except SocialClientError as exc:
                st.error(f"Couldn't update discoverability: {exc}")


def _requests_tab(ss) -> None:
    try:
        pending = social_client.list_pending_requests(ss["social_token"])
    except SocialClientError as exc:
        st.error(f"Couldn't load requests: {exc}")
        return

    incoming = [p for p in pending if p["direction"] == "incoming"]
    outgoing = [p for p in pending if p["direction"] == "outgoing"]

    st.markdown("**Add a friend by email**")
    add_col1, add_col2 = st.columns([3, 1])
    with add_col1:
        friend_email = st.text_input("Friend's email", key="add_friend_email", label_visibility="collapsed",
                                       placeholder="friend@example.com")
    with add_col2:
        if st.button("Send request", use_container_width=True) and friend_email:
            try:
                social_client.send_friend_request(ss["social_token"], friend_email.strip())
                st.success("Friend request sent!")
                st.rerun()
            except SocialClientError as exc:
                st.error(str(exc))

    st.markdown("---")
    if incoming:
        st.markdown(f"**Incoming requests ({len(incoming)})**")
        for req in incoming:
            c1, c2, c3 = st.columns([3, 1, 1])
            c1.write(req["display_name"])
            if c2.button("Accept", key=f"accept_{req['friendship_id']}"):
                try:
                    social_client.accept_friend_request(ss["social_token"], req["friendship_id"])
                    st.rerun()
                except SocialClientError as exc:
                    st.error(str(exc))
            if c3.button("Reject", key=f"reject_{req['friendship_id']}"):
                try:
                    social_client.reject_friend_request(ss["social_token"], req["friendship_id"])
                    st.rerun()
                except SocialClientError as exc:
                    st.error(str(exc))

    if outgoing:
        st.markdown(f"**Waiting on a response ({len(outgoing)})**")
        for req in outgoing:
            st.caption(f"⏳ {req['display_name']}")

    if not incoming and not outgoing:
        st.caption("No pending requests.")


def _discover_tab(ss) -> None:
    domain = ss.get("domain", "")
    st.caption(
        f"Showing discoverable students currently learning **{domain}**"
        if domain else "Pick a domain in the app to search students learning the same thing."
    )
    if not domain:
        return
    try:
        matches = social_client.discover(ss["social_token"], domain=domain)
    except SocialClientError as exc:
        st.error(f"Couldn't search: {exc}")
        return

    if not matches:
        st.caption("No discoverable students found for this domain yet.")
        return

    for m in matches:
        c1, c2 = st.columns([4, 1])
        status = "🟢 online" if m["online"] else "⚪ offline"
        c1.write(f"**{m['display_name']}** — {m['current_module'] or domain} · {status}")
        if c2.button("Add friend", key=f"discover_add_{m['social_id']}"):
            try:
                social_client.send_friend_request_by_id(ss["social_token"], m["social_id"])
                st.success(f"Friend request sent to {m['display_name']}!")
                st.rerun()
            except SocialClientError as exc:
                st.error(str(exc))


def _chat_panel(ss) -> None:
    try:
        friends = social_client.list_friends(ss["social_token"])
    except SocialClientError as exc:
        st.error(f"Couldn't load friends: {exc}")
        return

    if not friends:
        st.caption("No friends yet — send a request from the Requests tab.")
        return

    names = [f"{f['display_name']} {'🟢' if f['online'] else '⚪'}" for f in friends]
    idx = st.selectbox("Chat with", range(len(friends)), format_func=lambda i: names[i], key="chat_friend_idx")
    friend = friends[idx]

    from streamlit_autorefresh import st_autorefresh
    st_autorefresh(interval=3000, limit=None, key="friends_chat_tick")

    since_map = ss.setdefault("_chat_since", {})
    since_map.setdefault(friend["social_id"], None)

    all_msgs = ss.setdefault("_chat_history", {})
    history = all_msgs.setdefault(friend["social_id"], [])

    try:
        new_msgs = social_client.get_direct_messages(
            ss["social_token"], friend["social_id"], since=since_map[friend["social_id"]]
        )
        if new_msgs:
            history.extend(new_msgs)
            since_map[friend["social_id"]] = new_msgs[-1]["created_at"]
    except SocialClientError as exc:
        st.caption(f"(couldn't refresh messages: {exc})")

    chat_box = st.container(height=360)
    with chat_box:
        for msg in history:
            is_me = msg["sender_id"] == ss["social_id"]
            align = "flex-end" if is_me else "flex-start"
            bg = "#7c6ef5" if is_me else "rgba(255,255,255,0.06)"
            color = "#ffffff" if is_me else "#f2f2f8"
            st.markdown(f"""
            <div style="display:flex;justify-content:{align};margin:4px 0;">
              <div style="background:{bg};color:{color};padding:8px 12px;border-radius:12px;
                          max-width:70%;font-size:0.88rem;">
                {msg['body']}
              </div>
            </div>
            """, unsafe_allow_html=True)

    with st.form(key="chat_send_form", clear_on_submit=True):
        body = st.text_input("Message", label_visibility="collapsed", placeholder=f"Message {friend['display_name']}…")
        if st.form_submit_button("Send", use_container_width=True) and body.strip():
            try:
                social_client.send_direct_message(ss["social_token"], friend["social_id"], body.strip())
                st.rerun()
            except SocialClientError as exc:
                st.error(str(exc))


def page_friends() -> None:
    ss = st.session_state

    if not ss.get("social_token"):
        _connect_panel(ss)
        return

    st.markdown(f"""
    <div style="padding:0.5rem 0 0.5rem;">
      <div style="font-family:'Plus Jakarta Sans',sans-serif;font-size:1.6rem;font-weight:800;color:#f2f2f8;">
        👥 Friends — connected as {ss.get('social_display_name', '')}
      </div>
    </div>
    """, unsafe_allow_html=True)

    _discoverability_panel(ss)

    tab_chat, tab_requests, tab_discover = st.tabs(["💬 Chat", "🤝 Requests", "🔎 Find Students"])
    with tab_chat:
        _chat_panel(ss)
    with tab_requests:
        _requests_tab(ss)
    with tab_discover:
        _discover_tab(ss)
