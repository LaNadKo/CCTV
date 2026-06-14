from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import settings


class Base(DeclarativeBase):
    pass


def _require_database_url() -> str:
    value = settings.db_url.strip()
    if not value:
        raise RuntimeError("DATABASE_URL is required. Configure .env or start through scripts/cctv-up.ps1.")
    return value


engine: AsyncEngine = create_async_engine(_require_database_url(), echo=settings.debug)
SessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(
    engine,
    expire_on_commit=False,
)


async def get_session() -> AsyncSession:
    async with SessionLocal() as session:
        yield session
