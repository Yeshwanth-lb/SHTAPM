"""P1 · C1 tests — edge sensor-driver interface + calibration/clamp/health.

Hardware-free: fakes feed the real Sensor. No GPIO/I2C/broker/hardware.
"""

import inspect
import re
from datetime import datetime, timedelta

from edge.drivers import Reading, Sensor, now_iso_ms
from edge.drivers.fake import constant_raw, scripted_raw

FIXED_TS = "2026-08-10T12:00:00.123Z"


def _clock():
    return FIXED_TS


def _advancing_clock(start_iso: str, step_seconds: list[float]):
    """Deterministic injected clock (no wall-clock dependency): returns
    ``start_iso`` on the first call, then advances by ``step_seconds[i]``
    (cumulatively, relative to the previous call) on each subsequent call.
    Lets staleness tests control elapsed time between reads exactly."""
    start = datetime.fromisoformat(start_iso.replace("Z", "+00:00"))
    cumulative = [0.0]
    for step in step_seconds:
        cumulative.append(cumulative[-1] + step)
    offsets = iter(cumulative)

    def _tick() -> str:
        ts = start + timedelta(seconds=next(offsets))
        return ts.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ts.microsecond // 1000:03d}Z"

    return _tick


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


# ---------------------------------------------------------------------------
# Staleness (opt-in, max_age_seconds) — a driver stuck returning its last
# cached value is not caught by the raise/None/NaN checks above, since it
# "succeeds" every time; these tests cover that separate failure mode.
# ---------------------------------------------------------------------------


def test_max_age_seconds_has_no_invented_default():
    """No numeric age is guessed on the caller's behalf — the only default
    is 'staleness checking disabled' (None), matching value_range's own
    'intentionally NOT invented here' convention in this same class."""
    sig = inspect.signature(Sensor.__init__)
    assert sig.parameters["max_age_seconds"].default is None


def test_staleness_checking_is_opt_in_and_off_by_default():
    """Existing behavior is fully preserved when max_age_seconds is not
    passed: a value frozen far longer than any plausible bound still reads
    healthy, exactly like every Sensor construction elsewhere in the repo
    (fake_drivers(), the real drivers) that never passes this parameter."""
    clock = _advancing_clock(FIXED_TS, [10_000.0])
    s = Sensor(unit="°C", raw_read=constant_raw(24.5), clock=clock)
    s.read()
    r2 = s.read()
    assert r2.healthy is True and r2.value == 24.5


def test_reading_within_max_age_remains_healthy():
    clock = _advancing_clock(FIXED_TS, [5.0])
    s = Sensor(unit="°C", raw_read=constant_raw(24.5), clock=clock, max_age_seconds=10.0)
    r1 = s.read()
    r2 = s.read()
    assert r1.healthy is True
    assert r2.healthy is True and r2.value == 24.5


def test_reading_older_than_max_age_becomes_unhealthy():
    clock = _advancing_clock(FIXED_TS, [11.0])
    s = Sensor(unit="°C", raw_read=constant_raw(24.5), clock=clock, max_age_seconds=10.0)
    r1 = s.read()
    r2 = s.read()
    assert r1.healthy is True
    assert r2.healthy is False and r2.value is None  # None ⟺ unhealthy, same as every other case


def test_reading_exactly_at_max_age_boundary_remains_healthy():
    clock = _advancing_clock(FIXED_TS, [10.0])
    s = Sensor(unit="°C", raw_read=constant_raw(24.5), clock=clock, max_age_seconds=10.0)
    s.read()
    r2 = s.read()
    assert r2.healthy is True  # exactly at the bound is still "within" it


def test_reading_just_past_max_age_boundary_becomes_unhealthy():
    clock = _advancing_clock(FIXED_TS, [10.001])
    s = Sensor(unit="°C", raw_read=constant_raw(24.5), clock=clock, max_age_seconds=10.0)
    s.read()
    r2 = s.read()
    assert r2.healthy is False


def test_a_frozen_value_does_not_remain_healthy_indefinitely():
    """The scenario this increment closes: a driver whose raw_read keeps
    'succeeding' with the exact same cached value forever must eventually
    stop reading as healthy, once max_age_seconds is opted into."""
    clock = _advancing_clock(FIXED_TS, [1.0, 1.0, 1.0, 1.0, 100.0])
    s = Sensor(unit="g", raw_read=constant_raw(0.03), clock=clock, max_age_seconds=3.0)
    results = [s.read() for _ in range(6)]
    assert [r.healthy for r in results] == [True, True, True, True, False, False]


def test_value_change_resets_the_staleness_clock():
    """A genuinely new value restarts the age counter from zero — a sensor
    that changes reading is not penalized by how long its *previous* value
    had been current."""
    raw = scripted_raw([24.5, 25.0, 25.0])
    clock = _advancing_clock(FIXED_TS, [6.0, 9.0])  # 6s to the changed value, then +9s unchanged
    s = Sensor(unit="°C", raw_read=raw, clock=clock, max_age_seconds=10.0)
    r1 = s.read()
    r2 = s.read()
    r3 = s.read()
    assert r1.healthy is True and r1.value == 24.5
    assert r2.healthy is True and r2.value == 25.0  # changed value — clock resets, not stale
    assert r3.healthy is True and r3.value == 25.0  # only 9s since the change — still within 10s


def test_staleness_checked_after_calibration_and_clamp():
    """Staleness compares the final reported value (post-calibration,
    post-clamp), not the raw input — consistent with what a consumer
    actually observes as 'unchanged'."""
    clock = _advancing_clock(FIXED_TS, [11.0])
    s = Sensor(
        unit="A",
        raw_read=constant_raw(100.0),
        calibrate=lambda raw: raw / 10.0,
        clock=clock,
        max_age_seconds=10.0,
    )
    s.read()
    r2 = s.read()
    assert r2.healthy is False and r2.value is None


def test_transient_failure_does_not_bypass_staleness_tracking():
    """An exception/None/NaN read reports unhealthy for its own reason and
    does not reset the staleness clock — a driver that fails once and then
    resumes returning the same pre-failure value is still tracked from when
    that value first appeared, not from the moment it recovered."""
    raw = scripted_raw([24.5, OSError("blip"), 24.5])
    clock = _advancing_clock(FIXED_TS, [1.0, 10.0])
    s = Sensor(unit="°C", raw_read=raw, clock=clock, max_age_seconds=10.0)
    r1 = s.read()
    r2 = s.read()
    r3 = s.read()
    assert r1.healthy is True and r1.value == 24.5
    assert r2.healthy is False and r2.value is None  # the transient failure itself
    assert r3.healthy is False and r3.value is None  # 11s since 24.5 first appeared -> stale
