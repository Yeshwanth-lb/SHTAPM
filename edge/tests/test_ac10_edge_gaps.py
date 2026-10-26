"""AC10 gap-fill: Doc06 Phase 3 edge rows that had no direct test.

Each test names the Doc06 row it covers. Pure software (fake MQTT client,
fake drivers, injected sleep) — these prove the software behaviour only, not
the physical claim. See ``project-state/AC10_TEST_COVERAGE.md``.
"""

from __future__ import annotations

import json

from app.schemas.build import build_telemetry
from app.schemas.contracts import CHANNELS

from edge.acquisition.mqtt_publisher import ResilientTelemetryPublisher, buffer_capacity
from edge.acquisition.sampler import Sampler
from edge.drivers.base import Sensor
from edge.drivers.fake import constant_raw

SENSORS = {
    "temperature": 26.0,
    "vibration": 0.03,
    "pressure": 1013.0,
    "humidity": 45.0,
    "gas": 150.0,
    "current": 0.42,
}
TS = "2026-09-24T10:00:00.000Z"


class _FakeClient:
    def __init__(self):
        self.on_connect = None
        self.on_disconnect = None
        self.published = []

    def will_set(self, topic, payload, qos=0, retain=False):
        pass

    def publish(self, topic, payload, qos=0, retain=False):
        self.published.append((topic, payload))

    def disconnect(self):
        pass

    def fire_connect(self):
        self.on_connect(self, None, None, 0)

    def fire_disconnect(self):
        self.on_disconnect(self, None, 0)


def _telemetry_seqs(client) -> list[int]:
    return [
        json.loads(payload)["sample_seq"]
        for topic, payload in client.published
        if topic == "shtapm/pump-01/telemetry"
    ]


# ---- Phase 3 Edge: "Broker down 30s then up → buffered, replayed in order, no loss"


def test_30s_broker_outage_at_1hz_replays_every_frame_in_order():
    client = _FakeClient()
    publisher = ResilientTelemetryPublisher(device_id="pump-01", rate_hz=1, client=client)
    client.fire_connect()
    publisher.publish(build_telemetry("pump-01", TS, SENSORS, 0))

    client.fire_disconnect()
    for seq in range(1, 31):  # 30 s of frames at 1 Hz while the broker is down
        publisher.publish(build_telemetry("pump-01", TS, SENSORS, seq))
    assert _telemetry_seqs(client) == [0]

    client.fire_connect()
    publisher.publish(build_telemetry("pump-01", TS, SENSORS, 31))

    assert _telemetry_seqs(client) == list(range(32))


def test_default_retention_outlasts_a_30s_outage_at_every_supported_rate():
    for rate_hz in (1, 2, 5, 10):
        assert buffer_capacity(rate_hz) >= 30 * rate_hz


# ---- Phase 3 Edge: "10 Hz burst → stable, no overflow"


def test_10hz_burst_for_60s_stays_bounded_and_contiguous():
    drivers = {
        ch: Sensor(unit="x", raw_read=constant_raw(SENSORS[ch]), clock=lambda: TS)
        for ch in CHANNELS
    }
    sampler = Sampler(device_id="pump-01", drivers=drivers, clock=lambda: TS, buffer_capacity=50)
    ticks = {"n": 0}
    slept: list[float] = []

    def keep_going() -> bool:
        ticks["n"] += 1
        return ticks["n"] <= 600  # 60 s at 10 Hz

    sampler.run(10.0, should_continue=keep_going, sleep=slept.append)

    assert len(slept) == 600
    assert all(period == 0.1 for period in slept)
    buffered = [m.sample_seq for m in sampler.buffer.snapshot()]
    assert len(buffered) == 50
    assert buffered == list(range(550, 600))
