"""Live scenario injection on the edge (D032): LiveInjector, CommandListener,
and AcquisitionRuntime's frame_transform seam."""

from __future__ import annotations

import json
import threading

import pytest
from app.schemas.command import CancelCommand, InjectCommand
from app.schemas.contracts import CHANNELS

from edge.acquisition.command_listener import CommandListener
from edge.acquisition.mqtt_publisher import ResilientTelemetryPublisher
from edge.acquisition.runtime import AcquisitionRuntime
from edge.acquisition.sampler import Sampler
from edge.drivers.fake import fake_drivers
from edge.injection.live import LiveInjector
from simulator.generator import TelemetrySimulator


def _frames(count: int, seed: int = 5):
    sim = TelemetrySimulator(seed=seed)
    return sim.generate(count, [f"2026-10-26T10:00:{i % 60:02d}.000Z" for i in range(count)])


def _inject(scenario: str, params: dict, *, duration_s: int = 5, channel: str = "current", **kw):
    return InjectCommand(
        action="inject",
        command_id=kw.get("command_id", "c1"),
        device_id=kw.get("device_id", "pump-01"),
        scenario=scenario,
        channel=channel,
        duration_s=duration_s,
        params=params,
        issued_by="admin@example.com",
        issued_at="2026-10-26T10:00:00.000+00:00",
    )


def _cancel(command_id: str = "c1") -> CancelCommand:
    return CancelCommand(
        action="cancel",
        command_id=command_id,
        device_id="pump-01",
        issued_by="admin@example.com",
        issued_at="2026-10-26T10:00:05.000+00:00",
    )


def _injector(rate_hz: float = 1.0, history_seconds: int = 60) -> LiveInjector:
    return LiveInjector(device_id="pump-01", rate_hz=rate_hz, history_seconds=history_seconds)


def _run(injector: LiveInjector, frames) -> list:
    return [injector.transform(f) for f in frames]


def _current_offsets(out, clean) -> list[float]:
    return [
        round(o.sensors.current - c.sensors.current, 9) for o, c in zip(out, clean, strict=True)
    ]


# --- LiveInjector -----------------------------------------------------------------


def test_no_injection_is_a_passthrough():
    frames = _frames(10)
    assert _run(_injector(), frames) == frames


def test_constant_spoof_pins_only_the_target_for_exactly_its_duration():
    injector = _injector()
    clean = _frames(10)
    assert injector.submit(_inject("constant_spoof", {"value": 0.42}, duration_s=4))
    out = _run(injector, clean)
    assert [f.sensors.current for f in out[:4]] == [0.42] * 4
    assert [f.sensors.current for f in out[4:]] == [f.sensors.current for f in clean[4:]]
    for ch in CHANNELS:
        if ch != "current":
            assert [getattr(f.sensors, ch) for f in out] == [getattr(f.sensors, ch) for f in clean]
    assert [f.sample_seq for f in out] == [f.sample_seq for f in clean]
    assert injector.status() is None  # ended on its own


def test_rates_are_per_second_regardless_of_sample_rate():
    """A drift of 0.2/s must reach 0.2 after one second at 2 Hz (two samples)."""
    injector = _injector(rate_hz=2.0)
    clean = _frames(4)
    injector.submit(_inject("drift", {"rate": 0.2}, duration_s=2))  # 4 samples at 2 Hz
    out = _run(injector, clean)
    assert _current_offsets(out, clean) == [0.1, 0.2, 0.3, 0.4]


def test_bias_and_spike_add_to_the_live_value():
    for scenario, params, delta in (
        ("bias_fdi", {"bias": 0.5}, 0.5),
        ("spike", {"amplitude": 3.0}, 3.0),
    ):
        injector = _injector()
        clean = _frames(3)
        injector.submit(_inject(scenario, params, duration_s=3))
        out = _run(injector, clean)
        assert _current_offsets(out, clean) == [delta] * 3


def test_stuck_at_holds_the_value_at_onset():
    injector = _injector()
    clean = _frames(5)
    injector.submit(_inject("stuck_at", {}, duration_s=5))
    out = _run(injector, clean)
    assert {f.sensors.current for f in out} == {clean[0].sensors.current}


def test_adaptive_stealth_offset_never_exceeds_its_cap():
    injector = _injector()
    clean = _frames(10)
    injector.submit(
        _inject("adaptive_stealth_fdi", {"rate": 0.1, "residual_cap": 0.25}, duration_s=10)
    )
    out = _run(injector, clean)
    offsets = [o.sensors.current - c.sensors.current for o, c in zip(out, clean, strict=False)]
    assert max(offsets) == pytest.approx(0.25)
    assert offsets[0] == pytest.approx(0.1)


def test_replay_copies_the_clean_values_from_lookback_seconds_ago():
    injector = _injector()
    history = _frames(10, seed=1)
    _run(injector, history)
    assert injector.submit(_inject("replay", {"lookback_s": 6}, duration_s=3))
    live = _frames(3, seed=2)
    out = _run(injector, live)
    assert [f.sensors.current for f in out] == [f.sensors.current for f in history[4:7]]


def test_replay_never_copies_an_earlier_injected_value():
    injector = _injector()
    clean = _frames(6, seed=3)
    injector.submit(_inject("constant_spoof", {"value": 99.0}, duration_s=3))
    _run(injector, clean)  # 3 spoofed + 3 clean published
    injector.submit(_inject("replay", {"lookback_s": 6}, duration_s=3, command_id="c2"))
    out = _run(injector, _frames(3, seed=4))
    assert 99.0 not in [f.sensors.current for f in out]
    assert [f.sensors.current for f in out] == [f.sensors.current for f in clean[:3]]


def test_replay_without_enough_history_is_rejected():
    injector = _injector()
    _run(injector, _frames(3))
    assert injector.submit(_inject("replay", {"lookback_s": 10}, duration_s=5)) is False
    assert injector.status() is None


def test_command_for_another_device_is_ignored():
    injector = _injector()
    assert injector.submit(_inject("spike", {"amplitude": 1.0}, device_id="pump-02")) is False
    assert injector.status() is None


def test_cancel_ends_the_injection_immediately():
    injector = _injector()
    clean = _frames(6)
    injector.submit(_inject("constant_spoof", {"value": 0.0}, duration_s=30))
    first = _run(injector, clean[:2])
    assert injector.cancel(_cancel("c1"))
    rest = _run(injector, clean[2:])
    assert [f.sensors.current for f in first] == [0.0, 0.0]
    assert rest == clean[2:]


def test_cancel_with_the_wrong_id_is_ignored_and_star_cancels_anything():
    injector = _injector()
    injector.submit(_inject("constant_spoof", {"value": 0.0}, duration_s=30))
    assert injector.cancel(_cancel("someone-else")) is False
    assert injector.status() is not None
    assert injector.cancel(_cancel("*")) is True
    assert injector.status() is None


def test_a_new_command_replaces_the_running_one():
    injector = _injector()
    injector.submit(_inject("constant_spoof", {"value": 1.0}, duration_s=30))
    injector.submit(_inject("constant_spoof", {"value": 2.0}, duration_s=30, command_id="c2"))
    [out] = _run(injector, _frames(1))
    assert out.sensors.current == 2.0
    assert injector.status().command_id == "c2"


def test_status_reports_progress():
    injector = _injector()
    injector.submit(_inject("bias_fdi", {"bias": 0.1}, duration_s=5, channel="vibration"))
    _run(injector, _frames(2))
    status = injector.status()
    assert (status.scenario, status.channel, status.kind) == ("bias_fdi", "vibration", "attack")
    assert (status.frames_done, status.frames_total) == (2, 5)


def test_a_failing_injection_ends_itself_and_publishes_the_clean_frame():
    injector = _injector()
    injector.submit(_inject("bias_fdi", {"bias": 1e308}, duration_s=5))
    clean = _frames(2)
    big = clean[0].model_copy(
        update={"sensors": clean[0].sensors.model_copy(update={"current": 1e308})}
    )
    assert injector.transform(big) == big  # 1e308 + 1e308 overflows to inf -> ended
    assert injector.status() is None


def test_transform_is_safe_against_concurrent_commands():
    injector = _injector()
    frames = _frames(200)
    errors: list[Exception] = []

    def _commands():
        try:
            for i in range(100):
                injector.submit(_inject("spike", {"amplitude": 1.0}, command_id=f"c{i}"))
                injector.cancel(_cancel("*"))
        except Exception as e:  # pragma: no cover - surfaced below
            errors.append(e)

    thread = threading.Thread(target=_commands)
    thread.start()
    out = _run(injector, frames)
    thread.join()
    assert errors == []
    assert len(out) == len(frames)


def test_injector_validates_its_configuration():
    with pytest.raises(ValueError):
        LiveInjector(device_id="p", rate_hz=0, history_seconds=10)
    with pytest.raises(ValueError):
        LiveInjector(device_id="p", rate_hz=1, history_seconds=0)


# --- CommandListener --------------------------------------------------------------


class _FakeClient:
    def __init__(self) -> None:
        self.subscriptions: list[tuple[str, int]] = []

    def subscribe(self, topic, qos=0):
        self.subscriptions.append((topic, qos))


def test_listener_subscribes_to_its_device_command_topic_at_qos1():
    listener = CommandListener(device_id="pump-01", injector=_injector())
    client = _FakeClient()
    listener.attach(client)
    client.on_connect(client, None, {}, 0)
    assert client.subscriptions == [("shtapm/pump-01/command", 1)]


def test_listener_applies_valid_commands_and_counts_rejections():
    injector = _injector()
    listener = CommandListener(device_id="pump-01", injector=injector)
    assert listener.handle(_inject("spike", {"amplitude": 1.0}).model_dump_json().encode())
    assert injector.status() is not None
    assert listener.handle(_cancel("c1").model_dump_json())
    assert injector.status() is None
    assert listener.handle(b"{not json") is False
    assert listener.handle(json.dumps({"action": "actuate", "relay": "off"})) is False
    assert (listener.applied_count, listener.rejected_count) == (2, 2)


def test_listener_never_raises_when_the_injector_does():
    class _Exploding:
        def submit(self, command):
            raise RuntimeError("boom")

    listener = CommandListener(device_id="pump-01", injector=_Exploding())  # type: ignore[arg-type]
    assert listener.handle(_inject("spike", {"amplitude": 1.0}).model_dump_json()) is False


# --- AcquisitionRuntime seam ---------------------------------------------------


class _RecordingClient:
    def __init__(self) -> None:
        self.published: list[tuple[str, str]] = []
        self.on_connect = None

    def will_set(self, *a, **k):
        pass

    def publish(self, topic, payload, qos=0, retain=False):
        self.published.append((topic, payload))

    def disconnect(self):
        pass


VALUES = {
    "temperature": 25.0,
    "vibration": 0.1,
    "pressure": 916.0,
    "humidity": 60.0,
    "gas": 150.0,
    "current": 0.5,
}


def _runtime(frame_transform, seen: list):
    client = _RecordingClient()
    publisher = ResilientTelemetryPublisher(device_id="pump-01", rate_hz=1.0, client=client)
    publisher._on_connect(client, None, {}, 0)  # mark connected without a broker
    runtime = AcquisitionRuntime(
        sampler=Sampler(device_id="pump-01", drivers=fake_drivers(VALUES)),
        publisher=publisher,
        rate_hz=1.0,
        on_healthy_frame=seen.append,
        frame_transform=frame_transform,
    )
    return runtime, client


def _published_current(client) -> list[float]:
    return [
        json.loads(p)["sensors"]["current"] for t, p in client.published if t.endswith("telemetry")
    ]


def test_runtime_monitors_and_publishes_the_injected_frame():
    injector = _injector()
    injector.submit(_inject("constant_spoof", {"value": 9.0}, duration_s=2))
    seen: list = []
    runtime, client = _runtime(injector.transform, seen)
    for _ in range(3):
        runtime.tick()
    assert [f.sensors.current for f in seen] == [9.0, 9.0, 0.5]
    assert _published_current(client) == [9.0, 9.0, 0.5]


def test_runtime_falls_back_to_the_clean_frame_when_the_transform_raises():
    def _boom(frame):
        raise RuntimeError("bad transform")

    seen: list = []
    runtime, client = _runtime(_boom, seen)
    runtime.tick()
    assert [f.sensors.current for f in seen] == [0.5]
    assert _published_current(client) == [0.5]
