from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.db import get_session
from app.dependencies import get_current_user

router = APIRouter(prefix="/system", tags=["system"])


@router.get("/changes")
async def data_changes(
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user),
) -> dict[str, Any]:
    """Lightweight data revisions for client-side tab cache invalidation."""

    _ = current_user

    cameras = await _revision(
        session,
        _count(models.Camera, models.Camera.deleted_at.is_(None)),
        _max(models.Camera.camera_id, models.Camera.deleted_at.is_(None)),
        _max(models.Camera.created_at, models.Camera.deleted_at.is_(None)),
        _count(models.CameraEndpoint),
        _max(models.CameraEndpoint.camera_endpoint_id),
        _max(models.CameraEndpoint.created_at),
        _count(models.CameraPreset),
        _max(models.CameraPreset.camera_preset_id),
        _count(models.CameraRoiZone),
        _max(models.CameraRoiZone.roi_zone_id),
    )
    groups = await _revision(
        session,
        _count(models.Group),
        _max(models.Group.group_id),
        _max(models.Group.created_at),
        _count(models.ProcessorCameraAssignment),
    )
    persons = await _revision(
        session,
        _count(models.Person, models.Person.deleted_at.is_(None)),
        _max(models.Person.person_id, models.Person.deleted_at.is_(None)),
        _max(models.Person.created_at, models.Person.deleted_at.is_(None)),
        _count(models.PersonEmbedding),
        _max(models.PersonEmbedding.person_embedding_id),
        _max(models.PersonEmbedding.created_at),
    )
    recordings = await _revision(
        session,
        _count(models.RecordingFile),
        _max(models.RecordingFile.recording_file_id),
        _max(models.RecordingFile.started_at),
        _max(models.RecordingFile.created_at),
    )
    events = await _revision(
        session,
        _count(models.Event),
        _max(models.Event.event_id),
        _max(models.Event.event_ts),
        _count(models.EventReview),
        _max(models.EventReview.event_review_id),
        _max(models.EventReview.updated_at),
    )
    processors = await _revision(
        session,
        _count(models.Processor),
        _max(models.Processor.processor_id),
        _max(models.Processor.created_at),
        _count(models.ProcessorCameraAssignment),
        _count(models.ProcessorCommand),
        _max(models.ProcessorCommand.command_id),
        _max(models.ProcessorCommand.created_at),
        _max(models.ProcessorCommand.completed_at),
    )
    users = await _revision(
        session,
        _count(models.User),
        _max(models.User.user_id),
        _max(models.User.created_at),
        _count(models.UserMfaMethod),
        _max(models.UserMfaMethod.user_mfa_id),
        _max(models.UserMfaMethod.created_at),
        _max(models.UserMfaMethod.last_used_at),
    )
    api_keys = await _revision(
        session,
        _count(models.ApiKey),
        _max(models.ApiKey.api_key_id),
        _max(models.ApiKey.created_at),
    )

    return {
        "server_time": datetime.utcnow().isoformat(timespec="seconds"),
        "sections": {
            "cameras": cameras,
            "groups": groups,
            "persons": persons,
            "recordings": recordings,
            "events": events,
            "processors": processors,
            "users": users,
            "api_keys": api_keys,
        },
    }


async def _revision(session: AsyncSession, *statements: Select[Any]) -> str:
    values = []
    for statement in statements:
        values.append(_normalize_revision_value((await session.execute(statement)).scalar()))
    return "|".join(values)


def _count(model: type[Any], *where: Any) -> Select[Any]:
    statement = select(func.count()).select_from(model)
    for condition in where:
        statement = statement.where(condition)
    return statement


def _max(column: Any, *where: Any) -> Select[Any]:
    statement = select(func.max(column))
    for condition in where:
        statement = statement.where(condition)
    return statement


def _normalize_revision_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)
