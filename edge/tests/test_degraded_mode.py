"""Single-sensor loss (D045, NFR-R1): one dead sensor holds its last good value
and is reported stale instead of stopping the stream; a dead current sensor
stops a running pump."""

from __future__ import annotations

from app.schemas.contracts import CHANNELS

from edge.acquisition.health import ChannelHealthBoard
from edge.acquisition.sampler import Sampler
from edge.actuation.relay import FakeActuator, RelayController, RelayState
from edge.actuation.supervisor import SafetySupervisor
from edge.drivers.base import Sensor
from edge.drivers.fake import constant_raw, scripted_raw

VALUES = {
    "temperature": 26.0,
    "vibration": 0.5,
    "pressure": 916.0,
    "humidity": 45.0,
    "gas": 150.0,
    "current": 0.75,
}


def _clock():
    return "2026-10-27T10:00:00.000Z"


def _drivers(**scripts):
    drivers = {
        ch: Sensor(unit="x", raw_read=constant_raw(VALUES[ch]), clock=_clock) for ch in CHANNELS
    }
    for ch, script in scripts.items():
        drivers[ch] = Sensor(unit="x", raw_read=scripted_raw(script), clock=_clock)
    return drivers


def _sampler(**scripts) -> Sampler:
    return Sampler(
        device_id="pump-01", drivers=_drivers(**scripts), clock=_clock, hold_last_good=True
    )


def test_a_sensor_dying_mid_run_holds_its_last_good_value():
    s = _sampler(humidity=[45.0, 46.0, OSError("dht"), OSError("dht")])
    values = []
    for _ in range(4):
        result = s.sample_once()
        assert result.frame is not None  # the stream never stops
        values.append((result.frame.sensors.humidity, result.stale))
    assert values == [
        (45.0, frozenset()),
        (46.0, frozenset()),
        (46.0, frozenset({"humidity"})),  # last good value, flagged
        (46.0, frozenset({"humidity"})),
    ]
    assert [m.sample_seq for m in s.buffer.snapshot()] == [0, 1, 2, 3]


def test_recovery_clears_the_flag():
    s = _sampler(pressure=[916.0, OSError("i2c"), 917.0])
    stale = [s.sample_once().stale for _ in range(3)]
    assert stale == [frozenset(), frozenset({"pressure"}), frozenset()]


def test_a_sensor_dead_since_start_up_still_withholds_the_frame():
    """No good reading ever = nothing honest to hold."""
    s = _sampler(humidity=[OSError("dht"), OSError("dht")])
    result = s.sample_once()
    assert result.frame is None and result.healthy is False


def test_without_degraded_mode_the_old_behaviour_is_unchanged():
    s = Sampler(
        device_id="pump-01", drivers=_drivers(humidity=[45.0, OSError("dht")]), clock=_clock
    )
    assert s.sample_once().frame is not None
    assert s.sample_once().frame is None


def test_health_board_tracks_dead_sensors_and_since_when():
    t = {"now": 0.0}
    board = ChannelHealthBoard(clock=lambda: t["now"], dead_after_s=0.0)
    s = _sampler(current=[0.75, OSError("i2c"), OSError("i2c"), 0.76])
    board.update(s.sample_once())
    assert board.stale() == frozenset()
    board.update(s.sample_once())
    t["now"] = 4.0
    board.update(s.sample_once())
    assert board.stale() == frozenset({"current"}) and board.dead_for("current") == 4.0
    board.update(s.sample_once())
    assert board.stale() == frozenset() and board.dead_for("current") is None


def test_a_short_blip_is_not_reported_dead():
    """D047: the DHT22 misses 2-3 s of reads when the motor starts; that must
    not flash SENSOR DEAD (the value is still held)."""
    t = {"now": 0.0}
    board = ChannelHealthBoard(clock=lambda: t["now"])  # default 5 s
    s = _sampler(humidity=[50.0, OSError("dht"), OSError("dht"), OSError("dht"), 50.2])
    for second in range(5):
        t["now"] = float(second)
        board.update(s.sample_once())
        assert board.stale() == frozenset()


def test_a_sustained_failure_is_reported_after_five_seconds():
    t = {"now": 0.0}
    board = ChannelHealthBoard(clock=lambda: t["now"])
    s = _sampler(humidity=[50.0] + [OSError("dht")] * 10)
    seen = []
    for second in range(8):
        t["now"] = float(second)
        board.update(s.sample_once())
        seen.append("humidity" in board.stale())
    assert seen == [False, False, False, False, False, False, True, True]


def test_a_dead_current_sensor_stops_a_running_pump():
    """Dry-run protection is blind on a held current value, so the watchdog
    is not fed and the pump stops after the timeout."""
    t = {"now": 0.0}
    published = []
    actuator = FakeActuator()
    supervisor = SafetySupervisor(
        device_id="pump-01",
        relay=RelayController(actuator),
        hardware=False,
        publish=published.append,
        watchdog_timeout_s=10.0,
        clock=lambda: t["now"],
        now_iso=_clock,
    )
    supervisor.start(watchdog_thread=False)
    from app.schemas.actuation import RelayCommand

    supervisor.command(
        RelayCommand(
            action="relay",
            command_id="c1",
            device_id="pump-01",
            state="on",
            issued_by="admin@example.com",
            issued_at=_clock(),
        )
    )
    s = _sampler(current=[0.75] + [OSError("i2c")] * 20)
    for second in range(12):
        t["now"] = float(second)
        result = s.sample_once()
        supervisor.on_frame(result.frame, stale=result.stale)
        supervisor.check_watchdog()
    assert actuator.get_state() is RelayState.OFF
    assert published[-1].cause == "watchdog"
    assert "current sensor is dead" in published[-1].reason


def test_other_dead_sensors_do_not_stop_the_pump():
    t = {"now": 0.0}
    actuator = FakeActuator()
    supervisor = SafetySupervisor(
        device_id="pump-01",
        relay=RelayController(actuator),
        hardware=False,
        publish=lambda status: None,
        watchdog_timeout_s=10.0,
        clock=lambda: t["now"],
        now_iso=_clock,
    )
    supervisor.start(watchdog_thread=False)
    actuator.set_state(RelayState.ON)
    s = _sampler(humidity=[45.0] + [OSError("dht")] * 20)
    for second in range(15):
        t["now"] = float(second)
        result = s.sample_once()
        supervisor.on_frame(result.frame, stale=result.stale)
        supervisor.check_watchdog()
    assert actuator.get_state() is RelayState.ON


def test_decision_message_reports_stale_channels():
    from edge.pipeline.decision_diagnostic import build_decision_diagnostic_message

    assert "stale_channels" in build_decision_diagnostic_message.__code__.co_varnames
