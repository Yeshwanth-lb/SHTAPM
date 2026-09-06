"""U06 within-episode confidence intervals -- pure, additive, opt-in,
standard-library-only. Implements the Wilson score interval for a single
binomial proportion, applied ONLY to already-produced numerator/
denominator pairs from the four existing U06 axis/comparison summaries.

data_source=synthetic · execution_mode=simulation · model_status=diagnostic_unvalidated

METHODOLOGY -- HUMAN-APPROVED, NOT THIS MODULE'S OWN CHOICE: the Wilson
score interval and the 95% confidence level were explicitly approved by
the U06 decision owner as a design decision (see ``project-state/
DECISIONS.md``'s "U06 -- Confidence-Interval Methodology Decision"
record), following the earlier methodology review's own conclusion that a
WITHIN-EPISODE binomial interval (uncertainty from a finite number of
observed steps in ONE episode) is meaningful today, while a CROSS-SEED
interval would currently be degenerate (every axis value is already
byte-identical across all 5 seeds of every committed scenario -- see the
seed-repetition reports' own EMPIRICAL NOTE sections). This module
implements ONLY the former.

SCOPE -- WITHIN-EPISODE ONLY, NO CROSS-SEED OR POOLED COMPUTATION: every
function in this module accepts exactly ONE numerator/denominator pair (or
one already-produced summary object carrying exactly one such pair) and
returns exactly one interval. Nothing here iterates over multiple seeds,
multiple scenarios, or multiple baselines, and nothing here computes a
mean, standard deviation, variance, or any other cross-episode
aggregate -- doing so would be a cross-seed/pooled statistic, explicitly
out of scope (see the design proposal and methodology review that preceded
this increment). This module never imports anything from the
injection-framework package, ``edge.rl.reward``, ``edge.rl.fallback_gate``,
``edge.rl.policy``, ``edge.rl.environment``, or ``edge.eval.rl_training``,
and it never modifies any of the four existing summary modules
(``edge.eval.u06_rate_summary``, ``edge.eval.u06_tracker_agreement``,
``edge.eval.u06_ground_truth_rate_summary``, ``edge.eval.
u06_channel_agreement``) -- it only reads already-computed fields from
their already-committed output dataclasses.

USES ORIGINAL COUNTS, NEVER ALREADY-ROUNDED RATES: every function here
takes the underlying integer numerator/denominator (or reads them directly
off an existing summary object), never a pre-computed floating-point rate
-- computing a proportion's confidence interval from a rounded rate would
lose precision the original counts already have. There is deliberately no
function anywhere in this module that accepts a bare ``rate: float`` as
its primary input.

STANDARD LIBRARY ONLY: the Wilson z-score for the (single) approved
confidence level is computed via ``statistics.NormalDist`` (Python's own
standard library, available since 3.8) -- no new external dependency (e.g.
``scipy``) is introduced anywhere in this module.

NO THRESHOLD, NO VERDICT, NO RECOMMENDATION, NO REAL-WORLD CLAIM: this
module computes an interval's lower/upper bounds only. It never compares
an interval against any acceptable-rate threshold, never emits a pass/
fail judgment or recommendation, and never claims real-world accuracy,
safety, effectiveness, validation, or production readiness for any
scenario, baseline, or axis. U06 (``project-state/DECISIONS.md``) remains
fully open -- nothing here resolves or partially resolves it.

ZERO-OPPORTUNITY / UNDEFINED-RATE HANDLING: mirroring every existing axis
module's own convention, a zero denominator (no opportunity to compute a
rate at all) returns ``None`` -- never a degenerate ``(0.0, 0.0)`` or
``(0.0, 1.0)`` interval, which would misrepresent "no opportunity" as a
real, if uncertain, measurement.
"""

from __future__ import annotations

from dataclasses import dataclass
from statistics import NormalDist

EXECUTION_MODE = "simulation"
DATA_SOURCE = "synthetic"
MODEL_STATUS = "diagnostic_unvalidated"

# The single approved confidence level (see module docstring's METHODOLOGY
# section) -- not a caller-adjustable default in ordinary use, though the
# low-level function accepts it explicitly for testability against other
# levels (e.g. verifying the formula itself, not for producing an
# alternative U06-facing interval).
APPROVED_CONFIDENCE_LEVEL = 0.95


@dataclass(frozen=True)
class WilsonScoreInterval:
    """One within-episode Wilson score confidence interval around a single
    binomial proportion -- see module docstring. NOT a cross-seed or
    pooled uncertainty estimate; NOT a threshold, verdict, or
    recommendation of any kind.

    ``lower_bound``/``upper_bound`` are both clipped defensively to
    ``[0.0, 1.0]`` against floating-point drift -- the Wilson formula
    itself is already mathematically bounded within that range.
    """

    numerator: int
    denominator: int
    rate: float
    confidence_level: float
    lower_bound: float
    upper_bound: float

    execution_mode: str = EXECUTION_MODE
    data_source: str = DATA_SOURCE
    model_status: str = MODEL_STATUS


def wilson_score_interval(
    numerator: int,
    denominator: int,
    *,
    confidence_level: float = APPROVED_CONFIDENCE_LEVEL,
) -> WilsonScoreInterval | None:
    """Compute the Wilson score interval for ``numerator`` successes out of
    ``denominator`` trials -- see module docstring. Pure, deterministic,
    numerically stable (closed-form formula, no iteration or randomness).

    Returns ``None`` iff ``denominator == 0`` -- see module docstring's
    ZERO-OPPORTUNITY / UNDEFINED-RATE HANDLING section; never a degenerate
    interval for a zero-opportunity case.

    Raises ``ValueError`` for any structurally invalid input (negative
    counts, ``numerator > denominator``, or a confidence level outside
    ``(0, 1)``) -- these indicate a caller error, not a diagnostic
    condition to route around silently.
    """
    if denominator < 0:
        raise ValueError(f"denominator must be >= 0, got {denominator}")
    if numerator < 0:
        raise ValueError(f"numerator must be >= 0, got {numerator}")
    if numerator > denominator:
        raise ValueError(
            f"numerator ({numerator}) must not exceed denominator ({denominator})"
        )
    if not 0.0 < confidence_level < 1.0:
        raise ValueError(f"confidence_level must be in (0, 1), got {confidence_level}")

    if denominator == 0:
        return None

    n = float(denominator)
    phat = numerator / n
    # Two-sided interval: split the remaining probability mass evenly
    # across both tails, exactly as every standard binomial-proportion
    # interval (Wilson included) is conventionally defined.
    z = NormalDist().inv_cdf(1.0 - (1.0 - confidence_level) / 2.0)
    z_squared = z * z

    denominator_term = 1.0 + z_squared / n
    center = (phat + z_squared / (2.0 * n)) / denominator_term
    margin = (z / denominator_term) * (
        (phat * (1.0 - phat) / n + z_squared / (4.0 * n * n)) ** 0.5
    )

    lower_bound = max(0.0, center - margin)
    upper_bound = min(1.0, center + margin)

    return WilsonScoreInterval(
        numerator=numerator,
        denominator=denominator,
        rate=phat,
        confidence_level=confidence_level,
        lower_bound=lower_bound,
        upper_bound=upper_bound,
    )


# ---------------------------------------------------------------------------
# Per-axis convenience wrappers -- each reads the ORIGINAL numerator/
# denominator pair directly off an already-committed summary object,
# never a rounded rate. Each returns None under the exact same conditions
# wilson_score_interval() itself does (zero denominator).
# ---------------------------------------------------------------------------


def axis_i_false_isolation_interval(summary) -> WilsonScoreInterval | None:
    """Axis (i) (``edge.eval.u06_rate_summary.EpisodeRateSummary``)
    proxy-based false-isolation rate."""
    return wilson_score_interval(
        summary.false_isolation_numerator, summary.false_isolation_denominator
    )


def axis_i_missed_fault_interval(summary) -> WilsonScoreInterval | None:
    """Axis (i) proxy-based missed-fault rate."""
    return wilson_score_interval(
        summary.missed_fault_numerator, summary.missed_fault_denominator
    )


def axis_iii_false_isolation_interval(summary) -> WilsonScoreInterval | None:
    """Axis (iii) (``edge.eval.u06_ground_truth_rate_summary.
    GroundTruthRateSummary``) ground-truth-anchored false-isolation rate."""
    return wilson_score_interval(
        summary.false_isolation_numerator, summary.false_isolation_denominator
    )


def axis_iii_missed_fault_interval(summary) -> WilsonScoreInterval | None:
    """Axis (iii) ground-truth-anchored missed-fault rate."""
    return wilson_score_interval(
        summary.missed_fault_numerator, summary.missed_fault_denominator
    )


def axis_ii_tracker_agreement_interval(summary) -> WilsonScoreInterval | None:
    """Axis (ii) (``edge.eval.u06_tracker_agreement.
    TrackerAgreementSummary``) presence-only tracker-agreement rate.
    ``agreement_rate``'s own numerator is
    ``agreement_active_count + agreement_nominal_count`` (both count as
    "agreement" per axis (ii)'s own definition); its denominator is
    ``total_observations`` -- reconstructed here from the same raw counts
    axis (ii) itself already reports, never from the rounded rate."""
    numerator = summary.agreement_active_count + summary.agreement_nominal_count
    return wilson_score_interval(numerator, summary.total_observations)


def channel_agreement_interval(summary) -> WilsonScoreInterval | None:
    """Channel-matched agreement (``edge.eval.u06_channel_agreement.
    ChannelAgreementSummary``) exact-set-match rate."""
    return wilson_score_interval(
        summary.channel_match_count, summary.channel_match_observation_count
    )
