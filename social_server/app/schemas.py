"""Pydantic request/response models for the social server API."""

from typing import Optional

from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    email: EmailStr
    display_name: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=8)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class AuthResponse(BaseModel):
    social_id: str
    display_name: str
    token: str


class ProfileUpdate(BaseModel):
    display_name: Optional[str] = None
    discoverable: Optional[bool] = None
    current_domain: Optional[str] = None
    current_module: Optional[str] = None


class AccountOut(BaseModel):
    social_id: str
    display_name: str
    discoverable: bool
    current_domain: str
    current_module: str
    online: bool


class FriendRequestCreate(BaseModel):
    email: EmailStr


class FriendRequestBySocialId(BaseModel):
    social_id: str


class FriendshipOut(BaseModel):
    friendship_id: int
    social_id: str
    display_name: str
    status: str
    online: bool
    direction: str  # "incoming" | "outgoing"


class MessageCreate(BaseModel):
    recipient_social_id: Optional[str] = None
    room_id: Optional[str] = None
    body: str = Field(min_length=1, max_length=4000)


class MessageOut(BaseModel):
    id: int
    sender_id: str
    sender_name: str
    recipient_id: Optional[str]
    room_id: Optional[str]
    body: str
    created_at: str


class RoomCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    member_emails: list[str] = Field(default_factory=list)


class RoomOut(BaseModel):
    room_id: str
    name: str
    member_count: int
