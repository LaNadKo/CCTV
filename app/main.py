import logging
import time
from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app import db
from app.config import settings
from app.routers import auth, groups, cameras, users, admin, detections, api_keys, recordings
from app.routers import processors as processors_router
from app.routers import persons as persons_router
from app.routers import reports as reports_router

# face router requires torch/facenet — import conditionally
try:
    from app.routers import face as face_router
    _has_face = True
except ImportError:
    _has_face = False
from app.security import decode_token

app = FastAPI(
    title=settings.app_name,
    debug=settings.debug,
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

audit_logger = logging.getLogger("app.audit")
if not audit_logger.handlers:
    handler = logging.StreamHandler()
    fmt = logging.Formatter("%(asctime)s [AUDIT] %(message)s")
    handler.setFormatter(fmt)
    audit_logger.addHandler(handler)
audit_logger.setLevel(logging.INFO)


@app.middleware("http")
async def audit_log(request: Request, call_next):
    start = time.monotonic()
    user = "-"
    token = None
    auth_header = request.headers.get("authorization")
    if auth_header and auth_header.lower().startswith("bearer "):
        token = auth_header.split(" ", 1)[1]
    else:
        token = request.query_params.get("token") or request.query_params.get("access_token")
    if token:
        try:
            payload = decode_token(token)
            user = str(payload.get("sub") or "-")
        except Exception:
            user = "invalid-token"
    response = await call_next(request)
    dur_ms = (time.monotonic() - start) * 1000
    audit_logger.info(
        "%s %s status=%s dur_ms=%.1f user=%s",
        request.method,
        request.url.path,
        response.status_code,
        dur_ms,
        user,
    )
    return response


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.get("/health/db")
async def health_db(session: AsyncSession = Depends(db.get_session)) -> dict:
    await session.execute(text("SELECT 1"))
    return {"status": "ok", "db": "ok"}


app.include_router(auth.router)
app.include_router(groups.router)
app.include_router(cameras.router)
app.include_router(users.router)
if _has_face:
    app.include_router(face_router.router)
app.include_router(admin.router)
app.include_router(detections.router)
app.include_router(api_keys.router)
app.include_router(recordings.router)
app.include_router(processors_router.router)
app.include_router(persons_router.router)
app.include_router(reports_router.router)
app.mount("/recordings/static", StaticFiles(directory="recordings"), name="recordings-static")
app.mount("/snapshots", StaticFiles(directory="snapshots"), name="snapshots-static")

detector_manager = None


async def _ensure_processor_api_key():
    """Auto-create processor API key from PROCESSOR_API_KEY env if not already in DB."""
    from app.security import hash_api_key, verify_api_key
    from app import models
    from sqlalchemy import select
    async with db.SessionLocal() as session:
        result = await session.execute(select(models.ApiKey).where(models.ApiKey.is_active.is_(True)))
        for key in result.scalars().all():
            if verify_api_key(settings.processor_api_key, key.key_hash):
                return
        key_hash = hash_api_key(settings.processor_api_key)
        obj = models.ApiKey(
            key_hash=key_hash,
            description="Processor service (auto)",
            scopes="processor:register,processor:heartbeat,processor:read,processor:write",
        )
        session.add(obj)
        await session.commit()
        logging.getLogger(__name__).info("Auto-created processor API key")


async def _seed_default_admin():
    """Create default admin/admin user if no users exist."""
    from app import models
    from app.security import hash_password
    from sqlalchemy import select, func
    async with db.SessionLocal() as session:
        # Ensure roles exist
        for role_id, role_name in [(1, "admin"), (2, "user"), (3, "viewer")]:
            existing = await session.execute(select(models.Role).where(models.Role.role_id == role_id))
            if not existing.scalar_one_or_none():
                session.add(models.Role(role_id=role_id, name=role_name))
        await session.flush()
        count = (await session.execute(select(func.count()).select_from(models.User))).scalar() or 0
        if count > 0:
            await session.commit()
            return
        admin_user = models.User(
            login="admin",
            password_hash=hash_password("admin"),
            role_id=1,
            must_change_password=True,
        )
        session.add(admin_user)
        await session.commit()
        logging.getLogger(__name__).info("Created default admin user (login=admin, password=admin)")


async def _seed_event_types():
    """Ensure default event types exist by name (idempotent)."""
    from app import models
    from sqlalchemy import select, text
    required_names = ["face_recognized", "face_unknown", "motion_detected", "person_detected"]
    async with db.SessionLocal() as session:
        # Keep the serial sequence in sync with existing rows before inserts.
        await session.execute(
            text(
                """
                SELECT setval(
                    pg_get_serial_sequence('event_types', 'event_type_id'),
                    COALESCE((SELECT MAX(event_type_id) FROM event_types), 1),
                    true
                )
                """
            )
        )
        for name in required_names:
            existing = await session.execute(
                select(models.EventType).where(models.EventType.name == name)
            )
            if existing.scalar_one_or_none() is None:
                session.add(models.EventType(name=name))
        await session.commit()


@app.on_event("startup")
async def startup_tasks():
    global detector_manager
    await _seed_default_admin()
    await _seed_event_types()
    await _ensure_processor_api_key()
    if settings.enable_embedded_detector:
        from app.detector import DetectionManager
        detector_manager = DetectionManager()
        await detector_manager.start()


@app.on_event("shutdown")
async def shutdown_tasks():
    global detector_manager
    if detector_manager:
        await detector_manager.stop()
        detector_manager = None
