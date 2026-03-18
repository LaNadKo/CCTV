"""Home/Room/Member Pydantic schemas."""
from __future__ import annotations
from datetime import datetime
from pydantic import BaseModel


class HomeCreate(BaseModel):
    name: str
    description: str | None = None


class HomeUpdate(BaseModel):
    name: str | None = None
    description: str | None = None


class HomeOut(BaseModel):
    home_id: int
    name: str
    description: str | None = None
    created_at: datetime
    member_count: int = 0
    room_count: int = 0
    my_role: str | None = None


class RoomCreate(BaseModel):
    name: str
    order_index: int = 0


class RoomUpdate(BaseModel):
    name: str | None = None
    order_index: int | None = None


class RoomCameraOut(BaseModel):
    room_id: int
    camera_id: int
    camera_name: str
    added_at: datetime


class RoomOut(BaseModel):
    room_id: int
    home_id: int
    name: str
    order_index: int
    created_at: datetime
    cameras: list[RoomCameraOut] = []


class InviteCreate(BaseModel):
    role: str = "member"
    invite_type: str = "link"
    target_email: str | None = None
    expires_hours: int = 72


class InviteOut(BaseModel):
    invitation_id: int
    invite_code: str
    invite_type: str
    role: str
    expires_at: datetime | None = None
    accepted_at: datetime | None = None


class JoinByCode(BaseModel):
    invite_code: str


class MemberOut(BaseModel):
    user_id: int
    login: str
    role: str
    joined_at: datetime


class MemberRoleUpdate(BaseModel):
    role: str


class TransferOwnership(BaseModel):
    new_owner_user_id: int


class ActivityOut(BaseModel):
    activity_id: int
    user_id: int | None = None
    user_login: str | None = None
    action: str
    details: dict | None = None
    created_at: datetime


class HomeDetailOut(BaseModel):
    home_id: int
    name: str
    description: str | None = None
    created_at: datetime
    my_role: str | None = None
    rooms: list[RoomOut] = []
    members: list[MemberOut] = []
