"""PRONOSTIA LSTM prognosis training harness (P3 · D021-D026). TRAINING
METHODOLOGY IMPLEMENTATION ONLY.

Implements the sliding-window training-example structure, leave-one-
bearing-out (LOBO) cross-validation, multi-task loss, and evaluation
metrics investigated and settled (this session, read-only) for FR-M1/M2
prognosis training. Builds strictly on the already-committed layers:
``pronostia_prep.py`` (raw-data loading), ``pronostia_prognosis_input.py``
(11-column input tensor), ``pronostia_prognosis_targets.py`` (D025/D026
RUL + HealthState targets), and ``lstm_prognosis.py`` (frozen
architecture). No tensor-construction or target-generation logic is
duplicated here -- both are delegated to their existing modules.

Same status as ``edge/eval/twin_training.py`` and its siblings: not on
pytest ``testpaths``' production path, not wired into any acceptance
criterion, not part of ``edge/pipeline/cycle.py`` or any P2/P3 production
wiring. The real ~1.1GB downloaded PRONOSTIA dataset is never committed to
this repo; this module's own tests use small synthetic
``PronostiaRunSequence`` fixtures only. Running this harness against the
real dataset requires the caller to load bearings via
``pronostia_prep.load_bearing_run`` themselves and supply the resulting
sequences here -- not performed by this module or its tests.

TRAINING-EXAMPLE STRUCTURE (settled this session, not a DECISIONS.md
entry -- see rationale below):
  - One training example = one fixed-length sliding window of
    ``WINDOW_SIZE`` consecutive timesteps from a single bearing's
    ``PronostiaRunSequence``.
  - The target for a window ``[t, ..., t+WINDOW_SIZE-1]`` is the
    RUL/HealthState AT THE WINDOW'S FINAL TIMESTEP (``t+WINDOW_SIZE-1``)
    -- the only interpretation compatible with ``_LSTMPrognosisNet``'s
    existing forward path, which derives both heads from the LSTM's
    final hidden state (the state after observing the entire window).
    This model therefore answers "given this window of history, what is
    the health/RUL right now (at the end of it)", never a future
    prediction beyond the window nor a reconstruction of its start.
  - Full-bearing-sequence training (one example per bearing) was
    evaluated and rejected: ``_LSTMPrognosisNet`` produces exactly one
    prediction per input sequence, so an ungapped ~28,000-timestep
    sequence would need to be paired with exactly one of its ~28,000
    per-timestep targets -- an unresolved mismatch -- and backpropagation
    through a sequence that long risks vanishing/exploding LSTM
    gradients. Sliding windows resolve both problems without any
    architecture change.

WHY THE CONFIGURATION CONSTANTS BELOW ARE NOT A DECISIONS.md ENTRY: each
one (window size, stride, loss functions, optimizer interface, batch
size, multi-task weighting) is an implementation/hyperparameter-level
choice resolvable by direct repository precedent (``WINDOW_SIZE`` matches
``edge/anomaly/preprocess.py``'s documented ``window_size=30`` default;
MSE matches ``twin_training.py``'s regression-loss precedent) or standard
ML practice, not an irreversible policy call comparable to D021-D026 (which
concern dataset scope, target semantics, and numeric HealthState
boundaries). None of these values is empirically tuned against PRONOSTIA
data by this module -- see the session's own read-only investigations for
the full comparative reasoning. Like ``twin_training.py``'s own fixtures,
these are open to revision without a decision-record change if training
behavior warrants it.

LEAKAGE DISCIPLINE (D025, applied to training itself): the only supported
orchestration entry point, ``run_leave_one_bearing_out``, refuses any
``sequences`` mapping containing a bearing_id outside
``TRAINING_BEARINGS_D025`` -- structurally impossible to pass a test-split
or ``Validation_Set``/``Full_Test_Set`` bearing through this module. Each
LOBO fold trains on 3 bearings' windows and validates on the 4th's, with
zero sample-level overlap (different physical bearings) and a freshly
initialized network per fold (no cross-fold weight leakage).

Nothing here claims trained accuracy: any loss/metric value produced by
running this module's own tests (tiny synthetic fixtures, one or two
epochs) is plumbing verification only, exactly as ``twin_training.py``
already documents for the digital twin.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass

import torch
from app.schemas.contracts import HealthState

from edge.eval.pronostia_prep import PronostiaRunSequence
from edge.eval.pronostia_prognosis_input import pronostia_sequence_to_prognosis_input
from edge.eval.pronostia_prognosis_targets import TRAINING_BEARINGS_D025, compute_prognosis_targets
from edge.models.lstm_prognosis import _HEALTH_STATE_ORDER, _LSTMPrognosisNet
from edge.trust.engine import TrustReading

# ---- Harness configuration (see module docstring: not a DECISIONS.md entry) ----
WINDOW_SIZE = 30  # matches edge/anomaly/preprocess.py's documented default
STRIDE = 1  # full overlap; standard sliding-window practice
LAMBDA = 1.0  # multi-task weight; justified by RUL's internal [0,1] normalization below


@dataclass(frozen=True)
class WindowExample:
    """One sliding-window training example. ``input_tensor`` is
    ``(1, window_size, 11)`` (D022/D024). ``rul_seconds``/``health_state``
    are the D025/D026 targets AT THE WINDOW'S FINAL TIMESTEP only --
    never an aggregate over the window. ``bearing_lifetime`` (that
    bearing's own ``N-1``, D025) is carried per-example so RUL can be
    normalized to a per-bearing [0,1] fraction at training/evaluation
    time without any cross-bearing/global statistic (D025's leakage
    discipline)."""

    input_tensor: torch.Tensor
    health_state: HealthState
    rul_seconds: float
    bearing_lifetime: float


def make_window_examples(
    seq: PronostiaRunSequence,
    trust: Mapping[str, TrustReading],
    *,
    window_size: int = WINDOW_SIZE,
    stride: int = STRIDE,
) -> list[WindowExample]:
    """Slice one bearing's full sequence into ``WindowExample``s.

    Delegates entirely to existing modules: the full-sequence input
    tensor comes from ``pronostia_sequence_to_prognosis_input`` (D022/
    D024, unmodified), and the full-sequence per-timestep targets come
    from ``compute_prognosis_targets`` (D025/D026, unmodified) -- which
    also enforces ``seq.bearing_id`` is one of the 4 D025 training
    bearings, raising ``ValueError`` otherwise. This function performs
    no target computation or tensor construction of its own; it only
    slices both by matching final-timestep index.

    Returns an empty list if the sequence is shorter than ``window_size``
    (no full window fits) -- not an error, since a too-short bearing
    contributes no examples rather than a fabricated partial one.

    Raises:
        ValueError: if ``window_size`` or ``stride`` is not >= 1; anything
            ``compute_prognosis_targets``/``pronostia_sequence_to_prognosis_input``
            themselves raise (bearing_id not D025-authorized, missing
            trust entries, empty sequence).
    """
    if window_size < 1:
        raise ValueError(f"window_size must be >= 1, got {window_size}")
    if stride < 1:
        raise ValueError(f"stride must be >= 1, got {stride}")

    full_input = pronostia_sequence_to_prognosis_input(seq, trust)  # (1, N, 11)
    targets = compute_prognosis_targets(seq)  # validates seq.bearing_id itself

    n = len(seq.temperature)
    bearing_lifetime = float(n - 1)  # D025's own total_lifetime; 0.0 only when n==1

    examples: list[WindowExample] = []
    start = 0
    while start + window_size <= n:
        end = start + window_size
        target_index = end - 1  # window's FINAL timestep -- see module docstring
        examples.append(
            WindowExample(
                input_tensor=full_input[:, start:end, :],
                health_state=targets.health_state[target_index],
                rul_seconds=targets.rul_seconds[target_index],
                bearing_lifetime=bearing_lifetime,
            )
        )
        start += stride
    return examples


def _health_state_index(health_state: HealthState) -> int:
    """Index into the model's own fixed health-class ordering
    (``_HEALTH_STATE_ORDER``) -- reused, never redefined, so training
    targets and inference-time argmax always agree on class order."""
    return _HEALTH_STATE_ORDER.index(health_state)


def _rul_fraction(rul_seconds: float, bearing_lifetime: float) -> float:
    """Per-bearing RUL fraction (D025 leakage discipline: uses ONLY that
    example's own bearing_lifetime, never a cross-bearing statistic).
    ``bearing_lifetime == 0`` only occurs for a 1-timestep bearing (D025's
    own N=1 special case, RUL=0 trivially); defined as 0.0 rather than
    raising, matching ``compute_prognosis_targets``' own N=1 treatment."""
    if bearing_lifetime == 0:
        return 0.0
    return rul_seconds / bearing_lifetime


def _stack_batch(
    batch: list[WindowExample],
) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
    inputs = torch.cat([ex.input_tensor for ex in batch], dim=0)  # (B, window_size, 11)
    class_targets = torch.tensor([_health_state_index(ex.health_state) for ex in batch])
    reg_targets = torch.tensor(
        [[_rul_fraction(ex.rul_seconds, ex.bearing_lifetime)] for ex in batch], dtype=torch.float32
    )
    return inputs, class_targets, reg_targets


def _batches(examples: list[WindowExample], batch_size: int) -> Iterator[list[WindowExample]]:
    for i in range(0, len(examples), batch_size):
        yield examples[i : i + batch_size]


def train(
    network: _LSTMPrognosisNet,
    examples: list[WindowExample],
    *,
    epochs: int,
    optimizer: torch.optim.Optimizer,
    batch_size: int,
) -> list[float]:
    """Run ``epochs`` passes of combined-loss training over ``examples``,
    in minibatches of ``batch_size``. ``epochs``, ``optimizer``, and
    ``batch_size`` are all REQUIRED -- no default, mirroring
    ``twin_training.py``'s own convention; ``optimizer`` must already be
    constructed and bound to ``network.parameters()`` by the caller, and
    this function chooses no optimizer of its own.

    Loss per batch: ``CrossEntropyLoss(health_logits, class_targets) +
    LAMBDA * MSELoss(eta, rul_fraction_targets)`` -- classification on
    the raw HealthState index, regression on the per-bearing-normalized
    RUL fraction (see ``_rul_fraction``), never on raw seconds directly
    (D025's ~17x cross-bearing lifetime variation would otherwise let
    long-life bearings dominate the regression loss).

    Returns the per-epoch mean combined loss. Leaves ``network`` in
    ``eval()`` mode on return (safe to pass directly to ``evaluate``).

    Hardware-free plumbing verification ONLY when run on this module's
    own tiny synthetic tests: proves the forward/backward pass runs,
    loss is finite, and weights update -- establishes no trained
    accuracy or real-world validation claim whatsoever.
    """
    if epochs < 1:
        raise ValueError(f"epochs must be >= 1, got {epochs}")
    if batch_size < 1:
        raise ValueError(f"batch_size must be >= 1, got {batch_size}")
    if not examples:
        raise ValueError("cannot train on an empty example list")

    loss_history: list[float] = []
    for _ in range(epochs):
        network.train()
        epoch_loss = 0.0
        n_batches = 0
        for batch in _batches(examples, batch_size):
            optimizer.zero_grad()
            inputs, class_targets, reg_targets = _stack_batch(batch)
            health_logits, eta = network(inputs)
            class_loss = torch.nn.functional.cross_entropy(health_logits, class_targets)
            reg_loss = torch.nn.functional.mse_loss(eta, reg_targets)
            loss = class_loss + LAMBDA * reg_loss
            loss.backward()
            optimizer.step()
            epoch_loss += loss.item()
            n_batches += 1
        loss_history.append(epoch_loss / n_batches)
    network.eval()
    return loss_history


@dataclass(frozen=True)
class EvaluationMetrics:
    """HealthState + failure_eta metrics on one example set (one LOBO
    fold's held-out bearing, typically). HealthState and RUL are reported
    separately (see the session's own metrics investigation: no single
    aggregate score is justified for two heads measuring different
    things). ``confusion_matrix`` keys are ``(true_label, predicted_label)``
    string pairs; every ``(true, pred)`` combination is present (0 if
    unobserved), so the matrix always sums to ``n_examples``."""

    n_examples: int
    accuracy: float
    macro_f1: float
    per_class_recall: dict[str, float]
    per_class_precision: dict[str, float]
    confusion_matrix: dict[tuple[str, str], int]
    rmse_seconds: float
    mae_seconds: float
    mape_percent: float  # NaN if every example has rul_seconds == 0 (undefined)
    bias_seconds: float  # mean(predicted - true); positive = systematic over-prediction


def evaluate(network: _LSTMPrognosisNet, examples: list[WindowExample]) -> EvaluationMetrics:
    """Compute HealthState classification metrics and failure_eta
    regression metrics (in seconds) on ``examples``. No gradient tracking;
    puts ``network`` in ``eval()`` mode. RUL predictions (trained on the
    normalized fraction, see ``train``) are converted back to seconds
    per-example using that example's own ``bearing_lifetime`` -- never a
    shared/global scale -- before computing RMSE/MAE/MAPE/bias, so the
    reported error is directly interpretable against the wire contract's
    seconds unit.

    Raises:
        ValueError: if ``examples`` is empty.
    """
    if not examples:
        raise ValueError("cannot evaluate an empty example list")

    network.eval()
    true_classes: list[str] = []
    pred_classes: list[str] = []
    true_rul: list[float] = []
    pred_rul: list[float] = []
    with torch.no_grad():
        for example in examples:
            health_logits, eta = network(example.input_tensor)
            pred_index = int(torch.argmax(health_logits[0]).item())
            pred_classes.append(_HEALTH_STATE_ORDER[pred_index].value)
            true_classes.append(example.health_state.value)
            pred_rul.append(float(eta.item()) * example.bearing_lifetime)
            true_rul.append(example.rul_seconds)

    labels = [hs.value for hs in _HEALTH_STATE_ORDER]
    confusion: dict[tuple[str, str], int] = {(t, p): 0 for t in labels for p in labels}
    for t, p in zip(true_classes, pred_classes, strict=True):
        confusion[(t, p)] += 1

    n = len(examples)
    correct = sum(1 for t, p in zip(true_classes, pred_classes, strict=True) if t == p)
    accuracy = correct / n

    per_class_recall: dict[str, float] = {}
    per_class_precision: dict[str, float] = {}
    f1_scores: list[float] = []
    for label in labels:
        tp = confusion[(label, label)]
        fn = sum(confusion[(label, p)] for p in labels if p != label)
        fp = sum(confusion[(t, label)] for t in labels if t != label)
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        per_class_recall[label] = recall
        per_class_precision[label] = precision
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
        f1_scores.append(f1)
    macro_f1 = sum(f1_scores) / len(f1_scores)

    errors = [p - t for p, t in zip(pred_rul, true_rul, strict=True)]
    rmse = (sum(e**2 for e in errors) / n) ** 0.5
    mae = sum(abs(e) for e in errors) / n
    bias = sum(errors) / n
    pct_errors = [abs(e) / t for e, t in zip(errors, true_rul, strict=True) if t != 0]
    mape = (sum(pct_errors) / len(pct_errors) * 100) if pct_errors else float("nan")

    return EvaluationMetrics(
        n_examples=n,
        accuracy=accuracy,
        macro_f1=macro_f1,
        per_class_recall=per_class_recall,
        per_class_precision=per_class_precision,
        confusion_matrix=confusion,
        rmse_seconds=rmse,
        mae_seconds=mae,
        mape_percent=mape,
        bias_seconds=bias,
    )


def leave_one_bearing_out_splits(bearing_ids: Iterable[str]) -> list[tuple[tuple[str, ...], str]]:
    """Pure combinatorial helper: for N bearing ids, return N
    ``(train_ids, held_out_id)`` pairs, one per fold, each excluding
    exactly its own held-out id from ``train_ids``. Deterministically
    sorted (no dependency on input ordering or dict iteration order).

    Raises:
        ValueError: if fewer than 2 distinct bearing ids are given (LOBO
            is undefined with 0 or 1 bearings).
    """
    ids = sorted(set(bearing_ids))
    if len(ids) < 2:
        raise ValueError(f"leave-one-bearing-out requires >= 2 distinct bearing ids, got {ids}")
    return [(tuple(b for b in ids if b != held_out), held_out) for held_out in ids]


@dataclass(frozen=True)
class FoldResult:
    """One LOBO fold's outcome: which bearing was held out, how much
    training data the other bearings produced, the per-epoch training
    loss curve, and the held-out bearing's evaluation metrics."""

    held_out_bearing: str
    train_bearings: tuple[str, ...]
    n_train_examples: int
    train_loss_history: list[float]
    metrics: EvaluationMetrics


def run_leave_one_bearing_out(
    sequences: Mapping[str, PronostiaRunSequence],
    trust: Mapping[str, TrustReading],
    *,
    hidden_size: int,
    epochs: int,
    batch_size: int,
    optimizer_factory: Callable[[Iterator[torch.nn.Parameter]], torch.optim.Optimizer],
    window_size: int = WINDOW_SIZE,
    stride: int = STRIDE,
) -> list[FoldResult]:
    """Run full leave-one-bearing-out cross-validation over ``sequences``.

    For each fold: a FRESH ``_LSTMPrognosisNet(hidden_size=hidden_size)``
    is constructed (no cross-fold weight leakage), trained on the other
    bearings' windowed examples via ``train``, and evaluated on the held-
    out bearing's own windowed examples via ``evaluate``. Zero sample-
    level overlap between a fold's training and validation examples
    (different physical bearings).

    ``optimizer_factory`` is REQUIRED -- called once per fold on that
    fold's fresh ``network.parameters()`` -- so this function bakes in no
    optimizer choice of its own (same convention as ``train``).

    ``sequences`` MUST contain only D025-authorized training-bearing ids
    (``TRAINING_BEARINGS_D025``) -- structurally refuses any other
    bearing_id (test-split, ``Validation_Set``/``Full_Test_Set``, or a
    typo) before any training occurs.

    Raises:
        ValueError: if ``sequences`` contains any non-D025-training
            bearing id; if ``sequences`` has fewer than 2 entries (LOBO
            undefined); if any fold's training or validation set would be
            empty (a bearing shorter than ``window_size``).
    """
    unauthorized = sorted(set(sequences) - TRAINING_BEARINGS_D025)
    if unauthorized:
        raise ValueError(
            "run_leave_one_bearing_out only accepts D025's 4 usable training "
            f"bearings {sorted(TRAINING_BEARINGS_D025)}; got unauthorized id(s) {unauthorized}"
        )

    examples_by_bearing = {
        bearing_id: make_window_examples(seq, trust, window_size=window_size, stride=stride)
        for bearing_id, seq in sequences.items()
    }

    results: list[FoldResult] = []
    for train_ids, held_out in leave_one_bearing_out_splits(sequences.keys()):
        train_examples = [ex for bid in train_ids for ex in examples_by_bearing[bid]]
        val_examples = examples_by_bearing[held_out]
        if not train_examples:
            raise ValueError(f"fold held_out={held_out!r}: training bearings produced zero windows")
        if not val_examples:
            raise ValueError(f"held-out bearing {held_out!r} produced zero windows")

        network = _LSTMPrognosisNet(hidden_size=hidden_size)
        optimizer = optimizer_factory(network.parameters())
        loss_history = train(
            network, train_examples, epochs=epochs, optimizer=optimizer, batch_size=batch_size
        )
        metrics = evaluate(network, val_examples)

        results.append(
            FoldResult(
                held_out_bearing=held_out,
                train_bearings=train_ids,
                n_train_examples=len(train_examples),
                train_loss_history=loss_history,
                metrics=metrics,
            )
        )
    return results
