"""Processor management router."""
from __future__ import annotations

import base64
import json
from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app import models
from app.db import get_session
from app.dependencies import get_current_user, get_service_scopes
from app.permissions import is_home_admin
from app.schemas.processors import (
    AssignCamerasIn,
    AssignedCameraInfo,
    CameraAssignment,
    EndpointInfo,
    GalleryEntry,
    ProcessorEventIn,
    ProcessorEventOut,
    ProcessorHeartbeat,
    ProcessorOut,
    ProcessorRecordingIn,
    ProcessorRecordingOut,
    ProcessorRegister,
    ProcessorRegisterOut,
    StorageConfigOut,
)

router = APIRouter(prefix="/processors", tags=["processors"])


# ── Helper: resolve API key scopes ──

async def _require_scope(scope: str, x_api_key: str = Header(...), session: AsyncSession = Depends(get_session)):
    scopes = await get_service_scopes(x_api_key, session)
    if scope not in scopes and "*" not in scopes:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Missing scope: {scope}")
    return scopes


def require_scope(scope: str):
    async def _dep(x_api_key: str = Header(...), session: AsyncSession = Depends(get_session)):
        return await _require_scope(scope, x_api_key, session)
    return _dep


async def _ensure_admin(user: models.User, session: AsyncSession):
    if user.role_id == 1:
        return
    if await is_home_admin(session, user.user_id):
        return
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin only")


# ── API-key scoped endpoints (for processor service) ──

@router.post("/register", response_model=ProcessorRegisterOut, status_code=status.HTTP_201_CREATED)
async def register_processor(
    payload: ProcessorRegister,
    session: AsyncSession = Depends(get_session),
    _scopes=Depends(require_scope("processor:register")),
):
    proc = models.Processor(
        name=payload.name,
        status="registered",
        capabilities=json.dumps(payload.capabilities) if payload.capabilities else None,
    )
    session.add(proc)
    await session.commit()
    await session.refresh(proc)
    return ProcessorRegisterOut(processor_id=proc.processor_id, name=proc.name, status=proc.status)


@router.post("/{processor_id}/heartbeat")
async def processor_heartbeat(
    processor_id: int,
    payload: ProcessorHeartbeat,
    session: AsyncSession = Depends(get_session),
    x_api_key: str = Header(...),
):
    scopes = await get_service_scopes(x_api_key, session)
    if "processor:heartbeat" not in scopes and "*" not in scopes:
        raise HTTPException(status_code=403, detail="Missing scope: processor:heartbeat")
    proc = await session.get(models.Processor, processor_id)
    if not proc:
        raise HTTPException(status_code=404, detail="Processor not found")
    proc.status = payload.status
    proc.last_heartbeat = datetime.utcnow()
    await session.commit()
    return {"ok": True}


@router.get("/{processor_id}/assignments", response_model=list[CameraAssignment])
async def get_assignments(
    processor_id: int,
    session: AsyncSession = Depends(get_session),
    x_api_key: str = Header(...),
):
    scopes = await get_service_scopes(x_api_key, session)
    if "processor:read" not in scopes and "*" not in scopes:
        raise HTTPException(status_code=403, detail="Missing scope: processor:read")
    stmt = (
        select(models.ProcessorCameraAssignment)
        .where(models.ProcessorCameraAssignment.processor_id == processor_id)
        .options(selectinload(models.ProcessorCameraAssignment.camera))
    )
    result = await session.execute(stmt)
    assignments = result.scalars().all()
    out = []
    for a in assignments:
        cam = a.camera
        ep_result = await session.execute(
            select(models.CameraEndpoint).where(models.CameraEndpoint.camera_id == cam.camera_id)
        )
        endpoints = [
            EndpointInfo(
                endpoint_kind=e.endpoint_kind,
                endpoint_url=e.endpoint_url,
                username=e.username,
                password_secret=e.password_secret,
            )
            for e in ep_result.scalars().all()
        ]
        out.append(CameraAssignment(
            camera_id=cam.camera_id,
            name=cam.name,
            ip_address=cam.ip_address,
            stream_url=cam.stream_url,
            detection_enabled=cam.detection_enabled,
            recording_mode=cam.recording_mode,
            tracking_enabled=cam.tracking_enabled,
            tracking_mode=cam.tracking_mode,
            endpoints=endpoints,
        ))
    return out


@router.post("/{processor_id}/events", response_model=ProcessorEventOut)
async def push_event(
    processor_id: int,
    payload: ProcessorEventIn,
    session: AsyncSession = Depends(get_session),
    x_api_key: str = Header(...),
):
    scopes = await get_service_scopes(x_api_key, session)
    if "processor:write" not in scopes and "*" not in scopes:
        raise HTTPException(status_code=403, detail="Missing scope: processor:write")
    # Resolve event type by name from DB instead of hardcoded IDs
    et_result = await session.execute(
        select(models.EventType).where(models.EventType.name == payload.event_type)
    )
    et = et_result.scalar_one_or_none()
    if et is None:
        raise HTTPException(status_code=400, detail=f"Unknown event type: {payload.event_type}")
    event_type_id = et.event_type_id
    evt = models.Event(
        camera_id=payload.camera_id,
        event_type_id=event_type_id,
        person_id=payload.person_id,
        confidence=payload.confidence,
        processor_id=processor_id,
        track_id=payload.track_id,
    )
    session.add(evt)
    await session.flush()
    review = models.EventReview(event_id=evt.event_id, status="pending")
    session.add(review)
    await session.commit()
    return ProcessorEventOut(event_id=evt.event_id)


@router.post("/{processor_id}/recordings", response_model=ProcessorRecordingOut)
async def push_recording(
    processor_id: int,
    payload: ProcessorRecordingIn,
    session: AsyncSession = Depends(get_session),
    x_api_key: str = Header(...),
):
    scopes = await get_service_scopes(x_api_key, session)
    if "processor:write" not in scopes and "*" not in scopes:
        raise HTTPException(status_code=403, detail="Missing scope: processor:write")
    cam = await session.get(models.Camera, payload.camera_id)
    if not cam:
        raise HTTPException(status_code=404, detail="Camera not found")
    vs_result = await session.execute(
        select(models.VideoStream).where(models.VideoStream.camera_id == payload.camera_id).limit(1)
    )
    vs = vs_result.scalar_one_or_none()
    if not vs:
        vs = models.VideoStream(camera_id=payload.camera_id, enabled=True)
        session.add(vs)
        await session.flush()
    st_result = await session.execute(
        select(models.StorageTarget).where(models.StorageTarget.is_primary_recording.is_(True)).limit(1)
    )
    st = st_result.scalar_one_or_none()
    if not st:
        st_result = await session.execute(select(models.StorageTarget).limit(1))
        st = st_result.scalar_one_or_none()
    if not st:
        raise HTTPException(status_code=500, detail="No storage target configured")
    rf = models.RecordingFile(
        video_stream_id=vs.video_stream_id,
        storage_target_id=st.storage_target_id,
        file_kind=payload.file_kind,
        file_path=payload.file_path,
        duration_seconds=payload.duration_seconds,
        file_size_bytes=payload.file_size_bytes,
    )
    session.add(rf)
    await session.commit()
    await session.refresh(rf)
    return ProcessorRecordingOut(recording_file_id=rf.recording_file_id)


@router.get("/{processor_id}/gallery", response_model=list[GalleryEntry])
async def get_gallery(
    processor_id: int,
    session: AsyncSession = Depends(get_session),
    x_api_key: str = Header(...),
):
    scopes = await get_service_scopes(x_api_key, session)
    if "processor:read" not in scopes and "*" not in scopes:
        raise HTTPException(status_code=403, detail="Missing scope: processor:read")
    # Multi-embedding: return all entries from person_embeddings table
    pe_result = await session.execute(
        select(models.PersonEmbedding, models.Person)
        .join(models.Person, models.PersonEmbedding.person_id == models.Person.person_id)
    )
    rows = pe_result.all()
    gallery = []
    if rows:
        for emb_row, p in rows:
            label_parts = [p.last_name, p.first_name, p.middle_name]
            label = " ".join(x for x in label_parts if x) or f"Person #{p.person_id}"
            gallery.append(GalleryEntry(
                person_id=p.person_id,
                label=label,
                embedding_b64=base64.b64encode(emb_row.embedding).decode(),
            ))
    else:
        # Fallback to legacy single embedding
        result = await session.execute(select(models.Person).where(models.Person.embeddings.isnot(None)))
        persons = result.scalars().all()
        for p in persons:
            label_parts = [p.last_name, p.first_name, p.middle_name]
            label = " ".join(x for x in label_parts if x) or f"Person #{p.person_id}"
            gallery.append(GalleryEntry(
                person_id=p.person_id,
                label=label,
                embedding_b64=base64.b64encode(p.embeddings).decode(),
            ))
    return gallery


@router.get("/{processor_id}/storage-config", response_model=StorageConfigOut)
async def get_storage_config(
    processor_id: int,
    session: AsyncSession = Depends(get_session),
    x_api_key: str = Header(...),
):
    scopes = await get_service_scopes(x_api_key, session)
    if "processor:read" not in scopes and "*" not in scopes:
        raise HTTPException(status_code=403, detail="Missing scope: processor:read")
    st_result = await session.execute(
        select(models.StorageTarget).where(models.StorageTarget.is_primary_recording.is_(True)).limit(1)
    )
    st = st_result.scalar_one_or_none()
    if not st:
        st_result = await session.execute(select(models.StorageTarget).limit(1))
        st = st_result.scalar_one_or_none()
    if not st:
        raise HTTPException(status_code=404, detail="No storage target")
    config = None
    if st.connection_config:
        try:
            config = json.loads(st.connection_config)
        except (json.JSONDecodeError, TypeError):
            pass
    return StorageConfigOut(storage_type=st.storage_type, root_path=st.root_path, connection_config=config)


# ── JWT admin endpoints ──

@router.get("", response_model=list[ProcessorOut])
async def list_processors(
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user),
):
    await _ensure_admin(current_user, session)
    result = await session.execute(select(models.Processor))
    procs = result.scalars().all()
    out = []
    for p in procs:
        cnt_result = await session.execute(
            select(func.count()).where(models.ProcessorCameraAssignment.processor_id == p.processor_id)
        )
        cnt = cnt_result.scalar() or 0
        caps = None
        if p.capabilities:
            try:
                caps = json.loads(p.capabilities)
            except (json.JSONDecodeError, TypeError):
                pass
        # get assigned camera details
        cam_result = await session.execute(
            select(models.ProcessorCameraAssignment, models.Camera)
            .join(models.Camera, models.Camera.camera_id == models.ProcessorCameraAssignment.camera_id)
            .where(models.ProcessorCameraAssignment.processor_id == p.processor_id)
        )
        assigned = [AssignedCameraInfo(camera_id=cam.camera_id, name=cam.name) for _, cam in cam_result.all()]
        out.append(ProcessorOut(
            processor_id=p.processor_id,
            name=p.name,
            status=p.status,
            last_heartbeat=p.last_heartbeat,
            capabilities=caps,
            created_at=p.created_at,
            camera_count=cnt,
            assigned_cameras=assigned,
        ))
    return out


@router.post("/{processor_id}/assign", status_code=status.HTTP_200_OK)
async def assign_cameras(
    processor_id: int,
    payload: AssignCamerasIn,
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user),
):
    await _ensure_admin(current_user, session)
    proc = await session.get(models.Processor, processor_id)
    if not proc:
        raise HTTPException(status_code=404, detail="Processor not found")
    for cid in payload.camera_ids:
        cam = await session.get(models.Camera, cid)
        if not cam:
            continue
        existing = await session.execute(
            select(models.ProcessorCameraAssignment).where(
                models.ProcessorCameraAssignment.processor_id == processor_id,
                models.ProcessorCameraAssignment.camera_id == cid,
            )
        )
        if existing.scalar_one_or_none():
            continue
        session.add(models.ProcessorCameraAssignment(processor_id=processor_id, camera_id=cid))
    await session.commit()
    return {"ok": True}


@router.delete("/{processor_id}/assign/{camera_id}", status_code=status.HTTP_204_NO_CONTENT)
async def unassign_camera(
    processor_id: int,
    camera_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user),
):
    await _ensure_admin(current_user, session)
    result = await session.execute(
        select(models.ProcessorCameraAssignment).where(
            models.ProcessorCameraAssignment.processor_id == processor_id,
            models.ProcessorCameraAssignment.camera_id == camera_id,
        )
    )
    assignment = result.scalar_one_or_none()
    if assignment:
        await session.delete(assignment)
        await session.commit()
    return {}


@router.delete("/{processor_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_processor(
    processor_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user),
):
    await _ensure_admin(current_user, session)
    proc = await session.get(models.Processor, processor_id)
    if not proc:
        raise HTTPException(status_code=404, detail="Processor not found")
    await session.delete(proc)
    await session.commit()
    return {}
