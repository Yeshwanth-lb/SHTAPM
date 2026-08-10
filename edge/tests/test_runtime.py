"""C2→C3 runtime unit tests — fake drivers + fake MQTT client, no broker, no sleeping."""

import json

import pytest

from edge.acquisition.mqtt_publisher import ResilientTelemetryPublisher
from edge.acquisition.runtime import AcquisitionRuntime
from edge.acquisition.sampler import Sampler
from edge.drivers.base import Sensor
from edge.drivers.fake import constant_raw, fake_drivers, scripted_raw

VALUES = {
    "temperature": 26.0,
    "vibration": 0.03,
    "pressure": 1013.0,
    "humidity": 45.0,
    "gas": 150.0,
    "current": 0.42,
}
FIXED_TS = "2026-08-10T12:00:00.000Z"


def _clock():
    return FIXED_TS


class FakeClient:
    def __init__(self, fail_on_telemetry=False):
        self.on_connect = None
        self.on_disconnect = None
        self.will = None
        self.published = []
        self.disconnected = False
        self._fail = fail_on_telemetry

    def will_set(self, topic, payload, qos=0, retain=False):
        self.will = (topic, payload, qos, retain)

    def publish(self, topic, payload, qos=0, retain=False):
        if self._fail and topic.endswith("/telemetry"):
            raise RuntimeError("broker publish failed")
        self.published.append((topic, payload, qos, retain))

    def disconnect(self):
        self.disconnected = True

    def fire_connect(self):
        self.on_connect(self, None, None, 0)


def _wire(drivers, *, fail=False, rate_hz=5.0):
    client = FakeClient(fail_on_telemetry=fail)
    publisher = ResilientTelemetryPublisher(device_id="pump-01", rate_hz=rate_hz, client=client)
    sampler = Sampler(device_id="pump-01", drivers=drivers, clock=_clock)
    runtime = AcquisitionRuntime(sampler=sampler, publisher=publisher, rate_hz=rate_hz)
    return runtime, publisher, client


def _telemetry(client):
    return [json.loads(pl) for (t, pl, *_) in client.published if t.endswith("/telemetry")]


def _run_n(runtime, n, sleeps):
    calls = {"i": 0}

    def cont():
        calls["i"] += 1
        return calls["i"] <= n

    runtime.run(should_continue=cont, sleep=lambda p: sleeps.append(p))


def test_n_frames_published_in_order():
    runtime, _pub, client = _wire(fake_drivers(VALUES), rate_hz=5.0)
    client.fire_connect()  # publisher online → live publish
    sleeps: list[float] = []
    _run_n(runtime, 5, sleeps)
    seqs = [m["sample_seq"] for m in _telemetry(client)]
    assert seqs == [0, 1, 2, 3, 4]
    assert sleeps == [0.2, 0.2, 0.2, 0.2, 0.2]  # injected sleep at 1/5 Hz, no real wait


def test_unhealthy_tick_publishes_nothing():
    drivers = fake_drivers(VALUES)
    drivers["pressure"] = Sensor(unit="hPa", raw_read=scripted_raw([OSError("i2c")]), clock=_clock)
    runtime, _pub, client = _wire(drivers)
    client.fire_connect()
    res = runtime.tick()
    assert res.healthy is False and res.frame is None
    assert _telemetry(client) == []  # nothing published on the unhealthy tick


def test_unhealthy_then_healthy_only_publishes_healthy():
    drivers = fake_drivers(VALUES)
    drivers["gas"] = Sensor(
        unit="ppm", raw_read=scripted_raw([OSError("blip"), 150.0]), clock=_clock
    )
    runtime, _pub, client = _wire(drivers)
    client.fire_connect()
    runtime.tick()  # unhealthy → no publish
    runtime.tick()  # healthy → publish seq 0
    seqs = [m["sample_seq"] for m in _telemetry(client)]
    assert seqs == [0]  # only the healthy frame, seq not burned by the bad tick


def test_clean_shutdown_publishes_offline_and_disconnects():
    runtime, _pub, client = _wire(fake_drivers(VALUES))
    client.fire_connect()
    runtime.stop()
    assert ("shtapm/pump-01/status", "offline", 1, True) in client.published
    assert client.disconnected is True


def test_publish_exception_propagates_not_swallowed():
    runtime, _pub, client = _wire(fake_drivers(VALUES), fail=True)
    client.fire_connect()
    with pytest.raises(RuntimeError, match="broker publish failed"):
        runtime.tick()


def test_rate_out_of_range_rejected():
    _rt, publisher, _c = _wire(fake_drivers(VALUES))
    sampler = Sampler(device_id="pump-01", drivers=fake_drivers(VALUES), clock=_clock)
    for bad in (0.0, 0.5, 10.5):
        with pytest.raises(ValueError):
            AcquisitionRuntime(sampler=sampler, publisher=publisher, rate_hz=bad)


def test_fake_drivers_requires_all_channels():
    bad = {k: v for k, v in VALUES.items() if k != "current"}
    with pytest.raises(ValueError):
        fake_drivers(bad)


def test_frame_is_frozen_contract():
    runtime, _pub, client = _wire(fake_drivers(VALUES))
    client.fire_connect()
    runtime.tick()
    payload = _telemetry(client)[0]
    assert "type" not in payload
    assert set(payload.keys()) == {"device_id", "ts", "sensors", "sample_seq"}
    assert payload["ts"] == FIXED_TS

    # constant_raw is exercised through fake_drivers; keep a direct smoke check
    assert constant_raw(1.5)() == 1.5
