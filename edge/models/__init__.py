"""P3 model seams (interfaces only -- no trained models exist yet).

Modules
-------
twin
    ``TwinReconstructor`` -- injectable digital-twin reconstruction seam
    (FR-H2, D016: separate, channel-agnostic model). Protocol only; D016
    specifies no architecture, training objective, or hyperparameters, so no
    production implementation lives here.
"""

from edge.models.twin import TwinReconstructor

__all__ = ["TwinReconstructor"]
