"""Digital-twin reconstruction seam (P3 · FR-H2, D016).

Protocol only. D016 approves a separate, channel-agnostic digital-twin model
(FR-H2) but explicitly specifies no architecture, training objective, or
hyperparameters ("no layer sizes, hyperparameters, or loss functions are
specified or implied by this decision"). No production implementation is
provided in this module, or anywhere else in this slice: building even a
minimal non-learned reconstruction stub was explicitly deferred at
implementation-authorization time (see project-state/DECISIONS.md D016).

Tests exercise this Protocol with an explicit, non-spec fixture stub (see
edge/tests/test_self_heal.py) -- never a production implementation.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from edge.anomaly.preprocess import Window


@runtime_checkable
class TwinReconstructor(Protocol):
    """Injectable digital-twin seam: reconstruct one missing/isolated
    channel's current value from a window. Contract only -- says nothing
    about the reconstruction algorithm (no architecture chosen; UNDECIDED).

    IMPORTANT for any future implementation: ``window`` is the full window
    and still contains ``window.features[missing_channel]`` (that channel's
    own recent samples) -- nothing masks it out before this call. A correct
    implementation MUST NOT read ``window.features[missing_channel]``; it
    must reconstruct that channel's value using only the OTHER channels in
    ``window`` plus the ``missing_channel`` indicator (D016: "the available
    channels plus an indicator of which channel is missing"). Reading the
    missing channel's own data back out of ``window`` would make the
    reconstruction trivially equal to the raw reading, collapsing D018's
    divergence backstop to near-zero and defeating FR-H3 -- exactly the R3
    circularity risk D018 carries forward, not resolves.
    """

    def reconstruct(self, window: Window, missing_channel: str) -> float: ...
