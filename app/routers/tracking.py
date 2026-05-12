"""Hybrid camera/RuView active tracking endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.dependencies import get_current_user
from app.schemas.tracking import ActiveTrackingSnapshot
from app.services.active_tracking import get_active_tracking_snapshot

router = APIRouter(prefix="/tracking", tags=["tracking"])


@router.get("/active", response_model=ActiveTrackingSnapshot)
async def active_tracks(
    limit: int = Query(200, ge=1, le=1000),
    _current_user=Depends(get_current_user),
) -> ActiveTrackingSnapshot:
    return get_active_tracking_snapshot(limit=limit)
