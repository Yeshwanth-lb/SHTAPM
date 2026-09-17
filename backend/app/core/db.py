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


def _is_memory_sqlite(url: str) -> bool:
    """True for in-memory SQLite URLs, which behave fundamentally differently
    from file-backed ones: every new connection gets its OWN empty database.

    Covers all three spellings, including the bare ``sqlite://`` that
    SQLAlchemy treats as ``:memory:`` — missing that one silently hands each
    thread its own empty database instead of the shared test fixture.
    """
    if ":memory:" in url or "mode=memory" in url:
        return True
    # No database path after the scheme (e.g. "sqlite://") == in-memory.
    database_path = url.partition("://")[2].partition("?")[0]
    return database_path.strip("/") == ""


def make_engine(url: str) -> Engine:
    """SQLite gets ``check_same_thread=False`` either way — this app touches
    the DB from more than one thread (the MQTT consumer's persistence sink
    runs on paho's network thread, FastAPI request handlers run on another).

    Pooling then differs by SQLite flavour, because the two have opposite
    requirements:

    * **in-memory** (tests): ``StaticPool``, so all threads share the ONE
      connection that holds the database. A per-thread connection would hand
      each thread its own independently-empty in-memory DB.
    * **file-backed** (local dev/demo): the default pool, so each thread gets
      its OWN connection to the shared file. ``StaticPool`` here would force
      concurrent threads through a single ``sqlite3`` connection, which is not
      safe for simultaneous use even with ``check_same_thread=False`` — it
      raises ``sqlite3.InterfaceError: bad parameter or other API misuse``
      when the MQTT writer and an API reader overlap. Observed live against a
      real Pi stream: ``GET /readings`` returned 200 or 500 depending purely
      on whether a telemetry write happened to be in flight.

    Postgres (production) is unaffected and uses SQLAlchemy's defaults."""
    if url.startswith("sqlite"):
        if _is_memory_sqlite(url):
            return create_engine(
                url, connect_args={"check_same_thread": False}, poolclass=StaticPool
            )
        return create_engine(url, connect_args={"check_same_thread": False})
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
