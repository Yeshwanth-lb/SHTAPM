"""P2 tests — signal-agnostic Beta-reputation math (U01 foundation).

These validate ONLY the mathematics of the approved Beta recursion driven by a
supplied evidence value ``g``. They deliberately make NO claim about real spoof
detection, real sensor consistency, or any physics — ``g`` is injected directly.
The definitions of c/k/h are out of scope (U01/U02, undecided).

Traces correspond to the pre-approval analysis for lambda = 0.7:
  * healthy (g=1)        -> Trusted (>=0.7) within one window, stays there
  * strong spoof (g=0)   -> T_3 ~= 0.343 < 0.4 within 3 windows (from full trust)
  * recovery (g=1)       -> climbs back toward baseline, >=0.7 within 3 windows
  * collusion cap (g=0.7)-> converges to 0.7, cannot reach full trust (h term)
"""

import pytest

from edge.trust.beta import (
    TRUSTED_MIN,
    BetaState,
    TrustBand,
    classify,
    combine_g,
)


def _drive(state: BetaState, g: float, n: int) -> list[float]:
    """Apply ``g`` for ``n`` windows, returning the trust after each."""
    return [state.update(g) for _ in range(n)]


def _full_trust_state() -> BetaState:
    """A near-fully-trusted sensor: warm up with g=1 until steady (alpha->10/3,
    beta->0). 20 windows is plenty (0.7**20 ~= 8e-4)."""
    s = BetaState()
    _drive(s, 1.0, 20)
    assert s.trust > 0.99  # effectively full trust before the spoof
    return s


# --- priors / basic invariants ----------------------------------------------


def test_priors_give_neutral_half():
    s = BetaState()
    assert s.alpha == 1.0 and s.beta == 1.0
    assert s.trust == pytest.approx(0.5)
    assert s.band is TrustBand.SUSPICIOUS


def test_trust_always_in_unit_interval():
    s = BetaState()
    for g in (0.0, 0.25, 0.5, 0.75, 1.0):
        t = s.update(g)
        assert 0.0 <= t <= 1.0


def test_update_returns_new_trust():
    s = BetaState()
    returned = s.update(1.0)
    assert returned == pytest.approx(s.trust)


# --- combine_g (documented weights 0.4/0.3/0.3) ------------------------------


@pytest.mark.parametrize(
    "c,k,h,expected",
    [
        (1.0, 1.0, 1.0, 1.0),
        (0.0, 0.0, 0.0, 0.0),
        (1.0, 0.0, 0.0, 0.4),  # consistency only
        (0.0, 1.0, 0.0, 0.3),  # correlation only
        (0.0, 0.0, 1.0, 0.3),  # reliability only
        (1.0, 1.0, 0.0, 0.7),  # collusion: c+k faked, no reliability
    ],
)
def test_combine_g_weights(c, k, h, expected):
    assert combine_g(c, k, h) == pytest.approx(expected)


# --- classification bands (FR-T3) -------------------------------------------


def test_band_boundaries():
    assert classify(0.70) is TrustBand.TRUSTED
    assert classify(0.6999) is TrustBand.SUSPICIOUS
    assert classify(0.40) is TrustBand.SUSPICIOUS  # 0.4 is NOT malicious (strict <)
    assert classify(0.3999) is TrustBand.MALICIOUS
    assert classify(1.0) is TrustBand.TRUSTED
    assert classify(0.0) is TrustBand.MALICIOUS


# --- documented traces -------------------------------------------------------


def test_healthy_reaches_and_stays_trusted():
    # g=1 from the neutral prior: Trusted within one window, then stays.
    s = BetaState()
    t1 = s.update(1.0)
    assert t1 == pytest.approx(1.7 / 2.4, abs=1e-6)  # 0.70833...
    assert t1 >= 0.7 and s.band is TrustBand.TRUSTED
    for t in _drive(s, 1.0, 10):
        assert t >= 0.7  # never drops back out of Trusted


def test_strong_spoof_drops_below_0_4_within_3_windows():
    s = _full_trust_state()
    t = _drive(s, 0.0, 3)
    # Closed form from full trust: T_n ~= lambda**n -> 0.7, 0.49, 0.343.
    assert t[0] == pytest.approx(0.70, abs=0.01)
    assert t[1] == pytest.approx(0.49, abs=0.01)
    assert t[2] == pytest.approx(0.343, abs=0.01)
    assert t[2] < 0.4 and s.band is TrustBand.MALICIOUS


def test_recovery_climbs_back_toward_baseline_within_3_windows():
    s = _full_trust_state()
    _drive(s, 0.0, 3)  # spoof it down to ~0.343
    assert s.trust < 0.4
    r = _drive(s, 1.0, 3)  # spoof stops, healthy evidence resumes
    assert r[0] == pytest.approx(0.540, abs=0.01)
    assert r[1] == pytest.approx(0.678, abs=0.01)
    assert r[2] == pytest.approx(0.775, abs=0.01)
    assert r == sorted(r)  # monotonic climb toward baseline (FR-T4)
    assert r[2] >= 0.7 and s.band is TrustBand.TRUSTED


def test_collusion_reliability_cap_prevents_full_trust():
    # Faked consistency + correlation (c=k=1) but zero reliability (h=0):
    # g = 0.4 + 0.3 + 0.0 = 0.7. Steady-state trust converges to g = 0.7 and can
    # NEVER reach full trust — the 0.3 reliability weight is the ceiling.
    g = combine_g(1.0, 1.0, 0.0)
    assert g == pytest.approx(0.7)
    s = BetaState()
    trail = _drive(s, g, 40)
    assert all(t <= 0.7 + 1e-9 for t in trail)  # capped, never exceeds 0.7
    assert trail[-1] == pytest.approx(0.7, abs=1e-3)  # converges to the cap
    # Approaches the 0.7 ceiling from below and stays just under it: the 0.3
    # reliability weight keeps the sensor out of solid Trusted -> never full trust.
    assert s.trust < TRUSTED_MIN
    assert s.band is TrustBand.SUSPICIOUS


# --- validation --------------------------------------------------------------


@pytest.mark.parametrize("bad", [-0.01, 1.01, 2.0, -1.0])
def test_update_rejects_out_of_range_g(bad):
    with pytest.raises(ValueError):
        BetaState().update(bad)


@pytest.mark.parametrize("bad", [-0.1, 1.5])
def test_combine_g_rejects_out_of_range(bad):
    with pytest.raises(ValueError):
        combine_g(bad, 0.0, 0.0)


@pytest.mark.parametrize("lam", [0.0, -0.1, 1.5])
def test_invalid_forgetting_rejected(lam):
    with pytest.raises(ValueError):
        BetaState(forgetting=lam)


@pytest.mark.parametrize("a,b", [(0.0, 1.0), (1.0, 0.0), (-1.0, 1.0)])
def test_non_positive_priors_rejected(a, b):
    with pytest.raises(ValueError):
        BetaState(alpha=a, beta=b)
