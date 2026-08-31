"""PRONOSTIA -> prognosis input glue (P3 · D022/D023/D024). GLUE ONLY.

Converts one already-loaded ``PronostiaRunSequence``
(``edge/eval/pronostia_prep.py``) into the D022/D024-approved 11-column
prognosis input tensor, by calling the existing, unmodified
``build_prognosis_input`` (``edge/models/lstm_prognosis.py``) -- this module
does NOT reimplement or duplicate that tensor-construction logic.

Same status as ``edge/eval/pronostia_prep.py`` and its siblings: not on
pytest ``testpaths``' production path, not wired into any acceptance
criterion, not part of ``edge/pipeline/cycle.py`` or any P2/P3 production
wiring.

Does NOT modify ``PronostiaRunSequence`` and does NOT add fields for
pressure/humidity/gas/current to it -- those four channels are synthesized
here, at the glue boundary only, as explicit ``0.0`` placeholders paired
with ``0.0`` availability indicators (D024), never as fabricated
measurements.

``trust`` is a REQUIRED, caller-supplied argument -- this module does not
hardcode a trust value or invent a PRONOSTIA trust policy. PRONOSTIA data
was never scored by P2's ``TrustEngine``, so there is no "real" trust value
this module could assign; deciding what trust value(s) to use for
PRONOSTIA-sourced windows is left to the caller (e.g. a future training
harness), not decided here.

Does NOT perform: resampling, interpolation, feature engineering, fixed-size
windowing/chunking, normalization/scaling, HealthState labeling, RUL/ETA
labeling, training, batching, or pipeline integration. The constructed
``Window`` spans the ENTIRE supplied sequence (``start_index=0``,
``end_index=len(seq.temperature)``) -- no chunking into fixed-size training
windows is performed; that is a training-methodology question, not decided
here.
"""

from __future__ import annotations

from collections.abc import Mapping

import torch

from edge.anomaly.preprocess import Window
from edge.eval.pronostia_prep import PronostiaRunSequence
from edge.models.lstm_prognosis import build_prognosis_input
from edge.trust.engine import TrustReading


def pronostia_sequence_to_prognosis_input(
    seq: PronostiaRunSequence,
    trust: Mapping[str, TrustReading],
) -> torch.Tensor:
    """Build the D022/D024 11-column prognosis input tensor for one
    PRONOSTIA bearing run.

    Columns 0-5 (temperature, vibration, pressure, humidity, gas, current):
    ``temperature``/``vibration`` are ``seq``'s own real, unmodified values;
    ``pressure``/``humidity``/``gas``/``current`` are ``0.0`` at every
    timestep (PRONOSTIA supplies none of these -- D024).

    Columns 6-10 (vibration_observed, pressure_observed, humidity_observed,
    gas_observed, current_observed): ``vibration_observed`` is ``seq``'s own
    real D022 indicator; the four D024 indicators are ``0.0`` at every
    timestep, honestly flagging the four channels above as never observed.

    All tensor-construction logic is delegated to the existing
    ``build_prognosis_input`` -- this function only maps ``seq``'s fields
    (plus caller-supplied ``trust``) into that function's arguments.

    Raises:
        ValueError: propagated unmodified from ``build_prognosis_input`` if
            ``trust`` is missing an entry for any of the six ``CHANNELS``.
    """
    n = len(seq.temperature)
    zeros: tuple[float, ...] = (0.0,) * n

    window = Window(
        start_index=0,
        end_index=n,
        features={
            "temperature": seq.temperature,
            "vibration": seq.vibration,
            "pressure": zeros,
            "humidity": zeros,
            "gas": zeros,
            "current": zeros,
        },
    )
    availability = {
        "vibration": seq.vibration_observed,
        "pressure": zeros,
        "humidity": zeros,
        "gas": zeros,
        "current": zeros,
    }
    return build_prognosis_input(window, trust, availability)
