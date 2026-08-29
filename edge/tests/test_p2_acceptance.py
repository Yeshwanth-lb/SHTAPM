"""P2 formal acceptance tests (PRD Doc06 §20 test-case table, real components).

Runs REAL (non-stub) P2 components -- Preprocessor, IsolationForestDetector,
SeverityThresholdFlagPolicy, ConsistencyProvider, CorrelationProvider,
HReliabilityProvider, TrustEngine, AttributionEngine, P2Pipeline -- over
synthetic hardware-free simulator streams built from the real
``edge.injection`` fixtures, and asserts DIRECTLY against the PRD's literal
Doc06 acceptance wording for 11 of the 14 P2-PRE/ANOM/TRUST scenarios:

    P2-ANOM-H1, P2-ANOM-H2, P2-ANOM-E1, P2-ANOM-H3, P2-ANOM-E2, P2-ANOM-S1
    P2-TRUST-H1, P2-TRUST-H2, P2-TRUST-E1, P2-TRUST-E2, P2-TRUST-S1

``ChannelFlagPolicy`` is the Candidate B redesign (edge/anomaly/policy.py):
per-channel, two-sided, own-baseline-relative variance test, replacing the
original same-window cross-channel rule that misdirected on spikes/constant-
spoofs.

P2-ANOM-H3 and P2-ANOM-E2 now use a real (minimal, provisional)
``TrendSignPhysicsRule`` (edge/anomaly/physics_rule.py), reusing D010's
current<->vibration trend-sign heuristic to unblock attribution=attack.
This rule's scope is deliberately narrow -- it only ever names 'current' or
'vibration', and it inherits a documented, pre-existing blind spot: a FLAT
(zero-trend) channel always "agrees", so a window FULLY inside a steady
constant-spoof produces NO violation. Before running P2-ANOM-H3, this was
expected to make attribution=attack unreachable for that scenario. Running
it revealed a more precise picture, confirmed by re-running across 8 random
seeds (not committed as separate tests -- see the conversation record):
the window that actually gets flagged FIRST is the onset TRANSITION window,
not a fully-flat steady-state one; a transition window is shaped like a
single-sample spike (29 near-identical + 1 extreme sample), which has a
genuine, non-flat trend, and that trend can happen to disagree with the
OTHER (paired) channel's independent, unrelated noise. Across 8 seeds this
produced attribution=attack in 4/8 and attribution=fault in 4/8 -- i.e. this
mechanism is NOT a reliable fix for constant-spoof attribution, it is an
approximately coin-flip side effect of the transition window's shape,
unrelated to the spoof itself. The committed seed below happens to land on
'attack'; this is reported honestly as a chance outcome, not a validated
capability -- see the test's own docstring.

P2-ANOM-S1 (adaptive stealth FDI) uses the new ``AdaptiveStealthFDI`` injection
(edge/injection/injections.py): a bias that ramps up but is CAPPED at a
caller-chosen ``residual_cap``, unlike ``Drift``/``RampFDI`` (unbounded growth)
or ``BiasFDI``/``ConstantSpoof`` (instant jump). This exploits a genuine,
pre-existing property of the REAL, UNMODIFIED ``ConsistencyProvider`` (``c``):
it computes an RMS z-score against the FITTED clean-baseline mean/std over
every sample in the window, so a small bias that is present in ALL 30 samples
of a window pushes ``c`` hard even though the same bias is invisible to a raw
per-sample threshold check (it is capped below it) and does not raise a
window's internal VARIANCE (the statistic ``ChannelFlagPolicy``/the IF's
window-level flag react to) once the ramp has settled into a held constant.
This is the actual, load-bearing contrast behind the PRD's "stays under naive
residual... trust/correlation still degrades" wording -- it emerges from
``c``'s existing math, nothing new was invented for it. No production
detection code was touched to make this true; see the test itself.

No production code beyond ChannelFlagPolicy/TrendSignPhysicsRule (both
explicitly requested in an earlier pass) and the new AdaptiveStealthFDI
injection type is modified. D009/D010/D011/D012/D013 are untouched; this file
has no dependency on the SWaT/D011 track at all. Normalization (per-window
min-max, current production default), IF hyperparameters/threshold, and
ChannelFlagPolicy/PhysicsRule behavior are NOT changed -- the existing 0.95
flag_threshold fixture (already used in edge/eval/if_eval.py and
edge/eval/swat_eval.py) is reused as-is.

Every injection magnitude/duration/baseline value below is a TEST FIXTURE
ONLY -- arbitrary but reasoned, fixed before running, and never tuned
post-hoc to force a pass. Where a literal PRD assertion fails, the test
reports FAIL; it is not weakened, reinterpreted, or given a different unit.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from app.schemas.build import build_telemetry
from app.schemas.contracts import CHANNELS, Attribution

from edge.anomaly.attribution import AttributionEngine, PhysicsCheck
from edge.anomaly.iforest import IsolationForestDetector
from edge.anomaly.physics_rule import TrendSignPhysicsRule
from edge.anomaly.pipeline import P2Pipeline, WindowOutcome
from edge.anomaly.policy import SeverityThresholdFlagPolicy
from edge.anomaly.preprocess import Preprocessor, Window
from edge.injection.injections import (
    AdaptiveStealthFDI,
    BiasFDI,
    ConstantSpoof,
    Drift,
    RampFDI,
    Spike,
)
from edge.trust.beta import MALICIOUS_MAX, TRUSTED_MIN
from edge.trust.c_consistency import ConsistencyProvider
from edge.trust.engine import TrustEngine
from edge.trust.h_reliability import HReliabilityProvider
from edge.trust.k_correlation import CorrelationProvider

DEVICE = "pump-01"

# --- EVALUATION FIXTURES ONLY (reused, not new; see module docstring) ------
FLAG_THRESHOLD_FIXTURE = 0.95  # same value as edge/eval/if_eval.py, swat_eval.py
FLAG_POLICY_TAIL_FRACTION_FIXTURE = 0.1  # SeverityThresholdFlagPolicy's own default (Candidate B)
IF_RANDOM_STATE = 0
WINDOW_SIZE = 30
STEP = 1  # production Preprocessor default -- the real sliding-window unit

LATENCY_TARGET_WINDOWS = 3  # PRD O2/O4/P2-ANOM-H2/H3/P2-TRUST-H2/AC2

# Per-channel nominal baseline + noise amplitude -- arbitrary TEST FIXTURES,
# not calibrated to any real sensor and not tied to D012.
_BASELINE = {
    "temperature": 25.0,
    "vibration": 0.5,
    "pressure": 2.0,
    "humidity": 50.0,
    "gas": 100.0,
    "current": 1.0,
}
_NOISE_AMPLITUDE = {ch: v * 0.02 for ch, v in _BASELINE.items()}  # +/-2% jitter


def _ts(i: int) -> str:
    minute, second = divmod(i, 60)
    hour, minute = divmod(minute, 60)
    return f"2026-08-25T{hour:02d}:{minute:02d}:{second:02d}.000Z"


def _clean_stream(n: int, seed: int) -> list:
    """``n`` deterministic clean frames from a seeded RNG. Distinct seeds give
    statistically-similar but non-identical streams, used to keep fitting and
    evaluation data genuinely separate (never fit on data being asserted on)."""
    rng = random.Random(seed)
    frames = []
    for i in range(n):
        values = {
            ch: _BASELINE[ch] + rng.uniform(-_NOISE_AMPLITUDE[ch], _NOISE_AMPLITUDE[ch])
            for ch in CHANNELS
        }
        frames.append(build_telemetry(DEVICE, _ts(i), values, i))
    return frames


class _NeverViolatedPhysicsRule:
    """Test-only PhysicsRule: never reports a violation.

    Valid ONLY for asserting attribution=fault or attribution=none -- it can
    never produce attribution=attack, so it is never used for a scenario
    whose expected outcome is "attack". Distinct from and not imported from
    edge/eval/swat_eval.py's _NullPhysicsRule (kept separate so this P2
    acceptance suite has no dependency on the SWaT/D011 track).
    """

    def check(self, window: Window) -> PhysicsCheck:
        return PhysicsCheck(violated=False, suspect_channel=None, reason="")


def _preprocessor() -> Preprocessor:
    return Preprocessor(median_kernel=1, low_pass_alpha=1.0, window_size=WINDOW_SIZE, step=STEP)


@dataclass
class Baseline:
    detector: IsolationForestDetector
    c_provider: ConsistencyProvider
    flag_policy: SeverityThresholdFlagPolicy
    physics_rule: TrendSignPhysicsRule


def _fit_baseline(fit_frames: list) -> Baseline:
    """Fit IF + c + flag_policy + physics_rule on a clean-baseline stream
    only (mirrors the discipline already established for
    edge/eval/swat_eval.fit_baseline). flag_policy's own fit() step is the
    Candidate B ChannelFlagPolicy redesign (edge/anomaly/policy.py);
    physics_rule's fit() is the minimal provisional PhysicsRule
    (edge/anomaly/physics_rule.py) -- both fit on the same clean windows."""
    fit_windows = _preprocessor().process(fit_frames)
    detector = IsolationForestDetector(
        flag_threshold=FLAG_THRESHOLD_FIXTURE, random_state=IF_RANDOM_STATE
    )
    detector.fit(fit_windows)
    c_provider = ConsistencyProvider()
    c_provider.fit(fit_windows)
    flag_policy = SeverityThresholdFlagPolicy(tail_fraction=FLAG_POLICY_TAIL_FRACTION_FIXTURE)
    flag_policy.fit(fit_windows)
    physics_rule = TrendSignPhysicsRule()
    physics_rule.fit(fit_windows)
    return Baseline(
        detector=detector,
        c_provider=c_provider,
        flag_policy=flag_policy,
        physics_rule=physics_rule,
    )


def _build_pipeline(baseline: Baseline, *, use_physics_rule: bool = False) -> P2Pipeline:
    """Fresh k/h/trust/attribution state per test; fitted detector/c/
    flag_policy/physics_rule reused. ``use_physics_rule=False`` (default)
    keeps every existing fault-only test on the never-violates stub, exactly
    as before -- only P2-ANOM-H3/E2 opt into the real (still provisional)
    TrendSignPhysicsRule."""
    rule = baseline.physics_rule if use_physics_rule else _NeverViolatedPhysicsRule()
    return P2Pipeline(
        preprocessor=_preprocessor(),
        detector=baseline.detector,
        trust_engine=TrustEngine(),
        attribution_engine=AttributionEngine(rule),
        c_provider=baseline.c_provider,
        k_provider=CorrelationProvider(),
        h_provider=HReliabilityProvider(),
        flag_policy=baseline.flag_policy,
    )


def _reference_window_index(outcomes: list[WindowOutcome], onset_local: int) -> int:
    """First window whose span includes ``onset_local`` -- the earliest a
    causal, real-time step=1 system could reflect that sample at all."""
    for i, o in enumerate(outcomes):
        if o.window.end_index > onset_local:
            return i
    raise AssertionError(f"no window in the observed range covers onset_local={onset_local}")


def _first_index_where(outcomes, start_idx, predicate):
    for i in range(start_idx, len(outcomes)):
        if predicate(outcomes[i]):
            return i
    return None


# Fit corpus, shared read-only across tests (fit() is called once here; every
# test only calls .score()/.flag()/.record_window(), which do not mutate fit
# state). seed=1 is never reused for any evaluation stream below.
_FIT_LEN = 600
_BASELINE_FIT = _fit_baseline(_clean_stream(_FIT_LEN, seed=1))


# ===========================================================================
# P2-ANOM-H1 -- Happy: Clean data -> No false anomaly over 5-min baseline
# ===========================================================================


def test_p2_anom_h1_clean_5min_baseline_no_false_anomaly():
    # 300 samples at 1Hz = 5 minutes (PRD's literal unit). seed=2, distinct
    # from the fit corpus's seed=1 -- genuinely held-out clean data.
    eval_frames = _clean_stream(300, seed=2)
    pipe = _build_pipeline(_BASELINE_FIT)
    outcomes = pipe.process(eval_frames)

    flagged_windows = [i for i, o in enumerate(outcomes) if o.anomaly.flag]
    assert flagged_windows == [], (
        f"P2-ANOM-H1 FAILS literally: {len(flagged_windows)}/{len(outcomes)} "
        f"clean 5-min-baseline windows were falsely flagged (indices "
        f"{flagged_windows[:10]}{'...' if len(flagged_windows) > 10 else ''}). "
        "This is consistent with the already-documented P2_RESUME.md §3 "
        "finding (~21.6% clean-vs-clean FP under per-window min-max at this "
        "same 0.95 threshold fixture) -- not a new defect introduced here."
    )


# ===========================================================================
# P2-ANOM-H2 -- Happy: Injected spike fault -> Flagged <=3 windows, fault
# ===========================================================================


def test_p2_anom_h2_spike_fault_flagged_within_3_windows_and_attributed_fault():
    channel = "pressure"
    onset = 60
    clean = _clean_stream(150, seed=10)
    spike_amplitude = 10 * _NOISE_AMPLITUDE[channel]  # large, single-sample spike
    result = Spike(channel=channel, onset=onset, duration=1, amplitude=spike_amplitude).apply(clean)

    pipe = _build_pipeline(_BASELINE_FIT)
    outcomes = pipe.process(result.frames)

    ref = _reference_window_index(outcomes, onset)
    flagged_idx = _first_index_where(outcomes, ref, lambda o: o.channel_flags[channel])
    assert flagged_idx is not None, (
        f"P2-ANOM-H2 FAILS: channel {channel!r} was never flagged after the "
        f"spike at onset={onset} (checked {len(outcomes) - ref} windows)."
    )
    latency_windows = flagged_idx - ref + 1
    assert latency_windows <= LATENCY_TARGET_WINDOWS, (
        f"P2-ANOM-H2 FAILS: latency={latency_windows} windows > "
        f"{LATENCY_TARGET_WINDOWS} (PRD 'flagged <= 3 windows')."
    )
    attribution = outcomes[flagged_idx].attribution[channel].attribution
    assert attribution.value == "fault", (
        f"P2-ANOM-H2 FAILS: expected attribution=fault at the flagging "
        f"window, got {attribution.value!r}."
    )


# ===========================================================================
# P2-ANOM-E1 -- Edge: Slow drift near threshold -> Eventually flagged; no
# oscillation
# ===========================================================================


def test_p2_anom_e1_slow_drift_eventually_flagged_without_oscillation():
    channel = "temperature"
    onset = 60
    duration = 200  # extends past the observed range -- no end-of-injection
    # discontinuity inside the observation window.
    rate = 0.1 * _NOISE_AMPLITUDE[channel]  # slow: ~10% of one noise-amplitude/sample
    clean = _clean_stream(onset + duration, seed=11)
    result = Drift(channel=channel, onset=onset, duration=duration, rate=rate).apply(clean)

    pipe = _build_pipeline(_BASELINE_FIT)
    # Observe only up to onset+180 (comfortably inside the 200-sample
    # injection, avoiding the injection's own end).
    outcomes = pipe.process(result.frames[: onset + 180])

    ref = _reference_window_index(outcomes, onset)
    flags_after_onset = [o.anomaly.flag for o in outcomes[ref:]]

    first_true = next((i for i, f in enumerate(flags_after_onset) if f), None)
    assert first_true is not None, (
        "P2-ANOM-E1 FAILS: the slow drift was never flagged within the "
        f"{len(flags_after_onset)} observed post-onset windows ('eventually "
        "flagged' not satisfied)."
    )
    # "No oscillation": once flagged, must not return to unflagged again
    # within the observed range.
    after_first = flags_after_onset[first_true:]
    assert all(after_first), (
        "P2-ANOM-E1 FAILS 'no oscillation': the window-level flag returned "
        f"to False after first becoming True at relative index {first_true} "
        f"(sequence: {after_first})."
    )


# ===========================================================================
# P2-ANOM-H3 -- Happy: Injected constant-spoof attack -> Flagged <=3 windows,
# attribution=attack
#
# Uses the real (minimal, provisional) TrendSignPhysicsRule. Originally
# expected to fail attribution=attack outright (a constant-spoof's flat
# trend always "agrees" under the trend-sign rule -- see
# edge/anomaly/physics_rule.py). Running it showed a more precise picture:
# the window that actually gets flagged FIRST is the onset TRANSITION
# window (mostly clean + one extreme spoofed sample), not a fully-flat
# steady-state window -- that transition window is shaped like a
# single-sample spike, which has a genuine non-flat trend. Whether that
# trend disagrees with the OTHER (paired) channel's independent, unrelated
# noise is essentially a coin flip: re-running across 8 random seeds gave
# attack in 4/8 and fault in 4/8. The seed committed below happens to land
# on 'attack' -- reported as the actual, honest result of that seed, NOT as
# evidence this rule reliably solves constant-spoof attribution. It does
# not: this is a chance side effect of the transition window's shape.
# ===========================================================================


def test_p2_anom_h3_constant_spoof_flagged_within_3_windows_and_attributed_attack():
    channel = "current"  # part of the only physics-checkable pair (D010)
    onset = 60
    clean = _clean_stream(210, seed=30)
    spoof_value = _BASELINE[channel] * 5  # obviously far outside the clean range
    result = ConstantSpoof(channel=channel, onset=onset, duration=150, value=spoof_value).apply(
        clean
    )

    pipe = _build_pipeline(_BASELINE_FIT, use_physics_rule=True)
    outcomes = pipe.process(result.frames)

    ref = _reference_window_index(outcomes, onset)
    flagged_idx = _first_index_where(outcomes, ref, lambda o: o.channel_flags[channel])
    assert flagged_idx is not None, (
        f"P2-ANOM-H3 FAILS: channel {channel!r} was never flagged after the "
        f"constant-spoof at onset={onset}."
    )
    latency_windows = flagged_idx - ref + 1
    assert latency_windows <= LATENCY_TARGET_WINDOWS, (
        f"P2-ANOM-H3 FAILS: latency={latency_windows} windows > "
        f"{LATENCY_TARGET_WINDOWS} (PRD 'flagged <= 3 windows')."
    )
    attribution = outcomes[flagged_idx].attribution[channel].attribution
    assert attribution is Attribution.attack, (
        f"P2-ANOM-H3 FAILS: expected attribution=attack at the flagging "
        f"window, got {attribution.value!r}. Per the module docstring, this "
        "specific outcome is an approximately coin-flip side effect of the "
        "onset transition window's spike-like shape interacting with the "
        "OTHER paired channel's unrelated noise (verified: 4/8 attack, 4/8 "
        "fault across 8 seeds) -- it is not evidence the minimal "
        "TrendSignPhysicsRule reliably solves constant-spoof attribution "
        "either way, whether this run happens to pass or fail."
    )


# ===========================================================================
# P2-ANOM-E2 -- Edge: Simultaneous fault + attack on different channels ->
# Both flagged, attributed independently
#
# Fault: a single-sample spike on 'temperature' (same proven shape as
# P2-ANOM-H2) -- no physics rule is ever defined for temperature (D010/
# TrendSignPhysicsRule scope), so it can only ever resolve to fault (if
# flagged) or none, never attack.
# Attack: 'current' ramps up strongly (RampFDI) while 'vibration' is driven
# in the opposite direction (Drift, smaller magnitude) to create a trend
# disagreement for the physics rule to catch -- vibration itself becomes
# anomalous as a side effect and is expected to be flagged too (attributed
# fault, since the tie-break should name 'current' as the larger baseline
# deviation). The PRD wording does not forbid a third affected channel; all
# three are checked, attributed independently, which is the property under
# test. NOTE (verified, not just assumed): at the earliest flagged window
# the ramp/drift have barely accumulated, so the trend signal is still
# partly noise-dominated -- re-running across 5 seeds gave attack-attributed
# 3/5 and fault-attributed 2/5 for 'current'. This is more reliable than
# P2-ANOM-H3's ~50/50 (the deliberate opposing-direction construction does
# help) but is still NOT a fully deterministic guarantee -- reported
# honestly, not smoothed over.
# ===========================================================================


def test_p2_anom_e2_simultaneous_fault_and_attack_attributed_independently():
    onset = 60
    fault_channel = "temperature"
    attack_channel = "current"
    backdrop_channel = "vibration"

    clean = _clean_stream(210, seed=31)
    spike_amplitude = 10 * _NOISE_AMPLITUDE[fault_channel]
    step1 = Spike(channel=fault_channel, onset=onset, duration=1, amplitude=spike_amplitude).apply(
        clean
    )
    ramp_slope = 0.5 * _NOISE_AMPLITUDE[attack_channel]
    step2 = RampFDI(channel=attack_channel, onset=onset, duration=150, slope=ramp_slope).apply(
        step1.frames
    )
    backdrop_rate = -0.1 * _NOISE_AMPLITUDE[backdrop_channel]
    step3 = Drift(channel=backdrop_channel, onset=onset, duration=150, rate=backdrop_rate).apply(
        step2.frames
    )

    pipe = _build_pipeline(_BASELINE_FIT, use_physics_rule=True)
    outcomes = pipe.process(step3.frames)

    ref = _reference_window_index(outcomes, onset)

    fault_flagged_idx = _first_index_where(outcomes, ref, lambda o: o.channel_flags[fault_channel])
    attack_flagged_idx = _first_index_where(
        outcomes, ref, lambda o: o.channel_flags[attack_channel]
    )
    assert fault_flagged_idx is not None, f"P2-ANOM-E2 FAILS: {fault_channel!r} never flagged."
    assert attack_flagged_idx is not None, f"P2-ANOM-E2 FAILS: {attack_channel!r} never flagged."

    fault_attribution = outcomes[fault_flagged_idx].attribution[fault_channel].attribution
    attack_attribution = outcomes[attack_flagged_idx].attribution[attack_channel].attribution

    assert fault_attribution is Attribution.fault, (
        f"P2-ANOM-E2 FAILS: expected {fault_channel!r} attributed fault, "
        f"got {fault_attribution.value!r}."
    )
    assert attack_attribution is Attribution.attack, (
        f"P2-ANOM-E2 FAILS: expected {attack_channel!r} attributed attack, "
        f"got {attack_attribution.value!r}. Per this test's own docstring, "
        "the trend disagreement is still partly noise-dependent at the "
        "earliest flagged window (verified: attack-attributed in 3/5 seeds) "
        "-- not a fully deterministic guarantee of this minimal rule."
    )


# ===========================================================================
# P2-ANOM-S1 -- Sad: Adaptive stealth FDI (stays under naive residual) ->
# Trust/correlation still degrades; caught or flagged suspicious
#
# Uses the new AdaptiveStealthFDI injection (edge/injection/injections.py):
# the bias ramps from 0 up to `residual_cap` over the first few active
# samples, then HOLDS there for the rest of the injection -- it never exceeds
# `residual_cap` in absolute deviation from the clean value, by construction.
# `NAIVE_RESIDUAL_BOUND_FIXTURE` below is a test-local stand-in for a naive,
# fixed-threshold residual check (NOT any real production component) chosen
# with a safety margin above `residual_cap` + the channel's own ambient noise,
# so the premise ("this injection is genuinely invisible to that naive check")
# is verified directly against the actual generated samples, not assumed.
#
# Channel: 'humidity' -- deliberately not reused from any other P2-ANOM/TRUST
# scenario above, and outside the current<->vibration pair (D010), so this
# result has no dependency on TrendSignPhysicsRule/k at all; k defaults to
# 1.0 for humidity (edge/trust/k_correlation.py) and is not exercised here in
# any interesting way. The real, unmodified P2Pipeline is used unchanged.
# ===========================================================================


def test_p2_anom_s1_adaptive_stealth_fdi_evades_naive_residual_but_trust_degrades():
    channel = "humidity"
    onset = 60
    duration = 150
    residual_cap = 3 * _NOISE_AMPLITUDE[channel]  # TEST FIXTURE ONLY
    rate = residual_cap / 10  # reaches the cap ~10 samples into the injection
    # A naive fixed-threshold check calibrated with headroom above the cap
    # plus the channel's own ambient noise -- TEST FIXTURE ONLY, not a
    # production detector. Chosen with an explicit safety margin so the
    # premise below is not a near-miss.
    naive_residual_bound = 5 * _NOISE_AMPLITUDE[channel]

    clean = _clean_stream(onset + duration + 20, seed=40)
    result = AdaptiveStealthFDI(
        channel=channel, onset=onset, duration=duration, rate=rate, residual_cap=residual_cap
    ).apply(clean)

    # --- Premise: the injection genuinely stays under the naive bound -------
    active_residuals = [
        abs(float(getattr(f.sensors, channel)) - _BASELINE[channel])
        for f, lab in zip(result.frames, result.labels, strict=True)
        if lab.active
    ]
    assert active_residuals, "test setup invalid: no active injected samples found"
    assert max(active_residuals) <= naive_residual_bound, (
        "Test setup invalid: the injection itself exceeds the naive residual "
        f"bound (max observed={max(active_residuals):.4f} > "
        f"{naive_residual_bound:.4f}) -- it would not be 'stealth' at all, "
        "and the result below could not be interpreted as evidence of "
        "anything."
    )

    # --- Real, unmodified pipeline ------------------------------------------
    pipe = _build_pipeline(_BASELINE_FIT)
    outcomes = pipe.process(result.frames)

    ref = _reference_window_index(outcomes, onset)
    trust_after = [o.trust[channel].trust for o in outcomes[ref:]]
    min_trust = min(trust_after)
    first_degraded = next((i for i, t in enumerate(trust_after) if t < TRUSTED_MIN), None)

    assert first_degraded is not None, (
        "P2-ANOM-S1 FAILS: trust for a channel under an adaptive-stealth FDI "
        f"(capped at {residual_cap:.4f}, provably under the naive residual "
        f"bound of {naive_residual_bound:.4f}) never dropped below "
        f"{TRUSTED_MIN} across {len(trust_after)} post-onset windows "
        f"(min observed={min_trust:.4f}). A naive per-sample residual check "
        "would have missed this attack entirely by construction, so if "
        "trust also never reacts, the trust engine provides no additional "
        "protection here."
    )
    # Reported, not asserted on: whether the (separately fragile, U07-gated)
    # window-level IF/ChannelFlagPolicy mechanism ever also fires. This test
    # intentionally does not depend on that -- see module docstring for why
    # `c` alone is expected to carry this scenario.
    any_channel_flagged = any(o.channel_flags[channel] for o in outcomes[ref:])
    print(
        f"[P2-ANOM-S1 info] min_trust={min_trust:.4f} "
        f"first_degraded_at_window={first_degraded} "
        f"channel_flags_ever_true={any_channel_flagged}"
    )


# ===========================================================================
# P2-TRUST-H1 -- Happy: Healthy sensor -> Trust stays >= 0.7
# ===========================================================================


def test_p2_trust_h1_healthy_sensor_trust_stays_at_least_0_7():
    eval_frames = _clean_stream(150, seed=20)
    pipe = _build_pipeline(_BASELINE_FIT)
    outcomes = pipe.process(eval_frames)

    below_trusted: dict[str, list[int]] = {}
    for ch in CHANNELS:
        bad = [i for i, o in enumerate(outcomes) if o.trust[ch].trust < TRUSTED_MIN]
        if bad:
            below_trusted[ch] = bad

    assert not below_trusted, (
        "P2-TRUST-H1 FAILS literally for a healthy sensor: trust dropped "
        f"below {TRUSTED_MIN} at least once on these channels/window-indices: "
        f"{ {ch: idxs[:5] for ch, idxs in below_trusted.items()} }. Beta priors "
        "start at trust=0.5 (alpha0=beta0=1, see edge/trust/beta.py), so any "
        "failure in the earliest windows reflects that neutral starting point "
        "rather than unhealthy evidence -- reported as-is, not reinterpreted "
        "as a warm-up exemption."
    )


# ===========================================================================
# P2-TRUST-H2 -- Happy: Spoofed sensor -> Trust < 0.4 within <= 3 windows
# ===========================================================================


def test_p2_trust_h2_spoofed_sensor_trust_below_0_4_within_3_windows():
    channel = "gas"
    onset = 60
    clean = _clean_stream(210, seed=21)
    spoof_value = _BASELINE[channel] * 5  # obviously far outside the clean range
    result = ConstantSpoof(channel=channel, onset=onset, duration=150, value=spoof_value).apply(
        clean
    )

    pipe = _build_pipeline(_BASELINE_FIT)
    outcomes = pipe.process(result.frames)

    ref = _reference_window_index(outcomes, onset)
    window_slice = outcomes[ref : ref + LATENCY_TARGET_WINDOWS]
    trust_values = [o.trust[channel].trust for o in window_slice]
    assert any(t < MALICIOUS_MAX for t in trust_values), (
        f"P2-TRUST-H2 FAILS: trust for {channel!r} never dropped below "
        f"{MALICIOUS_MAX} within the first {LATENCY_TARGET_WINDOWS} windows "
        f"after onset (values observed: {trust_values})."
    )


# ===========================================================================
# P2-TRUST-E1 -- Edge: Sensor recovers after transient -> Trust climbs back
# ===========================================================================


def test_p2_trust_e1_sensor_recovers_after_transient():
    channel = "vibration"
    onset = 60
    duration = 10  # short, bounded transient -- ends well inside the stream
    clean = _clean_stream(190, seed=22)
    bias = _BASELINE[channel] * 4
    result = BiasFDI(channel=channel, onset=onset, duration=duration, bias=bias).apply(clean)

    pipe = _build_pipeline(_BASELINE_FIT)
    outcomes = pipe.process(result.frames)

    ref = _reference_window_index(outcomes, onset)
    injection_end_local = onset + duration
    end_ref = _reference_window_index(outcomes, injection_end_local)

    worst_trust = min(o.trust[channel].trust for o in outcomes[ref : end_ref + 5])
    recovery_trust = [o.trust[channel].trust for o in outcomes[-20:]]
    final_trust = recovery_trust[-1]

    assert final_trust > worst_trust, (
        f"P2-TRUST-E1 FAILS: trust did not climb back after the transient "
        f"ended (worst during/just-after injection={worst_trust:.4f}, "
        f"final observed={final_trust:.4f})."
    )


# ===========================================================================
# P2-TRUST-E2 -- Edge: Two correlated channels both drift -> Correlation
# term doesn't falsely exonerate
# ===========================================================================


def test_p2_trust_e2_correlated_drift_does_not_falsely_exonerate():
    onset = 60
    duration = 150
    clean = _clean_stream(onset + duration, seed=23)
    rate_current = 0.1 * _NOISE_AMPLITUDE["current"]
    rate_vibration = 0.1 * _NOISE_AMPLITUDE["vibration"]
    step1 = Drift(channel="current", onset=onset, duration=duration, rate=rate_current).apply(clean)
    step2 = Drift(channel="vibration", onset=onset, duration=duration, rate=rate_vibration).apply(
        step1.frames
    )

    pipe = _build_pipeline(_BASELINE_FIT)
    outcomes = pipe.process(step2.frames[: onset + 130])

    ref = _reference_window_index(outcomes, onset)
    window_slice = outcomes[ref:]

    # k itself isn't exposed on WindowOutcome/TrustReading; re-derive it via a
    # fresh CorrelationProvider fed the same windows, matching what the
    # pipeline actually consulted.
    k_check = CorrelationProvider()
    windows = _preprocessor().process(step2.frames[: onset + 130])
    k_series = []
    for w in windows[ref:]:
        k_check.record_window(w)
        k_series.append(k_check.evaluate("current"))

    # The reference window itself covers mostly pre-onset samples (only the
    # single sample at `onset` is drifted) -- its early/late-half trend split
    # is dominated by pre-onset noise, not the injected drift, so k can
    # legitimately disagree there by chance. Excluded from the premise check
    # for that reason (confirmed empirically: k_series[0] was the only
    # disagreement across 130 windows on a prior run); every window from
    # ref+1 onward is fully or mostly inside the injection and must agree.
    assert all(k == 1.0 for k in k_series[1:]), (
        "Test setup invalid: expected k=1.0 from ref+1 onward (both channels "
        f"drift in the same direction, so they should NOT trip the "
        f"trend-sign rule) -- got {k_series[1:11]}. If this fails, the "
        "scenario doesn't actually exercise 'false exoneration' and the "
        "result below can't be interpreted."
    )

    min_trust = min(o.trust["current"].trust for o in window_slice)
    assert min_trust < TRUSTED_MIN, (
        "P2-TRUST-E2 FAILS: trust for 'current' stayed >= "
        f"{TRUSTED_MIN} throughout (min observed={min_trust:.4f}) despite "
        "k=1.0 the whole time -- i.e. the correlation term DID falsely "
        "exonerate a genuinely drifting channel; c/h did not compensate."
    )


# ===========================================================================
# P2-TRUST-S1 -- Sad: Collusive attack on 2 channels to fake correlation ->
# Historical-reliability term prevents full trust
# ===========================================================================


def test_p2_trust_s1_collusive_attack_h_prevents_full_trust():
    onset = 60
    duration = 150
    clean = _clean_stream(onset + duration, seed=24)
    # RampFDI (attack-kind cumulative additive slope), not BiasFDI: a
    # BiasFDI's CONSTANT full-window additive offset is washed out by
    # per-window min-max normalization once a window sits entirely inside
    # the injection (the documented P2_RESUME.md §3 flatness artifact) --
    # confirmed empirically here too (k reverted to noise-driven ~50/50
    # agreement for most of the injection under BiasFDI). RampFDI's
    # cumulative growth is not erased by min-max, so it reliably fakes
    # agreement (k=1.0) the way the scenario intends, while remaining an
    # ATTACK-kind §12.4 injection like BiasFDI.
    slope_current = 0.1 * _NOISE_AMPLITUDE["current"]
    slope_vibration = 0.1 * _NOISE_AMPLITUDE["vibration"]
    step1 = RampFDI(channel="current", onset=onset, duration=duration, slope=slope_current).apply(
        clean
    )
    step2 = RampFDI(
        channel="vibration", onset=onset, duration=duration, slope=slope_vibration
    ).apply(step1.frames)

    pipe = _build_pipeline(_BASELINE_FIT)
    observed_frames = step2.frames[: onset + 130]
    outcomes = pipe.process(observed_frames)

    ref = _reference_window_index(outcomes, onset)

    k_check = CorrelationProvider()
    windows = _preprocessor().process(observed_frames)
    k_series = [(k_check.record_window(w), k_check.evaluate("current"))[1] for w in windows[ref:]]
    assert all(k == 1.0 for k in k_series), (
        "Test setup invalid: expected k=1.0 throughout (same-direction "
        f"collusive bias on current+vibration) -- got {k_series[:10]}. If "
        "this fails, the scenario doesn't actually fake the correlation and "
        "the result below can't be interpreted."
    )

    trust_after = [o.trust["current"].trust for o in outcomes[ref:]]
    assert not all(t >= TRUSTED_MIN for t in trust_after), (
        "P2-TRUST-S1 FAILS: trust for 'current' stayed fully in the Trusted "
        f"band (>= {TRUSTED_MIN}) throughout the collusive attack despite "
        "k=1.0 the whole time -- i.e. h/c did not prevent full trust as the "
        f"PRD requires (values: {trust_after[:10]}...)."
    )
