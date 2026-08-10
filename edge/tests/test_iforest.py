"""P2 tests — real Isolation Forest detector (FUNCTIONAL / interface only).

These are functional tests of the detector plumbing: fit/score/flag mechanics,
severity range, determinism, clean-baseline behaviour, and OBVIOUS synthetic
anomalies (values far outside the training cluster). They are NOT P2 acceptance
or dataset validation: they do NOT establish detection accuracy, cross-sensor
spoof detection, or any O3/O10 gate — those require SWaT/WADI/TEP (U07). All
thresholds/params below are TEST FIXTURES ONLY, not project specifications.

Skipped entirely when scikit-learn is unavailable (e.g. CI until sklearn is
added to CI deps) — same skip-pattern as the broker integration tests.
"""

import random

import pytest

pytest.importorskip("sklearn")

from app.schemas.contracts import CHANNELS  # noqa: E402

from edge.anomaly.attribution import AttributionEngine, PhysicsCheck  # noqa: E402
from edge.anomaly.detector import AnomalyDetector  # noqa: E402
from edge.anomaly.iforest import IsolationForestDetector  # noqa: E402
from edge.anomaly.pipeline import P2Pipeline  # noqa: E402
from edge.anomaly.preprocess import Preprocessor, Window  # noqa: E402
from edge.trust.engine import TrustEngine  # noqa: E402

WINDOW = 30
THRESHOLD_FIXTURE = 0.5  # TEST FIXTURE ONLY — not a project threshold
SEED_FIXTURE = 0  # TEST FIXTURE ONLY — determinism


def _win(fill: float) -> Window:
    return Window(0, WINDOW, {ch: tuple(fill for _ in range(WINDOW)) for ch in CHANNELS})


def _clean_windows(n: int, seed: int = 0) -> list[Window]:
    rng = random.Random(seed)
    out = []
    for _ in range(n):
        feats = {
            ch: tuple(0.5 + rng.uniform(-0.05, 0.05) for _ in range(WINDOW)) for ch in CHANNELS
        }
        out.append(Window(0, WINDOW, feats))
    return out


def _detector() -> IsolationForestDetector:
    return IsolationForestDetector(flag_threshold=THRESHOLD_FIXTURE, random_state=SEED_FIXTURE)


# --- protocol / fit ----------------------------------------------------------


def test_satisfies_anomaly_detector_protocol():
    assert isinstance(_detector(), AnomalyDetector)


def test_fit_sets_fitted_and_stores_distribution():
    det = _detector()
    assert det.fitted is False
    det.fit(_clean_windows(50))
    assert det.fitted is True


def test_score_and_flag_before_fit_raise():
    det = _detector()
    with pytest.raises(RuntimeError):
        det.score(_win(0.5))
    with pytest.raises(RuntimeError):
        det.flag(_win(0.5))


def test_fit_empty_rejected():
    with pytest.raises(ValueError):
        _detector().fit([])


# --- severity range ----------------------------------------------------------


def test_severity_in_unit_interval():
    det = _detector()
    det.fit(_clean_windows(200))
    for w in (_win(0.5), _win(5.0), _win(-3.0), _clean_windows(1, seed=99)[0]):
        s = det.score(w)
        assert 0.0 <= s <= 1.0


# --- determinism -------------------------------------------------------------


def test_deterministic_with_fixed_random_state():
    train = _clean_windows(200)
    probe = _win(3.0)
    d1 = _detector()
    d1.fit(train)
    d2 = _detector()
    d2.fit(train)
    assert d1.score(probe) == d2.score(probe)  # same seed -> identical


# --- clean-baseline behaviour ------------------------------------------------


def test_centroid_window_is_low_severity():
    det = _detector()
    det.fit(_clean_windows(200))
    # The training cluster centre (all 0.5) is the most-normal point.
    assert det.score(_win(0.5)) < 0.5
    assert det.flag(_win(0.5)) is False  # below the fixture threshold


# --- obvious synthetic anomaly ----------------------------------------------


def test_obvious_anomaly_scores_higher_and_flags():
    det = _detector()
    det.fit(_clean_windows(200))
    clean_sev = det.score(_win(0.5))
    anom_sev = det.score(_win(5.0))  # far outside the training cluster
    assert anom_sev == 1.0  # more anomalous than every clean window
    assert anom_sev > clean_sev  # higher severity == more anomalous
    assert det.flag(_win(5.0)) is True


def test_larger_deviation_not_less_anomalous():
    det = _detector()
    det.fit(_clean_windows(200))
    near = det.score(_win(0.7))
    far = det.score(_win(5.0))
    assert far >= near  # monotone: bigger departure not scored more normal


# --- flag threshold config ---------------------------------------------------


@pytest.mark.parametrize("bad", [-0.1, 1.1])
def test_flag_threshold_validated(bad):
    with pytest.raises(ValueError):
        IsolationForestDetector(flag_threshold=bad)


def test_threshold_controls_flag():
    det_hi = IsolationForestDetector(flag_threshold=1.0, random_state=SEED_FIXTURE)
    det_hi.fit(_clean_windows(200))
    # severity==1.0 only for beyond-max anomalies; a clean centroid stays under.
    assert det_hi.flag(_win(0.5)) is False


# --- drop-in behind the pipeline interface -----------------------------------


class _StubRule:
    def check(self, window: Window) -> PhysicsCheck:
        return PhysicsCheck(violated=False, suspect_channel=None, reason="")


class _NoFlags:
    def flags(self, window, anomaly):
        return {ch: False for ch in CHANNELS}


class _Const:
    def __init__(self, s: float) -> None:
        self.s = s

    def evaluate(self, channel: str) -> float:
        return self.s


def _ts(i: int) -> str:
    return f"2026-08-10T00:00:{i:02d}.000Z"


def test_isolation_forest_drops_into_pipeline():
    from app.schemas.build import build_telemetry

    det = _detector()
    det.fit(_clean_windows(200))
    pipe = P2Pipeline(
        preprocessor=Preprocessor(median_kernel=1, low_pass_alpha=1.0, window_size=WINDOW),
        detector=det,
        trust_engine=TrustEngine(),
        attribution_engine=AttributionEngine(_StubRule()),
        c_provider=_Const(1.0),
        k_provider=_Const(1.0),
        h_provider=_Const(1.0),
        flag_policy=_NoFlags(),
    )
    frames = [
        build_telemetry("pump-01", _ts(i), {ch: 10.0 + i for ch in CHANNELS}, i)
        for i in range(WINDOW)
    ]
    (outcome,) = pipe.process(frames)
    assert 0.0 <= outcome.anomaly.severity <= 1.0
    assert isinstance(outcome.anomaly.flag, bool)
