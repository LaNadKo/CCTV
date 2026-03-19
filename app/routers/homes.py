"""Homes management router (Xiaomi Home style)."""
from __future__ import annotations

import json
import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.db import get_session
from app.dependencies import get_current_user
from app.schemas.homes import (
    ActivityOut,
    HomeCreate,
    HomeDetailOut,
    HomeOut,
    HomeUpdate,
    InviteCreate,
    InviteOut,
    JoinByCode,
    MemberOut,
    MemberRoleUpdate,
    RoomCameraOut,
    RoomCreate,
    RoomOut,
    RoomUpdate,
    TransferOwnership,
)

router = APIRouter(prefix="/homes", tags=["homes"])

ROLE_LEVEL = {"guest": 0, "member": 1, "admin": 2, "owner": 3}


async def _get_membership(session: AsyncSession, home_id: int, user_id: int) -> models.HomeMember | None:
    result = await session.execute(
        select(models.HomeMember).where(
            models.HomeMember.home_id == home_id,
            models.HomeMember.user_id == user_id,
        )
    )
    return result.scalar_one_or_none()


async def _require_role(session: AsyncSession, home_id: int, user_id: int, min_role: str) -> models.HomeMember:
    m = await _get_membership(session, home_id, user_id)
    if not m:
        raise HTTPException(status_code=403, detail="Not a member of this home")
    if ROLE_LEVEL.get(m.role, 0) < ROLE_LEVEL.get(min_role, 0):
        raise HTTPException(status_code=403, detail=f"Requires at least {min_role} role")
    return m


async def _log_activity(session: AsyncSession, home_id: int, user_id: int, action: str, details: dict | None = None):
    session.add(models.HomeActivityLog(
        home_id=home_id,
        user_id=user_id,
        action=action,
        details=json.dumps(details) if details else None,
    ))


# ── Home CRUD ──

@router.post("", response_model=HomeOut, status_code=status.HTTP_201_CREATED)
async def create_home(
    payload: HomeCreate,
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user),
):
    home = models.Home(
        name=payload.name,
        description=payload.description,
        created_by_user_id=current_user.user_id,
    )
    session.add(home)
    await session.flush()
    session.add(models.HomeMember(
        home_id=home.home_id,
        user_id=current_user.user_id,
        role="owner",
    ))
    await _log_activity(session, home.home_id, current_user.user_id, "home_created", {"name": payload.name})
    await session.commit()
    await session.refresh(home)
    return HomeOut(
        home_id=home.home_id,
        name=home.name,
        description=home.description,
        created_at=home.created_at,
        member_count=1,
        room_count=0,
        my_role="owner",
    )


@router.get("", response_model=list[HomeOut])
async def list_homes(
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user),
):
    # system_admin sees all, others see their memberships
    if current_user.role_id == 1:
        result = await session.execute(select(models.Home))
    else:
        stmt = (
            select(models.Home)
            .join(models.HomeMember, models.HomeMember.home_id == models.Home.home_id)
            .where(models.HomeMember.user_id == current_user.user_id)
        )
        result = await session.execute(stmt)
    homes = result.scalars().all()
    out = []
    for h in homes:
        mc = await session.execute(select(func.count()).where(models.HomeMember.home_id == h.home_id))
        rc = await session.execute(select(func.count()).where(models.Room.home_id == h.home_id))
        m = await _get_membership(session, h.home_id, current_user.user_id)
        out.append(HomeOut(
            home_id=h.home_id,
            name=h.name,
            description=h.description,
            created_at=h.created_at,
            member_count=mc.scalar() or 0,
            room_count=rc.scalar() or 0,
            my_role=m.role if m else None,
        ))
    return out


@router.get("/{home_id}", response_model=HomeDetailOut)
async def get_home(
    home_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user),
):
    home = await session.get(models.Home, home_id)
    if not home:
        raise HTTPException(status_code=404, detail="Home not found")
    if current_user.role_id != 1:
        await _require_role(session, home_id, current_user.user_id, "guest")
    rooms_result = await session.execute(
        select(models.Room).where(models.Room.home_id == home_id).order_by(models.Room.order_index)
    )
    rooms = []
    for r in rooms_result.scalars().all():
        rc_result = await session.execute(
            select(models.RoomCamera, models.Camera)
            .join(models.Camera, models.Camera.camera_id == models.RoomCamera.camera_id)
            .where(models.RoomCamera.room_id == r.room_id)
        )
        cams = [RoomCameraOut(room_id=rc.room_id, camera_id=rc.camera_id, camera_name=cam.name, added_at=rc.added_at)
                for rc, cam in rc_result.all()]
        rooms.append(RoomOut(room_id=r.room_id, home_id=r.home_id, name=r.name, order_index=r.order_index, created_at=r.created_at, cameras=cams))
    members_result = await session.execute(
        select(models.HomeMember, models.User)
        .join(models.User, models.User.user_id == models.HomeMember.user_id)
        .where(models.HomeMember.home_id == home_id)
    )
    members = [MemberOut(user_id=m.user_id, login=u.login, role=m.role, joined_at=m.joined_at)
               for m, u in members_result.all()]
    my = await _get_membership(session, home_id, current_user.user_id)
    return HomeDetailOut(
        home_id=home.home_id, name=home.name, description=home.description,
        created_at=home.created_at, my_role=my.role if my else None,
        rooms=rooms, members=members,
    )


@router.patch("/{home_id}", response_model=HomeOut)
async def update_home(
    home_id: int,
    payload: HomeUpdate,
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user),
):
    await _require_role(session, home_id, current_user.user_id, "admin")
    home = await session.get(models.Home, home_id)
    if not home:
        raise HTTPException(status_code=404, detail="Home not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(home, field, value)
    await _log_activity(session, home_id, current_user.user_id, "home_updated")
    await session.commit()
    await session.refresh(home)
    mc = await session.execute(select(func.count()).where(models.HomeMember.home_id == home_id))
    rc = await session.execute(select(func.count()).where(models.Room.home_id == home_id))
    my = await _get_membership(session, home_id, current_user.user_id)
    return HomeOut(
        home_id=home.home_id, name=home.name, description=home.description,
        created_at=home.created_at, member_count=mc.scalar() or 0, room_count=rc.scalar() or 0,
        my_role=my.role if my else None,
    )


@router.delete("/{home_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_home(
    home_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user),
):
    await _require_role(session, home_id, current_user.user_id, "owner")
    home = await session.get(models.Home, home_id)
    if not home:
        raise HTTPException(status_code=404, detail="Home not found")
    await session.delete(home)
    await session.commit()
    return {}


# ── Rooms ──

@router.post("/{home_id}/rooms", response_model=RoomOut, status_code=status.HTTP_201_CREATED)
async def create_room(
    home_id: int,
    payload: RoomCreate,
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user),
):
    await _require_role(session, home_id, current_user.user_id, "admin")
    room = models.Room(home_id=home_id, name=payload.name, order_index=payload.order_index)
    session.add(room)
    await _log_activity(session, home_id, current_user.user_id, "room_created", {"name": payload.name})
    await session.commit()
    await session.refresh(room)
    return RoomOut(room_id=room.room_id, home_id=room.home_id, name=room.name, order_index=room.order_index, created_at=room.created_at)


@router.patch("/{home_id}/rooms/{room_id}", response_model=RoomOut)
async def update_room(
    home_id: int,
    room_id: int,
    payload: RoomUpdate,
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user),
):
    await _require_role(session, home_id, current_user.user_id, "admin")
    room = await session.get(models.Room, room_id)
    if not room or room.home_id != home_id:
        raise HTTPException(status_code=404, detail="Room not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(room, field, value)
    await session.commit()
    await session.refresh(room)
    return RoomOut(room_id=room.room_id, home_id=room.home_id, name=room.name, order_index=room.order_index, created_at=room.created_at)


@router.delete("/{home_id}/rooms/{room_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_room(
    home_id: int,
    room_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user),
):
    await _require_role(session, home_id, current_user.user_id, "admin")
    room = await session.get(models.Room, room_id)
    if not room or room.home_id != home_id:
        raise HTTPException(status_code=404, detail="Room not found")
    await session.delete(room)
    await _log_activity(session, home_id, current_user.user_id, "room_deleted", {"name": room.name})
    await session.commit()
    return {}


@router.post("/{home_id}/rooms/{room_id}/cameras/{camera_id}", status_code=status.HTTP_201_CREATED)
async def add_camera_to_room(
    home_id: int,
    room_id: int,
    camera_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user),
):
    await _require_role(session, home_id, current_user.user_id, "admin")
    room = await session.get(models.Room, room_id)
    if not room or room.home_id != home_id:
        raise HTTPException(status_code=404, detail="Room not found")
    cam = await session.get(models.Camera, camera_id)
    if not cam:
        raise HTTPException(status_code=404, detail="Camera not found")
    existing = await session.execute(
        select(models.RoomCamera).where(models.RoomCamera.room_id == room_id, models.RoomCamera.camera_id == camera_id)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Camera already in room")
    session.add(models.RoomCamera(room_id=room_id, camera_id=camera_id))
    await _log_activity(session, home_id, current_user.user_id, "camera_added", {"room": room.name, "camera": cam.name})
    await session.commit()
    return {"ok": True}


@router.delete("/{home_id}/rooms/{room_id}/cameras/{camera_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_camera_from_room(
    home_id: int,
    room_id: int,
    camera_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user),
):
    await _require_role(session, home_id, current_user.user_id, "admin")
    result = await session.execute(
        select(models.RoomCamera).where(models.RoomCamera.room_id == room_id, models.RoomCamera.camera_id == camera_id)
    )
    rc = result.scalar_one_or_none()
    if rc:
        await session.delete(rc)
        await session.commit()
    return {}


@router.get("/{home_id}/rooms/{room_id}/cameras", response_model=list[RoomCameraOut])
async def list_room_cameras(
    home_id: int,
    room_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user),
):
    if current_user.role_id != 1:
        await _require_role(session, home_id, current_user.user_id, "guest")
    result = await session.execute(
        select(models.RoomCamera, models.Camera)
        .join(models.Camera, models.Camera.camera_id == models.RoomCamera.camera_id)
        .where(models.RoomCamera.room_id == room_id)
    )
    return [
        RoomCameraOut(room_id=rc.room_id, camera_id=rc.camera_id, camera_name=cam.name, added_at=rc.added_at)
        for rc, cam in result.all()
    ]


# ── Invitations ──

@router.post("/{home_id}/invite", response_model=InviteOut)
async def create_invite(
    home_id: int,
    payload: InviteCreate,
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user),
):
    await _require_role(session, home_id, current_user.user_id, "admin")
    code = secrets.token_urlsafe(16)
    expires = datetime.utcnow() + timedelta(hours=payload.expires_hours)
    inv = models.HomeInvitation(
        home_id=home_id,
        invited_by_user_id=current_user.user_id,
        invite_type=payload.invite_type,
        invite_code=code,
        target_email=payload.target_email,
        role=payload.role,
        expires_at=expires,
    )
    session.add(inv)
    await _log_activity(session, home_id, current_user.user_id, "invite_created", {"role": payload.role})
    await session.commit()
    await session.refresh(inv)
    return InviteOut(
        invitation_id=inv.invitation_id, invite_code=inv.invite_code,
        invite_type=inv.invite_type, role=inv.role, expires_at=inv.expires_at,
    )


@router.post("/join/{invite_code}")
async def join_by_code(
    invite_code: str,
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user),
):
    result = await session.execute(
        select(models.HomeInvitation).where(models.HomeInvitation.invite_code == invite_code)
    )
    inv = result.scalar_one_or_none()
    if not inv:
        raise HTTPException(status_code=404, detail="Invalid invite code")
    if inv.expires_at and inv.expires_at < datetime.utcnow():
        raise HTTPException(status_code=410, detail="Invite expired")
    if inv.accepted_at:
        raise HTTPException(status_code=409, detail="Invite already used")
    existing = await _get_membership(session, inv.home_id, current_user.user_id)
    if existing:
        raise HTTPException(status_code=409, detail="Already a member")
    session.add(models.HomeMember(
        home_id=inv.home_id,
        user_id=current_user.user_id,
        role=inv.role,
        invited_by=inv.invited_by_user_id,
    ))
    inv.accepted_at = datetime.utcnow()
    inv.accepted_by_user_id = current_user.user_id
    await _log_activity(session, inv.home_id, current_user.user_id, "member_joined", {"role": inv.role})
    await session.commit()
    return {"ok": True, "home_id": inv.home_id, "role": inv.role}


# ── Member management ──

@router.patch("/{home_id}/members/{user_id}/role")
async def update_member_role(
    home_id: int,
    user_id: int,
    payload: MemberRoleUpdate,
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user),
):
    actor = await _require_role(session, home_id, current_user.user_id, "admin")
    target = await _get_membership(session, home_id, user_id)
    if not target:
        raise HTTPException(status_code=404, detail="Member not found")
    if payload.role == "owner":
        raise HTTPException(status_code=400, detail="Use transfer endpoint to assign owner")
    if ROLE_LEVEL.get(target.role, 0) >= ROLE_LEVEL.get(actor.role, 0):
        raise HTTPException(status_code=403, detail="Cannot modify member with equal or higher role")
    if ROLE_LEVEL.get(payload.role, 0) >= ROLE_LEVEL.get(actor.role, 0):
        raise HTTPException(status_code=403, detail="Cannot assign role equal or higher than your own")
    target.role = payload.role
    await _log_activity(session, home_id, current_user.user_id, "role_changed", {"user_id": user_id, "new_role": payload.role})
    await session.commit()
    return {"ok": True}


@router.delete("/{home_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(
    home_id: int,
    user_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user),
):
    if user_id == current_user.user_id:
        # self-leave
        target = await _get_membership(session, home_id, user_id)
        if not target:
            raise HTTPException(status_code=404, detail="Not a member")
        if target.role == "owner":
            raise HTTPException(status_code=400, detail="Owner cannot leave; transfer ownership first")
    else:
        actor = await _require_role(session, home_id, current_user.user_id, "admin")
        target = await _get_membership(session, home_id, user_id)
        if not target:
            raise HTTPException(status_code=404, detail="Member not found")
        if ROLE_LEVEL.get(target.role, 0) >= ROLE_LEVEL.get(actor.role, 0):
            raise HTTPException(status_code=403, detail="Cannot remove member with equal or higher role")
    await session.delete(target)
    await _log_activity(session, home_id, current_user.user_id, "member_removed", {"user_id": user_id})
    await session.commit()
    return {}


@router.post("/{home_id}/transfer")
async def transfer_ownership(
    home_id: int,
    payload: TransferOwnership,
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user),
):
    actor = await _require_role(session, home_id, current_user.user_id, "owner")
    target = await _get_membership(session, home_id, payload.new_owner_user_id)
    if not target:
        raise HTTPException(status_code=404, detail="Target user is not a member")
    target.role = "owner"
    actor.role = "admin"
    await _log_activity(session, home_id, current_user.user_id, "ownership_transferred", {"new_owner": payload.new_owner_user_id})
    await session.commit()
    return {"ok": True}


# ── Activity log ──

@router.get("/{home_id}/activity", response_model=list[ActivityOut])
async def get_activity(
    home_id: int,
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user),
):
    if current_user.role_id != 1:
        await _require_role(session, home_id, current_user.user_id, "member")
    result = await session.execute(
        select(models.HomeActivityLog, models.User)
        .outerjoin(models.User, models.User.user_id == models.HomeActivityLog.user_id)
        .where(models.HomeActivityLog.home_id == home_id)
        .order_by(models.HomeActivityLog.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    out = []
    for log, user in result.all():
        details = None
        if log.details:
            try:
                details = json.loads(log.details)
            except (json.JSONDecodeError, TypeError):
                pass
        out.append(ActivityOut(
            activity_id=log.activity_id,
            user_id=log.user_id,
            user_login=user.login if user else None,
            action=log.action,
            details=details,
            created_at=log.created_at,
        ))
    return out
