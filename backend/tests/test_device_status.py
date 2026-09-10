"""Device online/offline status from the MQTT LWT topic.

THE BUG THIS CLOSES: the edge has always published a retained
``shtapm/<device>/status`` (online on connect, offline via Last Will), but
nothing subscribed. ``devices.status`` therefore sat at its schema default
``offline`` forever — so the fleet view reported a running pump as offline
while its telemetry was visibly arriving, and `last_seen_at` was one second
old on the same row.
"""

from __future__ import annotations

import pytest

sa = pytest.importorskip("sqlalchemy")

from app.models import Base, Device  # noqa: E402
from app.models.enums import DeviceStatus  # noqa: E402
from app.mqtt.status_consumer import StatusConsumer, device_from_topic  # noqa: E402
from app.services.status_persistence import StatusPersistence  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402


class FakeMsg:
    def __init__(self, topic: str, payload: bytes | str) -> None:
        self.topic = topic
        self.payload = payload


@pytest.fixture()
def session_factory():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@pytest.fixture()
def persistence(session_factory):
    return StatusPersistence(session_factory)


def _device(session_factory, device_id="pump-01") -> Device | None:
    with session_factory() as db:
        return db.query(Device).filter(Device.device_id == device_id).one_or_none()


# ---------------------------------------------------------------------------
# Topic parsing
# ---------------------------------------------------------------------------


def test_parses_the_device_from_a_status_topic():
    assert device_from_topic("shtapm/pump-01/status") == "pump-01"


@pytest.mark.parametrize(
    "topic",
    [
        "shtapm/pump-01/telemetry",  # must not hijack telemetry
        "shtapm/pump-01/decision_diagnostic",
        "shtapm/pump-01",
        "shtapm/pump-01/status/extra",
        "other/pump-01/status",
        "",
    ],
)
def test_rejects_topics_that_are_not_status(topic):
    assert device_from_topic(topic) is None


# ---------------------------------------------------------------------------
# Consumer payload handling
# ---------------------------------------------------------------------------


def test_online_and_offline_reach_the_sink():
    seen: list[tuple[str, str]] = []
    consumer = StatusConsumer()
    consumer.add_sink(lambda d, s: seen.append((d, s)))

    consumer.handle(FakeMsg("shtapm/pump-01/status", b"online"))
    consumer.handle(FakeMsg("shtapm/pump-01/status", b"offline"))

    assert seen == [("pump-01", "online"), ("pump-01", "offline")]
    assert consumer.error_count == 0


def test_payload_is_tolerated_as_str_or_bytes_and_normalised():
    seen: list[tuple[str, str]] = []
    consumer = StatusConsumer()
    consumer.add_sink(lambda d, s: seen.append((d, s)))

    consumer.handle(FakeMsg("shtapm/pump-01/status", "ONLINE"))
    consumer.handle(FakeMsg("shtapm/pump-01/status", b"  offline\n"))

    assert seen == [("pump-01", "online"), ("pump-01", "offline")]


def test_an_unrecognised_payload_is_rejected_not_guessed():
    """A wrong 'online' is worse than no update. Anything that is not one of
    the two published words must leave the stored status untouched."""
    seen: list[tuple[str, str]] = []
    consumer = StatusConsumer()
    consumer.add_sink(lambda d, s: seen.append((d, s)))

    for payload in (b"", b"up", b"1", b"true", b'{"status":"online"}'):
        consumer.handle(FakeMsg("shtapm/pump-01/status", payload))

    assert seen == []
    assert consumer.error_count == 5


def test_a_sink_failure_never_breaks_ingestion():
    consumer = StatusConsumer()
    consumer.add_sink(lambda d, s: (_ for _ in ()).throw(RuntimeError("boom")))
    consumer.handle(FakeMsg("shtapm/pump-01/status", b"online"))  # must not raise


def test_subscription_is_the_status_wildcard():
    assert StatusConsumer().subscription == "shtapm/+/status"


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def test_online_is_persisted_to_devices_status(persistence, session_factory):
    persistence.persist("pump-01", "online")
    assert _device(session_factory).status == DeviceStatus.online


def test_offline_is_persisted(persistence, session_factory):
    persistence.persist("pump-01", "online")
    persistence.persist("pump-01", "offline")
    assert _device(session_factory).status == DeviceStatus.offline


def test_the_device_row_is_created_when_status_arrives_first(persistence, session_factory):
    """The publisher sends retained `online` at connect, before the first 1 Hz
    telemetry tick, so status legitimately precedes any reading."""
    assert _device(session_factory) is None
    persistence.persist("pump-01", "online")
    assert _device(session_factory) is not None


def test_status_never_touches_last_seen_at(persistence, session_factory):
    """last_seen_at means "when telemetry last arrived" and is owned by
    TelemetryPersistence. A retained `offline` replayed at backend startup must
    not rewrite it with the moment the backend reconnected."""
    with session_factory() as db:
        db.add(Device(device_id="pump-01", name="pump-01"))
        db.commit()

    persistence.persist("pump-01", "online")
    assert _device(session_factory).last_seen_at is None


def test_an_unmapped_status_is_ignored_rather_than_written(persistence, session_factory):
    persistence.persist("pump-01", "degraded")  # in the enum, never published
    device = _device(session_factory)
    # The row may be created, but the status must stay at its default.
    assert device is None or device.status == DeviceStatus.offline


def test_repeated_identical_status_is_idempotent(persistence, session_factory):
    persistence.persist("pump-01", "online")
    persistence.persist("pump-01", "online")
    assert _device(session_factory).status == DeviceStatus.online


def test_consumer_and_persistence_compose_end_to_end(persistence, session_factory):
    consumer = StatusConsumer()
    consumer.add_sink(persistence.persist)

    consumer.handle(FakeMsg("shtapm/pump-01/status", b"online"))
    assert _device(session_factory).status == DeviceStatus.online

    consumer.handle(FakeMsg("shtapm/pump-01/status", b"offline"))
    assert _device(session_factory).status == DeviceStatus.offline
