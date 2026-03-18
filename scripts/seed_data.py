import asyncio
from datetime import datetime

from sqlalchemy.dialects.postgresql import insert

from app.db import engine
from app import models


SEED_ROLES = [
    {"role_id": 1, "name": "admin"},
    {"role_id": 2, "name": "operator"},
    {"role_id": 3, "name": "viewer"},
]

SEED_STATUSES = [
    {"status_id": 1, "name": "active"},
    {"status_id": 2, "name": "inactive"},
]

SEED_EVENT_TYPES = [
    {"event_type_id": 1, "name": "face_recognized"},
    {"event_type_id": 2, "name": "face_unknown"},
    {"event_type_id": 3, "name": "motion_detected"},
    {"event_type_id": 4, "name": "intrusion"},
    {"event_type_id": 5, "name": "system"},
]

SEED_CAMERAS = [
    {
        "camera_id": 1,
        "name": "Laptop Cam",
        "location": "Local",
        "ip_address": None,
        "stream_url": None,
        "status_id": 1,
        "created_at": datetime.utcnow(),
    }
]


async def seed():
    async with engine.begin() as conn:
        await conn.execute(insert(models.Role).on_conflict_do_nothing(index_elements=["role_id"]), SEED_ROLES)
        await conn.execute(insert(models.Status).on_conflict_do_nothing(index_elements=["status_id"]), SEED_STATUSES)
        await conn.execute(
            insert(models.EventType).on_conflict_do_nothing(index_elements=["event_type_id"]),
            SEED_EVENT_TYPES,
        )
        await conn.execute(insert(models.Camera).on_conflict_do_nothing(index_elements=["camera_id"]), SEED_CAMERAS)
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed())
