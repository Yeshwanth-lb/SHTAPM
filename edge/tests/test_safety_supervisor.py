"""Safe Pump-Stop software (D041; FR-R1..R3, AC4): relay driver, dry-run
detection, latching safe-stop, watchdog, MQTT plumbing and boot wiring."""

from __future__ import annotations

import json
import subprocess

import pytest
from app.schemas.actuation import ActuationStatus, RelayCommand
from app.schemas.build import build_telemetry

from edge.actuation import gpio
from edge.actuation.gpio import PinctrlActuator, RelayConfigError, relay_config_from_env
from edge.actuation.mqtt import ActuationPublisher, RelayCommandListener
from edge.actuation.relay import FakeActuator, RelayController, RelayState
from edge.actuation.supervisor import CURRENT_IDLE_MAX_A, DryRunDetector, SafetySupervisor


class Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


class Runner:
    def __init__(self, returncode: int = 0) -> None:
        self.calls: list[list[str]] = []
        self.returncode = returncode

    def __call__(self, cmd, **kwargs):
        self.calls.append(cmd)
        return subprocess.CompletedProcess(cmd, self.returncode, "", "boom")


def _frame(current: float, i: int = 0):
    values = {
        "temperature": 26.0,
        "vibration": 0.5,
        "pressure": 916.0,
        "humidity": 45.0,
        "gas": 150.0,
        "current": current,
    }
    return build_telemetry("pump-01", f"2026-10-27T10:00:{i % 60:02d}.000Z", values, i)


def _command(state: str, device_id: str = "pump-01") -> RelayCommand:
    return RelayCommand(
        action="relay",
        command_id="c1",
        device_id=device_id,
        state=state,
        issued_by="admin@example.com",
        issued_at="2026-10-27T10:00:00.000Z",
    )


def _supervisor(dry_run=None, clock=None, actuator=None, timeout=10.0):
    clock = clock or Clock()
    published: list[ActuationStatus] = []
    actuator = actuator or FakeActuator()
    supervisor = SafetySupervisor(
        device_id="pump-01",
        relay=RelayController(actuator),
        hardware=False,
        publish=published.append,
        dry_run=dry_run,
        watchdog_timeout_s=timeout,
        clock=clock,
        now_iso=lambda: "2026-10-27T10:00:00.000Z",
    )
    supervisor.start(watchdog_thread=False)
    return supervisor, published, actuator, clock


# --- relay driver --------------------------------------------------------------


@pytest.mark.parametrize(
    "active_low, state, level",
    [
        (True, RelayState.ON, "dl"),
        (True, RelayState.OFF, "dh"),
        (False, RelayState.ON, "dh"),
        (False, RelayState.OFF, "dl"),
    ],
)
def test_pinctrl_levels_follow_polarity(active_low, state, level):
    runner = Runner()
    PinctrlActuator(27, active_low=active_low, run=runner).set_state(state)
    assert runner.calls == [["pinctrl", "set", "27", "op", level]]


@pytest.mark.parametrize("pin", [2, 3, 8, 9, 10, 11, 17])
def test_pins_used_by_the_bench_are_refused(pin):
    with pytest.raises(RelayConfigError, match="already used"):
        PinctrlActuator(pin, active_low=True, run=Runner())


def test_a_failed_pinctrl_call_raises_and_keeps_the_old_state():
    actuator = PinctrlActuator(27, active_low=True, run=Runner(returncode=1))
    with pytest.raises(OSError, match="exited 1"):
        actuator.set_state(RelayState.ON)
    assert actuator.get_state() is RelayState.OFF


def test_relay_config_from_env():
    assert relay_config_from_env({}) is None
    assert relay_config_from_env(
        {"SHTAPM_RELAY_GPIO": "27", "SHTAPM_RELAY_ACTIVE_LOW": "true"}
    ) == (27, True)
    with pytest.raises(RelayConfigError, match="never guessed"):
        relay_config_from_env({"SHTAPM_RELAY_GPIO": "27"})
    with pytest.raises(RelayConfigError, match="not a GPIO number"):
        relay_config_from_env({"SHTAPM_RELAY_GPIO": "x", "SHTAPM_RELAY_ACTIVE_LOW": "true"})
    with pytest.raises(RelayConfigError, match="DHT22"):
        relay_config_from_env({"SHTAPM_RELAY_GPIO": "17", "SHTAPM_RELAY_ACTIVE_LOW": "false"})


def test_systemd_off_hook(monkeypatch, capsys):
    monkeypatch.delenv("SHTAPM_RELAY_GPIO", raising=False)
    assert gpio.main(["off"]) == 0
    assert "nothing to switch off" in capsys.readouterr().out
    runner = Runner()
    monkeypatch.setenv("SHTAPM_RELAY_GPIO", "27")
    monkeypatch.setenv("SHTAPM_RELAY_ACTIVE_LOW", "true")
    monkeypatch.setattr(gpio.subprocess, "run", runner)
    assert gpio.main(["off"]) == 0
    assert runner.calls == [["pinctrl", "set", "27", "op", "dh"]]
    assert gpio.main(["on"]) == 2


# --- dry-run detection -----------------------------------------------------------


def test_dry_run_needs_spin_up_grace_band_and_hold():
    clock = Clock()
    detector = DryRunDetector(0.4, grace_s=5.0, hold_samples=3, clock=clock)
    detector.reset()
    assert not detector.observe(0.2, relay_on=True)  # inside the grace
    clock.t = 6.0
    assert [detector.observe(0.2, relay_on=True) for _ in range(3)] == [False, False, True]


def test_motor_off_current_is_not_a_dry_run():
    clock = Clock()
    detector = DryRunDetector(0.4, grace_s=0.0, hold_samples=1, clock=clock)
    detector.reset()
    assert not detector.observe(0.0, relay_on=True)  # spoof to 0 A / cut wire
    assert not detector.observe(0.75, relay_on=True)  # normal running
    assert detector.observe(0.3, relay_on=True)


def test_a_normal_sample_breaks_the_streak_and_relay_off_never_detects():
    clock = Clock()
    detector = DryRunDetector(0.4, grace_s=0.0, hold_samples=2, clock=clock)
    detector.reset()
    assert [detector.observe(v, relay_on=True) for v in (0.3, 0.7, 0.3)] == [False] * 3
    assert not detector.observe(0.3, relay_on=False)


def test_threshold_must_exceed_motor_off_current():
    with pytest.raises(ValueError, match="motor-off"):
        DryRunDetector(CURRENT_IDLE_MAX_A)


# --- supervisor ----------------------------------------------------------------


def test_startup_announces_relay_off():
    _, published, actuator, _ = _supervisor()
    assert actuator.get_state() is RelayState.OFF
    assert [(s.relay, s.cause, s.latched) for s in published] == [("off", "startup", False)]


def test_operator_start_and_stop():
    supervisor, published, actuator, _ = _supervisor()
    assert supervisor.command(_command("on"))
    assert actuator.get_state() is RelayState.ON
    supervisor.command(_command("off"))
    assert actuator.get_state() is RelayState.OFF
    assert [s.cause for s in published] == ["startup", "command", "command"]
    assert "admin@example.com" in published[1].reason


def test_command_for_another_device_is_ignored():
    supervisor, _, actuator, _ = _supervisor()
    assert not supervisor.command(_command("on", device_id="pump-02"))
    assert actuator.get_state() is RelayState.OFF


def test_safe_stop_latches_until_an_operator_restarts():
    supervisor, published, actuator, _ = _supervisor()
    supervisor.command(_command("on"))
    supervisor.safe_stop("safe_stop", "self-heal escalation")
    assert actuator.get_state() is RelayState.OFF and supervisor.latched
    assert (published[-1].relay, published[-1].cause, published[-1].latched) == (
        "off",
        "safe_stop",
        True,
    )
    supervisor.safe_stop("safe_stop", "again")  # already off + latched: no new status
    assert len(published) == 3
    supervisor.command(_command("on"))
    assert actuator.get_state() is RelayState.ON and not supervisor.latched


def test_dry_run_frames_stop_the_pump():
    clock = Clock()
    detector = DryRunDetector(0.4, grace_s=5.0, hold_samples=3, clock=clock)
    supervisor, published, actuator, _ = _supervisor(dry_run=detector, clock=clock)
    supervisor.command(_command("on"))
    clock.t = 10.0
    for i, current in enumerate((0.75, 0.3, 0.3, 0.3)):
        supervisor.on_frame(_frame(current, i))
    assert actuator.get_state() is RelayState.OFF
    assert published[-1].cause == "dry_run" and "0.300 A" in published[-1].reason


def test_watchdog_stops_a_running_pump_without_frames():
    supervisor, published, actuator, clock = _supervisor(timeout=10.0)
    supervisor.command(_command("on"))
    clock.t = 5.0
    supervisor.on_frame(_frame(0.75))
    clock.t = 14.0
    supervisor.check_watchdog()
    assert actuator.get_state() is RelayState.ON  # 9 s since the last frame
    clock.t = 16.0
    supervisor.check_watchdog()
    assert actuator.get_state() is RelayState.OFF
    assert published[-1].cause == "watchdog"


def test_watchdog_does_nothing_while_the_pump_is_off():
    supervisor, published, _, clock = _supervisor(timeout=10.0)
    clock.t = 60.0
    supervisor.check_watchdog()
    assert [s.cause for s in published] == ["startup"]


def test_shutdown_forces_off():
    supervisor, published, actuator, _ = _supervisor()
    supervisor.command(_command("on"))
    supervisor.stop()
    assert actuator.get_state() is RelayState.OFF
    assert published[-1].cause == "shutdown"


def test_a_relay_that_cannot_switch_off_is_reported_not_raised():
    class Stuck(FakeActuator):
        def set_state(self, state):
            if state is RelayState.OFF and len(self.history) > 1:
                raise OSError("relay stuck")
            super().set_state(state)

    supervisor, published, _, _ = _supervisor(actuator=Stuck())
    supervisor.command(_command("on"))
    supervisor.safe_stop("safe_stop", "escalation")  # must not raise
    assert published[-1].cause == "safe_stop"


# --- MQTT plumbing ---------------------------------------------------------------


class FakeClient:
    def __init__(self) -> None:
        self.published: list[tuple] = []
        self.subscribed: list[str] = []

    def publish(self, topic, payload, qos=0, retain=False):
        self.published.append((topic, json.loads(payload), qos, retain))

    def subscribe(self, topic, qos=0):
        self.subscribed.append(topic)


def test_status_is_retained_and_resent_on_reconnect():
    publisher = ActuationPublisher(device_id="pump-01")
    client = FakeClient()
    publisher.attach(client)
    supervisor = SafetySupervisor(
        device_id="pump-01",
        relay=RelayController(FakeActuator()),
        hardware=True,
        publish=publisher.publish,
    )
    supervisor.start(watchdog_thread=False)
    topic, payload, qos, retain = client.published[0]
    assert (topic, qos, retain) == ("shtapm/pump-01/actuation", 1, True)
    assert payload["relay"] == "off" and payload["hardware"] is True
    publisher._on_connect(client, None, None, 0)
    assert len(client.published) == 2


def test_relay_listener_applies_valid_and_rejects_invalid():
    supervisor, _, actuator, _ = _supervisor()
    listener = RelayCommandListener(device_id="pump-01", supervisor=supervisor)
    client = FakeClient()
    listener.attach(client)
    listener._on_connect(client, None, None, 0)
    assert client.subscribed == ["shtapm/pump-01/relay_command"]
    assert listener.handle(_command("on").model_dump_json())
    assert actuator.get_state() is RelayState.ON
    assert not listener.handle(b"not json")
    assert not listener.handle(json.dumps({"action": "inject"}))
    assert (listener.applied_count, listener.rejected_count) == (1, 2)


def test_injection_commands_cannot_reach_the_relay():
    """D032's guarantee survives D041: an injection payload on the relay topic
    is rejected, and relay commands have their own topic."""
    supervisor, _, actuator, _ = _supervisor()
    listener = RelayCommandListener(device_id="pump-01", supervisor=supervisor)
    inject = {
        "action": "inject",
        "command_id": "c1",
        "device_id": "pump-01",
        "scenario": "stuck_at",
        "channel": "current",
        "duration_s": 60,
        "params": {},
        "issued_by": "a@b.c",
        "issued_at": "2026-10-27T10:00:00.000Z",
    }
    assert not listener.handle(json.dumps(inject))
    assert actuator.get_state() is RelayState.OFF


# --- boot wiring (edge/main.py) ----------------------------------------------------


def test_replay_never_drives_the_physical_relay():
    from edge.main import _build_safety_supervisor

    env = {"SHTAPM_RELAY_GPIO": "27", "SHTAPM_RELAY_ACTIVE_LOW": "true"}
    supervisor = _build_safety_supervisor(
        device_id="pump-01", replay=True, publish=lambda s: None, env=env
    )
    supervisor.start(watchdog_thread=False)
    assert supervisor.last_status.hardware is False


def test_unsafe_relay_config_stops_the_boot():
    from edge.main import _build_safety_supervisor

    with pytest.raises(RelayConfigError):
        _build_safety_supervisor(
            device_id="pump-01",
            replay=False,
            publish=lambda s: None,
            env={"SHTAPM_RELAY_GPIO": "27"},
        )


def test_dry_run_threshold_from_env():
    from edge.main import _build_safety_supervisor

    with pytest.raises(RuntimeError, match="SHTAPM_DRY_RUN_CURRENT_A"):
        _build_safety_supervisor(
            device_id="pump-01",
            replay=False,
            publish=lambda s: None,
            env={"SHTAPM_DRY_RUN_CURRENT_A": "low"},
        )
    supervisor = _build_safety_supervisor(
        device_id="pump-01",
        replay=False,
        publish=lambda s: None,
        env={"SHTAPM_DRY_RUN_CURRENT_A": "0.4"},
    )
    assert supervisor._dry_run is not None and supervisor._dry_run.threshold_a == 0.4
