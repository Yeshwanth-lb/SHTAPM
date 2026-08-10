"""Synthetic fault/attack injection framework (P2 · PRD §12.4 test data).

Post-generation stream transforms that stamp a labelled fault or attack onto a
clean :class:`~app.schemas.contracts.TelemetryMessage` stream, for exercising
the P2 anomaly/trust/attribution pipeline WITHOUT hardware or a real dataset.

Scope (7 hardware-free §12.4 injections only):
  faults  : gradual drift, sudden spike, stuck-at
  attacks : bias FDI, ramp FDI, replay, constant-value spoof

NOT here (deliberate):
  * ``dry-run`` — §12.4 marks it physical; stays hardware/rig-gated (P3-SAFE).
  * Isolation Forest, trust signal definitions (c/k/h), attribution physics,
    dataset-specific rules — all out of scope / undecided.

The transforms invent NO magnitudes, durations, or thresholds: every such value
is a required caller argument. The frozen telemetry wire contract is untouched
(each frame is rebuilt through the shared ``build_telemetry``); the ground-truth
:class:`Label` metadata is for tests/evaluation only and never goes on the wire.
"""

from edge.injection.injections import (
    ATTACK_TYPES,
    FAULT_TYPES,
    BiasFDI,
    ConstantSpoof,
    Drift,
    Injection,
    InjectionResult,
    InjectionType,
    Kind,
    Label,
    RampFDI,
    Replay,
    Spike,
    StuckAt,
)

__all__ = [
    "ATTACK_TYPES",
    "FAULT_TYPES",
    "BiasFDI",
    "ConstantSpoof",
    "Drift",
    "Injection",
    "InjectionResult",
    "InjectionType",
    "Kind",
    "Label",
    "RampFDI",
    "Replay",
    "Spike",
    "StuckAt",
]
