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
from edge.pipeline.decision_diagnostic import DecisionDiagnosticPublisher

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
    decision_publisher = DecisionDiagnosticPublisher(device_id="pump-01")  # never started -> no-op
    monitor = _build_p2_monitor(
        fit_window_count=fit_window_count,
        device_id="pump-01",
        decision_publisher=decision_publisher,
    )
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
    # Each outcome now logs four lines: the P2 window itself, the
    # (stateless, log-only) FR-RL4 isolation decision, the (persistent,
    # log-only) FR-RL4 isolation tracking result, and the exact raw
    # per-channel values for that same window.
    all_records = [r for r in caplog.records if r.name == "shtapm.edge.main"]
    p2_records = [r for r in all_records if "P2 window" in r.getMessage()]
    isolation_records = [r for r in all_records if "FR-RL4 isolation decision" in r.getMessage()]
    tracking_records = [r for r in all_records if "FR-RL4 isolation tracking" in r.getMessage()]
    raw_value_records = [r for r in all_records if "P2 raw values" in r.getMessage()]
    assert len(all_records) == 12
    assert len(p2_records) == 3  # 1 at the fit/transition tick + 2 more sliding ticks
    assert len(isolation_records) == 3
    assert len(tracking_records) == 3
    assert len(raw_value_records) == 3
    assert all("anomaly=False" in r.getMessage() for r in p2_records)  # NullDetector
    # FR-RL4 logging must never claim a real isolation/actuation/recovery --
    # it only reports candidates/tracked channels for the caller to log (see
    # edge/pipeline/{isolation_fallback,isolation_tracker}.py).
    assert all("stateless, log-only" in r.getMessage() for r in isolation_records)
    assert all("persistent, log-only" in r.getMessage() for r in tracking_records)
    # Raw values must reflect the fake driver's exact constant VALUES --
    # never reconstructed, normalized, or derived.
    assert all("temperature=26.000" in r.getMessage() for r in raw_value_records)
    assert all("current=0.420" in r.getMessage() for r in raw_value_records)


def test_live_wiring_never_isolates_or_actuates():
    """Monitoring-only, by construction: AcquisitionRuntime/LiveP2Monitor/
    isolation_fallback/isolation_tracker/decision_diagnostic import nothing
    from edge/pipeline/self_heal.py, edge/pipeline/cycle.py, or
    edge/actuation/* -- a decision_diagnostic message is published (a new,
    separate, best-effort diagnostic topic, NOT the frozen `.../decision`
    topic/DecisionMessage shape -- see edge/pipeline/decision_diagnostic.py),
    but no isolation/substitution/actuation is ever performed anywhere in
    this wiring. AST-based (not substring search): decision_diagnostic.py's
    own docstring legitimately NAMES SelfHealOrchestrator/RelayController to
    explain that it does NOT call them, which a naive substring check can't
    distinguish from an actual import."""
    import ast
    import inspect

    import edge.acquisition.runtime as runtime_module
    import edge.pipeline.decision_diagnostic as decision_diagnostic_module
    import edge.pipeline.isolation_fallback as isolation_fallback_module
    import edge.pipeline.isolation_tracker as isolation_tracker_module
    import edge.pipeline.monitor as monitor_module

    modules = (
        runtime_module,
        monitor_module,
        isolation_fallback_module,
        isolation_tracker_module,
        decision_diagnostic_module,
    )
    forbidden_import_substrings = ("self_heal", "cycle", "actuation")
    for module in modules:
        tree = ast.parse(inspect.getsource(module))
        imported_modules: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_modules.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_modules.add(node.module)
        for forbidden in forbidden_import_substrings:
            assert not any(forbidden in name for name in imported_modules), (
                f"{module.__name__} imports something matching {forbidden!r}: {imported_modules}"
            )


def test_decision_diagnostic_publish_failure_never_interrupts_telemetry_or_p2_logging(caplog):
    """A broken decision_publisher (e.g. a broker rejecting the diagnostic
    topic) must never affect telemetry publishing or P2 monitoring/logging
    -- see edge/main.py's DECISION-DIAGNOSTIC PUBLISHING docstring section."""

    class _BrokenDecisionPublisher(DecisionDiagnosticPublisher):
        def publish(self, message):  # noqa: D102
            raise RuntimeError("broker rejected decision_diagnostic topic")

    fit_window_count = 1
    fit_buffer_size = 30 + (fit_window_count - 1) * 1
    total_ticks = fit_buffer_size  # exactly one emitted outcome (the fit/transition tick)

    client = FakeClient()
    publisher = ResilientTelemetryPublisher(device_id="pump-01", rate_hz=5.0, client=client)
    sampler = Sampler(device_id="pump-01", drivers=fake_drivers(VALUES))
    monitor = _build_p2_monitor(
        fit_window_count=fit_window_count,
        device_id="pump-01",
        decision_publisher=_BrokenDecisionPublisher(device_id="pump-01"),
    )
    runtime = AcquisitionRuntime(
        sampler=sampler, publisher=publisher, rate_hz=5.0, on_healthy_frame=monitor.on_frame
    )
    client.fire_connect()

    with caplog.at_level("INFO", logger="shtapm.edge.main"):
        for _ in range(total_ticks):
            runtime.tick()  # must not raise

    seqs = [m["sample_seq"] for m in _telemetry(client)]
    assert seqs == list(range(total_ticks))  # telemetry completely unaffected

    all_records = [r for r in caplog.records if r.name == "shtapm.edge.main"]
    raw_value_records = [r for r in all_records if "P2 raw values" in r.getMessage()]
    assert len(raw_value_records) == 1  # P2 logging (which triggers the publish attempt) still ran
