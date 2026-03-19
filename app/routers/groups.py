from typing import List, Set

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.db import get_session
from app.dependencies import get_current_user
from app.schemas.groups import (
    GroupCameraPermissionIn,
    GroupCameraPermissionOut,
    GroupCreate,
    GroupDetail,
    GroupOut,
    GroupInvite,
    GroupRoleUpdate,
    GroupTransferOwner,
)
from app.security import hash_password

router = APIRouter(prefix="/groups", tags=["groups"])

VALID_PERMISSIONS: Set[str] = {"view", "control", "admin"}
GROUP_OWNER_ROLE = "owner"
GROUP_ADMIN_ROLE = "admin"
GROUP_MEMBER_ROLE = "member"
DEFAULT_GROUP_NEW_USER_ROLE = GROUP_MEMBER_ROLE


async def _ensure_users_exist(session: AsyncSession, user_ids: List[int]) -> None:
    if not user_ids:
        return
    unique_ids = list(set(user_ids))
    result = await session.execute(select(models.User.user_id).where(models.User.user_id.in_(unique_ids)))
    found = set(result.scalars().all())
    missing = set(unique_ids) - found
    if missing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Users not found: {sorted(missing)}",
        )


async def _ensure_cameras_exist(session: AsyncSession, camera_ids: List[int]) -> None:
    if not camera_ids:
        return
    unique_ids = list(set(camera_ids))
    result = await session.execute(select(models.Camera.camera_id).where(models.Camera.camera_id.in_(unique_ids)))
    found = set(result.scalars().all())
    missing = set(unique_ids) - found
    if missing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cameras not found: {sorted(missing)}",
        )


async def _set_group_cameras(
    session: AsyncSession,
    group_id: int,
    permissions: List[GroupCameraPermissionIn],
    actor_role: str,
) -> None:
    for item in permissions:
        if item.permission not in VALID_PERMISSIONS:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid permission")
        if actor_role == GROUP_ADMIN_ROLE and item.target_role != GROUP_MEMBER_ROLE:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admins can manage permissions only for members",
            )
        await session.execute(
            delete(models.GroupCameraPermission).where(
                models.GroupCameraPermission.group_id == group_id,
                models.GroupCameraPermission.camera_id == item.camera_id,
                models.GroupCameraPermission.target_role == item.target_role,
            )
        )
        session.add(
            models.GroupCameraPermission(
                group_id=group_id,
                camera_id=item.camera_id,
                target_role=item.target_role,
                permission=item.permission,
            )
        )


async def _add_users_to_group(
    session: AsyncSession,
    group_id: int,
    user_ids: List[int],
    membership_role: str = DEFAULT_GROUP_NEW_USER_ROLE,
    invited_by: int | None = None,
) -> None:
    if not user_ids:
        return
    existing = await session.execute(
        select(models.UserGroup.user_id).where(
            models.UserGroup.group_id == group_id,
            models.UserGroup.user_id.in_(user_ids),
        )
    )
    already = set(existing.scalars().all())
    for user_id in set(user_ids):
        if user_id in already:
            continue
        session.add(
            models.UserGroup(
                user_id=user_id,
                group_id=group_id,
                membership_role=membership_role,
                invited_by=invited_by,
            )
        )


@router.post("", response_model=GroupOut, status_code=status.HTTP_201_CREATED)
async def create_group(
    payload: GroupCreate,
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user),
) -> GroupOut:
    # Ensure unique name
    existing = await session.execute(select(models.Group).where(models.Group.name == payload.name))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Group name already exists")

    await _ensure_cameras_exist(session, [p.camera_id for p in payload.camera_permissions])
    await _ensure_users_exist(session, payload.user_ids)

    group = models.Group(name=payload.name, description=payload.description)
    session.add(group)
    await session.flush()  # get group_id

    await _set_group_cameras(session, group.group_id, payload.camera_permissions, actor_role=GROUP_OWNER_ROLE)
    # creator becomes group admin
    session.add(
        models.UserGroup(
            user_id=current_user.user_id,
            group_id=group.group_id,
            membership_role=GROUP_OWNER_ROLE,
            invited_by=current_user.user_id,
        )
    )
    await _add_users_to_group(
        session,
        group.group_id,
        payload.user_ids,
        membership_role=DEFAULT_GROUP_NEW_USER_ROLE,
        invited_by=current_user.user_id,
    )
    await session.commit()
    await session.refresh(group)
    return GroupOut(
        group_id=group.group_id,
        name=group.name,
        description=group.description,
        membership_role=GROUP_OWNER_ROLE,
    )


@router.get("", response_model=List[GroupOut])
async def list_groups(
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user),
) -> List[GroupOut]:
    # Only groups where user is a member
    result = await session.execute(
        select(models.Group, models.UserGroup.membership_role)
        .join(models.UserGroup, models.UserGroup.group_id == models.Group.group_id)
        .where(models.UserGroup.user_id == current_user.user_id)
    )
    groups = result.all()
    return [
        GroupOut(
            group_id=g.group_id,
            name=g.name,
            description=g.description,
            membership_role=role,
        )
        for g, role in groups
    ]


@router.get("/{group_id}", response_model=GroupDetail)
async def get_group(
    group_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user),
) -> GroupDetail:
    result = await session.execute(
        select(models.Group, models.UserGroup.membership_role)
        .join(models.UserGroup, models.UserGroup.group_id == models.Group.group_id)
        .where(models.Group.group_id == group_id, models.UserGroup.user_id == current_user.user_id)
    )
    row = result.one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group not found or no access")
    group, membership_role = row

    perms_result = await session.execute(
        select(models.GroupCameraPermission).where(models.GroupCameraPermission.group_id == group_id)
    )
    perms = perms_result.scalars().all()
    return GroupDetail(
        group_id=group.group_id,
        name=group.name,
        description=group.description,
        membership_role=membership_role,
        cameras=[
            GroupCameraPermissionOut(camera_id=p.camera_id, permission=p.permission)
            for p in perms
        ],
    )


async def _get_membership_role(session: AsyncSession, group_id: int, user_id: int) -> str | None:
    res = await session.execute(
        select(models.UserGroup.membership_role).where(
            models.UserGroup.group_id == group_id,
            models.UserGroup.user_id == user_id,
        )
    )
    return res.scalar_one_or_none()


async def _ensure_group_admin(session: AsyncSession, group_id: int, user_id: int) -> str:
    res = await session.execute(
        select(models.UserGroup).where(
            models.UserGroup.group_id == group_id,
            models.UserGroup.user_id == user_id,
        )
    )
    membership = res.scalar_one_or_none()
    if membership is None or membership.membership_role not in (GROUP_OWNER_ROLE, GROUP_ADMIN_ROLE):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not a group admin")
    return membership.membership_role


@router.post("/{group_id}/cameras", response_model=GroupDetail)
async def set_group_cameras(
    group_id: int,
    permissions: List[GroupCameraPermissionIn],
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user),
) -> GroupDetail:
    result = await session.execute(select(models.Group).where(models.Group.group_id == group_id))
    group = result.scalar_one_or_none()
    if group is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group not found")

    actor_role = await _ensure_group_admin(session, group_id, current_user.user_id)
    await _ensure_cameras_exist(session, [p.camera_id for p in permissions])
    await _set_group_cameras(session, group_id, permissions, actor_role=actor_role)
    await session.commit()

    perms_result = await session.execute(
        select(models.GroupCameraPermission).where(models.GroupCameraPermission.group_id == group_id)
    )
    perms = perms_result.scalars().all()
    return GroupDetail(
        group_id=group.group_id,
        name=group.name,
        description=group.description,
        cameras=[
            GroupCameraPermissionOut(camera_id=p.camera_id, permission=p.permission)
            for p in perms
        ],
    )


@router.post("/{group_id}/users", response_model=GroupOut)
async def add_users(
    group_id: int,
    user_ids: List[int],
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user),
) -> GroupOut:
    result = await session.execute(select(models.Group).where(models.Group.group_id == group_id))
    group = result.scalar_one_or_none()
    if group is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group not found")

    await _ensure_group_admin(session, group_id, current_user.user_id)
    await _ensure_users_exist(session, user_ids)
    await _add_users_to_group(
        session,
        group_id,
        user_ids,
        membership_role=DEFAULT_GROUP_NEW_USER_ROLE,
        invited_by=current_user.user_id,
    )
    await session.commit()
    return GroupOut.model_validate(group)


@router.post("/{group_id}/invite", response_model=GroupOut)
async def invite_user(
    group_id: int,
    payload: GroupInvite,
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user),
) -> GroupOut:
    result = await session.execute(select(models.Group).where(models.Group.group_id == group_id))
    group = result.scalar_one_or_none()
    if group is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group not found")
    actor_role = await _ensure_group_admin(session, group_id, current_user.user_id)

    user_result = await session.execute(select(models.User).where(models.User.login == payload.login))
    user = user_result.scalar_one_or_none()
    if user is None:
        if not payload.password:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="User not found and password not provided"
            )
        user = models.User(
            login=payload.login,
            password_hash=hash_password(payload.password),
            role_id=3,  # viewer by default
        )
        session.add(user)
        await session.flush()

    # add membership if absent
    membership = await session.execute(
        select(models.UserGroup).where(
            models.UserGroup.group_id == group_id,
            models.UserGroup.user_id == user.user_id,
        )
    )
    if membership.scalar_one_or_none() is None:
        session.add(
            models.UserGroup(
                user_id=user.user_id,
                group_id=group_id,
                membership_role=DEFAULT_GROUP_NEW_USER_ROLE,
                invited_by=current_user.user_id,
            )
        )
    await session.commit()
    return GroupOut.model_validate(group)


@router.post("/{group_id}/members/{user_id}/role", response_model=GroupOut)
async def set_member_role(
    group_id: int,
    user_id: int,
    payload: GroupRoleUpdate,
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user),
) -> GroupOut:
    result = await session.execute(select(models.Group).where(models.Group.group_id == group_id))
    group = result.scalar_one_or_none()
    if group is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group not found")
    actor_role = await _ensure_group_admin(session, group_id, current_user.user_id)

    membership = await session.execute(
        select(models.UserGroup).where(
            models.UserGroup.group_id == group_id,
            models.UserGroup.user_id == user_id,
        )
    )
    m = membership.scalar_one_or_none()
    if m is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member not found in group")
    if m.membership_role == GROUP_OWNER_ROLE:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot change owner role")
    if actor_role != GROUP_OWNER_ROLE and payload.role == GROUP_ADMIN_ROLE:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only owner can set admin role")
    m.membership_role = payload.role
    await session.commit()
    return GroupOut.model_validate(group)


@router.post("/{group_id}/members/{user_id}/remove", response_model=GroupOut)
async def remove_member(
    group_id: int,
    user_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user),
) -> GroupOut:
    result = await session.execute(select(models.Group).where(models.Group.group_id == group_id))
    group = result.scalar_one_or_none()
    if group is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group not found")
    actor_role = await _ensure_group_admin(session, group_id, current_user.user_id)
    target_role = await _get_membership_role(session, group_id, user_id)
    if target_role is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member not found in group")
    if target_role == GROUP_OWNER_ROLE:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot remove owner")
    if actor_role == GROUP_ADMIN_ROLE and target_role != GROUP_MEMBER_ROLE:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admins can remove members only")

    await session.execute(
        delete(models.UserGroup).where(
            models.UserGroup.group_id == group_id,
            models.UserGroup.user_id == user_id,
        )
    )
    await session.commit()
    return GroupOut.model_validate(group)


@router.post("/{group_id}/transfer_owner", response_model=GroupOut)
async def transfer_owner(
    group_id: int,
    payload: GroupTransferOwner,
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user),
) -> GroupOut:
    result = await session.execute(select(models.Group).where(models.Group.group_id == group_id))
    group = result.scalar_one_or_none()
    if group is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group not found")
    actor_role = await _ensure_group_admin(session, group_id, current_user.user_id)
    if actor_role != GROUP_OWNER_ROLE:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only owner can transfer ownership")

    # Resolve target by login or user_id
    target_user = None
    if payload.login:
        res = await session.execute(select(models.User).where(models.User.login == payload.login))
        target_user = res.scalar_one_or_none()
    elif payload.new_owner_user_id:
        target_user = await session.get(models.User, payload.new_owner_user_id)

    if target_user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    membership = await session.execute(
        select(models.UserGroup).where(
            models.UserGroup.group_id == group_id,
            models.UserGroup.user_id == target_user.user_id,
        )
    )
    m = membership.scalar_one_or_none()
    if m is None:
        # add as member first
        m = models.UserGroup(
            user_id=target_user.user_id,
            group_id=group_id,
            membership_role=GROUP_MEMBER_ROLE,
            invited_by=current_user.user_id,
        )
        session.add(m)

    # demote current owner to admin
    await session.execute(
        models.UserGroup.__table__.update()
        .where(
            models.UserGroup.group_id == group_id,
            models.UserGroup.user_id == current_user.user_id,
        )
        .values(membership_role=GROUP_ADMIN_ROLE)
    )
    # promote target to owner
    m.membership_role = GROUP_OWNER_ROLE
    await session.commit()
    return GroupOut.model_validate(group)
