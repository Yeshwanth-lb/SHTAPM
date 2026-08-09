"""P1 · C1 tests — edge sensor-driver interface + calibration/clamp/health.

Hardware-free: fakes feed the real Sensor. No GPIO/I2C/broker/hardware.
"""

import re

from edge.drivers import Reading, Sensor, now_iso_ms
from edge.drivers.fake import constant_raw, scripted_raw

FIXED_TS = "2026-08-10T12:00:00.123Z"


def _clock():
    return FIXED_TS


def test_valid_reading_shape_and_values():
    s = Sensor(unit="°C", raw_read=constant_raw(24.5), clock=_clock)
    r = s.read()
    assert isinstance(r, Reading)
    assert r.value == 24.5 and r.unit == "°C" and r.ts == FIXED_TS and r.healthy is True
    assert set(r.as_dict().keys()) == {"value", "unit", "ts", "healthy"}


def test_calibration_applied():
    # raw ADC counts → engineering units
    s = Sensor(
        unit="A", raw_read=constant_raw(100.0), calibrate=lambda raw: raw / 10.0, clock=_clock
    )
    assert s.read().value == 10.0


def test_below_range_clamped_healthy():
    s = Sensor(unit="%", raw_read=constant_raw(-5.0), value_range=(0.0, 100.0), clock=_clock)
    r = s.read()
    assert r.value == 0.0 and r.healthy is True  # clamped, not garbage (P1-ACQ-E2)


def test_above_range_clamped_healthy():
    s = Sensor(unit="%", raw_read=constant_raw(150.0), value_range=(0.0, 100.0), clock=_clock)
    r = s.read()
    assert r.value == 100.0 and r.healthy is True


def test_in_range_not_clamped():
    s = Sensor(unit="hPa", raw_read=constant_raw(1013.2), value_range=(300.0, 1100.0), clock=_clock)
    assert s.read().value == 1013.2


def test_bad_read_raises_is_unhealthy():
    s = Sensor(unit="°C", raw_read=scripted_raw([OSError("i2c fault")]), clock=_clock)
    r = s.read()
    assert r.healthy is False and r.value is None and r.unit == "°C" and r.ts == FIXED_TS


def test_none_read_is_unhealthy():
    s = Sensor(unit="g", raw_read=scripted_raw([None]), clock=_clock)
    r = s.read()
    assert r.healthy is False and r.value is None


def test_nan_read_is_unhealthy():
    s = Sensor(unit="g", raw_read=constant_raw(float("nan")), clock=_clock)
    r = s.read()
    assert r.healthy is False and r.value is None


def test_calibration_raising_is_unhealthy():
    def bad_cal(_raw):
        raise ValueError("cal table missing")

    s = Sensor(unit="ppm", raw_read=constant_raw(50.0), calibrate=bad_cal, clock=_clock)
    assert s.read().healthy is False


def test_read_never_raises_and_recovers():
    # first read fails, second succeeds — driver keeps working (never throws)
    s = Sensor(unit="°C", raw_read=scripted_raw([RuntimeError("blip"), 26.0]), clock=_clock)
    r1 = s.read()
    r2 = s.read()
    assert r1.healthy is False and r1.value is None
    assert r2.healthy is True and r2.value == 26.0


def test_default_timestamp_is_valid_iso_ms():
    ts = now_iso_ms()
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z", ts)
    # parseable as a real UTC instant
    from datetime import datetime

    datetime.fromisoformat(ts.replace("Z", "+00:00"))


def test_real_sensor_read_uses_default_clock():
    s = Sensor(unit="°C", raw_read=constant_raw(20.0))  # default now_iso_ms
    r = s.read()
    assert r.healthy is True and r.value == 20.0
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z", r.ts)
