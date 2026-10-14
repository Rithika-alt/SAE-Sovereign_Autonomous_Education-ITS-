"""Thin HTTP client for the social_server API (friends/chat).

This is the only place in the dashboard that talks to a networked service
other than Ollama-adjacent local infra — everything here is scoped to
social data (accounts, friendships, messages). No lesson content, AI
interaction, progress, or knowledge-graph data is ever sent through this
client; see social_server/README.md for the boundary.
"""

import os
from typing import Dict, List, Optional

import requests

_TIMEOUT = 6  # seconds — the social server is a small local-network-ish call, not an LLM


class SocialClientError(Exception):
    """Raised for any non-2xx response, message pulled from the API's detail field."""


def _base_url() -> str:
    return os.getenv("SOCIAL_SERVER_URL", "http://localhost:8000").rstrip("/")


def _headers(token: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _request(method: str, path: str, token: Optional[str] = None, **kwargs):
    url = f"{_base_url()}{path}"
    headers = _headers(token) if token else {}
    try:
        resp = requests.request(method, url, headers=headers, timeout=_TIMEOUT, **kwargs)
    except requests.exceptions.RequestException as exc:
        raise SocialClientError(f"Could not reach the social server at {_base_url()}: {exc}") from exc

    if not resp.ok:
        try:
            detail = resp.json().get("detail", resp.text)
        except Exception:
            detail = resp.text
        raise SocialClientError(str(detail))
    return resp.json() if resp.content else None


# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------

def register(email: str, display_name: str, password: str) -> Dict:
    return _request("POST", "/accounts/register", json={
        "email": email, "display_name": display_name, "password": password,
    })


def login(email: str, password: str) -> Dict:
    return _request("POST", "/accounts/login", json={"email": email, "password": password})


def get_me(token: str) -> Dict:
    return _request("GET", "/accounts/me", token=token)


def update_me(token: str, **fields) -> Dict:
    """fields: display_name, discoverable, current_domain, current_module (any subset)."""
    return _request("PATCH", "/accounts/me", token=token, json=fields)


def discover(token: str, domain: str = "") -> List[Dict]:
    params = {"domain": domain} if domain else {}
    return _request("GET", "/accounts/discover", token=token, params=params)


# ---------------------------------------------------------------------------
# Friends
# ---------------------------------------------------------------------------

def send_friend_request(token: str, email: str) -> Dict:
    return _request("POST", "/friends/request", token=token, json={"email": email})


def send_friend_request_by_id(token: str, target_social_id: str) -> Dict:
    return _request("POST", "/friends/request_by_id", token=token, json={"social_id": target_social_id})


def accept_friend_request(token: str, friendship_id: int) -> Dict:
    return _request("POST", f"/friends/{friendship_id}/accept", token=token)


def reject_friend_request(token: str, friendship_id: int) -> Dict:
    return _request("POST", f"/friends/{friendship_id}/reject", token=token)


def list_friends(token: str) -> List[Dict]:
    return _request("GET", "/friends", token=token)


def list_pending_requests(token: str) -> List[Dict]:
    return _request("GET", "/friends/requests", token=token)


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------

def send_direct_message(token: str, recipient_social_id: str, body: str) -> Dict:
    return _request("POST", "/messages", token=token, json={
        "recipient_social_id": recipient_social_id, "body": body,
    })


def get_direct_messages(token: str, with_social_id: str, since: Optional[str] = None) -> List[Dict]:
    params = {"with": with_social_id}
    if since:
        params["since"] = since
    return _request("GET", "/messages", token=token, params=params)


def create_room(token: str, name: str, member_emails: Optional[List[str]] = None) -> Dict:
    return _request("POST", "/rooms", token=token, json={
        "name": name, "member_emails": member_emails or [],
    })


def list_rooms(token: str) -> List[Dict]:
    return _request("GET", "/rooms", token=token)


def send_room_message(token: str, room_id: str, body: str) -> Dict:
    return _request("POST", "/messages", token=token, json={"room_id": room_id, "body": body})


def get_room_messages(token: str, room_id: str, since: Optional[str] = None) -> List[Dict]:
    params = {"since": since} if since else {}
    return _request("GET", f"/rooms/{room_id}/messages", token=token, params=params)
