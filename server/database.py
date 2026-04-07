"""Async SQLAlchemy engine: PostgreSQL on Railway (DATABASE_URL) or local SQLite."""

from __future__ import annotations

import logging
import os
import ssl
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    pass


def _database_url() -> str:
    raw = os.environ.get("DATABASE_URL", "").strip()
    if raw:
        if raw.startswith("postgres://"):
            raw = "postgresql+asyncpg://" + raw[len("postgres://") :]
        elif raw.startswith("postgresql://") and "+asyncpg" not in raw.split("://", 1)[0]:
            raw = "postgresql+asyncpg://" + raw[len("postgresql://") :]
        return raw
    data_dir = Path(__file__).resolve().parent.parent / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return f"sqlite+aiosqlite:///{data_dir / 'dms.db'}"


DATABASE_URL = _database_url()


def _engine_kwargs(url: str) -> dict:
    """Use TLS for remote PostgreSQL (e.g. Railway); skip for SQLite and local Postgres."""
    if "sqlite" in url:
        return {}
    if "asyncpg" not in url:
        return {}
    try:
        host = (urlparse(url).hostname or "").lower()
    except Exception:
        host = ""
    if host in ("localhost", "127.0.0.1", ""):
        return {}
    return {"connect_args": {"ssl": ssl.create_default_context()}}


engine = create_async_engine(
    DATABASE_URL,
    echo=os.environ.get("SQL_ECHO", "").lower() in ("1", "true"),
    pool_pre_ping=True,
    **_engine_kwargs(DATABASE_URL),
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def init_db() -> None:
    """Create tables if they do not exist (Phase 1 — add Alembic later for migrations)."""
    from server import sql_models  # noqa: F401 — register models on Base.metadata

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database ready (%s)", "postgres" if "asyncpg" in DATABASE_URL else "sqlite")


