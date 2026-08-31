"""PRONOSTIA prognosis target generation (P3 · D025/D026). TARGETS ONLY.

Computes per-timestep RUL (``failure_eta``, seconds) and HealthState
training targets for one already-loaded ``PronostiaRunSequence``, exactly
per D025's methodology and D026's numeric proportions -- no
reinterpretation, no additional thresholds, no signal-derived logic.

Deliberately separate from:
  - ``edge/eval/pronostia_prep.py`` (raw-data parsing boundary -- unmodified,
    not imported here beyond its ``PronostiaRunSequence`` type).
  - ``edge/eval/pronostia_prognosis_input.py`` (input-tensor glue -- this
    module produces training *targets*, not model *inputs*; the two are
    independent and neither imports the other).
  - ``edge/models/lstm_prognosis.py`` (model definition -- untouched; this
    module does not import it and does not affect ``build_prognosis_input``
    or the 11-column input representation in any way).

D025 (exactly, restated for traceability):
  - Prognosis targets are generated ONLY for the 4 usable training-split
    bearings named in ``TRAINING_BEARINGS_D025`` below. This module
    validates a sequence's own ``bearing_id`` against that exact set
    (rather than trusting the caller-supplied ``split`` label alone, which
    ``pronostia_prep.py`` never independently verifies) before computing
    anything -- test-split bearings and any other bearing_id are refused,
    not silently processed.
  - ``RUL(t) = final_recorded_timestep_of_that_bearing - t``, in seconds
    (numerically identical to 1Hz timesteps here, per D022's gapless
    representation -- no alternative scale is invented from timestamps).
  - The final recorded timestep has ``RUL = 0``.
  - No cross-bearing/global normalization: every quantity here is computed
    from the single supplied sequence's own length only.

D026 (exactly, restated for traceability): Healthy if
``RUL / lifetime > 0.20``; Warning if ``0.05 < RUL / lifetime <= 0.20``;
Critical if ``RUL / lifetime <= 0.05``. Both proportions are explicit
modeling-policy values -- NOT empirically derived, NOT PRONOSTIA ground
truth. HealthState labels produced here are constructed modeling labels,
exactly as D025/D026 require -- never PRONOSTIA-provided annotations, never
a physical ground-truth claim.

Does NOT implement: windowing, stride/sampling, training-example
construction, model training, loss/optimizer/hyperparameters, or any
pipeline/cycle/self-heal integration. Does NOT use ``Validation_Set``/
``Full_Test_Set`` or any test-split bearing.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.schemas.contracts import HealthState

from edge.eval.pronostia_prep import PronostiaRunSequence

# D025: prognosis targets are generated ONLY for these 4 usable training
# bearings. Checked against a sequence's own bearing_id (its real identity),
# not against the caller-supplied `split` label, which pronostia_prep.py
# never independently verifies against bearing_id -- see load_bearing_run's
# own docstring.
TRAINING_BEARINGS_D025 = frozenset({"Bearing1_1", "Bearing1_2", "Bearing2_1", "Bearing3_1"})

# D026: explicit modeling-policy proportions -- NOT empirically derived,
# NOT PRONOSTIA ground truth. See DECISIONS.md D026 for the full rationale.
WARNING_PROPORTION_D026 = 0.20
CRITICAL_PROPORTION_D026 = 0.05


@dataclass(frozen=True)
class PronostiaPrognosisTargets:
    """Per-timestep RUL (``failure_eta``, seconds) and HealthState targets
    for one D025-authorized training bearing. Same length as the source
    ``PronostiaRunSequence``'s own sequence fields.
    """

    rul_seconds: tuple[float, ...]
    health_state: tuple[HealthState, ...]

    def __post_init__(self) -> None:
        if len(self.rul_seconds) != len(self.health_state):
            raise ValueError("rul_seconds/health_state length mismatch")


def _classify_health_state(rul_fraction: float) -> HealthState:
    """D026, exact boundary inclusivity: Healthy if ``fraction > 0.20``;
    Warning if ``0.05 < fraction <= 0.20``; Critical if ``fraction <= 0.05``.
    """
    if rul_fraction > WARNING_PROPORTION_D026:
        return HealthState.healthy
    if rul_fraction > CRITICAL_PROPORTION_D026:
        return HealthState.warning
    return HealthState.critical


def compute_prognosis_targets(seq: PronostiaRunSequence) -> PronostiaPrognosisTargets:
    """Compute D025/D026 RUL + HealthState targets for one training
    bearing's already-loaded ``PronostiaRunSequence``.

    For a sequence of N timesteps: ``rul_seconds[0] == N - 1``,
    ``rul_seconds[-1] == 0.0``, decreasing by exactly 1.0 per timestep.
    HealthState is derived from ``rul_seconds[t] / (N - 1)`` (that
    bearing's own lifetime proportion) -- never normalized across bearings.

    Raises:
        ValueError: if ``seq.bearing_id`` is not one of the 4
            D025-authorized training bearings, or if the sequence is
            empty (N=0, which cannot be represented meaningfully).
    """
    if seq.bearing_id not in TRAINING_BEARINGS_D025:
        raise ValueError(
            "prognosis targets may only be generated for D025's 4 usable "
            f"training bearings {sorted(TRAINING_BEARINGS_D025)}, got "
            f"{seq.bearing_id!r}"
        )

    n = len(seq.temperature)
    if n == 0:
        raise ValueError("cannot compute prognosis targets for an empty sequence (N=0)")

    total_lifetime = n - 1  # seconds; D025: RUL(t) = final_timestep - t
    rul_seconds = tuple(float(total_lifetime - t) for t in range(n))

    if n == 1:
        # total_lifetime == 0 -- RUL[0] == 0 trivially, and RUL/lifetime
        # would be an undefined 0/0. RUL == 0 unambiguously satisfies
        # D026's Critical rule (RUL <= 5% of lifetime) under any reading,
        # so Critical is assigned directly without computing a fraction.
        health_state: tuple[HealthState, ...] = (HealthState.critical,)
    else:
        health_state = tuple(_classify_health_state(rul / total_lifetime) for rul in rul_seconds)

    return PronostiaPrognosisTargets(rul_seconds=rul_seconds, health_state=health_state)
