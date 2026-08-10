"""Edge trust engine (P2 · Beta-reputation foundation).

This package hosts the per-sensor trust mathematics. This first module
(``beta``) is the **signal-agnostic** Beta-reputation core: it consumes a
pre-computed per-window evidence value ``g`` and evolves the trust score.

Deliberately NOT here (undecided — see ``project-state/DECISIONS.md``):
the definitions of the consistency ``c``, cross-sensor correlation ``k``, and
historical-reliability ``h`` signals (U01/U02). This module never computes them
— they are supplied to it. No Isolation Forest, injection, attribution, physics,
or dataset logic lives here.
"""
