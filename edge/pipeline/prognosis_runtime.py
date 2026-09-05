"""Live prognosis runtime wrapper (simulation-first end-to-end wiring).

execution_mode=simulation · prognosis_data_source=synthetic|pronostia ·
model_status=diagnostic_unvalidated · health_label_source=<caller-supplied|None>

Bridges the real per-cycle ``Window``/``TrustReading`` types this repo's P2
pipeline already produces to the existing, UNMODIFIED
``edge.models.lstm_prognosis`` (``LSTMPrognosisPredictor``,
``build_prognosis_input``). Contains no model architecture, training, or
target-generation logic of its own -- that already exists in
``edge/models/lstm_prognosis.py``, ``edge/eval/pronostia_prognosis_targets.py``,
and ``edge/eval/synthetic_prognosis_training.py``. This module is pure
wiring: it decides what to pass into those existing pieces each cycle and
how to degrade gracefully when a piece isn't available.

AVAILABILITY SEMANTICS: a channel is "available" (indicator 1.0 for every
timestep of the window) unless the caller explicitly names it in
``unavailable_channels``. This runtime's own default -- every channel
available unless told otherwise -- reflects a true fact about the
simulation context it is built for (every fake sensor is always sampled
each tick), not a fabricated assumption. ``unavailable_channels`` is for a
channel that has been isolated / produced no reading at all this cycle,
distinct from a channel that IS being read but is merely low-confidence
(the latter is what ``trust`` already communicates via FR-M3's existing
trust-weighting in ``build_prognosis_input`` -- unchanged here).

TEMPERATURE AVAILABILITY -- CORRECTION from this module's first version.
Per D022/D024, only the five non-temperature channels have a model-input
availability COLUMN at all (temperature is the always-available
representation clock in the offline PRONOSTIA design this input scheme was
built for -- a dataset where temperature genuinely can never be "missing"
because its own sampling defines the timeline). The live/simulation
runtime has no such guarantee: a real or simulated temperature sensor can
be isolated like any other channel.

Investigated and rejected: widening ``PROGNOSIS_INPUT_WIDTH_D024`` from 11
to 12 to add a temperature availability column. Rejected because (a) it
would change a contract shared with the independent PRONOSTIA training
path (``edge/eval/pronostia_prognosis_input.py``,
``edge/models/lstm_prognosis.py``), which has no genuine temperature-
unavailable case to represent in the first place -- every existing
PRONOSTIA-trained network would then need retraining or padding purely to
satisfy a scenario that dataset cannot produce; and (b) the actual gap is
narrower than the whole input scheme: only ONE channel's absence has no
representation, not the general mechanism.

CHOSEN FIX (this module only -- ``edge/models/lstm_prognosis.py`` is
UNCHANGED, contract width stays 11): when the caller names ``"temperature"``
in ``unavailable_channels``, ``predict()`` builds a LOCAL COPY of ``trust``
with that channel's trust forced to ``0.0`` before calling the predictor --
using the one signal-suppression mechanism the existing 11-column
architecture actually offers for temperature specifically. This is an
explicit, documented compromise, NOT a claim that trust and availability
are the same signal in general (they are not -- see AVAILABILITY SEMANTICS
above, and ``edge/models/lstm_prognosis.py``'s own docstring). Every
``PrognosisResult`` produced this way carries a non-``None``
``temperature_availability_limitation`` explaining exactly this, so the
compromise is never silent to a downstream caller (RL, dashboard, or a
future test). The caller's own supplied ``trust["temperature"]`` value is
never mutated -- only the copy passed into this one prediction call is
forced.

GRACEFUL-DEGRADATION CONTRACT: this module never fabricates a health or
failure_eta value it has no basis for. With no predictor configured (e.g.
no checkpoint file exists yet), ``predict()`` returns a ``PrognosisResult``
with ``health=None``/``failure_eta=None`` and ``status=
"predictor_unavailable"`` -- never a crash, never a silently-invented
default class or ETA.

``model_status`` is always ``"diagnostic_unvalidated"`` here: nothing in
this repo has a mechanism to mark a prognosis model production-validated,
and this module makes no such claim regardless of which
``prognosis_data_source``/``health_label_source`` produced the injected
predictor's weights/labels. Real pump/bench validation remains a separate,
not-yet-done step for any model used through this wrapper.
"""

from __future__ import annotations

import os
from collections.abc import Collection, Mapping
from dataclasses import dataclass

from app.schemas.contracts import CHANNELS, HealthState

from edge.anomaly.preprocess import Window
from edge.models.lstm_prognosis import LSTMPrognosisPredictor
from edge.trust.beta import classify
from edge.trust.engine import TrustReading

EXECUTION_MODE = "simulation"
MODEL_STATUS = "diagnostic_unvalidated"

# The only two prognosis_data_source values this project currently
# distinguishes: edge/eval/pronostia_prognosis_training.py's real (if
# methodology-only-validated) PRONOSTIA/FEMTO path, and
# edge/eval/synthetic_prognosis_training.py's edge.models.degradation_
# generator-based path. Neither is claimed equivalent to the other, and
# neither is claimed hardware/field validated -- see module docstring.
PROGNOSIS_DATA_SOURCES: frozenset[str] = frozenset({"synthetic", "pronostia"})

# D022/D024: only these five channels have a model-input availability
# column (temperature is the always-available representation clock) --
# reusing CHANNELS[1:] directly rather than importing lstm_prognosis's
# underscore-prefixed internal constant.
_AVAILABILITY_INPUT_CHANNELS: tuple[str, ...] = CHANNELS[1:]

_TEMPERATURE_UNAVAILABLE_NOTE = (
    "temperature has no model-input availability column (D022/D024's "
    "11-column design uses temperature as the always-available "
    "representation clock, unchanged by this module); an isolated/"
    "unavailable temperature reading is represented here by forcing its "
    "trust to 0.0 before this cycle's prognosis input is built, since "
    "trust and availability are not otherwise interchangeable in this "
    "design -- see edge/pipeline/prognosis_runtime.py's module docstring "
    "for why this compromise was chosen over widening the input contract."
)


@dataclass(frozen=True)
class PrognosisResult:
    """One cycle's prognosis output (or honest non-output -- see module
    docstring's graceful-degradation contract).

    ``availability`` reports, per frozen ``CHANNELS`` entry, whether that
    channel was treated as available THIS cycle -- present even when
    ``status == "predictor_unavailable"``, so a caller always has the
    per-channel signal regardless of whether a prediction was produced.

    ``temperature_availability_limitation`` is ``None`` unless
    ``"temperature"`` was named unavailable this cycle, in which case it
    explains the trust-forcing compromise applied -- see module docstring.
    """

    health: HealthState | None
    failure_eta: float | None
    status: str  # "ok" | "predictor_unavailable"
    availability: Mapping[str, bool]
    prognosis_data_source: str
    execution_mode: str = EXECUTION_MODE
    model_status: str = MODEL_STATUS
    health_label_source: str | None = None
    temperature_availability_limitation: str | None = None


class PrognosisRuntime:
    """Per-device wrapper around an optional ``LSTMPrognosisPredictor``.

    ``predictor=None`` is a first-class, fully supported state (see
    ``from_checkpoint``) -- every ``predict()`` call then returns
    ``status="predictor_unavailable"`` rather than raising.

    ``health_label_source`` is optional metadata (default ``None`` =
    unspecified) describing where the injected predictor's CLASSIFICATION
    labels came from, if known -- e.g.
    ``edge.eval.synthetic_prognosis_training.HEALTH_LABEL_SOURCE``
    (``"synthetic_policy_fixture"``) for a predictor trained by that
    harness. This is independent of ``prognosis_data_source`` (which
    describes the TELEMETRY/degradation data source, not the label
    boundary policy) -- the two axes can differ or either can be
    unspecified.
    """

    def __init__(
        self,
        *,
        predictor: LSTMPrognosisPredictor | None,
        prognosis_data_source: str,
        health_label_source: str | None = None,
    ) -> None:
        if prognosis_data_source not in PROGNOSIS_DATA_SOURCES:
            raise ValueError(
                f"prognosis_data_source must be one of {sorted(PROGNOSIS_DATA_SOURCES)}, "
                f"got {prognosis_data_source!r}"
            )
        self._predictor = predictor
        self._prognosis_data_source = prognosis_data_source
        self._health_label_source = health_label_source

    @classmethod
    def from_checkpoint(
        cls,
        path: str,
        *,
        hidden_size: int,
        prognosis_data_source: str,
        health_label_source: str | None = None,
    ) -> PrognosisRuntime:
        """Attempt to load a trained checkpoint at ``path``. If the file
        does not exist, returns a runtime with no predictor (see the
        graceful-degradation contract in the module docstring) instead of
        raising -- this is the intended, supported way to run the
        simulation pathway before any checkpoint has been produced.

        ``hidden_size`` is REQUIRED -- mirrors
        ``LSTMPrognosisPredictor.from_checkpoint``'s own requirement (not
        inferable from the checkpoint alone).
        """
        if not os.path.exists(path):
            return cls(
                predictor=None,
                prognosis_data_source=prognosis_data_source,
                health_label_source=health_label_source,
            )
        predictor = LSTMPrognosisPredictor.from_checkpoint(path, hidden_size=hidden_size)
        return cls(
            predictor=predictor,
            prognosis_data_source=prognosis_data_source,
            health_label_source=health_label_source,
        )

    def predict(
        self,
        window: Window,
        trust: Mapping[str, TrustReading],
        *,
        unavailable_channels: Collection[str] = (),
    ) -> PrognosisResult:
        """Produce (or honestly decline to produce) this cycle's prognosis
        output for ``window``.

        ``unavailable_channels`` names channels with no reading at all this
        cycle (e.g. isolated by P2/FR-RL4) -- distinct from ``trust``'s
        existing low-confidence weighting (FR-M3, unchanged). Naming
        ``"temperature"`` here triggers the trust-forcing compromise
        described in the module docstring's TEMPERATURE AVAILABILITY
        section (the result's ``temperature_availability_limitation``
        explains it); every other named channel gets a real model-input
        availability column, unaffected by this special case.

        Raises:
            ValueError: if ``unavailable_channels`` names anything outside
                the frozen ``CHANNELS``.
        """
        unknown = sorted(set(unavailable_channels) - set(CHANNELS))
        if unknown:
            raise ValueError(
                f"unavailable_channels contains unknown channel(s) {unknown}; "
                f"must be one of {CHANNELS}"
            )

        availability_report = {ch: ch not in unavailable_channels for ch in CHANNELS}
        temperature_note = (
            _TEMPERATURE_UNAVAILABLE_NOTE if "temperature" in unavailable_channels else None
        )

        if self._predictor is None:
            return PrognosisResult(
                health=None,
                failure_eta=None,
                status="predictor_unavailable",
                availability=availability_report,
                prognosis_data_source=self._prognosis_data_source,
                health_label_source=self._health_label_source,
                temperature_availability_limitation=temperature_note,
            )

        effective_trust = trust
        if temperature_note is not None and "temperature" in trust:
            forced = dict(trust)
            forced["temperature"] = TrustReading(
                channel="temperature", g=trust["temperature"].g, trust=0.0, band=classify(0.0)
            )
            effective_trust = forced

        model_availability = {
            ch: tuple(0.0 if ch in unavailable_channels else 1.0 for _ in range(window.size))
            for ch in _AVAILABILITY_INPUT_CHANNELS
        }
        health, failure_eta = self._predictor.predict(window, effective_trust, model_availability)
        return PrognosisResult(
            health=health,
            failure_eta=failure_eta,
            status="ok",
            availability=availability_report,
            prognosis_data_source=self._prognosis_data_source,
            health_label_source=self._health_label_source,
            temperature_availability_limitation=temperature_note,
        )
