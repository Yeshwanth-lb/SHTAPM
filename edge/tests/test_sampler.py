"""C2 tests — edge sampler (fake C1 drivers, injected clock, no sleeping)."""

import pytest
from app.schemas.contracts import CHANNELS, TelemetryMessage

from edge.acquisition.sampler import Sampler
from edge.drivers.base import Sensor
from edge.drivers.fake import constant_raw, scripted_raw

# Plausible per-channel constant values for healthy fakes.
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


def _healthy_drivers():
    return {
        ch: Sensor(unit="x", raw_read=constant_raw(VALUES[ch]), clock=_clock) for ch in CHANNELS
    }


def _sampler(drivers=None, **kw):
    return Sampler(device_id="pump-01", drivers=drivers or _healthy_drivers(), clock=_clock, **kw)


def test_all_healthy_builds_frozen_frame():
    s = _sampler()
    r = s.sample_once()
    assert r.healthy is True and isinstance(r.frame, TelemetryMessage)
    assert r.frame.device_id == "pump-01" and r.frame.ts == FIXED_TS
    dumped = r.frame.sensors.model_dump()
    assert set(dumped.keys()) == set(CHANNELS)
    assert dumped["temperature"] == 26.0 and dumped["current"] == 0.42
    # contract round-trip (serialized telemetry stays contract-compatible)
    TelemetryMessage.model_validate(r.frame.model_dump())


def test_sample_seq_monotonic_and_buffered():
    s = _sampler()
    seqs = [s.sample_once().frame.sample_seq for _ in range(3)]
    assert seqs == [0, 1, 2]
    assert [m.sample_seq for m in s.buffer.snapshot()] == [0, 1, 2]


def test_unhealthy_channel_no_frame_but_readings_preserved():
    drivers = _healthy_drivers()
    drivers["pressure"] = Sensor(unit="hPa", raw_read=scripted_raw([OSError("i2c")]), clock=_clock)
    s = _sampler(drivers=drivers)
    r = s.sample_once()
    assert r.healthy is False and r.frame is None
    # C1 health/values preserved; NOT imputed
    assert r.readings["pressure"].healthy is False and r.readings["pressure"].value is None
    assert r.readings["temperature"].healthy is True and r.readings["temperature"].value == 26.0
    assert len(s.buffer) == 0  # nothing buffered on an unhealthy tick


def test_unhealthy_does_not_consume_seq():
    drivers = _healthy_drivers()
    bad = Sensor(unit="hPa", raw_read=scripted_raw([OSError("blip"), 1013.0]), clock=_clock)
    drivers["pressure"] = bad
    s = _sampler(drivers=drivers)
    r1 = s.sample_once()  # unhealthy (first read raises)
    r2 = s.sample_once()  # healthy (second read ok)
    assert r1.healthy is False and r1.frame is None
    assert r2.healthy is True and r2.frame.sample_seq == 0  # seq not burned by the bad tick


def test_no_exception_on_ordinary_bad_read():
    drivers = _healthy_drivers()
    drivers["gas"] = Sensor(unit="ppm", raw_read=scripted_raw([None]), clock=_clock)
    s = _sampler(drivers=drivers)
    r = s.sample_once()  # must NOT raise
    assert r.healthy is False and r.frame is None


def test_ctor_rejects_wrong_channel_set():
    drivers = _healthy_drivers()
    del drivers["gas"]
    with pytest.raises(ValueError):
        Sampler(device_id="pump-01", drivers=drivers, clock=_clock)


def test_run_rejects_out_of_range_rate():
    s = _sampler()
    for bad in (0.5, 0.0, 10.5, 20):
        with pytest.raises(ValueError):
            s.run(bad, should_continue=lambda: False)


def test_run_uses_injected_sleep_no_real_wait():
    s = _sampler()
    ticks = {"n": 0}
    slept = []

    def cont():
        ticks["n"] += 1
        return ticks["n"] <= 3  # 3 iterations then stop

    s.run(5.0, should_continue=cont, sleep=lambda p: slept.append(p))
    assert len(s.buffer) == 3  # 3 healthy frames buffered
    assert slept == [0.2, 0.2, 0.2]  # period 1/5, injected sleep (no real wait)


def test_buffer_overwrites_oldest_when_full():
    s = _sampler(buffer_capacity=2)
    for _ in range(5):
        s.sample_once()
    assert [m.sample_seq for m in s.buffer.snapshot()] == [3, 4]  # oldest overwritten
