"""LSTM prognosis skeleton: UNTRAINED architecture/plumbing ONLY (P3 · FR-M1-3,
D016). This module does NOT implement, claim, or validate FR-M1 (health-state
prediction) or FR-M2 (failure-ETA prediction) -- see the P3 prognosis
architecture scoping pass for the full rationale.

Implements the recommended-and-approved shape: one shared, single-layer,
unidirectional PyTorch LSTM encoder over the existing P2 ``Window`` (its
existing window size, unchanged) -> final hidden state -> two independent
heads (``health``: 3-way classification logits, ``failure_eta``: scalar
regression). No dropout, attention, extra layers, or bidirectionality.
``hidden_size`` is a REQUIRED constructor argument with NO production
default anywhere in this module, mirroring ``edge/models/lstm_twin.py``.

Trust-weighting (FR-M3) is a pure continuous elementwise scaling of each
channel's window values by that channel's own existing P2 trust score
(``TrustReading.trust``, already in [0,1]) -- no new isolation decision,
threshold, or trust policy is introduced by this module.

No ``Protocol`` seam is defined here (unlike ``edge/models/twin.py``):
unlike the digital-twin, which ``SelfHealOrchestrator`` already injects
against, no P3 code currently consumes a prognosis predictor -- FR-RL1 (the
only documented future consumer) does not exist in this repo. Introducing a
Protocol now would be speculative; ``LSTMPrognosisPredictor``'s own public
``predict`` method is the interface a future seam can be extracted from once
a real consumer exists.

NOT provided anywhere in this module: training, a training harness (not even
a non-meaningful diagnostic one -- the existing simulator has no notion of
degradation to derive even a fake label from), dataset/label handling, loss
function, optimizer, HealthState thresholds/definitions, failure_eta
horizon/units/calibration, or integration into any existing P2/P3 pipeline
file. The health/failure_eta this predictor returns come from a randomly
initialized (or otherwise untrained) network and carry no accuracy or
calibration claim whatsoever.
"""

from __future__ import annotations

from collections.abc import Mapping

import torch
from app.schemas.contracts import CHANNELS, HealthState

from edge.anomaly.preprocess import Window
from edge.trust.engine import TrustReading

# Explicit, deterministic index -> HealthState mapping for the health head's
# 3-way output. This ordering is a plumbing choice only (arbitrary but
# fixed) -- it is NOT a claim that the network has learned or been
# calibrated to produce these classes correctly.
_HEALTH_STATE_ORDER: tuple[HealthState, ...] = (
    HealthState.healthy,
    HealthState.warning,
    HealthState.critical,
)


def build_trust_weighted_input(window: Window, trust: Mapping[str, TrustReading]) -> torch.Tensor:
    """Build the prognosis model's ``(1, window.size, len(CHANNELS))`` input
    tensor: per timestep, each channel's value scaled by that channel's own
    ``trust[channel].trust`` (continuous weighting only -- no threshold,
    isolation decision, or banding).

    Raises:
        ValueError: if ``trust`` is missing an entry for any channel in the
            frozen ``CHANNELS``.
    """
    missing = [ch for ch in CHANNELS if ch not in trust]
    if missing:
        raise ValueError(f"missing trust reading(s) for channel(s) {missing}")

    rows: list[list[float]] = []
    for t in range(window.size):
        row = [window.features[ch][t] * trust[ch].trust for ch in CHANNELS]
        rows.append(row)
    values = torch.tensor(rows, dtype=torch.float32)  # (window.size, len(CHANNELS))
    return values.unsqueeze(0)  # (1, window.size, len(CHANNELS))


class _LSTMPrognosisNet(torch.nn.Module):
    """Single-layer, unidirectional LSTM -> final hidden state -> two
    independent heads (health logits, failure_eta scalar). ``hidden_size``
    is REQUIRED, no default (see module docstring)."""

    def __init__(self, hidden_size: int) -> None:
        super().__init__()
        input_size = len(CHANNELS)
        self._lstm = torch.nn.LSTM(
            input_size=input_size,
            hidden_size=hidden_size,
            num_layers=1,
            batch_first=True,
            bidirectional=False,
        )
        self._health_head = torch.nn.Linear(hidden_size, len(_HEALTH_STATE_ORDER))
        self._eta_head = torch.nn.Linear(hidden_size, 1)

    def forward(self, x: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        """``x``: ``(batch, seq_len, len(CHANNELS))`` ->
        ``(health_logits: (batch, 3), failure_eta: (batch, 1))``."""
        _, (h_n, _) = self._lstm(x)
        final_hidden = h_n[-1]
        return self._health_head(final_hidden), self._eta_head(final_hidden)


class LSTMPrognosisPredictor:
    """Wraps a (trained or freshly initialized) ``_LSTMPrognosisNet``.
    Untrained architecture/plumbing ONLY -- see module docstring. Does NOT
    constitute FR-M1/M2 validation."""

    def __init__(self, network: _LSTMPrognosisNet) -> None:
        self._network = network
        self._network.eval()

    def predict(
        self, window: Window, trust: Mapping[str, TrustReading]
    ) -> tuple[HealthState, float]:
        """Returns ``(health, failure_eta)``. Neither value carries any
        accuracy or calibration claim -- see module docstring."""
        input_tensor = build_trust_weighted_input(window, trust)
        with torch.no_grad():
            health_logits, eta = self._network(input_tensor)
        health_index = int(torch.argmax(health_logits[0]).item())
        return _HEALTH_STATE_ORDER[health_index], float(eta.item())

    def save(self, path: str) -> None:
        """Persist the underlying network's weights. No checkpoint produced
        by this project's own tests/tooling is committed to the repo."""
        torch.save(self._network.state_dict(), path)

    @classmethod
    def from_checkpoint(cls, path: str, hidden_size: int) -> LSTMPrognosisPredictor:
        """``hidden_size`` REQUIRED -- must match the checkpoint's own
        architecture; not inferable from the saved state dict alone
        without additional bookkeeping this module does not add."""
        network = _LSTMPrognosisNet(hidden_size=hidden_size)
        network.load_state_dict(torch.load(path, weights_only=True))
        return cls(network)
