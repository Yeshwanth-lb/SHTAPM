"""P0 gap-closure item 1 -- end-to-end proof that the REAL edge/main.py
wiring (Sampler -> AcquisitionRuntime -> LiveP2Monitor, composed by
``edge.main._build_p2_monitor`` exactly as shipped) invokes P2 processing on
every tick AND that telemetry publishing is unaffected. Uses edge.main's own
composition function directly (not a re-implementation), so this test
breaks if the real wiring in edge/main.py ever drifts from what's tested
here -- unlike edge/tests/test_live_p2_monitor.py, which rebuilds an
equivalent pipeline locally to stay hardware-import-free.
"""

from __future__ import annotations

import json

from edge.acquisition.mqtt_publisher import ResilientTelemetryPublisher
from edge.acquisition.runtime import AcquisitionRuntime
from edge.acquisition.sampler import Sampler
from edge.drivers.fake import fake_drivers
from edge.main import _build_p2_monitor

VALUES = {
    "temperature": 26.0,
    "vibration": 0.03,
    "pressure": 1013.0,
    "humidity": 45.0,
    "gas": 150.0,
    "current": 0.42,
}


class FakeClient:
    """Minimal fake paho client -- same shape as edge/tests/test_runtime.py's."""

    def __init__(self) -> None:
        self.on_connect = None
        self.published: list[tuple[str, str]] = []

    def will_set(self, topic, payload, qos=0, retain=False):
        pass

    def publish(self, topic, payload, qos=0, retain=False):
        self.published.append((topic, payload))

    def disconnect(self):
        pass

    def fire_connect(self):
        self.on_connect(self, None, None, 0)


def _telemetry(client: FakeClient):
    return [
        json.loads(payload) for (topic, payload) in client.published if topic.endswith("/telemetry")
    ]


def test_live_wiring_publishes_telemetry_and_invokes_p2_processing(caplog):
    # FIT_WINDOW_COUNT=3 -> fit_buffer_size = 30 + (3-1)*1 = 32 (see
    # edge/pipeline/monitor.py's formula). Feed 2 extra ticks past that so
    # both the warm-up transition and the steady one-window-per-tick phase
    # are exercised in one test.
    fit_window_count = 3
    fit_buffer_size = 30 + (fit_window_count - 1) * 1
    total_ticks = fit_buffer_size + 2

    client = FakeClient()
    publisher = ResilientTelemetryPublisher(device_id="pump-01", rate_hz=5.0, client=client)
    sampler = Sampler(device_id="pump-01", drivers=fake_drivers(VALUES))
    monitor = _build_p2_monitor(fit_window_count=fit_window_count)
    runtime = AcquisitionRuntime(
        sampler=sampler, publisher=publisher, rate_hz=5.0, on_healthy_frame=monitor.on_frame
    )
    client.fire_connect()

    with caplog.at_level("INFO", logger="shtapm.edge.main"):
        for _ in range(total_ticks):
            runtime.tick()

    # Telemetry publishing still works, unaffected by P2 monitoring.
    seqs = [m["sample_seq"] for m in _telemetry(client)]
    assert seqs == list(range(total_ticks))

    # P2 processing was genuinely invoked (real, non-stub components,
    # exactly as edge/main.py composes them) and logged -- proving the
    # wiring is live, not re-implementing/stubbing it for this test.
    # Each outcome now logs two lines: the P2 window itself, and the
    # (stateless, log-only) FR-RL4 isolation decision derived from it.
    all_records = [r for r in caplog.records if r.name == "shtapm.edge.main"]
    p2_records = [r for r in all_records if "P2 window" in r.getMessage()]
    isolation_records = [r for r in all_records if "FR-RL4 isolation decision" in r.getMessage()]
    assert len(all_records) == 6
    assert len(p2_records) == 3  # 1 at the fit/transition tick + 2 more sliding ticks
    assert len(isolation_records) == 3
    assert all("anomaly=False" in r.getMessage() for r in p2_records)  # NullDetector
    # FR-RL4 decision logging must never claim a real isolation/actuation --
    # it only reports candidates for the caller to log (see
    # edge/pipeline/isolation_fallback.py).
    assert all("stateless, log-only" in r.getMessage() for r in isolation_records)


def test_live_wiring_never_isolates_actuates_or_publishes_a_decision():
    """Monitoring-only, by construction: AcquisitionRuntime/LiveP2Monitor/
    isolation_fallback import nothing from edge/pipeline/self_heal.py,
    edge/pipeline/cycle.py, or edge/actuation/*, and edge/main.py's MQTT
    publisher only ever publishes telemetry/status topics (no decision/
    ledger topic exists)."""
    import edge.acquisition.runtime as runtime_module
    import edge.pipeline.isolation_fallback as isolation_fallback_module
    import edge.pipeline.monitor as monitor_module

    for module in (runtime_module, monitor_module, isolation_fallback_module):
        with open(module.__file__, encoding="utf-8") as f:
            content = f.read()
        assert "RelayController" not in content
        assert "SelfHealOrchestrator" not in content
        assert "process_isolated_channels" not in content
