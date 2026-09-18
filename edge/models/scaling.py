"""Fixed per-channel scale for the digital twin (P3 · D029).

WHY THIS EXISTS: ``edge/anomaly/preprocess.py`` normalises each window to its
OWN min/max, so a normalised value means "where this sample sits within this
window's range". That is fine for anomaly detection, which only compares shapes
within a window, but it is not invertible in any useful way: recovering
engineering units from it requires that window's min/max, which are computed
from the very channel the self-healing path has decided not to trust. Using
them to denormalise a substitute for that channel is circular.

This scaler is fitted ONCE on clean-baseline data and then held fixed, so
``denormalize(normalize(x)) == x`` for any x, independent of any later window.
That is what lets a twin reconstruction become a substitutable engineering
value (FR-H1/FR-H2).

Z-score, not min-max: a real bench capture contains genuine single-sample
outliers (the BMP280 read 750.86 hPa twice against a ~917 hPa baseline,
measured 2026-09-18). A min-max fit is defined ENTIRELY by the two extreme
samples, so one dropout redefines the whole range and pushes every ordinary
reading to one end of it. Mean/std dilutes a single outlier across all n
samples, and matches the fit-time z-score form ``edge/pipeline/divergence.py``
already uses.

This is not a claim that mean/std is robust to outliers -- such a sample does
inflate the fitted std noticeably. It is the weaker, sufficient claim that it
does not relocate typical values to the edge of the scale.

Fitting on clean data only is the same leakage discipline already required of
``ConsistencyProvider``/``ChannelFlagPolicy``/``DivergenceScorer``: an attacked
or faulty segment must never define what "normal scale" means.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from app.schemas.contracts import CHANNELS

# Guards against a zero-variance channel collapsing the scale to a division by
# zero. Numerical stability only -- not a tunable parameter, and deliberately
# the same convention as edge/pipeline/divergence.py's own std floor.
_STD_FLOOR = 1e-8


class ChannelScaler:
    """Per-channel mean/std fitted on clean baseline data, then fixed.

    Must be ``fit()`` for a channel before ``normalize``/``denormalize`` is
    called for it -- an unfitted channel raises rather than silently assuming
    a unit scale, which would produce plausible-looking nonsense.
    """

    def __init__(self) -> None:
        self._mean: dict[str, float] = {}
        self._std: dict[str, float] = {}

    @property
    def fitted_channels(self) -> frozenset[str]:
        return frozenset(self._mean)

    def fit(self, values_by_channel: Mapping[str, Sequence[float]]) -> None:
        """Fit per-channel mean/std from clean-baseline values in engineering
        units. Channels absent from the mapping stay unfitted; a later call
        adds or overwrites only the channels it names.

        Raises:
            ValueError: on an unknown channel, an empty mapping, or a channel
                with no values.
        """
        if not values_by_channel:
            raise ValueError("fit() requires at least one channel's values")
        for channel, values in values_by_channel.items():
            if channel not in CHANNELS:
                raise ValueError(f"unknown channel {channel!r}; must be one of {CHANNELS}")
            observations = list(values)
            if not observations:
                raise ValueError(f"fit() requires at least one value for channel {channel!r}")
            mean = sum(observations) / len(observations)
            variance = sum((v - mean) ** 2 for v in observations) / len(observations)
            self._mean[channel] = mean
            self._std[channel] = variance**0.5 or _STD_FLOOR

    def _require_fitted(self, channel: str) -> None:
        if channel not in CHANNELS:
            raise ValueError(f"unknown channel {channel!r}; must be one of {CHANNELS}")
        if channel not in self._mean:
            raise RuntimeError(f"ChannelScaler used for {channel!r} before fit() for that channel")

    def normalize(self, channel: str, raw_value: float) -> float:
        """Engineering units -> fixed z-score scale."""
        self._require_fitted(channel)
        return (raw_value - self._mean[channel]) / self._std[channel]

    def denormalize(self, channel: str, scaled_value: float) -> float:
        """Fixed z-score scale -> engineering units.

        Exact inverse of ``normalize`` for a fitted channel. This is what turns
        a twin reconstruction into a value that can stand in for the isolated
        sensor's own reading.
        """
        self._require_fitted(channel)
        return scaled_value * self._std[channel] + self._mean[channel]
