"""RL state representation (FR-RL1) -- simulation-first, no learning yet.

PRD FR-RL1 (docs/SHTAPM_PRD-4.md): "The agent shall consume a state vector
`[health, anomaly_flag, T1..T6, failure_ETA]`." No DECISIONS.md entry
narrows, widens, or reorders this -- U06 (RL reward shaping) is the only
open RL-related item, and it does not touch the state vector's shape. This
module implements exactly that ordering: no added element, no reordering,
no renamed field, no invented dimension.

STATE_WIDTH = 9. Fixed order (index: field):
    0            health
    1            anomaly_flag
    2..7         T1..T6 (per-channel trust, in CHANNELS' own frozen order:
                 temperature, vibration, pressure, humidity, gas, current)
    8            failure_eta

``health`` -- FR-RL1 does not specify HealthState (categorical) vs. a
continuous score, and neither does any DECISIONS.md entry. This module
accepts a plain ``float | None``; the caller decides its source.
``PrognosisRuntime``/``LSTMPrognosisPredictor`` currently expose only a
categorical ``HealthState`` (see ``edge/pipeline/prognosis_runtime.py``) --
no continuous score exists there yet. The only continuous source
implemented so far is ``edge/rl/environment.py``, which uses the synthetic
degradation generator's own ground-truth continuous ``health`` value
(``edge/models/degradation_generator.py``) -- explicitly NOT a trained
model's inference. This module itself makes no assumption about where
``health`` came from; it only validates that, when present, it lies in
``[0, 1]``.

``failure_eta`` -- when sourced from a real ``PrognosisResult.failure_eta``,
its numeric scale/units are NOT assumed here: they depend on which
``prognosis_data_source`` trained the injected predictor (``pronostia``:
RUL-derived seconds; ``synthetic``: the degradation generator's own
``[0, 1]`` health-fraction target, per
``edge/eval/synthetic_prognosis_training.py``). This module treats it as
an opaque, unit-less continuous scalar and only rejects non-finite values.

MISSING PROGNOSIS DATA: ``health``/``failure_eta`` may be genuinely
unavailable (e.g. ``PrognosisResult.status == "predictor_unavailable"``).
``RLState`` accepts ``None`` for both and exposes ``prognosis_available``
(``False`` iff either is ``None``) as separate, UN-VECTORIZED metadata --
FR-RL1's 9-wide vector is never silently widened to carry this flag.
``to_vector()`` still always returns a full 9-wide tuple (a numeric model
needs a fixed-width input); a missing value is substituted with
``MISSING_PROGNOSIS_FILL_VALUE`` (0.0) -- chosen to match this project's
existing "default to the conservative/worst-case reading when data is
missing" convention (``edge/actuation/relay.py``'s default-OFF,
``edge/actuation/watchdog.py``'s fail-to-safe), NOT a claim that 0.0 is the
channel's true value. ``prognosis_available`` is the authoritative signal;
any real consumer of ``to_vector()`` must check it before trusting indices
0 and 8.

``anomaly_flag``/``T1..T6`` have no "unavailable" state here: P2's
``WindowOutcome`` (``edge/anomaly/pipeline.py``) always carries a boolean
anomaly flag and a ``TrustReading`` for every one of the frozen
``CHANNELS`` -- there is no existing "missing trust" concept to represent.

``to_vector()`` returns a plain ``tuple[float, ...]`` rather than a numpy
array or torch tensor -- this project has no existing numpy dependency,
and every other fixed-length numeric sequence in this codebase
(``edge.anomaly.preprocess.Window.features``) already uses plain tuples. A
future policy layer converts to whatever tensor type it needs.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass

from app.schemas.contracts import CHANNELS

from edge.trust.engine import TrustReading

STATE_WIDTH = 9
MISSING_PROGNOSIS_FILL_VALUE = 0.0

# Exactly FR-RL1's ordering, restated as field names for tooling/logging.
STATE_FIELD_ORDER: tuple[str, ...] = (
    "health",
    "anomaly_flag",
    *(f"trust_{ch}" for ch in CHANNELS),
    "failure_eta",
)
assert len(STATE_FIELD_ORDER) == STATE_WIDTH  # guards the two from silently drifting apart


@dataclass(frozen=True)
class RLState:
    """One cycle's FR-RL1 state. Construct via ``build_rl_state`` in the
    common case (accepts P2's own ``TrustReading`` mapping directly)."""

    health: float | None
    anomaly_flag: bool
    trust: Mapping[str, float]
    failure_eta: float | None
    execution_mode: str | None = None
    prognosis_data_source: str | None = None
    health_label_source: str | None = None

    def __post_init__(self) -> None:
        missing = sorted(set(CHANNELS) - set(self.trust))
        if missing:
            raise ValueError(
                f"trust is missing required channel(s) {missing}; must cover {CHANNELS}"
            )
        extra = sorted(set(self.trust) - set(CHANNELS))
        if extra:
            raise ValueError(f"trust names unknown channel(s) {extra}; must be one of {CHANNELS}")
        for ch, value in self.trust.items():
            _require_finite_in_unit_interval(value, f"trust[{ch!r}]")
        if self.health is not None:
            _require_finite_in_unit_interval(self.health, "health")
        if self.failure_eta is not None and not math.isfinite(self.failure_eta):
            raise ValueError(f"failure_eta must be finite, got {self.failure_eta}")

    @property
    def prognosis_available(self) -> bool:
        """``True`` iff BOTH ``health`` and ``failure_eta`` are present.
        Partial availability (one present, one missing) is still reported
        as unavailable -- a caller relying on partial prognosis data is a
        decision for a future increment, not assumed here."""
        return self.health is not None and self.failure_eta is not None

    def to_vector(self) -> tuple[float, ...]:
        """The FR-RL1 9-wide numeric vector, in ``STATE_FIELD_ORDER``.
        Missing ``health``/``failure_eta`` are substituted with
        ``MISSING_PROGNOSIS_FILL_VALUE`` -- see module docstring; check
        ``prognosis_available`` before trusting indices 0/8."""
        fill = MISSING_PROGNOSIS_FILL_VALUE
        health_value = self.health if self.health is not None else fill
        eta_value = self.failure_eta if self.failure_eta is not None else fill
        vector = (
            health_value,
            1.0 if self.anomaly_flag else 0.0,
            *(self.trust[ch] for ch in CHANNELS),
            eta_value,
        )
        assert len(vector) == STATE_WIDTH
        return vector


def _require_finite_in_unit_interval(value: float, name: str) -> None:
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite, got {value}")
    if not (0.0 <= value <= 1.0):
        raise ValueError(f"{name} must be in [0, 1], got {value}")


def build_rl_state(
    *,
    health: float | None,
    anomaly_flag: bool,
    trust: Mapping[str, TrustReading],
    failure_eta: float | None,
    execution_mode: str | None = None,
    prognosis_data_source: str | None = None,
    health_label_source: str | None = None,
) -> RLState:
    """Build an ``RLState`` directly from what P2's ``WindowOutcome`` and
    ``PrognosisRuntime`` already produce per cycle -- ``trust`` is the exact
    ``dict[str, TrustReading]`` shape ``WindowOutcome.trust`` already has,
    not a pre-extracted ``dict[str, float]`` (that extraction happens here,
    once, so callers never duplicate it).

    Raises:
        ValueError: if ``trust`` does not cover exactly the frozen
            ``CHANNELS``, or if any value is out of its documented range
            (delegated to ``RLState.__post_init__``).
    """
    missing = sorted(set(CHANNELS) - set(trust))
    if missing:
        raise ValueError(f"trust is missing required channel(s) {missing}; must cover {CHANNELS}")
    trust_values = {ch: trust[ch].trust for ch in CHANNELS}
    return RLState(
        health=health,
        anomaly_flag=anomaly_flag,
        trust=trust_values,
        failure_eta=failure_eta,
        execution_mode=execution_mode,
        prognosis_data_source=prognosis_data_source,
        health_label_source=health_label_source,
    )
