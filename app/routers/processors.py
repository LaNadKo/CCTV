"""Processor management router."""
from __future__ import annotations

import base64
import asyncio
import json
import logging
import secrets
import os
import subprocess
import time
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Request, UploadFile, status
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app import models
from app.config import settings
from app.db import get_session
from app.dependencies import get_current_user, get_service_identity, get_service_scopes
from app.ffmpeg_tools import ffmpeg_bin, ffprobe_bin
from app.permissions import is_admin
from app.rate_limit import check_rate_limit
from app.processor_media import (
    build_processor_file_path,
    effective_processor_status,
    is_processor_effectively_online,
    parse_processor_file_path,
    safe_processor_relative_path,
)
from app.recording_storage import (
    backend_recording_path,
    ensure_backend_storage_target,
    ensure_video_stream,
    safe_recording_relative_path,
    sha256_file,
)
from app.schemas.processors import (
    AssignCamerasIn,
    AssignedCameraInfo,
    CameraAssignment,
    EndpointInfo,
    PresetInfo,
    GalleryEntry,
    GenerateCodeOut,
    ProcessorCommandCreate,
    ProcessorCommandOut,
    ProcessorCommandResult,
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
from app.security import decrypt_secret, hash_api_key

router = APIRouter(prefix="/processors", tags=["processors"])
log = logging.getLogger("app.processors")
_gallery_cache: list[GalleryEntry] | None = None
_gallery_cache_ts = 0.0
_GALLERY_CACHE_TTL = 30.0
_MAX_EVENT_SNAPSHOT_BYTES = 8 * 1024 * 1024
_MAX_EVENT_SNAPSHOT_B64_CHARS = ((_MAX_EVENT_SNAPSHOT_BYTES + 2) // 3) * 4
_MAX_PROCESSOR_COMMAND_RESULT_BODY_BYTES = 256 * 1024
_PROCESSOR_CONNECTION_CODE_BYTES = 12
_PROCESSOR_CONNECTION_CODE_TTL_MINUTES = 15
_PROCESSOR_CONNECT_ATTEMPTS_PER_IP = 20
_PROCESSOR_CONNECT_ATTEMPTS_PER_CODE_AND_IP = 5
_PROCESSOR_CONNECT_RATE_WINDOW_SECONDS = 5 * 60


class UploadTooLargeError(Exception):
    pass


def _copy_upload_to_path(source, destination: Path, max_bytes: int) -> int:
    source.seek(0)
    total = 0
    with destination.open("wb") as target:
        while True:
            chunk = source.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                raise UploadTooLargeError(f"Upload exceeds {max_bytes} bytes")
            target.write(chunk)
    return total


def _ffmpeg_bin() -> str | None:
    return ffmpeg_bin()


def _ffprobe_bin() -> str | None:
    return ffprobe_bin(_ffmpeg_bin())


def _video_codec(path: Path) -> str | None:
    ffprobe_bin = _ffprobe_bin()
    if not ffprobe_bin:
        return None
    try:
        proc = subprocess.run(
            [
                ffprobe_bin,
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=codec_name",
                "-of",
                "default=nokey=1:noprint_wrappers=1",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.strip().lower() or None


def _normalize_video_upload(path: Path) -> bool:
    ffmpeg_bin = _ffmpeg_bin()
    if not ffmpeg_bin or not path.is_file() or path.stat().st_size <= 0:
        return False

    codec = _video_codec(path)

    temp = path.with_name(f"{path.name}.{os.getpid()}.h264.tmp.mp4")
    if codec == "h264":
        cmd = [
            ffmpeg_bin,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(path),
            "-map",
            "0:v:0",
            "-c:v",
            "copy",
            "-an",
            "-movflags",
            "+faststart",
            str(temp),
        ]
    else:
        cmd = [
            ffmpeg_bin,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(path),
            "-vf",
            "scale=trunc(iw/2)*2:trunc(ih/2)*2",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-tune",
            "zerolatency",
            "-pix_fmt",
            "yuv420p",
            "-an",
            "-movflags",
            "+faststart",
            str(temp),
        ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        if proc.returncode != 0 or not temp.is_file() or temp.stat().st_size <= 0:
            log.warning("Failed to normalize uploaded recording %s: %s", path, (proc.stderr or "")[-500:])
            return False
        converted_codec = _video_codec(temp)
        if converted_codec is not None and converted_codec != "h264":
            log.warning("Normalized recording %s is not H264", temp)
            return False
        temp.replace(path)
        return True
    except Exception:
        log.exception("Failed to normalize uploaded recording %s", path)
        return False
    finally:
        if temp.exists():
            try:
                temp.unlink()
            except OSError:
                pass


def _normalize_uploads_enabled() -> bool:
    return os.getenv("CCTV_NORMALIZE_UPLOADED_RECORDINGS", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
_PROCESSOR_STORAGE_NAME = "Processor Media"
SUPPORTED_COMMANDS = {
    "reload_assignments",
    "restart_workers",
    "stop_all_cameras",
    "resume_cameras",
    "refresh_gallery",
    "start_runtime",
    "stop_runtime",
    "restart_runtime",
    "apply_detection_settings",
}
SUPERVISOR_COMMANDS = {"start_runtime", "stop_runtime", "restart_runtime"}
_MAX_COMMAND_RESULT_CHARS = 64 * 1024


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


async def _require_service_scope(
    session: AsyncSession,
    x_api_key: str,
    scope: str,
) -> tuple[int, list[str]]:
    api_key_id, scopes = await get_service_identity(x_api_key, session)
    if scope not in scopes and "*" not in scopes:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Missing scope: {scope}")
    return api_key_id, scopes


async def _authorize_processor_key(
    session: AsyncSession,
    processor_id: int,
    x_api_key: str,
    scope: str,
) -> tuple[models.Processor, list[str]]:
    api_key_id, scopes = await _require_service_scope(session, x_api_key, scope)
    proc = await session.get(models.Processor, processor_id)
    if not proc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Processor not found")
    if "*" not in scopes:
        if proc.api_key_id is None:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Processor is not paired to this API key")
        if proc.api_key_id != api_key_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="API key is not bound to this processor")
    return proc, scopes


async def _ensure_processor_camera_assignment(
    session: AsyncSession,
    processor_id: int,
    camera_id: int,
    scopes: list[str],
) -> None:
    if "*" in scopes:
        return
    result = await session.execute(
        select(models.ProcessorCameraAssignment).where(
            models.ProcessorCameraAssignment.processor_id == processor_id,
            models.ProcessorCameraAssignment.camera_id == camera_id,
        )
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Camera is not assigned to this processor")


async def _processor_has_camera_assignments(session: AsyncSession, processor_id: int) -> bool:
    result = await session.execute(
        select(models.ProcessorCameraAssignment.camera_id)
        .where(models.ProcessorCameraAssignment.processor_id == processor_id)
        .limit(1)
    )
    return result.first() is not None


def _ensure_admin(user: models.User) -> None:
    if not is_admin(user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin only")


def invalidate_gallery_cache() -> None:
    global _gallery_cache, _gallery_cache_ts
    _gallery_cache = None
    _gallery_cache_ts = 0.0


def _decode_snapshot_b64(snapshot_b64: str | None) -> bytes | None:
    if not snapshot_b64:
        return None
    raw = snapshot_b64.strip()
    if raw.startswith("data:") and "," in raw:
        raw = raw.split(",", 1)[1]
    if len(raw) > _MAX_EVENT_SNAPSHOT_B64_CHARS:
        raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail="Snapshot payload is too large")
    try:
        decoded = base64.b64decode(raw, validate=True)
    except Exception:
        return None
    if len(decoded) > _MAX_EVENT_SNAPSHOT_BYTES:
        raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail="Snapshot payload is too large")
    return decoded


def _store_snapshot(event_id: int, snapshot_bytes: bytes) -> str:
    snapshots_dir = Path("snapshots")
    snapshots_dir.mkdir(parents=True, exist_ok=True)
    path = snapshots_dir / f"event_{event_id}.jpg"
    path.write_bytes(snapshot_bytes)
    return str(path)


def _safe_node_uid(value: str | None) -> str | None:
    if not value:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    return normalized[:128]


async def _find_processor_for_node(
    session: AsyncSession,
    *,
    node_uid: str | None,
    api_key_id: int | None = None,
    name: str | None = None,
    hostname: str | None = None,
) -> models.Processor | None:
    if node_uid:
        result = await session.execute(
            select(models.Processor).where(models.Processor.node_uid == node_uid)
        )
        found = result.scalar_one_or_none()
        if found is not None:
            return found
    if name and hostname:
        filters = [
            models.Processor.name == name,
            models.Processor.hostname == hostname,
        ]
        if api_key_id is not None:
            filters.append(models.Processor.api_key_id == api_key_id)
        result = await session.execute(
            select(models.Processor).where(*filters)
        )
        return result.scalar_one_or_none()
    return None


def _apply_processor_metadata(
    proc: models.Processor,
    *,
    name: str,
    node_uid: str | None,
    api_key_id: int | None,
    status_value: str,
    hostname: str | None,
    ip_address: str | None,
    os_info: str | None,
    version: str | None,
    capabilities: dict | None,
) -> None:
    proc.name = name
    proc.node_uid = node_uid or proc.node_uid
    proc.api_key_id = api_key_id if api_key_id is not None else proc.api_key_id
    proc.hostname = hostname or proc.hostname
    proc.ip_address = ip_address or proc.ip_address
    proc.os_info = os_info or proc.os_info
    proc.version = version or proc.version
    proc.status = status_value
    proc.last_heartbeat = datetime.utcnow()
    if capabilities is not None:
        proc.capabilities = json.dumps(capabilities)


def _json_or_none(value: str | None):
    if not value:
        return None
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return value


def _limited_command_text(value, *, field_name: str) -> str | None:
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        text = json.dumps(value, ensure_ascii=False)
    else:
        text = str(value)
    if len(text) > _MAX_COMMAND_RESULT_CHARS:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"{field_name} is too large",
        )
    return text


async def _read_command_result_payload(request: Request) -> ProcessorCommandResult:
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > _MAX_PROCESSOR_COMMAND_RESULT_BODY_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail="Processor command result body is too large",
            )
    try:
        raw_payload = json.loads(bytes(body))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON body") from exc
    try:
        return ProcessorCommandResult.model_validate(raw_payload)
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=exc.errors()) from exc


def _command_to_out(command: models.ProcessorCommand) -> ProcessorCommandOut:
    return ProcessorCommandOut(
        command_id=command.command_id,
        processor_id=command.processor_id,
        command_type=command.command_type,
        payload=_json_or_none(command.payload),
        status=command.status,
        result=_json_or_none(command.result),
        error_message=command.error_message,
        requested_by_user_id=command.requested_by_user_id,
        created_at=command.created_at,
        claimed_at=command.claimed_at,
        completed_at=command.completed_at,
    )


def _queue_processor_command(
    session: AsyncSession,
    processor_id: int,
    command_type: str,
    requested_by_user_id: int | None = None,
) -> None:
    session.add(
        models.ProcessorCommand(
            processor_id=processor_id,
            command_type=command_type,
            status="pending",
            requested_by_user_id=requested_by_user_id,
        )
    )


# ── Connection code flow (universal: LAN + WAN) ──

def _new_processor_connection_code() -> str:
    return secrets.token_urlsafe(_PROCESSOR_CONNECTION_CODE_BYTES).upper()


@router.post("/generate-code", response_model=GenerateCodeOut)
async def generate_connection_code(
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user),
):
    """Admin generates a short-lived code that a processor app uses to register."""
    _ensure_admin(current_user)
    code = _new_processor_connection_code()
    expires = datetime.utcnow() + timedelta(minutes=_PROCESSOR_CONNECTION_CODE_TTL_MINUTES)
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
    check_rate_limit(
        request,
        "processor-connect-ip",
        attempts=_PROCESSOR_CONNECT_ATTEMPTS_PER_IP,
        window_seconds=_PROCESSOR_CONNECT_RATE_WINDOW_SECONDS,
        detail="Too many processor connection attempts",
    )
    check_rate_limit(
        request,
        f"processor-connect-code:{payload.code}",
        attempts=_PROCESSOR_CONNECT_ATTEMPTS_PER_CODE_AND_IP,
        window_seconds=_PROCESSOR_CONNECT_RATE_WINDOW_SECONDS,
        detail="Too many attempts for this processor connection code",
    )
    result = await session.execute(
        select(models.ProcessorConnectionCode).where(
            models.ProcessorConnectionCode.code == payload.code,
            models.ProcessorConnectionCode.used_at.is_(None),
        ).with_for_update()
    )
    code_rec = result.scalar_one_or_none()
    if not code_rec:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invalid or already used code")
    if code_rec.expires_at < datetime.utcnow():
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="Code expired")

    # Detect IP from request
    client_ip = payload.ip_address or (request.client.host if request.client else None)

    node_uid = _safe_node_uid(payload.node_uid)
    proc = await _find_processor_for_node(
        session,
        node_uid=node_uid,
        name=payload.name,
        hostname=payload.hostname,
    )
    if proc is not None and proc.api_key_id is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Processor is already paired; revoke its API key before reconnecting",
        )

    # Generate API key only after the one-time code and target processor have
    # been locked and validated.
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

    if proc is None:
        proc = models.Processor(name=payload.name, status="online")
        session.add(proc)
    _apply_processor_metadata(
        proc,
        name=payload.name,
        node_uid=node_uid,
        api_key_id=api_key.api_key_id,
        status_value="online",
        hostname=payload.hostname,
        ip_address=client_ip,
        os_info=payload.os_info,
        version=payload.version,
        capabilities=payload.capabilities,
    )
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
    x_api_key: str = Header(...),
):
    api_key_id, _scopes = await _require_service_scope(session, x_api_key, "processor:register")
    node_uid = _safe_node_uid(payload.node_uid)
    proc = await _find_processor_for_node(
        session,
        node_uid=node_uid,
        api_key_id=api_key_id,
        name=payload.name,
        hostname=payload.hostname,
    )
    if proc is None:
        proc = models.Processor(name=payload.name, status="registered")
        session.add(proc)
    elif proc.api_key_id is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Processor is unpaired; reconnect it with a connection code",
        )
    elif proc.api_key_id != api_key_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Processor is already paired to another API key",
        )
    _apply_processor_metadata(
        proc,
        name=payload.name,
        node_uid=node_uid,
        api_key_id=api_key_id,
        status_value="registered",
        hostname=payload.hostname,
        ip_address=payload.ip_address,
        os_info=payload.os_info,
        version=payload.version,
        capabilities=payload.capabilities,
    )
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
    proc, _scopes = await _authorize_processor_key(session, processor_id, x_api_key, "processor:heartbeat")
    heartbeat_at = datetime.utcnow()
    is_supervisor_heartbeat = payload.status == "supervisor_online"
    if not is_supervisor_heartbeat:
        proc.status = payload.status
        proc.last_heartbeat = heartbeat_at
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
    if payload.media_port is not None or payload.media_token or is_supervisor_heartbeat:
        capabilities = {}
        if proc.capabilities:
            try:
                capabilities = json.loads(proc.capabilities)
            except (json.JSONDecodeError, TypeError):
                capabilities = {}
        if payload.capabilities:
            capabilities.update(payload.capabilities)
        if is_supervisor_heartbeat:
            capabilities["supervisor"] = {
                "online": True,
                "runtime_running": (payload.stats or {}).get("runtime_running"),
                "heartbeat_at": heartbeat_at.isoformat(),
            }
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
    _proc, scopes = await _authorize_processor_key(session, processor_id, x_api_key, "processor:read")
    if "*" not in scopes and not await _processor_has_camera_assignments(session, processor_id):
        return []
    stmt = (
        select(models.ProcessorCameraAssignment)
        .join(models.Camera, models.Camera.camera_id == models.ProcessorCameraAssignment.camera_id)
        .where(
            models.ProcessorCameraAssignment.processor_id == processor_id,
            models.Camera.deleted_at.is_(None),
        )
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
        preset_result = await session.execute(
            select(models.CameraPreset)
            .where(models.CameraPreset.camera_id == cam.camera_id)
            .order_by(models.CameraPreset.order_index.asc(), models.CameraPreset.camera_preset_id.asc())
        )
        endpoints = [
            EndpointInfo(
                endpoint_kind=e.endpoint_kind,
                endpoint_url=e.endpoint_url,
                username=e.username,
                password_secret=decrypt_secret(e.password_secret) if e.password_secret else None,
                is_primary=e.is_primary,
            )
            for e in ep_result.scalars().all()
        ]
        presets = [
            PresetInfo(
                camera_preset_id=row.camera_preset_id,
                name=row.name,
                preset_token=row.preset_token,
                order_index=row.order_index,
                dwell_seconds=row.dwell_seconds,
            )
            for row in preset_result.scalars().all()
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
            tracking_target_person_id=cam.tracking_target_person_id,
            connection_kind=cam.connection_kind,
            supports_ptz=cam.supports_ptz,
            onvif_profile_token=cam.onvif_profile_token,
            endpoints=endpoints,
            presets=presets,
        ))
    return out


@router.post("/{processor_id}/events", response_model=ProcessorEventOut)
async def push_event(
    processor_id: int,
    payload: ProcessorEventIn,
    session: AsyncSession = Depends(get_session),
    x_api_key: str = Header(...),
):
    _proc, scopes = await _authorize_processor_key(session, processor_id, x_api_key, "processor:write")
    et_result = await session.execute(
        select(models.EventType).where(models.EventType.name == payload.event_type)
    )
    et = et_result.scalar_one_or_none()
    if et is None:
        raise HTTPException(status_code=400, detail=f"Unknown event type: {payload.event_type}")
    cam = await session.get(models.Camera, payload.camera_id)
    if cam is None or cam.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Camera not found")
    await _ensure_processor_camera_assignment(session, processor_id, payload.camera_id, scopes)
    event_type_id = et.event_type_id
    review_required = payload.event_type == "face_unknown"
    resolved_person_id = payload.person_id
    if resolved_person_id is not None:
        person = await session.get(models.Person, resolved_person_id)
        if person is None or person.deleted_at is not None:
            resolved_person_id = None
            if payload.event_type == "face_recognized":
                fallback_result = await session.execute(
                    select(models.EventType).where(models.EventType.name == "face_unknown")
                )
                fallback = fallback_result.scalar_one_or_none()
                if fallback is not None:
                    event_type_id = fallback.event_type_id
                    review_required = True
    evt = models.Event(
        camera_id=payload.camera_id,
        event_type_id=event_type_id,
        person_id=resolved_person_id,
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
    _proc, scopes = await _authorize_processor_key(session, processor_id, x_api_key, "processor:write")
    cam = await session.get(models.Camera, payload.camera_id)
    if not cam or cam.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Camera not found")
    await _ensure_processor_camera_assignment(session, processor_id, payload.camera_id, scopes)
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
    parsed_path = parse_processor_file_path(payload.file_path)
    if parsed_path is not None:
        source_processor_id, relative_path = parsed_path
        if source_processor_id != processor_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Recording path belongs to another processor",
            )
    else:
        try:
            relative_path = safe_processor_relative_path(payload.file_path)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Invalid processor recording path",
            ) from exc
    rf = models.RecordingFile(
        video_stream_id=vs.video_stream_id,
        storage_target_id=st.storage_target_id,
        file_kind=payload.file_kind,
        file_path=build_processor_file_path(processor_id, relative_path),
        started_at=payload.started_at or datetime.utcnow(),
        ended_at=payload.ended_at,
        duration_seconds=payload.duration_seconds,
        file_size_bytes=payload.file_size_bytes,
    )
    session.add(rf)
    await session.commit()
    await session.refresh(rf)
    return ProcessorRecordingOut(recording_file_id=rf.recording_file_id)


@router.post("/{processor_id}/recordings/upload", response_model=ProcessorRecordingOut)
async def upload_recording(
    processor_id: int,
    camera_id: int = Form(...),
    file_path: str = Form(...),
    file_kind: str = Form(default="video"),
    started_at: datetime | None = Form(default=None),
    ended_at: datetime | None = Form(default=None),
    duration_seconds: float | None = Form(default=None),
    file_size_bytes: int | None = Form(default=None),
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
    x_api_key: str = Header(...),
):
    _proc, scopes = await _authorize_processor_key(session, processor_id, x_api_key, "processor:write")
    if file_kind not in {"video", "snapshot"}:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Unsupported file_kind")
    cam = await session.get(models.Camera, camera_id)
    if not cam or cam.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Camera not found")
    await _ensure_processor_camera_assignment(session, processor_id, camera_id, scopes)

    started = started_at or datetime.utcnow()
    relative_path = safe_recording_relative_path(
        camera_id=camera_id,
        started_at=started,
        source_path=file_path,
    )
    destination = backend_recording_path(relative_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_path = destination.with_name(
        f".{destination.name}.{secrets.token_hex(12)}.upload"
    )

    actual_size = 0
    try:
        try:
            actual_size = await asyncio.to_thread(
                _copy_upload_to_path,
                file.file,
                temp_path,
                settings.processor_recording_upload_max_bytes,
            )
        except UploadTooLargeError as exc:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail=f"Recording upload is too large; limit is {settings.processor_recording_upload_max_bytes} bytes",
            ) from exc
        if actual_size <= 0:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Empty recording upload")

        if file_kind == "video" and _normalize_uploads_enabled():
            await asyncio.to_thread(_normalize_video_upload, temp_path)
            actual_size = temp_path.stat().st_size

        checksum = await asyncio.to_thread(sha256_file, temp_path)
        suffix = f"_p{processor_id}_{int(started.timestamp())}_{checksum[:12]}"
        final_path = destination.with_name(
            f"{destination.stem}{suffix}{destination.suffix}"
        )
        temp_path.replace(final_path)

        existing_result = await session.execute(
            select(models.RecordingFile).where(models.RecordingFile.file_path == str(final_path))
        )
        existing = existing_result.scalar_one_or_none()
        if existing is not None:
            existing.file_size_bytes = actual_size
            existing.checksum = checksum
            existing.ended_at = ended_at or existing.ended_at
            existing.duration_seconds = duration_seconds or existing.duration_seconds
            await session.commit()
            return ProcessorRecordingOut(recording_file_id=existing.recording_file_id)

        video_stream = await ensure_video_stream(session, camera_id)
        storage_target = await ensure_backend_storage_target(session)
        recording = models.RecordingFile(
            video_stream_id=video_stream.video_stream_id,
            storage_target_id=storage_target.storage_target_id,
            file_kind=file_kind,
            file_path=str(final_path),
            started_at=started,
            ended_at=ended_at,
            duration_seconds=duration_seconds,
            file_size_bytes=actual_size if actual_size is not None else file_size_bytes,
            checksum=checksum,
        )
        session.add(recording)
        await session.commit()
        await session.refresh(recording)
        return ProcessorRecordingOut(recording_file_id=recording.recording_file_id)
    finally:
        await file.close()
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                log.warning("Failed to remove temporary upload %s", temp_path)


@router.get("/{processor_id}/gallery", response_model=list[GalleryEntry])
async def get_gallery(
    processor_id: int,
    session: AsyncSession = Depends(get_session),
    x_api_key: str = Header(...),
):
    global _gallery_cache, _gallery_cache_ts
    _proc, scopes = await _authorize_processor_key(session, processor_id, x_api_key, "processor:read")
    if "*" not in scopes and not await _processor_has_camera_assignments(session, processor_id):
        return []
    now = time.monotonic()
    if _gallery_cache is not None and (now - _gallery_cache_ts) < _GALLERY_CACHE_TTL:
        return _gallery_cache
    pe_result = await session.execute(
        select(models.PersonEmbedding, models.Person)
        .join(models.Person, models.PersonEmbedding.person_id == models.Person.person_id)
        .where(models.Person.deleted_at.is_(None))
    )
    rows = pe_result.all()
    gallery = []
    for emb_row, p in rows:
        label_parts = [p.last_name, p.first_name, p.middle_name]
        label = " ".join(x for x in label_parts if x) or f"Person #{p.person_id}"
        gallery.append(GalleryEntry(
            person_id=p.person_id,
            label=label,
            embedding_b64=base64.b64encode(emb_row.embedding).decode(),
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
    _proc, scopes = await _authorize_processor_key(session, processor_id, x_api_key, "processor:read")
    if "*" not in scopes and not await _processor_has_camera_assignments(session, processor_id):
        return StorageConfigOut(
            storage_type="local",
            root_path="processor://local",
            connection_config={"mode": "processor_local"},
        )
    st_result = await session.execute(
        select(models.StorageTarget).where(models.StorageTarget.is_primary_recording.is_(True)).limit(1)
    )
    st = st_result.scalar_one_or_none()
    if not st:
        st_result = await session.execute(select(models.StorageTarget).limit(1))
        st = st_result.scalar_one_or_none()
    if not st:
        return StorageConfigOut(
            storage_type="local",
            root_path="processor://local",
            connection_config={"mode": "processor_local"},
        )
    config = None
    if st.connection_config:
        try:
            config = json.loads(st.connection_config)
        except (json.JSONDecodeError, TypeError):
            pass
    return StorageConfigOut(storage_type=st.storage_type, root_path=st.root_path, connection_config=config)


@router.get("/{processor_id}/commands/pending", response_model=list[ProcessorCommandOut])
async def claim_pending_commands(
    processor_id: int,
    limit: int = 10,
    runner: str = "runtime",
    session: AsyncSession = Depends(get_session),
    x_api_key: str = Header(...),
):
    _proc, _scopes = await _authorize_processor_key(session, processor_id, x_api_key, "processor:read")
    safe_limit = max(1, min(limit, 25))
    command_filter = models.ProcessorCommand.command_type.notin_(SUPERVISOR_COMMANDS)
    if runner.strip().lower() == "supervisor":
        command_filter = models.ProcessorCommand.command_type.in_(SUPERVISOR_COMMANDS)
    result = await session.execute(
        select(models.ProcessorCommand)
        .where(
            models.ProcessorCommand.processor_id == processor_id,
            models.ProcessorCommand.status == "pending",
            command_filter,
        )
        .order_by(models.ProcessorCommand.created_at.asc(), models.ProcessorCommand.command_id.asc())
        .limit(safe_limit)
        .with_for_update(skip_locked=True)
    )
    commands = result.scalars().all()
    now = datetime.utcnow()
    for command in commands:
        command.status = "running"
        command.claimed_at = now
    await session.commit()
    for command in commands:
        await session.refresh(command)
    return [_command_to_out(command) for command in commands]


@router.post("/{processor_id}/commands/{command_id}/result", response_model=ProcessorCommandOut)
async def complete_processor_command(
    processor_id: int,
    command_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
    x_api_key: str = Header(...),
):
    payload = await _read_command_result_payload(request)
    _proc, _scopes = await _authorize_processor_key(session, processor_id, x_api_key, "processor:write")
    if payload.status not in {"succeeded", "failed"}:
        raise HTTPException(status_code=400, detail="Command result status must be succeeded or failed")
    command = await session.get(models.ProcessorCommand, command_id)
    if not command or command.processor_id != processor_id:
        raise HTTPException(status_code=404, detail="Command not found")
    if command.status == "cancelled":
        raise HTTPException(status_code=409, detail="Command is cancelled")
    if command.status != "running":
        raise HTTPException(status_code=409, detail="Command is not running")
    command.status = payload.status
    command.result = _limited_command_text(payload.result, field_name="Command result")
    command.error_message = _limited_command_text(payload.error_message, field_name="Command error")
    command.completed_at = datetime.utcnow()
    await session.commit()
    await session.refresh(command)
    return _command_to_out(command)


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
            select(func.count())
            .select_from(models.ProcessorCameraAssignment)
            .join(models.Camera, models.Camera.camera_id == models.ProcessorCameraAssignment.camera_id)
            .where(
                models.ProcessorCameraAssignment.processor_id == p.processor_id,
                models.Camera.deleted_at.is_(None),
            )
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
            .where(
                models.ProcessorCameraAssignment.processor_id == p.processor_id,
                models.Camera.deleted_at.is_(None),
            )
        )
        assigned = [AssignedCameraInfo(camera_id=cam.camera_id, name=cam.name) for _, cam in cam_result.all()]
        pending_result = await session.execute(
            select(func.count())
            .select_from(models.ProcessorCommand)
            .where(
                models.ProcessorCommand.processor_id == p.processor_id,
                models.ProcessorCommand.status == "pending",
            )
        )
        running_result = await session.execute(
            select(func.count())
            .select_from(models.ProcessorCommand)
            .where(
                models.ProcessorCommand.processor_id == p.processor_id,
                models.ProcessorCommand.status == "running",
            )
        )
        last_command_result = await session.execute(
            select(models.ProcessorCommand)
            .where(models.ProcessorCommand.processor_id == p.processor_id)
            .order_by(models.ProcessorCommand.created_at.desc(), models.ProcessorCommand.command_id.desc())
            .limit(1)
        )
        last_command = last_command_result.scalar_one_or_none()
        out.append(ProcessorOut(
            processor_id=p.processor_id,
            name=p.name,
            node_uid=p.node_uid,
            status=effective_processor_status(p),
            last_heartbeat=p.last_heartbeat,
            capabilities=caps,
            ip_address=p.ip_address,
            os_info=p.os_info,
            version=p.version,
            metrics=metrics,
            created_at=p.created_at,
            camera_count=cnt,
            assigned_cameras=assigned,
            pending_commands=pending_result.scalar() or 0,
            running_commands=running_result.scalar() or 0,
            last_command=_command_to_out(last_command) if last_command else None,
        ))
    return out


@router.get("/{processor_id}/commands", response_model=list[ProcessorCommandOut])
async def list_processor_commands(
    processor_id: int,
    limit: int = 30,
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user),
):
    _ensure_admin(current_user)
    proc = await session.get(models.Processor, processor_id)
    if not proc:
        raise HTTPException(status_code=404, detail="Processor not found")
    safe_limit = max(1, min(limit, 100))
    result = await session.execute(
        select(models.ProcessorCommand)
        .where(models.ProcessorCommand.processor_id == processor_id)
        .order_by(models.ProcessorCommand.created_at.desc(), models.ProcessorCommand.command_id.desc())
        .limit(safe_limit)
    )
    return [_command_to_out(command) for command in result.scalars().all()]


@router.post("/{processor_id}/commands", response_model=ProcessorCommandOut, status_code=status.HTTP_201_CREATED)
async def create_processor_command(
    processor_id: int,
    payload: ProcessorCommandCreate,
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user),
):
    _ensure_admin(current_user)
    proc = await session.get(models.Processor, processor_id)
    if not proc:
        raise HTTPException(status_code=404, detail="Processor not found")
    command_type = payload.command_type.strip()
    if command_type not in SUPPORTED_COMMANDS:
        raise HTTPException(status_code=400, detail=f"Unsupported command: {command_type}")
    if command_type == "start_runtime" and is_processor_effectively_online(proc):
        command = models.ProcessorCommand(
            processor_id=processor_id,
            command_type=command_type,
            payload=json.dumps(payload.payload or {}),
            status="succeeded",
            requested_by_user_id=current_user.user_id,
            completed_at=datetime.utcnow(),
            result=json.dumps({"message": "Runtime is already running"}),
        )
        session.add(command)
        await session.commit()
        await session.refresh(command)
        return _command_to_out(command)
    command = models.ProcessorCommand(
        processor_id=processor_id,
        command_type=command_type,
        payload=json.dumps(payload.payload or {}),
        status="pending",
        requested_by_user_id=current_user.user_id,
    )
    session.add(command)
    await session.commit()
    await session.refresh(command)
    return _command_to_out(command)


@router.post("/{processor_id}/commands/{command_id}/cancel", response_model=ProcessorCommandOut)
async def cancel_processor_command(
    processor_id: int,
    command_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user),
):
    _ensure_admin(current_user)
    command = await session.get(models.ProcessorCommand, command_id)
    if not command or command.processor_id != processor_id:
        raise HTTPException(status_code=404, detail="Command not found")
    if command.status not in {"pending", "running"}:
        return _command_to_out(command)
    command.status = "cancelled"
    command.completed_at = datetime.utcnow()
    await session.commit()
    await session.refresh(command)
    return _command_to_out(command)


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
    changed = False
    for cid in payload.camera_ids:
        cam = await session.get(models.Camera, cid)
        if not cam or cam.deleted_at is not None:
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
        changed = True
    if changed:
        _queue_processor_command(session, processor_id, "reload_assignments", current_user.user_id)
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
        _queue_processor_command(session, processor_id, "reload_assignments", current_user.user_id)
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
