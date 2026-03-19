"""Processor management router."""
from __future__ import annotations

import base64
import json
import logging
import secrets
import time
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app import models
from app.db import get_session
from app.dependencies import get_current_user, get_service_scopes
from app.permissions import is_admin
from app.schemas.processors import (
    AssignCamerasIn,
    AssignedCameraInfo,
    CameraAssignment,
    EndpointInfo,
    GalleryEntry,
    GenerateCodeOut,
    ProcessorConnect,
    ProcessorConnectOut,
    ProcessorEventIn,
    ProcessorEventOut,
    ProcessorHeartbeat,
    ProcessorOut,
    ProcessorRecordingIn,
    ProcessorRecordingOut,
    ProcessorRegister,
    ProcessorRegisterOut,
    StorageConfigOut,
    SystemMetrics,
)
from app.security import hash_api_key

router = APIRouter(prefix="/processors", tags=["processors"])
log = logging.getLogger("app.processors")
_gallery_cache: list[GalleryEntry] | None = None
_gallery_cache_ts = 0.0
_GALLERY_CACHE_TTL = 30.0
_PROCESSOR_STORAGE_NAME = "Processor Media"


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


def _ensure_admin(user: models.User) -> None:
    if not is_admin(user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin only")


def _decode_snapshot_b64(snapshot_b64: str | None) -> bytes | None:
    if not snapshot_b64:
        return None
    raw = snapshot_b64.strip()
    if raw.startswith("data:") and "," in raw:
        raw = raw.split(",", 1)[1]
    try:
        return base64.b64decode(raw)
    except Exception:
        return None


def _store_snapshot(event_id: int, snapshot_bytes: bytes) -> str:
    snapshots_dir = Path("snapshots")
    snapshots_dir.mkdir(parents=True, exist_ok=True)
    path = snapshots_dir / f"event_{event_id}.jpg"
    path.write_bytes(snapshot_bytes)
    return str(path)


# ── Connection code flow (universal: LAN + WAN) ──

@router.post("/generate-code", response_model=GenerateCodeOut)
async def generate_connection_code(
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user),
):
    """Admin generates a short-lived code that a processor app uses to register."""
    _ensure_admin(current_user)
    code = secrets.token_urlsafe(6)[:8].upper()
    expires = datetime.utcnow() + timedelta(hours=24)
    rec = models.ProcessorConnectionCode(
        code=code,
        created_by_user_id=current_user.user_id,
        expires_at=expires,
    )
    session.add(rec)
    await session.commit()
    return GenerateCodeOut(code=code, expires_at=expires)


@router.post("/connect", response_model=ProcessorConnectOut)
async def connect_processor(
    payload: ProcessorConnect,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """Processor exchanges a connection code for a permanent API key."""
    result = await session.execute(
        select(models.ProcessorConnectionCode).where(
            models.ProcessorConnectionCode.code == payload.code,
            models.ProcessorConnectionCode.used_at.is_(None),
        )
    )
    code_rec = result.scalar_one_or_none()
    if not code_rec:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invalid or already used code")
    if code_rec.expires_at < datetime.utcnow():
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="Code expired")

    # Generate API key with processor scopes
    raw_key = secrets.token_urlsafe(32)
    key_hash = hash_api_key(raw_key)
    api_key = models.ApiKey(
        key_hash=key_hash,
        description=f"Auto: processor {payload.name}",
        scopes="processor:register,processor:heartbeat,processor:read,processor:write",
        is_active=True,
    )
    session.add(api_key)
    await session.flush()

    # Detect IP from request
    client_ip = payload.ip_address or (request.client.host if request.client else None)

    # Create processor
    proc = models.Processor(
        name=payload.name,
        api_key_id=api_key.api_key_id,
        hostname=payload.hostname,
        ip_address=client_ip,
        os_info=payload.os_info,
        version=payload.version,
        status="online",
        capabilities=json.dumps(payload.capabilities) if payload.capabilities else None,
        last_heartbeat=datetime.utcnow(),
    )
    session.add(proc)
    await session.flush()

    # Mark code as used
    code_rec.used_at = datetime.utcnow()
    code_rec.used_by_processor_id = proc.processor_id

    await session.commit()
    return ProcessorConnectOut(
        processor_id=proc.processor_id,
        name=proc.name,
        api_key=raw_key,
        status=proc.status,
    )


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
    request: Request,
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
    # Store metrics
    if payload.metrics:
        proc.last_metrics = payload.metrics.model_dump_json()
    elif payload.stats:
        proc.last_metrics = json.dumps(payload.stats)
    # Update IP if changed
    if payload.ip_address:
        proc.ip_address = payload.ip_address
    elif request.client:
        proc.ip_address = request.client.host
    if payload.hostname:
        proc.hostname = payload.hostname
    if payload.os_info:
        proc.os_info = payload.os_info
    if payload.version:
        proc.version = payload.version
    if payload.media_port is not None or payload.media_token:
        capabilities = {}
        if proc.capabilities:
            try:
                capabilities = json.loads(proc.capabilities)
            except (json.JSONDecodeError, TypeError):
                capabilities = {}
        if payload.capabilities:
            capabilities.update(payload.capabilities)
        if payload.media_port is not None:
            capabilities["media_port"] = payload.media_port
        if payload.media_token:
            capabilities["media_token"] = payload.media_token
        proc.capabilities = json.dumps(capabilities)
    elif payload.capabilities:
        capabilities = {}
        if proc.capabilities:
            try:
                capabilities = json.loads(proc.capabilities)
            except (json.JSONDecodeError, TypeError):
                capabilities = {}
        capabilities.update(payload.capabilities)
        proc.capabilities = json.dumps(capabilities)
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
    et_result = await session.execute(
        select(models.EventType).where(models.EventType.name == payload.event_type)
    )
    et = et_result.scalar_one_or_none()
    if et is None:
        raise HTTPException(status_code=400, detail=f"Unknown event type: {payload.event_type}")
    cam = await session.get(models.Camera, payload.camera_id)
    if cam is None:
        raise HTTPException(status_code=404, detail="Camera not found")
    event_type_id = et.event_type_id
    review_required = payload.event_type == "face_unknown"
    evt = models.Event(
        camera_id=payload.camera_id,
        event_type_id=event_type_id,
        person_id=payload.person_id,
        confidence=payload.confidence,
        processor_id=processor_id,
        track_id=payload.track_id,
        event_ts=payload.event_ts or datetime.now(),
    )
    session.add(evt)
    await session.flush()

    snapshot_bytes = _decode_snapshot_b64(payload.snapshot_b64)
    if snapshot_bytes:
        try:
            _store_snapshot(evt.event_id, snapshot_bytes)
        except Exception:
            log.exception("Failed to store snapshot for event %s", evt.event_id)

    if review_required:
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
        st = models.StorageTarget(
            name=_PROCESSOR_STORAGE_NAME,
            root_path="processor://",
            device_kind="network",
            purpose="recording",
            is_primary_recording=True,
            is_active=True,
            storage_type="network",
        )
        session.add(st)
        await session.flush()
    rf = models.RecordingFile(
        video_stream_id=vs.video_stream_id,
        storage_target_id=st.storage_target_id,
        file_kind=payload.file_kind,
        file_path=payload.file_path,
        started_at=payload.started_at or datetime.utcnow(),
        ended_at=payload.ended_at,
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
    global _gallery_cache, _gallery_cache_ts
    scopes = await get_service_scopes(x_api_key, session)
    if "processor:read" not in scopes and "*" not in scopes:
        raise HTTPException(status_code=403, detail="Missing scope: processor:read")
    now = time.monotonic()
    if _gallery_cache is not None and (now - _gallery_cache_ts) < _GALLERY_CACHE_TTL:
        return _gallery_cache
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
    _gallery_cache = gallery
    _gallery_cache_ts = now
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
    _ensure_admin(current_user)
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
        metrics = None
        if p.last_metrics:
            try:
                metrics = SystemMetrics(**json.loads(p.last_metrics))
            except Exception:
                pass
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
            ip_address=p.ip_address,
            os_info=p.os_info,
            version=p.version,
            metrics=metrics,
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
    _ensure_admin(current_user)
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
    _ensure_admin(current_user)
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
    _ensure_admin(current_user)
    proc = await session.get(models.Processor, processor_id)
    if not proc:
        raise HTTPException(status_code=404, detail="Processor not found")
    await session.delete(proc)
    await session.commit()
    return {}
