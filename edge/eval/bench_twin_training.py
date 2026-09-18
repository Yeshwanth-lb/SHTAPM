"""Train + evaluate the digital twin on a REAL bench capture (P3 · D029).

Diagnostic/offline tooling, same status as every other ``edge/eval/*.py``
module: not production, not imported by ``edge/main.py``, not on any acceptance
path. It trains the existing, unmodified ``LSTMTwinReconstructor`` (D016
architecture) on a real five-sensor load capture produced by
``edge/scripts/load_capture.py``.

HOW THIS DIFFERS FROM ``edge/eval/twin_training.py``: that harness trains on the
D005/D008 simulator, whose clean baseline has no cross-channel structure beyond
each channel's own mean (D017), so it can only prove the ML plumbing runs. This
one trains on measured hardware in which a real relationship was first shown to
exist (current<->vibration, r=0.76, R^2=0.58 -- see
``project-state/BENCH_LOAD_VALIDATION.md``).

SCALE: inputs and targets use ``edge.models.scaling.ChannelScaler`` (D029), a
fixed clean-baseline z-score, NOT the per-window min-max of
``edge/anomaly/preprocess.py``. That is what makes a reconstruction invertible
back to engineering units so it can actually substitute for a sensor.

HONEST BASELINE: every reported error is compared against predicting the
channel's own training-set mean. A model that cannot beat that has learned
nothing, however small its MSE looks in normalised units.

GAS IS EXCLUDED, NOT SYNTHESISED: no MQ-135 driver exists, so a bench capture
contains no gas measurement. Fabricating one to fill the six-wide input would
make the training set indistinguishable from measured data. Gas is instead
masked as unavailable (value 0.0 in scaled space, i.e. the channel mean), and
no twin is trained to reconstruct it.
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
from collections.abc import Sequence
from dataclasses import dataclass

import torch
from app.schemas.contracts import CHANNELS

from edge.anomaly.preprocess import Window
from edge.models.lstm_twin import LSTMTwinReconstructor, _LSTMTwinNet, build_masked_input
from edge.models.scaling import ChannelScaler
from edge.models.twin_bundle import save_bundle

# Channels a bench capture actually measures. `gas` is absent by construction
# (no MQ-135 driver); see module docstring.
MEASURED_CHANNELS: tuple[str, ...] = (
    "temperature",
    "vibration",
    "pressure",
    "humidity",
    "current",
)

# Reconstruction targets. Restricted to the channels with demonstrated
# cross-channel structure on this rig -- BENCH_LOAD_VALIDATION.md measured
# R^2 < 0.006 between current and pressure/temperature/humidity, so training a
# twin to reconstruct those from load would be fitting noise.
DEFAULT_TARGETS: tuple[str, ...] = ("current", "vibration")

WINDOW_SIZE = 30  # matches edge/anomaly/preprocess.py's documented default

# Training fixtures -- NOT project specification values. D016 specifies no
# hyperparameters; these are explicit, overridable arguments.
HIDDEN_SIZE_FIXTURE = 32
EPOCHS_FIXTURE = 30
LEARNING_RATE_FIXTURE = 0.01
SEED_FIXTURE = 0
HOLDOUT_FRACTION_FIXTURE = 0.3


@dataclass(frozen=True)
class Sample:
    """One capture row, already reduced to the channels this rig measures.

    ``index`` is the row's position in the ORIGINAL capture, retained so
    windows are only built from genuinely consecutive samples -- see
    build_windows().
    """

    index: int
    values: dict[str, float]


@dataclass(frozen=True)
class Evaluation:
    channel: str
    n_train: int
    n_test: int
    model_rmse_scaled: float
    baseline_rmse_scaled: float
    model_rmse_raw: float
    baseline_rmse_raw: float
    unit: str

    @property
    def skill(self) -> float:
        """Fraction of the mean-predictor's error removed. <= 0 means the model
        is no better than predicting the channel's own mean."""
        if self.baseline_rmse_scaled == 0:
            return 0.0
        return 1.0 - (self.model_rmse_scaled / self.baseline_rmse_scaled)


def load_capture(path: str) -> list[Sample]:
    """Read a load_capture.py JSONL file, keeping only rows where every
    measured channel is healthy.

    Rows with an unhealthy channel are DROPPED rather than imputed: the DHT22
    drops out under motor EMI (~30% of load samples), and inventing values for
    those would be fabricating exactly the data the capture proves is missing.
    """
    samples: list[Sample] = []
    dropped = 0
    with open(path, encoding="utf-8") as handle:
        for row_index, line in enumerate(handle):
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            values = {
                "temperature": row.get("temperature_c"),
                "vibration": row.get("vibration_g_driver"),
                "pressure": row.get("pressure_hpa"),
                "humidity": row.get("humidity_pct"),
                "current": row.get("current_a"),
            }
            if any(v is None for v in values.values()):
                dropped += 1
                continue
            samples.append(Sample(index=row_index, values=values))
    print(f"loaded {len(samples)} complete samples ({dropped} dropped for an unhealthy channel)")
    return samples


def fit_scaler(samples: Sequence[Sample]) -> ChannelScaler:
    scaler = ChannelScaler()
    scaler.fit({ch: [s.values[ch] for s in samples] for ch in MEASURED_CHANNELS})
    return scaler


def build_windows(samples: Sequence[Sample], scaler: ChannelScaler) -> list[Window]:
    """Windows of WINDOW_SIZE genuinely CONSECUTIVE samples, in the twin's
    fixed scaled space.

    Contiguity is checked against each sample's original capture index, not its
    position in the filtered list. Rows are dropped wherever a channel was
    unhealthy (the DHT22 drops out under motor EMI for ~30% of load samples),
    so consecutive surviving rows are frequently NOT consecutive in time. A
    window stitched across such a gap would present samples seconds or minutes
    apart as a continuous 30 s history, and the LSTM would be learning a
    temporal structure that never happened.

    `gas` is filled with 0.0 -- the channel mean in z-score space, i.e. "no
    information", which is the honest representation of a channel this rig
    does not measure. It is never a reconstruction target.
    """
    windows: list[Window] = []
    skipped_for_gaps = 0
    for start in range(0, len(samples) - WINDOW_SIZE + 1):
        chunk = samples[start : start + WINDOW_SIZE]
        if chunk[-1].index - chunk[0].index != WINDOW_SIZE - 1:
            skipped_for_gaps += 1
            continue
        features: dict[str, tuple[float, ...]] = {}
        for ch in CHANNELS:
            if ch in MEASURED_CHANNELS:
                features[ch] = tuple(scaler.normalize(ch, s.values[ch]) for s in chunk)
            else:
                features[ch] = (0.0,) * WINDOW_SIZE
        windows.append(Window(start_index=start, end_index=start + WINDOW_SIZE, features=features))
    if skipped_for_gaps:
        print(f"  skipped {skipped_for_gaps} windows that would have spanned a dropout gap")
    return windows


def train_for_channel(
    windows: Sequence[Window],
    channel: str,
    *,
    hidden_size: int,
    epochs: int,
    learning_rate: float,
    seed: int,
) -> _LSTMTwinNet:
    torch.manual_seed(seed)
    network = _LSTMTwinNet(hidden_size=hidden_size)
    optimizer = torch.optim.Adam(network.parameters(), lr=learning_rate)
    network.train()
    for _ in range(epochs):
        for window in windows:
            optimizer.zero_grad()
            prediction = network(build_masked_input(window, channel))
            target = torch.tensor([[window.features[channel][-1]]], dtype=torch.float32)
            loss = torch.nn.functional.mse_loss(prediction, target)
            loss.backward()
            optimizer.step()
    return network


def evaluate(
    network: _LSTMTwinNet,
    train_windows: Sequence[Window],
    test_windows: Sequence[Window],
    channel: str,
    scaler: ChannelScaler,
    unit: str,
) -> Evaluation:
    """RMSE against a predict-the-training-mean baseline, in both scaled and
    engineering units. Denormalising both makes the error physically readable
    (e.g. amps) instead of only meaningful in z-score space."""
    reconstructor = LSTMTwinReconstructor(network)
    train_targets = [w.features[channel][-1] for w in train_windows]
    baseline_prediction = statistics.mean(train_targets)

    model_sq, baseline_sq = [], []
    for window in test_windows:
        truth = window.features[channel][-1]
        model_sq.append((reconstructor.reconstruct(window, channel) - truth) ** 2)
        baseline_sq.append((baseline_prediction - truth) ** 2)

    model_rmse = (sum(model_sq) / len(model_sq)) ** 0.5
    baseline_rmse = (sum(baseline_sq) / len(baseline_sq)) ** 0.5
    # A z-score-scaled error maps to engineering units by multiplying by std,
    # which is exactly denormalize() minus the mean offset.
    span = scaler.denormalize(channel, 1.0) - scaler.denormalize(channel, 0.0)
    return Evaluation(
        channel=channel,
        n_train=len(train_windows),
        n_test=len(test_windows),
        model_rmse_scaled=model_rmse,
        baseline_rmse_scaled=baseline_rmse,
        model_rmse_raw=model_rmse * abs(span),
        baseline_rmse_raw=baseline_rmse * abs(span),
        unit=unit,
    )


def derive_divergence_threshold(
    network: _LSTMTwinNet,
    train_windows: Sequence[Window],
    test_windows: Sequence[Window],
    channel: str,
) -> None:
    """Measure what divergence thresholds cost on CLEAN held-out data (U05).

    `divergence_threshold` has been open since August as "data-gated: needs real
    reconstruction-error statistics". This produces exactly those statistics.

    Method mirrors production: DivergenceScorer fits per-channel mean/std of the
    residual on clean training data, then z-scores new residuals. Every window
    here is clean (no injected attack), so ANY window scoring above a candidate
    threshold is a FALSE positive -- a healthy sensor that would be wrongly
    escalated toward Safe Pump-Stop.

    Reports the cost of each candidate rather than choosing one: the choice
    trades false escalations against detection sensitivity, which is a policy
    call, not a measurement.
    """
    from edge.pipeline.divergence import DivergenceScorer

    reconstructor = LSTMTwinReconstructor(network)
    train_residuals = [
        reconstructor.reconstruct(w, channel) - w.features[channel][-1] for w in train_windows
    ]
    scorer = DivergenceScorer()
    scorer.fit({channel: train_residuals})

    test_scores = sorted(
        scorer.score(channel, reconstructor.reconstruct(w, channel) - w.features[channel][-1])
        for w in test_windows
    )
    n = len(test_scores)
    print(f"\n--- divergence on CLEAN held-out data: {channel} (n={n}) ---")
    print(f"  max clean score observed: {test_scores[-1]:.2f} sigma")
    print(f"\n  {'threshold':>10}{'false escalations':>20}{'rate':>10}")
    for threshold in (2.0, 2.5, 3.0, 3.5, 4.0, 5.0, 6.0):
        false_positives = sum(1 for s in test_scores if s >= threshold)
        print(f"  {threshold:>10.1f}{false_positives:>20}{false_positives / n:>9.1%}")
    print(
        "\n  Every window above is clean, so each count is a healthy sensor that\n"
        "  would have been escalated. Choosing a value trades these against\n"
        "  sensitivity to real divergence -- a policy call, not a measurement."
    )


UNITS = {
    "temperature": "degC",
    "vibration": "g",
    "pressure": "hPa",
    "humidity": "%",
    "current": "A",
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", help="load_capture.py JSONL file")
    parser.add_argument("--targets", nargs="*", default=list(DEFAULT_TARGETS))
    parser.add_argument("--hidden-size", type=int, default=HIDDEN_SIZE_FIXTURE)
    parser.add_argument("--epochs", type=int, default=EPOCHS_FIXTURE)
    parser.add_argument("--learning-rate", type=float, default=LEARNING_RATE_FIXTURE)
    parser.add_argument("--seed", type=int, default=SEED_FIXTURE)
    parser.add_argument("--holdout", type=float, default=HOLDOUT_FRACTION_FIXTURE)
    parser.add_argument("--save-prefix", default=None, help="write <prefix>_<channel>.pt")
    args = parser.parse_args()

    samples = load_capture(args.capture)
    if len(samples) < WINDOW_SIZE * 4:
        print(f"ERROR: need at least {WINDOW_SIZE * 4} samples", file=sys.stderr)
        return 1

    # Chronological split: the holdout is the TAIL of the capture, never a
    # random shuffle. Neighbouring 1 Hz windows overlap by 29/30 samples, so a
    # random split would put near-identical windows on both sides and report a
    # meaninglessly optimistic score.
    split = int(len(samples) * (1.0 - args.holdout))
    train_samples, test_samples = samples[:split], samples[split:]

    # The scale is fitted on the training segment only -- same leakage
    # discipline as D025's cross-bearing statistics and DivergenceScorer's fit.
    scaler = fit_scaler(train_samples)
    train_windows = build_windows(train_samples, scaler)
    test_windows = build_windows(test_samples, scaler)
    print(f"train windows: {len(train_windows)}   test windows: {len(test_windows)}")
    random.Random(args.seed).shuffle(train_windows)

    print(f"\n{'channel':<12}{'model RMSE':>14}{'mean RMSE':>14}{'skill':>10}   verdict")
    print("-" * 68)
    results: list[Evaluation] = []
    for channel in args.targets:
        network = train_for_channel(
            train_windows,
            channel,
            hidden_size=args.hidden_size,
            epochs=args.epochs,
            learning_rate=args.learning_rate,
            seed=args.seed,
        )
        result = evaluate(network, train_windows, test_windows, channel, scaler, UNITS[channel])
        results.append(result)
        verdict = (
            "beats mean"
            if result.skill > 0.1
            else "no better than mean" if result.skill > -0.1 else "WORSE than mean"
        )
        print(
            f"{channel:<12}{result.model_rmse_raw:>10.5f} {result.unit:<3}"
            f"{result.baseline_rmse_raw:>10.5f} {result.unit:<3}"
            f"{result.skill:>9.1%}   {verdict}"
        )
        if result.skill > 0.1:
            derive_divergence_threshold(network, train_windows, test_windows, channel)
        if args.save_prefix:
            # Save the SCALE and residual statistics with the weights: a
            # checkpoint loaded against a different scale produces confident,
            # plausible, meaningless numbers rather than an error.
            reconstructor = LSTMTwinReconstructor(network)
            residuals = [
                reconstructor.reconstruct(w, channel) - w.features[channel][-1]
                for w in train_windows
            ]
            residual_mean = statistics.mean(residuals)
            residual_std = statistics.pstdev(residuals) or 1e-8
            save_bundle(
                f"{args.save_prefix}_{channel}",
                channel=channel,
                reconstructor=reconstructor,
                scaler=scaler,
                residual_mean=residual_mean,
                residual_std=residual_std,
                hidden_size=args.hidden_size,
                skill=result.skill,
                trained_on=args.capture,
            )
            print(f"  saved bundle: {args.save_prefix}_{channel}.pt + .json")

    print(
        "\nSkill = fraction of the mean-predictor's error removed. <= 0 means the\n"
        "model learned nothing useful, regardless of how small its raw RMSE looks."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
