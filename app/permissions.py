from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models

PERMISSION_LEVEL = {"view": 1, "control": 2, "admin": 3}


async def _best_user_permission(session: AsyncSession, user_id: int, camera_id: int) -> Optional[str]:
    result = await session.execute(
        select(models.UserCameraPermission.permission).where(
            models.UserCameraPermission.user_id == user_id,
            models.UserCameraPermission.camera_id == camera_id,
        )
    )
    perms = result.scalars().all()
    if not perms:
        return None
    return max(perms, key=lambda p: PERMISSION_LEVEL.get(p, 0))


async def _best_group_permission(session: AsyncSession, user_id: int, camera_id: int) -> Optional[str]:
    sub_membership = (
        select(models.UserGroup.group_id, models.UserGroup.membership_role)
        .where(models.UserGroup.user_id == user_id)
        .subquery()
    )
    stmt = (
        select(
            models.GroupCameraPermission.permission,
            models.GroupCameraPermission.target_role,
            sub_membership.c.membership_role,
        )
        .select_from(models.GroupCameraPermission)
        .join(sub_membership, models.GroupCameraPermission.group_id == sub_membership.c.group_id)
        .where(models.GroupCameraPermission.camera_id == camera_id)
    )
    result = await session.execute(stmt)
    best: Optional[str] = None
    for permission, target_role, membership_role in result.fetchall():
        effective_role = "admin" if membership_role in ("owner", "admin") else "member"
        if effective_role == "admin":
            if target_role not in ("admin", "member"):
                continue
        else:
            if target_role != "member":
                continue
        if best is None or PERMISSION_LEVEL.get(permission, 0) > PERMISSION_LEVEL.get(best, 0):
            best = permission
    return best


HOME_ROLE_PERMISSION = {"owner": "admin", "admin": "control", "member": "view", "guest": "view"}


async def _best_home_permission(session: AsyncSession, user_id: int, camera_id: int) -> Optional[str]:
    """Resolve camera access through Home → Room → Camera hierarchy."""
    stmt = (
        select(models.HomeMember.role)
        .join(models.Room, models.Room.home_id == models.HomeMember.home_id)
        .join(models.RoomCamera, models.RoomCamera.room_id == models.Room.room_id)
        .where(
            models.HomeMember.user_id == user_id,
            models.RoomCamera.camera_id == camera_id,
        )
    )
    result = await session.execute(stmt)
    roles = result.scalars().all()
    if not roles:
        return None
    best = None
    for role in roles:
        perm = HOME_ROLE_PERMISSION.get(role)
        if perm and (best is None or PERMISSION_LEVEL.get(perm, 0) > PERMISSION_LEVEL.get(best, 0)):
            best = perm
    return best


async def user_camera_permission(
    session: AsyncSession, user_id: int, camera_id: int
) -> Optional[str]:
    direct = await _best_user_permission(session, user_id, camera_id)
    via_group = await _best_group_permission(session, user_id, camera_id)
    via_home = await _best_home_permission(session, user_id, camera_id)
    candidates = [p for p in [direct, via_group, via_home] if p is not None]
    if not candidates:
        return None
    return max(candidates, key=lambda p: PERMISSION_LEVEL.get(p, 0))


def check_permission(actual: Optional[str], required: str) -> bool:
    if actual is None:
        return False
    return PERMISSION_LEVEL.get(actual, 0) >= PERMISSION_LEVEL.get(required, 0)


async def is_home_admin(session: AsyncSession, user_id: int) -> bool:
    """Check if user is owner or admin of any home."""
    result = await session.execute(
        select(models.HomeMember.role).where(
            models.HomeMember.user_id == user_id,
            models.HomeMember.role.in_(["owner", "admin"]),
        )
    )
    return result.scalar_one_or_none() is not None
