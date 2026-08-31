"""LSTM digital-twin: hardware-free plumbing/ML-pipeline development ONLY
(P3 · FR-H2, D016).

Implements the approved architecture exactly: single-layer, unidirectional
PyTorch LSTM over the existing 30-timestep, six-channel preprocessed
``Window`` -> final hidden state -> Linear -> one scalar reconstruction.
The missing channel is zeroed and an explicit one-hot missing-channel
indicator (repeated at every timestep) is concatenated to the input.

``hidden_size`` is a REQUIRED constructor argument with NO production
default anywhere in this module -- D016 explicitly leaves layer sizes/
hyperparameters unspecified; only the architecture *shape* (single-layer,
unidirectional, LSTM->Linear->scalar) has been approved, not a width.

NOT claimed here or anywhere in this module: meaningful reconstruction
accuracy, or real-world validation. The existing D005/D008 simulator's
clean baseline has no cross-channel or temporal structure beyond each
channel's own fitted mean (see the P3 digital-twin scoping pass), so even
a well-trained network here only proves the ML plumbing works.

Satisfies ``edge.models.twin.TwinReconstructor`` structurally (that
Protocol is unmodified) -- no change to ``twin.py``, ``contracts.py``,
P2, ``simulator/``, or ``edge/actuation/*``. Preserves the existing
invariant: ``missing_channel``'s own value is never read from ``window``
anywhere in this module -- ``build_masked_input`` substitutes 0.0 for that
channel without ever indexing into its true values.
"""

from __future__ import annotations

import torch
from app.schemas.contracts import CHANNELS

from edge.anomaly.preprocess import Window


def build_masked_input(window: Window, missing_channel: str) -> torch.Tensor:
    """Build the twin's ``(1, window.size, 2*len(CHANNELS))`` input tensor
    for one window with ``missing_channel`` masked out.

    Per timestep: the ``len(CHANNELS)``-wide channel-value vector (with
    ``missing_channel``'s own value replaced by 0.0 -- never read from
    ``window``) concatenated with a ``len(CHANNELS)``-wide one-hot
    indicator marking which channel is missing, identical at every
    timestep.

    Raises:
        ValueError: if ``missing_channel`` is not one of the frozen
            ``CHANNELS``.
    """
    if missing_channel not in CHANNELS:
        raise ValueError(f"unknown channel {missing_channel!r}; must be one of {CHANNELS}")

    rows: list[list[float]] = []
    for t in range(window.size):
        row = [0.0 if ch == missing_channel else window.features[ch][t] for ch in CHANNELS]
        rows.append(row)
    values = torch.tensor(rows, dtype=torch.float32)  # (window.size, len(CHANNELS))

    mask_index = CHANNELS.index(missing_channel)
    indicator = torch.zeros(len(CHANNELS), dtype=torch.float32)
    indicator[mask_index] = 1.0
    indicator = indicator.expand(window.size, -1)  # (window.size, len(CHANNELS))

    combined = torch.cat([values, indicator], dim=1)  # (window.size, 2*len(CHANNELS))
    return combined.unsqueeze(0)  # (1, window.size, 2*len(CHANNELS))


class _LSTMTwinNet(torch.nn.Module):
    """Single-layer, unidirectional LSTM -> final hidden state -> Linear ->
    one scalar. ``hidden_size`` is REQUIRED, no default (see module
    docstring)."""

    def __init__(self, hidden_size: int) -> None:
        super().__init__()
        input_size = 2 * len(CHANNELS)
        self._lstm = torch.nn.LSTM(
            input_size=input_size,
            hidden_size=hidden_size,
            num_layers=1,
            batch_first=True,
            bidirectional=False,
        )
        self._head = torch.nn.Linear(hidden_size, 1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """``x``: ``(batch, seq_len, 2*len(CHANNELS))`` -> ``(batch, 1)``."""
        _, (h_n, _) = self._lstm(x)
        return self._head(h_n[-1])


class LSTMTwinReconstructor:
    """``TwinReconstructor`` implementation backed by a (trained or freshly
    initialized) ``_LSTMTwinNet``. Hardware-free plumbing/ML-pipeline
    development only -- see module docstring."""

    def __init__(self, network: _LSTMTwinNet) -> None:
        self._network = network
        self._network.eval()

    def reconstruct(self, window: Window, missing_channel: str) -> float:
        input_tensor = build_masked_input(window, missing_channel)
        with torch.no_grad():
            output = self._network(input_tensor)
        return float(output.item())

    def save(self, path: str) -> None:
        """Persist the underlying network's weights. No checkpoint produced
        by this project's own tests/tooling is committed to the repo."""
        torch.save(self._network.state_dict(), path)

    @classmethod
    def from_checkpoint(cls, path: str, hidden_size: int) -> LSTMTwinReconstructor:
        """``hidden_size`` REQUIRED -- must match the checkpoint's own
        architecture; not inferable from the saved state dict alone
        without additional bookkeeping this module does not add."""
        network = _LSTMTwinNet(hidden_size=hidden_size)
        network.load_state_dict(torch.load(path, weights_only=True))
        return cls(network)
