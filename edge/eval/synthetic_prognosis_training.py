"""Synthetic-degradation LSTM prognosis training harness (hardware-free,
DIAGNOSTIC ONLY -- simulation-first prognosis pathway).

prognosis_data_source=synthetic · health_label_source=synthetic_policy_fixture
model_status=diagnostic_unvalidated · execution_mode=simulation

Same status as ``edge/eval/twin_training.py`` and
``edge/eval/pronostia_prognosis_training.py``: not on pytest ``testpaths``'
production path, not wired into any acceptance criterion, not part of
``edge/pipeline/cycle.py`` or any P2/P3 production wiring.

Uses ``edge.models.degradation_generator.SyntheticDegradationGenerator``
instead of the real PRONOSTIA/FEMTO dataset --
``edge/eval/pronostia_prognosis_training.py`` is the separate, independent
harness for that real (methodology-only-validated, D021) dataset. Neither
module imports the other, and output trained here is never claimed
equivalent to, or a substitute for, PRONOSTIA-derived training -- see
``edge/pipeline/prognosis_runtime.py``'s ``prognosis_data_source``
distinction.

WINDOWING CONVENTION -- deliberately DIFFERENT from
``pronostia_prognosis_training.py``: that harness slices raw, un-normalized
PRONOSTIA values from one whole-sequence tensor, then applies its own
training-fold z-score normalization (needed because PRONOSTIA input bypasses
``edge.anomaly.preprocess.Preprocessor`` entirely). This module instead
builds windows via the SAME ``Preprocessor.process()`` sliding-window
convention ``edge.pipeline.monitor.LiveP2Monitor`` already uses for live
telemetry (identity filters, existing ``window_size``/``step``) --
``PrognosisRuntime`` (this project's live/simulation prognosis wrapper)
will always receive ``Preprocessor``-built, already-normalized ``Window``s
from the live pipeline, never a raw PRONOSTIA-style sequence, so training
data here is built the same way for consistency with actual runtime input.

HEALTHSTATE CLASSIFICATION LABELS -- a SEPARATE policy from D026, not a
reuse of it: mapping this generator's continuous ``health`` ground truth
(``[0, 1]``) to a HealthState class requires a boundary choice, and
``pronostia_prognosis_training.py``'s D026 boundary (20%/5%) is an explicit,
PRONOSTIA-specific modeling-policy decision -- reusing it here for an
unrelated synthetic curve would misrepresent it as validated for this
context. ``SYNTHETIC_HEALTH_WARNING_THRESHOLD``/``SYNTHETIC_HEALTH_
CRITICAL_THRESHOLD`` below are therefore named, documented, and valued
DIFFERENTLY from D026's 0.20/0.05 on purpose -- not merely relabeled -- so
the two can never be visually or numerically conflated by a future reader.
Like D020's ``UNCERTAINTY_CAP_D020``, these are canonical, importable
fixture values; the functions that consume them (``classify_synthetic_
health``, ``make_training_examples``) still require them as explicit,
caller-supplied arguments with no default baked into the function itself,
so nothing here can silently apply a boundary the caller didn't choose.
``health_label_source="synthetic_policy_fixture"`` names this distinct
label origin wherever it needs to be reported (e.g.
``edge.pipeline.prognosis_runtime.PrognosisRuntime``'s optional
constructor argument of the same name).

BOTH HEADS ARE NOW TRAINED (correction from this harness's first version,
which trained the regression head only and left classification
untrained/uncalibrated by design). ``train()`` now applies a combined
CrossEntropy (classification) + MSE (regression) loss, mirroring
``pronostia_prognosis_training.train()``'s own combined-loss structure
without reusing its D026-derived class targets or bearing-specific
semantics -- see module docstring above and ``train()``'s own docstring.
"""

from __future__ import annotations

from collections.abc import Mapping

import torch
from app.schemas.contracts import CHANNELS, HealthState

from edge.anomaly.preprocess import Preprocessor
from edge.models.degradation_generator import SyntheticDegradationGenerator
from edge.models.lstm_prognosis import _HEALTH_STATE_ORDER, _LSTMPrognosisNet, build_prognosis_input
from edge.trust.engine import TrustReading

PROGNOSIS_DATA_SOURCE = "synthetic"
HEALTH_LABEL_SOURCE = "synthetic_policy_fixture"

# Deliberately DIFFERENT from D026's 0.20/0.05 (PRONOSTIA-specific policy) --
# see module docstring's HEALTHSTATE CLASSIFICATION LABELS section. Not
# empirically derived; not a final research value; a simulation-only
# fixture, importable so callers/tests share one canonical copy.
SYNTHETIC_HEALTH_WARNING_THRESHOLD = 0.25
SYNTHETIC_HEALTH_CRITICAL_THRESHOLD = 0.10

# Multi-task loss weight for the regression term (mirrors pronostia_
# prognosis_training.py's own LAMBDA, restated independently -- see module
# docstring on why the two harnesses stay separate). A simulation/training
# convenience, not a project specification.
REGRESSION_LOSS_WEIGHT_FIXTURE = 1.0


def classify_synthetic_health(
    health_fraction: float, *, warning_threshold: float, critical_threshold: float
) -> HealthState:
    """Map a continuous synthetic ``health`` value to a ``HealthState``
    training label, using CALLER-SUPPLIED boundaries -- never a baked-in
    default (see module docstring). Mirrors D026's inequality structure
    (Healthy if ``> warning_threshold``; Warning if
    ``critical_threshold < x <= warning_threshold``; Critical otherwise)
    without reusing its numeric values.

    Raises:
        ValueError: if the thresholds do not satisfy
            ``0.0 <= critical_threshold < warning_threshold <= 1.0``.
    """
    if not (0.0 <= critical_threshold < warning_threshold <= 1.0):
        raise ValueError(
            "thresholds must satisfy 0.0 <= critical_threshold < warning_threshold <= 1.0, "
            f"got warning_threshold={warning_threshold}, critical_threshold={critical_threshold}"
        )
    if health_fraction > warning_threshold:
        return HealthState.healthy
    if health_fraction > critical_threshold:
        return HealthState.warning
    return HealthState.critical


class SyntheticWindowExample:
    """One sliding-window training example: an 11-column prognosis input
    tensor plus the ground-truth ``health_fraction`` (``[0, 1]``, from
    ``edge.models.degradation_generator``) and its derived ``health_state``
    label, both AT THE WINDOW'S FINAL TIMESTEP -- the only interpretation
    compatible with ``_LSTMPrognosisNet``'s final-hidden-state forward path
    (same convention as ``pronostia_prognosis_training.WindowExample``,
    restated independently here rather than imported -- see module
    docstring on why the two harnesses stay separate)."""

    __slots__ = ("input_tensor", "health_fraction", "health_state")

    def __init__(
        self, input_tensor: torch.Tensor, health_fraction: float, health_state: HealthState
    ) -> None:
        self.input_tensor = input_tensor
        self.health_fraction = health_fraction
        self.health_state = health_state


def make_training_examples(
    generator: SyntheticDegradationGenerator,
    timestamps: list[str],
    preprocessor: Preprocessor,
    trust: Mapping[str, TrustReading],
    *,
    warning_threshold: float,
    critical_threshold: float,
) -> list[SyntheticWindowExample]:
    """Generate one synthetic degradation trajectory and slice it into
    sliding-window training examples via the existing, unmodified
    ``Preprocessor.process()`` -- no new windowing logic, no injections, no
    modification to ``generator``/``preprocessor``.

    Every channel is treated as available for the whole trajectory (the
    generator always produces a full reading every tick) -- this mirrors
    ``PrognosisRuntime``'s own default for a fully-observed simulation
    cycle (``edge/pipeline/prognosis_runtime.py``).

    ``warning_threshold``/``critical_threshold`` are REQUIRED -- no
    default, per module docstring (typically
    ``SYNTHETIC_HEALTH_WARNING_THRESHOLD``/``SYNTHETIC_HEALTH_CRITICAL_
    THRESHOLD``, but never silently assumed).
    """
    trajectory = generator.generate(timestamps)
    windows = preprocessor.process(list(trajectory.frames))

    examples: list[SyntheticWindowExample] = []
    for k, window in enumerate(windows):
        final_tick = k * preprocessor.step + window.size - 1
        availability = {ch: (1.0,) * window.size for ch in CHANNELS[1:]}
        input_tensor = build_prognosis_input(window, trust, availability)
        health_fraction = trajectory.health[final_tick]
        health_state = classify_synthetic_health(
            health_fraction,
            warning_threshold=warning_threshold,
            critical_threshold=critical_threshold,
        )
        examples.append(
            SyntheticWindowExample(
                input_tensor=input_tensor,
                health_fraction=health_fraction,
                health_state=health_state,
            )
        )
    return examples


def _health_state_index(health_state: HealthState) -> int:
    """Index into the model's own fixed health-class ordering -- reused,
    never redefined, so training targets and inference-time argmax always
    agree on class order (same discipline as
    ``pronostia_prognosis_training._health_state_index``)."""
    return _HEALTH_STATE_ORDER.index(health_state)


def train(
    network: _LSTMPrognosisNet,
    examples: list[SyntheticWindowExample],
    *,
    epochs: int,
    optimizer: torch.optim.Optimizer,
    regression_loss_weight: float = REGRESSION_LOSS_WEIGHT_FIXTURE,
) -> list[float]:
    """Run ``epochs`` passes of combined CrossEntropy (classification) + MSE
    (regression) training over ``examples`` -- BOTH heads are trained (see
    module docstring's correction note). ``epochs``/``optimizer`` are
    REQUIRED, mirroring ``twin_training.train``'s own convention;
    ``optimizer`` must already be bound to ``network.parameters()``.

    Hardware-free plumbing verification ONLY: proves the forward/backward
    pass runs for both heads, loss is finite, and weights update on
    synthetic data. Does NOT establish, and must never be read as
    establishing, meaningful prognosis accuracy or real-world validation --
    ``examples``' ``health_state`` labels come from
    ``SYNTHETIC_HEALTH_WARNING_THRESHOLD``/``SYNTHETIC_HEALTH_CRITICAL_
    THRESHOLD``, explicit simulation policy fixtures, never validated
    boundaries.

    Raises:
        ValueError: if ``epochs < 1`` or ``examples`` is empty.
    """
    if epochs < 1:
        raise ValueError(f"epochs must be >= 1, got {epochs}")
    if not examples:
        raise ValueError("cannot train on an empty example list")

    loss_history: list[float] = []
    for _ in range(epochs):
        network.train()
        epoch_loss = 0.0
        for example in examples:
            optimizer.zero_grad()
            health_logits, eta = network(example.input_tensor)
            class_target = torch.tensor([_health_state_index(example.health_state)])
            reg_target = torch.tensor([[example.health_fraction]], dtype=torch.float32)
            class_loss = torch.nn.functional.cross_entropy(health_logits, class_target)
            reg_loss = torch.nn.functional.mse_loss(eta, reg_target)
            loss = class_loss + regression_loss_weight * reg_loss
            loss.backward()
            optimizer.step()
            epoch_loss += loss.item()
        loss_history.append(epoch_loss / len(examples))
    network.eval()
    return loss_history


def main() -> None:
    """Diagnostic entry point: ``python -m edge.eval.synthetic_prognosis_training``.
    Trains a tiny LSTM prognosis network (both heads) on one synthetic
    degradation trajectory and prints a loss-curve summary. NOT an accuracy
    claim -- see ``train()``'s docstring."""
    from edge.models.degradation_generator import ChannelDegradationConfig
    from edge.trust.beta import classify

    # ---- DIAGNOSTIC FIXTURES ONLY (arbitrary, NOT project specs) ----------
    LENGTH_FIXTURE = 100
    HIDDEN_SIZE_FIXTURE = 4
    EPOCHS_FIXTURE = 2
    LEARNING_RATE_FIXTURE = 0.01
    SEED_FIXTURE = 1337

    generator = SyntheticDegradationGenerator(
        length=LENGTH_FIXTURE,
        start_health=1.0,
        end_health=0.0,
        seed=SEED_FIXTURE,
        channels={
            "vibration": ChannelDegradationConfig(healthy_value=0.03, degraded_value=1.2),
            "temperature": ChannelDegradationConfig(healthy_value=26.0, degraded_value=60.0),
        },
    )
    timestamps = [f"2026-08-10T00:{i // 60:02d}:{i % 60:02d}.000Z" for i in range(LENGTH_FIXTURE)]
    preprocessor = Preprocessor(median_kernel=1, low_pass_alpha=1.0, window_size=30, step=1)
    trust = {ch: TrustReading(channel=ch, g=1.0, trust=1.0, band=classify(1.0)) for ch in CHANNELS}

    examples = make_training_examples(
        generator,
        timestamps,
        preprocessor,
        trust,
        warning_threshold=SYNTHETIC_HEALTH_WARNING_THRESHOLD,
        critical_threshold=SYNTHETIC_HEALTH_CRITICAL_THRESHOLD,
    )

    network = _LSTMPrognosisNet(hidden_size=HIDDEN_SIZE_FIXTURE)
    # ADAM_OPTIMIZER_FIXTURE: a diagnostic choice for this harness's own
    # smoke-training run only -- NOT an approved project optimizer spec.
    ADAM_OPTIMIZER_FIXTURE = torch.optim.Adam(network.parameters(), lr=LEARNING_RATE_FIXTURE)

    loss_history = train(network, examples, epochs=EPOCHS_FIXTURE, optimizer=ADAM_OPTIMIZER_FIXTURE)

    print("=== Synthetic-degradation LSTM prognosis training harness (diagnostic) ===")
    print(f"{len(examples)} sliding-window training examples from one synthetic trajectory")
    print(f"loss[0]={loss_history[0]:.6f}  loss[-1]={loss_history[-1]:.6f}")
    print(
        "NOTE: this only proves the training/inference PLUMBING works "
        "(forward/backward pass, loss computation, weight updates) on "
        "SYNTHETIC data (prognosis_data_source=synthetic, health_label_"
        "source=synthetic_policy_fixture). Both heads were trained, but "
        "this establishes NO meaningful prognosis accuracy or real-world "
        "validation (model_status=diagnostic_unvalidated)."
    )


if __name__ == "__main__":
    main()
