"""Friend request / accept / reject / list endpoints."""

from fastapi import APIRouter, Depends, HTTPException, status

from app.db import get_connection
from app.dependencies import get_current_social_id
from app.presence import is_online
from app.schemas import FriendRequestBySocialId, FriendRequestCreate, FriendshipOut

router = APIRouter(prefix="/friends", tags=["friends"])


def _create_friendship(conn, social_id: str, target_id: str) -> int:
    if target_id == social_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "You can't friend yourself.")

    with conn.cursor() as cur:
        cur.execute(
            """SELECT id, status FROM friendships
               WHERE (requester_id = %s AND addressee_id = %s)
                  OR (requester_id = %s AND addressee_id = %s)""",
            (social_id, target_id, target_id, social_id),
        )
        existing = cur.fetchone()
    if existing:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Friendship already exists (status: {existing['status']}).",
        )

    with conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO friendships (requester_id, addressee_id, status)
                   VALUES (%s, %s, 'pending') RETURNING id""",
                (social_id, target_id),
            )
            return cur.fetchone()["id"]


@router.post("/request", status_code=status.HTTP_201_CREATED)
def send_friend_request(body: FriendRequestCreate, social_id: str = Depends(get_current_social_id)):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT social_id FROM social_accounts WHERE email = %s", (body.email.lower(),)
            )
            target = cur.fetchone()
        if not target:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "No account found with that email.")

        new_id = _create_friendship(conn, social_id, target["social_id"])
    finally:
        conn.close()

    return {"friendship_id": new_id, "status": "pending"}


@router.post("/request_by_id", status_code=status.HTTP_201_CREATED)
def send_friend_request_by_id(body: FriendRequestBySocialId, social_id: str = Depends(get_current_social_id)):
    """Same as /request but by social_id — used by the "Find Students"
    discovery flow, which only ever sees social_id (not email) for
    students who opted into discoverability."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM social_accounts WHERE social_id = %s", (body.social_id,))
            if not cur.fetchone():
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Account not found.")

        new_id = _create_friendship(conn, social_id, body.social_id)
    finally:
        conn.close()

    return {"friendship_id": new_id, "status": "pending"}


def _respond_to_request(friendship_id: int, social_id: str, new_status: str) -> dict:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM friendships WHERE id = %s", (friendship_id,))
            row = cur.fetchone()
        if not row:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Friend request not found.")
        if row["addressee_id"] != social_id:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the recipient can respond to this request.")
        if row["status"] != "pending":
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Request already {row['status']}.")

        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE friendships SET status = %s WHERE id = %s", (new_status, friendship_id)
                )
    finally:
        conn.close()

    return {"friendship_id": friendship_id, "status": new_status}


@router.post("/{friendship_id}/accept")
def accept_friend_request(friendship_id: int, social_id: str = Depends(get_current_social_id)):
    return _respond_to_request(friendship_id, social_id, "accepted")


@router.post("/{friendship_id}/reject")
def reject_friend_request(friendship_id: int, social_id: str = Depends(get_current_social_id)):
    return _respond_to_request(friendship_id, social_id, "rejected")


@router.get("", response_model=list[FriendshipOut])
def list_friends(social_id: str = Depends(get_current_social_id)):
    """Accepted friends only — see /friends/requests for pending ones."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT f.id AS friendship_id, a.social_id, a.display_name, a.last_seen,
                          f.status,
                          CASE WHEN f.requester_id = %s THEN 'outgoing' ELSE 'incoming' END AS direction
                   FROM friendships f
                   JOIN social_accounts a
                     ON a.social_id = CASE WHEN f.requester_id = %s THEN f.addressee_id ELSE f.requester_id END
                   WHERE (f.requester_id = %s OR f.addressee_id = %s) AND f.status = 'accepted'
                   ORDER BY a.display_name""",
                (social_id, social_id, social_id, social_id),
            )
            rows = cur.fetchall()
    finally:
        conn.close()

    return [
        FriendshipOut(
            friendship_id=r["friendship_id"],
            social_id=r["social_id"],
            display_name=r["display_name"],
            status=r["status"],
            online=is_online(r["last_seen"]),
            direction=r["direction"],
        )
        for r in rows
    ]


@router.get("/requests", response_model=list[FriendshipOut])
def list_pending_requests(social_id: str = Depends(get_current_social_id)):
    """Both incoming (need my response) and outgoing (I'm waiting) pending requests."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT f.id AS friendship_id, a.social_id, a.display_name, a.last_seen,
                          f.status,
                          CASE WHEN f.requester_id = %s THEN 'outgoing' ELSE 'incoming' END AS direction
                   FROM friendships f
                   JOIN social_accounts a
                     ON a.social_id = CASE WHEN f.requester_id = %s THEN f.addressee_id ELSE f.requester_id END
                   WHERE (f.requester_id = %s OR f.addressee_id = %s) AND f.status = 'pending'
                   ORDER BY f.created_at DESC""",
                (social_id, social_id, social_id, social_id),
            )
            rows = cur.fetchall()
    finally:
        conn.close()

    return [
        FriendshipOut(
            friendship_id=r["friendship_id"],
            social_id=r["social_id"],
            display_name=r["display_name"],
            status=r["status"],
            online=is_online(r["last_seen"]),
            direction=r["direction"],
        )
        for r in rows
    ]
