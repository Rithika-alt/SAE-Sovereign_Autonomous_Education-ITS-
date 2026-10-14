"""Registration, login, profile, and discovery endpoints."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.db import get_connection
from app.dependencies import get_current_social_id
from app.presence import is_online
from app.schemas import (
    AccountOut,
    AuthResponse,
    LoginRequest,
    ProfileUpdate,
    RegisterRequest,
)
from app.security import create_session, hash_password, verify_password

router = APIRouter(prefix="/accounts", tags=["accounts"])


@router.post("/register", response_model=AuthResponse)
def register(body: RegisterRequest):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM social_accounts WHERE email = %s", (body.email.lower(),))
            if cur.fetchone():
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "An account with that email already exists.")

        social_id = str(uuid.uuid4())
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO social_accounts (social_id, email, display_name, password_hash)
                       VALUES (%s, %s, %s, %s)""",
                    (social_id, body.email.lower(), body.display_name.strip(), hash_password(body.password)),
                )
    finally:
        conn.close()

    token = create_session(social_id)
    return AuthResponse(social_id=social_id, display_name=body.display_name.strip(), token=token)


@router.post("/login", response_model=AuthResponse)
def login(body: LoginRequest):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT social_id, display_name, password_hash FROM social_accounts WHERE email = %s",
                (body.email.lower(),),
            )
            row = cur.fetchone()
    finally:
        conn.close()

    if not row or not verify_password(body.password, row["password_hash"]):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect email or password.")

    token = create_session(row["social_id"])
    return AuthResponse(social_id=row["social_id"], display_name=row["display_name"], token=token)


@router.get("/me", response_model=AccountOut)
def get_me(social_id: str = Depends(get_current_social_id)):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT social_id, display_name, discoverable, current_domain,
                          current_module, last_seen
                   FROM social_accounts WHERE social_id = %s""",
                (social_id,),
            )
            row = cur.fetchone()
    finally:
        conn.close()

    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Account not found.")
    return AccountOut(**{**row, "online": is_online(row["last_seen"])})


@router.patch("/me", response_model=AccountOut)
def update_me(body: ProfileUpdate, social_id: str = Depends(get_current_social_id)):
    fields, values = [], []
    for col in ("display_name", "discoverable", "current_domain", "current_module"):
        val = getattr(body, col)
        if val is not None:
            fields.append(f"{col} = %s")
            values.append(val)

    conn = get_connection()
    try:
        if fields:
            values.append(social_id)
            with conn:
                with conn.cursor() as cur:
                    cur.execute(
                        f"UPDATE social_accounts SET {', '.join(fields)} WHERE social_id = %s",
                        values,
                    )

        with conn.cursor() as cur:
            cur.execute(
                """SELECT social_id, display_name, discoverable, current_domain,
                          current_module, last_seen
                   FROM social_accounts WHERE social_id = %s""",
                (social_id,),
            )
            row = cur.fetchone()
    finally:
        conn.close()

    return AccountOut(**{**row, "online": is_online(row["last_seen"])})


@router.get("/discover", response_model=list[AccountOut])
def discover(
    domain: str = Query(default=""),
    social_id: str = Depends(get_current_social_id),
):
    """List discoverable accounts, optionally filtered by current_domain.

    Only ever returns accounts that opted in via discoverable=true — this is
    the one place student learning activity (domain/module) is visible to
    anyone beyond the student themself, and it's explicit opt-in.
    """
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            if domain:
                cur.execute(
                    """SELECT social_id, display_name, discoverable, current_domain,
                              current_module, last_seen
                       FROM social_accounts
                       WHERE discoverable = TRUE AND social_id != %s AND current_domain = %s
                       ORDER BY last_seen DESC NULLS LAST LIMIT 50""",
                    (social_id, domain),
                )
            else:
                cur.execute(
                    """SELECT social_id, display_name, discoverable, current_domain,
                              current_module, last_seen
                       FROM social_accounts
                       WHERE discoverable = TRUE AND social_id != %s
                       ORDER BY last_seen DESC NULLS LAST LIMIT 50""",
                    (social_id,),
                )
            rows = cur.fetchall()
    finally:
        conn.close()

    return [AccountOut(**{**r, "online": is_online(r["last_seen"])}) for r in rows]
