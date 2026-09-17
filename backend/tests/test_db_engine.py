"""``make_engine`` pooling contract (P4 · core/db.py).

The two SQLite flavours need OPPOSITE pooling, and getting it wrong fails in
a way unit tests never saw until the app ran against a real device stream:

* in-memory  -> StaticPool is REQUIRED (a per-thread connection would be a
  separate, empty database, breaking every test that writes then reads).
* file-backed -> StaticPool is HARMFUL (one shared ``sqlite3`` connection used
  concurrently by the MQTT persistence thread and an API request thread raises
  ``sqlite3.InterfaceError: bad parameter or other API misuse``).

The concurrency test below reproduces that second case directly.
"""

from __future__ import annotations

import threading

from app.core.db import make_engine
from sqlalchemy import text
from sqlalchemy.pool import StaticPool


def test_in_memory_sqlite_shares_one_connection():
    """StaticPool keeps the single connection that HOLDS an in-memory DB.

    All three spellings must be recognised — ``sqlite://`` is the one the
    existing WS/app-boot tests actually use, and treating it as file-backed
    gives each thread its own empty database ("no such table: users").
    """
    for url in ("sqlite:///:memory:", "sqlite://", "sqlite:///?mode=memory&cache=shared"):
        engine = make_engine(url)
        assert isinstance(engine.pool, StaticPool), url
        assert engine.dialect.name == "sqlite"


def test_file_sqlite_does_not_use_static_pool(tmp_path):
    """A file DB must hand each thread its own connection — see module docstring."""
    engine = make_engine(f"sqlite:///{tmp_path / 'dev.db'}")
    assert not isinstance(engine.pool, StaticPool)


def _select_one_from_another_thread(engine) -> list[BaseException]:
    """Run a trivial query on a thread that did not create ``engine``.

    Returns whatever it raised, so the caller can assert on it — a sqlite
    connection guarded by ``check_same_thread`` raises ProgrammingError here.
    """
    errors: list[BaseException] = []

    def _touch() -> None:
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1")).scalar_one()
        except BaseException as exc:  # noqa: BLE001 — surfaced via `errors`
            errors.append(exc)

    thread = threading.Thread(target=_touch)
    thread.start()
    thread.join(timeout=30)
    return errors


def test_sqlite_disables_same_thread_check(tmp_path):
    """Both flavours are touched from more than one thread."""
    for url in ("sqlite:///:memory:", f"sqlite:///{tmp_path / 'dev.db'}"):
        engine = make_engine(url)
        assert engine.dialect.name == "sqlite"
        assert _select_one_from_another_thread(engine) == [], url


def test_file_sqlite_survives_concurrent_writer_and_reader(tmp_path):
    """Regression: the live failure mode.

    A background writer (standing in for the MQTT persistence sink on paho's
    thread) and a reader (standing in for an API request) hit the same
    file-backed engine at once. Under StaticPool this raised
    ``sqlite3.InterfaceError`` intermittently; each thread having its own
    connection makes it safe.
    """
    engine = make_engine(f"sqlite:///{tmp_path / 'dev.db'}")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE reading (seq INTEGER PRIMARY KEY, value REAL)"))

    errors: list[BaseException] = []
    stop = threading.Event()

    def _writer() -> None:
        try:
            for seq in range(200):
                with engine.begin() as conn:
                    conn.execute(
                        text("INSERT INTO reading (seq, value) VALUES (:s, :v)"),
                        {"s": seq, "v": float(seq)},
                    )
        except BaseException as exc:  # noqa: BLE001 — surfaced via `errors`
            errors.append(exc)
        finally:
            stop.set()

    def _reader() -> None:
        try:
            while not stop.is_set():
                with engine.connect() as conn:
                    conn.execute(text("SELECT seq, value FROM reading")).fetchall()
        except BaseException as exc:  # noqa: BLE001 — surfaced via `errors`
            errors.append(exc)

    threads = [threading.Thread(target=_writer), threading.Thread(target=_reader)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert errors == [], f"concurrent access raised: {errors!r}"
    with engine.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM reading")).scalar_one() == 200
