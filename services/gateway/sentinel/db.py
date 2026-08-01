"""Async SQLAlchemy engine and session plumbing."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from .settings import settings

log = logging.getLogger("sentinel.db")


class Base(DeclarativeBase):
    pass


def _engine_kwargs() -> dict[str, Any]:
    kwargs: dict[str, Any] = {"echo": False, "future": True, "pool_pre_ping": True}
    if settings.is_postgres:
        kwargs["pool_size"] = settings.db_pool_size
        kwargs["max_overflow"] = settings.db_max_overflow
        kwargs["pool_recycle"] = 300
    return kwargs


engine = create_async_engine(settings.sqlalchemy_url, **_engine_kwargs())
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    session = SessionLocal()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session


async def init_db() -> None:
    from . import models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    log.info("schema ready (%s)", "postgres" if settings.is_postgres else "sqlite")


async def dispose_db() -> None:
    await engine.dispose()
