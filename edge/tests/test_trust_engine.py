"""P2 tests — per-channel trust engine shell (math/interface only).

These validate the engine plumbing and the documented Beta math wired per
channel. They inject explicit (c, k, h) scores or deterministic stub providers
and make NO claim about real consistency/correlation/reliability, real anomaly
detection, or any P2 trust acceptance gate.
"""

import pytest
from app.schemas.contracts import CHANNELS

from edge.trust.beta import TrustBand
from edge.trust.engine import SignalProvider, TrustEngine, TrustReading


# --- deterministic stub providers (TEST ONLY — not signal definitions) -------
class ConstantSignalProvider:
    """Returns the same score for every channel."""

    def __init__(self, score: float) -> None:
        self.score = score

    def evaluate(self, channel: str) -> float:
        return self.score


class MappingSignalProvider:
    """Returns a per-channel score from an explicit mapping."""

    def __init__(self, scores: dict[str, float]) -> None:
        self.scores = scores

    def evaluate(self, channel: str) -> float:
        return self.scores[channel]


# --- initialization ----------------------------------------------------------


def test_init_one_neutral_state_per_channel():
    eng = TrustEngine()
    snap = eng.snapshot()
    assert set(snap) == set(CHANNELS)
    for ch in CHANNELS:
        assert eng.trust(ch) == pytest.approx(0.5)  # priors alpha0=beta0=1
        assert eng.band(ch) is TrustBand.SUSPICIOUS


def test_snapshot_does_not_mutate_state():
    eng = TrustEngine()
    eng.snapshot()
    eng.snapshot()
    assert eng.trust("pressure") == pytest.approx(0.5)  # untouched


# --- weighted combination (documented 0.4/0.3/0.3) --------------------------


@pytest.mark.parametrize(
    "c,k,h,expected_g",
    [
        (1.0, 1.0, 1.0, 1.0),
        (0.0, 0.0, 0.0, 0.0),
        (1.0, 0.0, 0.0, 0.4),
        (0.0, 1.0, 0.0, 0.3),
        (0.0, 0.0, 1.0, 0.3),
        (0.5, 0.5, 0.5, 0.5),
    ],
)
def test_update_channel_reports_weighted_g(c, k, h, expected_g):
    eng = TrustEngine()
    r = eng.update_channel("current", c, k, h)
    assert isinstance(r, TrustReading)
    assert r.channel == "current"
    assert r.g == pytest.approx(expected_g)


# --- per-channel independence ------------------------------------------------


def test_channels_are_independent():
    eng = TrustEngine()
    eng.update_channel("pressure", 0.0, 0.0, 0.0)  # drive pressure down only
    assert eng.trust("pressure") < 0.5
    for ch in CHANNELS:
        if ch != "pressure":
            assert eng.trust(ch) == pytest.approx(0.5)  # others untouched


def test_update_all_updates_only_supplied_channels():
    eng = TrustEngine()
    eng.update_all({"gas": (1.0, 1.0, 1.0), "vibration": (0.0, 0.0, 0.0)})
    assert eng.trust("gas") > 0.5
    assert eng.trust("vibration") < 0.5
    assert eng.trust("temperature") == pytest.approx(0.5)


# --- band transitions --------------------------------------------------------


def test_g1_moves_into_trusted():
    eng = TrustEngine()
    r = eng.update_channel("temperature", 1.0, 1.0, 1.0)  # g=1
    assert r.trust == pytest.approx(1.7 / 2.4, abs=1e-6)  # 0.708...
    assert r.band is TrustBand.TRUSTED


def test_g0_moves_into_malicious():
    eng = TrustEngine()
    r = eng.update_channel("temperature", 0.0, 0.0, 0.0)  # g=0
    assert r.trust == pytest.approx(0.7 / 2.4, abs=1e-6)  # 0.291...
    assert r.band is TrustBand.MALICIOUS


def test_mid_evidence_stays_suspicious():
    eng = TrustEngine()
    r = eng.update_channel("humidity", 0.5, 0.5, 0.5)  # g=0.5
    assert r.trust == pytest.approx(0.5)
    assert r.band is TrustBand.SUSPICIOUS


# --- multiple windows --------------------------------------------------------


def test_multiple_windows_climb_monotonically():
    eng = TrustEngine()
    trail = [eng.update_channel("current", 1.0, 1.0, 1.0).trust for _ in range(4)]
    assert trail == sorted(trail)  # monotonic climb under g=1
    assert trail[0] >= 0.7 and eng.band("current") is TrustBand.TRUSTED


def test_multiple_windows_drop_under_zero_evidence():
    eng = TrustEngine()
    trail = [eng.update_channel("current", 0.0, 0.0, 0.0).trust for _ in range(3)]
    assert trail == sorted(trail, reverse=True)  # monotonic drop under g=0
    assert eng.band("current") is TrustBand.MALICIOUS


# --- injected stub signals ---------------------------------------------------


def test_stub_providers_satisfy_protocol():
    assert isinstance(ConstantSignalProvider(0.5), SignalProvider)
    assert isinstance(MappingSignalProvider({}), SignalProvider)


def test_update_from_constant_providers():
    eng = TrustEngine()
    zero = ConstantSignalProvider(0.0)
    out = eng.update_from_providers(zero, zero, zero)  # g=0 everywhere
    assert set(out) == set(CHANNELS)
    for ch in CHANNELS:
        assert out[ch].g == pytest.approx(0.0)
        assert eng.band(ch) is TrustBand.MALICIOUS


def test_update_from_mapping_providers_per_channel():
    eng = TrustEngine()
    c = MappingSignalProvider({ch: (1.0 if ch == "pressure" else 0.0) for ch in CHANNELS})
    k = ConstantSignalProvider(0.0)
    h = ConstantSignalProvider(0.0)
    out = eng.update_from_providers(c, k, h)
    assert out["pressure"].g == pytest.approx(0.4)  # only c=1 on pressure
    assert out["gas"].g == pytest.approx(0.0)


# --- validation --------------------------------------------------------------


def test_unknown_channel_rejected_on_update():
    with pytest.raises(ValueError):
        TrustEngine().update_channel("flow", 1.0, 1.0, 1.0)


@pytest.mark.parametrize("accessor", ["trust", "band"])
def test_unknown_channel_rejected_on_access(accessor):
    eng = TrustEngine()
    with pytest.raises(ValueError):
        getattr(eng, accessor)("flow")


@pytest.mark.parametrize("c,k,h", [(1.5, 0.0, 0.0), (0.0, -0.1, 0.0), (0.0, 0.0, 2.0)])
def test_out_of_range_signal_rejected(c, k, h):
    with pytest.raises(ValueError):
        TrustEngine().update_channel("current", c, k, h)
