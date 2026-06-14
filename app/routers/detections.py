import asyncio
import logging
import time
from typing import List
from pathlib import Path
from datetime import datetime

import cv2
import httpx
import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Header, status, Query
from fastapi.responses import FileResponse, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.db import get_session
from app.dependencies import get_current_user, get_current_user_allow_query, get_current_user_optional, get_service_scopes
from app.permissions import check_permission, user_camera_permission_sync, is_admin
from app.processor_media import get_processor_by_id, get_processor_media_base_url, get_processor_media_headers
from app.schemas.detections import (
    DetectionIn,
    DetectionResponse,
    EventReviewUpdate,
    PendingEvent,
    ReviewCandidate,
)
from app.vision import extract_best_face_embedding as _extract_best_face_embedding

router = APIRouter(prefix="/detections", tags=["detections"])
log = logging.getLogger(__name__)

_CANDIDATE_CACHE_TTL_SECONDS = 180.0
_candidate_cache: dict[int, tuple[float, list[ReviewCandidate]]] = {}
_MAX_EVENT_SNAPSHOT_PROXY_BYTES = 8 * 1024 * 1024
_MAX_EVENT_SNAPSHOT_PIXELS = 12_000_000


async def _find_event_type_id(session: AsyncSession, name: str) -> int:
    res = await session.execute(select(models.EventType).where(models.EventType.name == name))
    et = res.scalar_one_or_none()
    if et is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unknown event type: {name}")
    return et.event_type_id


def _person_label(person: models.Person) -> str:
    parts = [person.last_name, person.first_name, person.middle_name]
    return " ".join(part for part in parts if part) or f"Персона #{person.person_id}"


def _cos_sim(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-6))


def _decoded_image_pixel_count(image) -> int:
    if getattr(image, "ndim", 0) < 2:
        return 0
    shape = getattr(image, "shape", ())
    if len(shape) < 2:
        return 0
    return int(shape[0]) * int(shape[1])


def _decode_image(data: bytes) -> np.ndarray | None:
    arr = np.frombuffer(data, dtype=np.uint8)
    if arr.size == 0:
        return None
    image = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if image is None:
        return None
    if _decoded_image_pixel_count(image) > _MAX_EVENT_SNAPSHOT_PIXELS:
        return None
    return image


async def _fetch_processor_snapshot_bytes(
    url: str,
    headers: dict[str, str],
    *,
    timeout: float,
) -> tuple[bytes, str] | None:
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream("GET", url, headers=headers) as upstream:
                if upstream.status_code >= 400:
                    return None
                content_length = upstream.headers.get("content-length")
                if content_length:
                    try:
                        if int(content_length) > _MAX_EVENT_SNAPSHOT_PROXY_BYTES:
                            return None
                    except ValueError:
                        pass
                payload = bytearray()
                async for chunk in upstream.aiter_bytes():
                    if not chunk:
                        continue
                    payload.extend(chunk)
                    if len(payload) > _MAX_EVENT_SNAPSHOT_PROXY_BYTES:
                        return None
                return bytes(payload), upstream.headers.get("content-type", "image/jpeg")
    except httpx.HTTPError:
        return None


async def _read_event_snapshot_bytes(session: AsyncSession, event: models.Event) -> bytes | None:
    local_snapshot = Path("snapshots").resolve() / f"event_{event.event_id}.jpg"
    if local_snapshot.exists():
        try:
            return local_snapshot.read_bytes()
        except OSError:
            return None

    if event.processor_id is None:
        return None
    proc = await get_processor_by_id(session, event.processor_id)
    if proc is None:
        return None
    try:
        url = f"{get_processor_media_base_url(proc)}/media/snapshots/event_{event.event_id}.jpg"
    except RuntimeError:
        return None
    headers = get_processor_media_headers(proc)
    fetched = await _fetch_processor_snapshot_bytes(url, headers, timeout=6.0)
    if fetched is None:
        return None
    return fetched[0]


async def _event_candidate_persons(
    session: AsyncSession,
    event: models.Event,
    limit: int = 3,
) -> list[ReviewCandidate]:
    limit = max(1, min(limit, 5))
    cached = _candidate_cache.get(event.event_id)
    now = time.monotonic()
    if cached and now - cached[0] <= _CANDIDATE_CACHE_TTL_SECONDS:
        return cached[1][:limit]

    image_bytes = await _read_event_snapshot_bytes(session, event)
    if not image_bytes:
        _candidate_cache[event.event_id] = (now, [])
        return []
    image = _decode_image(image_bytes)
    if image is None:
        _candidate_cache[event.event_id] = (now, [])
        return []

    try:
        emb = await asyncio.to_thread(_extract_best_face_embedding, image)
    except Exception:
        log.exception("Local review candidate embedding extraction failed for event=%s", event.event_id)
        emb = None
    if emb is None:
        try:
            from app.routers.persons import _extract_best_face_embedding_via_processor

            emb = await _extract_best_face_embedding_via_processor(session, image, event.camera_id)
        except HTTPException as exc:
            log.warning(
                "Processor review candidate embedding extraction failed for event=%s detail=%s",
                event.event_id,
                exc.detail,
            )
            emb = None
        except Exception:
            log.exception("Processor review candidate embedding extraction crashed for event=%s", event.event_id)
            emb = None
    if emb is None:
        _candidate_cache[event.event_id] = (now, [])
        return []

    result = await session.execute(
        select(models.PersonEmbedding, models.Person)
        .join(models.Person, models.PersonEmbedding.person_id == models.Person.person_id)
        .where(models.Person.deleted_at.is_(None))
    )
    best_by_person: dict[int, tuple[float, models.Person]] = {}
    probe = np.asarray(emb, dtype=np.float32)
    for embedding_row, person in result.all():
        ref = np.frombuffer(embedding_row.embedding, dtype=np.float32)
        if ref.size == 0 or ref.shape != probe.shape:
            continue
        similarity = _cos_sim(probe, ref)
        previous = best_by_person.get(person.person_id)
        if previous is None or similarity > previous[0]:
            best_by_person[person.person_id] = (similarity, person)

    candidates = [
        ReviewCandidate(
            person_id=person.person_id,
            person_label=_person_label(person),
            similarity=round(max(0.0, min(similarity, 1.0)), 4),
            probability=round(max(0.0, min(similarity, 1.0)) * 100.0, 2),
        )
        for similarity, person in best_by_person.values()
        if similarity >= 0.35
    ]
    candidates.sort(key=lambda item: item.similarity, reverse=True)
    candidates = candidates[:5]
    _candidate_cache[event.event_id] = (now, candidates)
    return candidates[:limit]


async def _notify_admins_for_camera(session: AsyncSession, camera_id: int, event_id: int) -> None:
    """Notify all admins about unknown face detection."""
    res_admins = await session.execute(select(models.User.user_id).where(models.User.role_id == 1))
    admin_ids = set(res_admins.scalars().all())

    for user_id in admin_ids:
        notif = models.Notification(
            event_id=event_id,
            title="Unknown face detected",
            message=f"Camera {camera_id}: review required",
            severity="warning",
        )
        session.add(notif)
        await session.flush()
        delivery = models.NotificationDelivery(
            notification_id=notif.notification_id,
            user_id=user_id,
            channel="push",
            status="pending",
        )
        session.add(delivery)


@router.post("", response_model=DetectionResponse, status_code=status.HTTP_201_CREATED)
async def create_detection(
    payload: DetectionIn,
    session: AsyncSession = Depends(get_session),
    current_user: models.User | None = Depends(get_current_user_optional),
    x_api_key: str | None = Header(default=None, alias="X-Api-Key"),
) -> DetectionResponse:
    # Allow either user token or service API key with scope
    if x_api_key:
        scopes = await get_service_scopes(x_api_key, session=session)
        if "detections:create" not in scopes:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Scope detections:create required")
        actor_user_id = None
    else:
        if current_user is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
        # Require at least control permission on camera
        perm = user_camera_permission_sync(current_user)
        if not check_permission(perm, "control") and not is_admin(current_user):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permission on camera")
        actor_user_id = current_user.user_id

    if payload.person_id is not None:
        person = await session.get(models.Person, payload.person_id)
        if person is None or person.deleted_at is not None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Person not found")
    camera = await session.get(models.Camera, payload.camera_id)
    if camera is None or camera.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Camera not found")
    if payload.recording_file_id is not None:
        recording_result = await session.execute(
            select(models.RecordingFile)
            .join(models.VideoStream, models.VideoStream.video_stream_id == models.RecordingFile.video_stream_id)
            .where(
                models.RecordingFile.recording_file_id == payload.recording_file_id,
                models.VideoStream.camera_id == payload.camera_id,
            )
        )
        if recording_result.scalar_one_or_none() is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Recording does not belong to this camera",
            )

    if payload.person_id:
        et_id = await _find_event_type_id(session, payload.event_type or "face_recognized")
        review_required = False
    elif payload.event_type == "motion_detected":
        et_id = await _find_event_type_id(session, "motion_detected")
        review_required = False
    else:
        et_id = await _find_event_type_id(session, payload.event_type or "face_unknown")
        review_required = True

    evt = models.Event(
        camera_id=payload.camera_id,
        event_type_id=et_id,
        person_id=payload.person_id,
        recording_file_id=payload.recording_file_id,
        confidence=payload.confidence,
        created_by_user_id=actor_user_id,
    )
    session.add(evt)
    await session.flush()

    if review_required:
        review = models.EventReview(event_id=evt.event_id, status="pending")
        session.add(review)
        await _notify_admins_for_camera(session, payload.camera_id, evt.event_id)

    await session.commit()
    return DetectionResponse(event_id=evt.event_id, review_required=review_required)


@router.get("/pending", response_model=List[PendingEvent])
async def list_pending(
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user),
) -> List[PendingEvent]:
    perm = user_camera_permission_sync(current_user)
    if not check_permission(perm, "control"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not allowed to review events")

    res = await session.execute(
        select(models.Event, models.EventReview, models.EventType, models.Camera)
        .join(models.EventReview, models.Event.event_id == models.EventReview.event_id)
        .join(models.EventType, models.Event.event_type_id == models.EventType.event_type_id)
        .join(models.Camera, models.Event.camera_id == models.Camera.camera_id)
        .where(models.EventReview.status == "pending")
        .where(models.EventType.name != "face_recognized")
        .order_by(models.Event.event_ts.desc())
    )
    items: List[PendingEvent] = []
    rows = res.all()
    for event, review, event_type, camera in rows:
        snapshot_path = Path("snapshots").resolve() / f"event_{event.event_id}.jpg"
        items.append(
            PendingEvent(
                event_id=event.event_id,
                camera_id=event.camera_id,
                camera_name=camera.name,
                camera_location=camera.location,
                event_type_id=event.event_type_id,
                event_ts=event.event_ts.isoformat(),
                person_id=event.person_id,
                person_label=None,
                recording_file_id=event.recording_file_id,
                confidence=float(event.confidence) if event.confidence is not None else None,
                snapshot_url=f"/detections/events/{event.event_id}/snapshot" if event.processor_id or snapshot_path.exists() else None,
            )
        )
    return items


@router.get("/events/{event_id}/snapshot")
async def event_snapshot(
    event_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user_allow_query),
):
    event = await session.get(models.Event, event_id)
    if event is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found")
    perm = user_camera_permission_sync(current_user)
    if not check_permission(perm, "view"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    if event.processor_id is not None:
        proc = await get_processor_by_id(session, event.processor_id)
        if proc is not None:
            url = f"{get_processor_media_base_url(proc)}/media/snapshots/event_{event_id}.jpg"
            headers = get_processor_media_headers(proc)
            try:
                fetched = await _fetch_processor_snapshot_bytes(url, headers, timeout=20.0)
                if fetched is not None:
                    payload, media_type = fetched
                    return Response(
                        content=payload,
                        media_type=media_type,
                    )
            except Exception:
                pass

    local_snapshot = Path("snapshots").resolve() / f"event_{event_id}.jpg"
    if local_snapshot.exists():
        return FileResponse(local_snapshot, media_type="image/jpeg")

    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Snapshot not found")


@router.get("/events/{event_id}/candidates", response_model=list[ReviewCandidate])
async def event_candidates(
    event_id: int,
    limit: int = Query(default=3, ge=1, le=5),
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user),
) -> list[ReviewCandidate]:
    event = await session.get(models.Event, event_id)
    if event is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found")
    perm = user_camera_permission_sync(current_user)
    if not check_permission(perm, "control"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not allowed to review this event")
    return await _event_candidate_persons(session, event, limit=limit)


@router.post("/events/{event_id}/review", response_model=dict)
async def review_event(
    event_id: int,
    payload: EventReviewUpdate,
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user),
) -> dict:
    evt = await session.get(models.Event, event_id)
    if evt is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found")
    # Require at least control permission (admin or user role)
    perm = user_camera_permission_sync(current_user)
    if not check_permission(perm, "control"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not allowed to review this event")

    review = await session.execute(
        select(models.EventReview).where(models.EventReview.event_id == event_id)
    )
    review_obj = review.scalar_one_or_none()
    if review_obj is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No review pending for this event")
    if payload.person_id is not None:
        person = await session.get(models.Person, payload.person_id)
        if person is None or person.deleted_at is not None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Person not found")
    review_obj.status = payload.status
    review_obj.reviewer_user_id = current_user.user_id
    review_obj.person_id = payload.person_id
    review_obj.note = payload.note
    review_obj.updated_at = datetime.now()

    if payload.person_id and evt.person_id is None:
        evt.person_id = payload.person_id
    if payload.status == "approved" and payload.person_id:
        face_recognized_type_id = await _find_event_type_id(session, "face_recognized")
        evt.event_type_id = face_recognized_type_id

    await session.commit()
    return {"event_id": event_id, "status": review_obj.status, "person_id": review_obj.person_id}


@router.post("/review/reject-all", response_model=dict)
async def reject_all_pending(
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user),
) -> dict:
    perm = user_camera_permission_sync(current_user)
    if not check_permission(perm, "control"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not allowed to review events")

    result = await session.execute(
        select(models.EventReview).where(models.EventReview.status == "pending")
    )
    reviews = result.scalars().all()
    updated = 0
    for review_obj in reviews:
        review_obj.status = "rejected"
        review_obj.reviewer_user_id = current_user.user_id
        review_obj.updated_at = datetime.now()
        updated += 1

    await session.commit()
    return {"updated": updated}


@router.get("/stats/presence")
async def stats_presence(
    camera_id: int | None = Query(default=None),
    person_id: int | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user),
):
    """Простая статистика: сколько раз и когда видели людей (face_recognized события)."""
    perm = user_camera_permission_sync(current_user)
    if perm is None:
        return []

    stmt = select(models.Event).join(models.EventType).where(models.EventType.name == "face_recognized")
    if camera_id:
        stmt = stmt.where(models.Event.camera_id == camera_id)
    if person_id:
        stmt = stmt.where(models.Event.person_id == person_id)
    res = await session.execute(stmt)
    rows = res.scalars().all()
    summary = {}
    for ev in rows:
        key = (ev.person_id, ev.camera_id)
        rec = summary.setdefault(key, {"count": 0, "first_ts": ev.event_ts, "last_ts": ev.event_ts})
        rec["count"] += 1
        if ev.event_ts < rec["first_ts"]:
            rec["first_ts"] = ev.event_ts
        if ev.event_ts > rec["last_ts"]:
            rec["last_ts"] = ev.event_ts
    output = []
    for (pid, cid), rec in summary.items():
        label = None
        if pid:
            person = await session.get(models.Person, pid)
            if person:
                parts = [person.last_name, person.first_name, person.middle_name]
                label = " ".join([p for p in parts if p]) or f"ID {pid}"
        output.append(
            {
                "person_id": pid,
                "person_label": label,
                "camera_id": cid,
                "count": rec["count"],
                "first_ts": rec["first_ts"].isoformat(),
                "last_ts": rec["last_ts"].isoformat(),
            }
        )
    return output


@router.get("/timeline")
async def timeline(
    camera_id: int | None = Query(default=None),
    date_from: str | None = Query(default=None, description="ISO datetime start"),
    date_to: str | None = Query(default=None, description="ISO datetime end"),
    limit: int = Query(default=3000, ge=1, le=10000),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user),
):
    perm = user_camera_permission_sync(current_user)
    if perm is None:
        return []

    stmt = select(models.Event, models.EventType).join(models.EventType)
    if camera_id:
        stmt = stmt.where(models.Event.camera_id == camera_id)
    if date_from:
        try:
            df = datetime.fromisoformat(date_from)
            stmt = stmt.where(models.Event.event_ts >= df)
        except ValueError:
            pass
    if date_to:
        try:
            dt = datetime.fromisoformat(date_to)
            stmt = stmt.where(models.Event.event_ts <= dt)
        except ValueError:
            pass
    stmt = stmt.order_by(models.Event.event_ts.desc()).offset(offset).limit(limit)
    res = await session.execute(stmt)
    rows = res.all()
    out = []
    for ev, et in rows:
        out.append(
            {
                "event_id": ev.event_id,
                "camera_id": ev.camera_id,
                "event_ts": ev.event_ts.isoformat(),
                "person_id": ev.person_id,
                "event_type": et.name,
            }
        )
    return out
