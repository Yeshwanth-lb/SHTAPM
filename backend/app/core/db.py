"""SQLAlchemy engine/session wiring (P4).

Deliberately takes a URL rather than reading the environment itself, so
tests can point at an isolated SQLite engine without touching
``DATABASE_URL`` (the real Postgres/TimescaleDB URL, per ``core.config
.DatabaseSettings``). The FastAPI app wires the real engine once at
startup (``app.main`` lifespan) and stores the sessionmaker on
``app.state`` — ``get_db`` reads it back per-request.
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager

from fastapi import Request
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool


def make_engine(url: str) -> Engine:
    """SQLite gets ``StaticPool`` + ``check_same_thread=False`` — the
    documented SQLAlchemy pattern for one shared in-memory/file DB visible
    across threads (needed here: the MQTT consumer's persistence sink runs
    on paho's network thread, FastAPI request handlers run on another).
    Without it, a bare ``sqlite:///:memory:`` engine can hand different
    threads different, independently-empty in-memory databases."""
    if url.startswith("sqlite"):
        return create_engine(
            url, connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
    return create_engine(url)


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db(request: Request) -> Generator[Session, None, None]:
    """FastAPI dependency: one ``Session`` per request, closed after."""
    session_factory: sessionmaker[Session] = request.app.state.db_sessionmaker
    with session_factory() as session:
        yield session


@contextmanager
def session_scope(session_factory: sessionmaker[Session]) -> Generator[Session, None, None]:
    """Non-request-scoped session (background/service code, tests)."""
    with session_factory() as session:
        yield session
