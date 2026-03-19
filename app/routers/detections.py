from typing import List
from pathlib import Path
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Header, status, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.db import get_session
from app.dependencies import get_current_user, get_service_scopes
from app.permissions import check_permission, user_camera_permission
from app.schemas.detections import DetectionIn, DetectionResponse, EventReviewUpdate, PendingEvent
from app.camera_utils import resolve_source

router = APIRouter(prefix="/detections", tags=["detections"])


async def _find_event_type_id(session: AsyncSession, name: str) -> int:
    res = await session.execute(select(models.EventType).where(models.EventType.name == name))
    et = res.scalar_one_or_none()
    if et is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unknown event type: {name}")
    return et.event_type_id


async def _notify_admins_for_camera(session: AsyncSession, camera_id: int, event_id: int) -> None:
    # users with owner/admin role in groups that have camera permission OR global role_id=1
    # global admins
    admin_ids = set()
    res_global = await session.execute(select(models.User.user_id).where(models.User.role_id == 1))
    admin_ids.update(res_global.scalars().all())

    # group owners/admins
    sub_groups = (
        select(models.GroupCameraPermission.group_id)
        .where(models.GroupCameraPermission.camera_id == camera_id)
        .subquery()
    )
    res_members = await session.execute(
        select(models.UserGroup.user_id).where(
            models.UserGroup.group_id.in_(select(sub_groups.c.group_id)),
            models.UserGroup.membership_role.in_(["owner", "admin"]),
        )
    )
    admin_ids.update(res_members.scalars().all())

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
    current_user: models.User = Depends(get_current_user),
    x_api_key: str | None = Header(default=None, alias="X-Api-Key"),
) -> DetectionResponse:
    # Allow either user token or service API key with scope
    if x_api_key:
        scopes = await get_service_scopes(x_api_key, session=session)
        if "detections:create" not in scopes:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Scope detections:create required")
        actor_user_id = None
    else:
        # Require at least control permission on camera
        perm = await user_camera_permission(session, current_user.user_id, payload.camera_id)
        if not check_permission(perm, "control") and current_user.role_id != 1:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permission on camera")
        actor_user_id = current_user.user_id

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
    res = await session.execute(
        select(models.Event, models.EventReview)
        .join(models.EventReview, models.Event.event_id == models.EventReview.event_id)
        .where(models.EventReview.status == "pending")
    )
    items: List[PendingEvent] = []
    rows = res.all()
    for event, review in rows:
        perm = await user_camera_permission(session, current_user.user_id, event.camera_id)
        if perm:
            snapshot_path = Path("snapshots").resolve() / f"event_{event.event_id}.jpg"
            person_label = None
            if event.person_id:
                person = await session.get(models.Person, event.person_id)
                if person:
                    parts = [person.last_name, person.first_name, person.middle_name]
                    person_label = " ".join([p for p in parts if p]) or f"ID {person.person_id}"
            items.append(
                PendingEvent(
                    event_id=event.event_id,
                    camera_id=event.camera_id,
                    event_type_id=event.event_type_id,
                    event_ts=str(event.event_ts),
                    person_id=event.person_id,
                    person_label=person_label,
                    recording_file_id=event.recording_file_id,
                    confidence=float(event.confidence) if event.confidence is not None else None,
                    snapshot_url=f"/snapshots/event_{event.event_id}.jpg" if snapshot_path.exists() else None,
                )
            )
    return items


@router.post("/events/{event_id}/review", response_model=dict)
async def review_event(
    event_id: int,
    payload: EventReviewUpdate,
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user),
) -> dict:
    # must have admin/owner for camera or global admin
    evt = await session.get(models.Event, event_id)
    if evt is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found")
    if current_user.role_id != 1:
        perm = await user_camera_permission(session, current_user.user_id, evt.camera_id)
        # require at least control to review
        if not check_permission(perm, "control"):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not allowed to review this event")

    review = await session.execute(
        select(models.EventReview).where(models.EventReview.event_id == event_id)
    )
    review_obj = review.scalar_one_or_none()
    if review_obj is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No review pending for this event")
    review_obj.status = payload.status
    review_obj.reviewer_user_id = current_user.user_id
    review_obj.person_id = payload.person_id
    review_obj.note = payload.note
    review_obj.updated_at = datetime.utcnow()

    if payload.person_id and evt.person_id is None:
        evt.person_id = payload.person_id

    await session.commit()
    return {"event_id": event_id, "status": review_obj.status, "person_id": review_obj.person_id}


@router.get("/stats/presence")
async def stats_presence(
    camera_id: int | None = Query(default=None),
    person_id: int | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user),
):
    """
    Простая статистика: сколько раз и когда видели людей (face_recognized события).
    """
    stmt = select(models.Event).join(models.EventType).where(models.EventType.name == "face_recognized")
    if camera_id:
        stmt = stmt.where(models.Event.camera_id == camera_id)
    if person_id:
        stmt = stmt.where(models.Event.person_id == person_id)
    res = await session.execute(stmt)
    rows = res.scalars().all()
    summary = {}
    for ev in rows:
        # permission check per camera
        perm = await user_camera_permission(session, current_user.user_id, ev.camera_id)
        if not perm and current_user.role_id != 1:
            continue
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
                "first_ts": str(rec["first_ts"]),
                "last_ts": str(rec["last_ts"]),
            }
        )
    return output


@router.get("/timeline")
async def timeline(
    camera_id: int | None = Query(default=None),
    date_from: str | None = Query(default=None, description="ISO datetime start"),
    date_to: str | None = Query(default=None, description="ISO datetime end"),
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user),
):
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
    res = await session.execute(stmt)
    rows = res.all()
    out = []
    for ev, et in rows:
        perm = await user_camera_permission(session, current_user.user_id, ev.camera_id)
        if not perm and current_user.role_id != 1:
            continue
        out.append(
            {
                "event_id": ev.event_id,
                "camera_id": ev.camera_id,
                "event_ts": str(ev.event_ts),
                "person_id": ev.person_id,
                "event_type": et.name,
            }
        )
    return out
