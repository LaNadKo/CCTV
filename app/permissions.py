"""Simplified permission system based only on system roles."""
from typing import Optional

from app import models

ROLE_ADMIN = 1
ROLE_USER = 2
ROLE_VIEWER = 3

PERMISSION_LEVEL = {"view": 1, "control": 2, "admin": 3}
ROLE_CAMERA_PERMISSION = {
    ROLE_ADMIN: "admin",
    ROLE_USER: "control",
    ROLE_VIEWER: "view",
}


def user_camera_permission_sync(user: models.User) -> Optional[str]:
    return ROLE_CAMERA_PERMISSION.get(user.role_id)


async def user_camera_permission(session, user_id: int, camera_id: int) -> Optional[str]:
    user = await session.get(models.User, user_id)
    if user is None:
        return None
    return user_camera_permission_sync(user)


def check_permission(actual: Optional[str], required: str) -> bool:
    if actual is None:
        return False
    return PERMISSION_LEVEL.get(actual, 0) >= PERMISSION_LEVEL.get(required, 0)


def is_admin(user: models.User) -> bool:
    return user.role_id == ROLE_ADMIN


def is_at_least_user(user: models.User) -> bool:
    return user.role_id in (ROLE_ADMIN, ROLE_USER)
