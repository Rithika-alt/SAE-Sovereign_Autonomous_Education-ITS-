"""1:1 and group-room messaging endpoints — REST + polling (see GET .../since)."""

import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.db import get_connection
from app.dependencies import get_current_social_id
from app.schemas import MessageCreate, MessageOut, RoomCreate, RoomOut

router = APIRouter(tags=["messages"])


def _are_friends(conn, a: str, b: str) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            """SELECT 1 FROM friendships
               WHERE status = 'accepted'
                 AND ((requester_id = %s AND addressee_id = %s)
                   OR (requester_id = %s AND addressee_id = %s))""",
            (a, b, b, a),
        )
        return cur.fetchone() is not None


def _is_room_member(conn, room_id: str, social_id: str) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM room_members WHERE room_id = %s AND social_id = %s",
            (room_id, social_id),
        )
        return cur.fetchone() is not None


@router.post("/messages", response_model=MessageOut, status_code=status.HTTP_201_CREATED)
def send_message(body: MessageCreate, social_id: str = Depends(get_current_social_id)):
    if not body.recipient_social_id and not body.room_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Must set recipient_social_id or room_id.")
    if body.recipient_social_id and body.room_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Set only one of recipient_social_id or room_id.")

    conn = get_connection()
    try:
        if body.recipient_social_id:
            if not _are_friends(conn, social_id, body.recipient_social_id):
                raise HTTPException(status.HTTP_403_FORBIDDEN, "You can only message accepted friends.")
        else:
            if not _is_room_member(conn, body.room_id, social_id):
                raise HTTPException(status.HTTP_403_FORBIDDEN, "You're not a member of that room.")

        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO messages (sender_id, recipient_id, room_id, body)
                       VALUES (%s, %s, %s, %s)
                       RETURNING id, sender_id, recipient_id, room_id, body, created_at""",
                    (social_id, body.recipient_social_id, body.room_id, body.body),
                )
                row = cur.fetchone()

        with conn.cursor() as cur:
            cur.execute("SELECT display_name FROM social_accounts WHERE social_id = %s", (social_id,))
            sender_name = cur.fetchone()["display_name"]
    finally:
        conn.close()

    return MessageOut(
        id=row["id"], sender_id=row["sender_id"], sender_name=sender_name,
        recipient_id=row["recipient_id"], room_id=row["room_id"],
        body=row["body"], created_at=row["created_at"].isoformat(),
    )


@router.get("/messages", response_model=list[MessageOut])
def get_direct_messages(
    with_: str = Query(alias="with"),
    since: Optional[str] = Query(default=None),
    social_id: str = Depends(get_current_social_id),
):
    """Poll for messages exchanged with one friend. Pass `since` (ISO 8601,
    the created_at of the last message you already have) to fetch only new
    ones — this is what dashboard/social_client.py polls on a timer via
    streamlit-autorefresh."""
    conn = get_connection()
    try:
        if not _are_friends(conn, social_id, with_):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Not friends with that account.")

        since_dt = datetime.fromisoformat(since) if since else datetime(1970, 1, 1, tzinfo=timezone.utc)
        with conn.cursor() as cur:
            cur.execute(
                """SELECT m.id, m.sender_id, a.display_name AS sender_name,
                          m.recipient_id, m.room_id, m.body, m.created_at
                   FROM messages m JOIN social_accounts a ON a.social_id = m.sender_id
                   WHERE m.room_id IS NULL
                     AND ((m.sender_id = %s AND m.recipient_id = %s)
                       OR (m.sender_id = %s AND m.recipient_id = %s))
                     AND m.created_at > %s
                   ORDER BY m.created_at ASC LIMIT 200""",
                (social_id, with_, with_, social_id, since_dt),
            )
            rows = cur.fetchall()
    finally:
        conn.close()

    return [
        MessageOut(
            id=r["id"], sender_id=r["sender_id"], sender_name=r["sender_name"],
            recipient_id=r["recipient_id"], room_id=r["room_id"],
            body=r["body"], created_at=r["created_at"].isoformat(),
        )
        for r in rows
    ]


@router.post("/rooms", response_model=RoomOut, status_code=status.HTTP_201_CREATED)
def create_room(body: RoomCreate, social_id: str = Depends(get_current_social_id)):
    room_id = str(uuid.uuid4())
    conn = get_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO rooms (room_id, name, created_by) VALUES (%s, %s, %s)",
                    (room_id, body.name.strip(), social_id),
                )
                cur.execute(
                    "INSERT INTO room_members (room_id, social_id) VALUES (%s, %s)",
                    (room_id, social_id),
                )
                member_count = 1
                for email in body.member_emails:
                    cur.execute(
                        "SELECT social_id FROM social_accounts WHERE email = %s", (email.lower(),)
                    )
                    member = cur.fetchone()
                    if member and _are_friends(conn, social_id, member["social_id"]):
                        cur.execute(
                            """INSERT INTO room_members (room_id, social_id) VALUES (%s, %s)
                               ON CONFLICT DO NOTHING""",
                            (room_id, member["social_id"]),
                        )
                        member_count += 1
    finally:
        conn.close()

    return RoomOut(room_id=room_id, name=body.name.strip(), member_count=member_count)


@router.get("/rooms", response_model=list[RoomOut])
def list_rooms(social_id: str = Depends(get_current_social_id)):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT r.room_id, r.name, COUNT(rm2.social_id) AS member_count
                   FROM rooms r
                   JOIN room_members rm ON rm.room_id = r.room_id AND rm.social_id = %s
                   JOIN room_members rm2 ON rm2.room_id = r.room_id
                   GROUP BY r.room_id, r.name
                   ORDER BY r.name""",
                (social_id,),
            )
            rows = cur.fetchall()
    finally:
        conn.close()

    return [RoomOut(room_id=r["room_id"], name=r["name"], member_count=r["member_count"]) for r in rows]


@router.get("/rooms/{room_id}/messages", response_model=list[MessageOut])
def get_room_messages(
    room_id: str,
    since: Optional[str] = Query(default=None),
    social_id: str = Depends(get_current_social_id),
):
    conn = get_connection()
    try:
        if not _is_room_member(conn, room_id, social_id):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "You're not a member of that room.")

        since_dt = datetime.fromisoformat(since) if since else datetime(1970, 1, 1, tzinfo=timezone.utc)
        with conn.cursor() as cur:
            cur.execute(
                """SELECT m.id, m.sender_id, a.display_name AS sender_name,
                          m.recipient_id, m.room_id, m.body, m.created_at
                   FROM messages m JOIN social_accounts a ON a.social_id = m.sender_id
                   WHERE m.room_id = %s AND m.created_at > %s
                   ORDER BY m.created_at ASC LIMIT 200""",
                (room_id, since_dt),
            )
            rows = cur.fetchall()
    finally:
        conn.close()

    return [
        MessageOut(
            id=r["id"], sender_id=r["sender_id"], sender_name=r["sender_name"],
            recipient_id=r["recipient_id"], room_id=r["room_id"],
            body=r["body"], created_at=r["created_at"].isoformat(),
        )
        for r in rows
    ]
