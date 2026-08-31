"""Self-supervised LSTM digital-twin training harness (hardware-free,
DIAGNOSTIC ONLY -- P3 · D016/D017).

Same status as edge/eval/if_eval.py / swat_eval.py / preproc_experiment.py:
not on pytest ``testpaths``' production path, not wired into any
acceptance criterion. Uses the existing D005/D008 simulator +
edge/anomaly/preprocess.Preprocessor AS-IS -- no injections, no new
simulator capability, no modification to either.

Pipeline: simulator clean stream -> documented preprocessing (30-sample
windows) -> self-supervised channel masking (edge.models.lstm_twin.
build_masked_input) -> real _LSTMTwinNet -> MSE loss.

NOTHING here is a project specification: hidden_size, epochs, the
optimizer, and every other numeric/procedural value below are DIAGNOSTIC
FIXTURES (labelled ``*_FIXTURE`` where they stand in for an otherwise-
unresolved value), never project defaults. In particular, the optimizer is
never constructed inside this module's own training function -- it is a
REQUIRED, caller-supplied ``torch.optim.Optimizer`` instance; where this
module's own ``main()`` supplies one for its own diagnostic run, it is
Adam, explicitly labelled ``ADAM_OPTIMIZER_FIXTURE`` and not presented as
an approved project choice.

Per the P3 digital-twin scoping pass: the existing simulator's clean
baseline has no cross-channel or temporal structure beyond each channel's
own fitted mean, so nothing trained here establishes, or should be read as
establishing, meaningful reconstruction accuracy or real-world validation.
"""

from __future__ import annotations

import torch
from app.schemas.contracts import CHANNELS, TelemetryMessage

from edge.anomaly.preprocess import Preprocessor, Window
from edge.models.lstm_twin import _LSTMTwinNet, build_masked_input
from simulator.generator import TelemetrySimulator

# ---- DIAGNOSTIC FIXTURES ONLY (arbitrary, NOT project specs) --------------
# Identity filters (median_kernel=1, alpha=1.0) so this harness adds no
# undocumented smoothing beyond the documented pipeline; window_size stays
# the documented default 30. Same convention as edge/eval/if_eval.py.
PREPROC_FIXTURE = {"median_kernel": 1, "low_pass_alpha": 1.0, "window_size": 30, "step": 1}

TRAIN_SEED_FIXTURE = 1337  # simulator determinism only
FRAME_COUNT_FIXTURE = 100
HIDDEN_SIZE_FIXTURE = 4
EPOCHS_FIXTURE = 2
LEARNING_RATE_FIXTURE = 0.01  # feeds ADAM_OPTIMIZER_FIXTURE below, not a project spec


def _ts(i: int) -> str:
    """Deterministic ISO timestamp from the sample index (no wall clock).
    Same pattern as edge/eval/if_eval.py."""
    return f"2026-08-10T00:{i // 60:02d}:{i % 60:02d}.000Z"


def generate_clean_windows(frame_count: int, seed: int, preprocessor: Preprocessor) -> list[Window]:
    """Clean-baseline windows from the existing simulator + Preprocessor,
    used exactly as they already exist elsewhere in this repo -- no
    injections, no new simulator/preprocessing capability."""
    sim = TelemetrySimulator(seed=seed)
    frames: list[TelemetryMessage] = sim.generate(frame_count, [_ts(i) for i in range(frame_count)])
    return preprocessor.process(frames)


def make_training_examples(windows: list[Window]) -> list[tuple[torch.Tensor, float, str]]:
    """One self-supervised masked-reconstruction example per (window,
    channel) pair -- every channel of every window is masked once,
    deterministically (no masking RNG needed). Target is the TRUE,
    already-[0,1]-normalized value of the masked channel's last sample in
    that window."""
    examples: list[tuple[torch.Tensor, float, str]] = []
    for window in windows:
        for channel in CHANNELS:
            input_tensor = build_masked_input(window, channel)
            target = window.features[channel][-1]
            examples.append((input_tensor, target, channel))
    return examples


def train(
    network: _LSTMTwinNet,
    examples: list[tuple[torch.Tensor, float, str]],
    *,
    epochs: int,
    optimizer: torch.optim.Optimizer,
) -> list[float]:
    """Run ``epochs`` passes of MSE-reconstruction training over
    ``examples``. ``epochs`` and ``optimizer`` are REQUIRED -- no default.
    ``optimizer`` must already be constructed and bound to
    ``network.parameters()`` by the caller; this function chooses no
    optimizer of its own. Returns the per-epoch mean loss.

    Hardware-free plumbing verification ONLY: proves the forward/backward
    pass runs, loss is finite, and weights update. Does NOT establish, and
    must never be read as establishing, meaningful reconstruction accuracy
    -- see module docstring.
    """
    loss_history: list[float] = []
    for _ in range(epochs):
        epoch_loss = 0.0
        for input_tensor, target, _channel in examples:
            optimizer.zero_grad()
            prediction = network(input_tensor)
            loss = torch.nn.functional.mse_loss(prediction, torch.tensor([[target]]))
            loss.backward()
            optimizer.step()
            epoch_loss += loss.item()
        loss_history.append(epoch_loss / len(examples))
    return loss_history


def main() -> None:
    """Diagnostic entry point: ``python -m edge.eval.twin_training``. Trains
    a tiny LSTM twin on simulator-only data and prints a loss-curve
    summary. NOT an accuracy claim -- see train()'s docstring."""
    preprocessor = Preprocessor(**PREPROC_FIXTURE)
    windows = generate_clean_windows(
        frame_count=FRAME_COUNT_FIXTURE, seed=TRAIN_SEED_FIXTURE, preprocessor=preprocessor
    )
    examples = make_training_examples(windows)

    network = _LSTMTwinNet(hidden_size=HIDDEN_SIZE_FIXTURE)
    # ADAM_OPTIMIZER_FIXTURE: a diagnostic choice for this harness's own
    # smoke-training run only -- NOT an approved project optimizer spec.
    ADAM_OPTIMIZER_FIXTURE = torch.optim.Adam(network.parameters(), lr=LEARNING_RATE_FIXTURE)

    loss_history = train(network, examples, epochs=EPOCHS_FIXTURE, optimizer=ADAM_OPTIMIZER_FIXTURE)

    print("=== LSTM digital-twin training harness (diagnostic, NOT acceptance) ===")
    print(f"{len(windows)} clean windows, {len(examples)} masked-channel training examples")
    print(f"loss[0]={loss_history[0]:.6f}  loss[-1]={loss_history[-1]:.6f}")
    print(
        "NOTE: this only proves the training/inference PLUMBING works "
        "(forward/backward pass, loss computation, weight updates). It does "
        "NOT establish meaningful reconstruction accuracy -- the simulator's "
        "clean baseline has no cross-channel or temporal structure beyond "
        "each channel's own fitted mean, and no real-world validation is "
        "claimed or implied."
    )


if __name__ == "__main__":
    main()
