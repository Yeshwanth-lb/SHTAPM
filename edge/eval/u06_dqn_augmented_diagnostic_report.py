"""U06 DQN-augmented aggregate diagnostic report -- pure, additive,
opt-in. Extends the existing, unmodified, torch-free aggregate diagnostic
report (``edge.eval.u06_diagnostic_report``) with a third, optional set of
rows produced by the standalone DQN diagnostic evaluation (``edge.eval.
u06_dqn_evaluation_report``), WHEN torch is genuinely available in this
environment.

data_source=synthetic · execution_mode=simulation · model_status=diagnostic_unvalidated

ARCHITECTURE -- SEPARATE INTEGRATION LAYER, NOT A MODIFICATION TO EITHER
EXISTING MODULE (the architectural decision approved for this increment):
this is a NEW, isolated module. It does not modify ``edge.eval.
u06_diagnostic_report`` (which remains torch-free, unmodified, serving the
two deterministic baselines exactly as before this increment) or
``edge.eval.u06_dqn_evaluation_report`` (which remains exactly as
previously approved and built: fixed diagnostic configuration, dedicated
seed ``5001``, fresh in-memory training, no checkpoint persistence). The
alternative considered and rejected was adding a third baseline row
directly inside ``edge.eval.u06_diagnostic_report.build_diagnostic_report()``
-- rejected because that would make importing ``edge.eval.
u06_diagnostic_report`` itself (used by every seed-repetition report and
by every other existing consumer) unconditionally depend on ``torch``.
Keeping the two source reports untouched and combining them in a new,
separate module is the smallest architecture that avoids that outcome.

DEFERRED IMPORT, NOT AN UNCONDITIONAL DEPENDENCY: merely importing THIS
module never requires ``torch`` -- ``edge.eval.u06_dqn_evaluation_report``
is imported only INSIDE ``build_dqn_augmented_diagnostic_report()``, and
only after ``TORCH_AVAILABLE`` (computed once, via
``importlib.util.find_spec("torch") is not None`` -- a static check with
no import side effect) confirms torch is present. ``DQNScenarioResult`` is
referenced only in type annotations (guarded by ``typing.TYPE_CHECKING``,
combined with this module's own ``from __future__ import annotations``),
never imported at module scope.

NEVER SILENTLY SKIPPED FOR ANY OTHER REASON: the ONLY condition under
which DQN evaluation is skipped is torch being genuinely unavailable --
documented explicitly via ``dqn_evaluation_skipped_reason``. When torch
IS available, any exception ``train_dqn()`` or ``edge.eval.
u06_dqn_evaluation_report`` itself raises propagates normally -- this
module contains no broad exception handler that would silently swallow a
real failure and report it as an unavailability.

BASELINE RESULTS ALWAYS POPULATED: ``baseline_results`` (the two
deterministic baselines, with their own within-episode confidence
intervals -- see ``edge.eval.u06_diagnostic_report``'s own
CONFIDENCE-INTERVAL WIRING section) are always present, regardless of
torch availability -- DQN evaluation is a strictly additive extension,
never a replacement.

NO CONFIDENCE INTERVALS ADDED TO DQN ROWS IN THIS INCREMENT: confidence-
interval wiring was explicitly scoped to the aggregate diagnostic report
and the nine seed-repetition reports only -- ``DQNScenarioResult`` (from
``edge.eval.u06_dqn_evaluation_report``) is used here completely
unmodified, carrying no interval fields. Adding them would require either
modifying that already-approved module or duplicating its result shape --
both out of scope for this integration-only increment.

NO NEW METHODOLOGY, NO THRESHOLD, NO VERDICT, NO REAL-WORLD CLAIM: this
module invents no new interval, axis, training configuration, or
reward-weight choice -- it only assembles two already-approved,
already-built reports into one combined view. Every disclaimer either
wrapped report's own module docstring already attaches to its numbers is
unchanged and still applies. U06 (``project-state/DECISIONS.md``) remains
fully open -- nothing here resolves or partially resolves it.
"""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from typing import TYPE_CHECKING

from edge.eval.u06_diagnostic_report import (
    ScenarioBaselineResult,
    build_diagnostic_report,
)

if TYPE_CHECKING:
    from edge.eval.u06_dqn_evaluation_report import DQNScenarioResult

EXECUTION_MODE = "simulation"
DATA_SOURCE = "synthetic"
MODEL_STATUS = "diagnostic_unvalidated"

# The ONLY reason DQN evaluation is ever skipped -- see module docstring's
# NEVER SILENTLY SKIPPED FOR ANY OTHER REASON section.
TORCH_UNAVAILABLE_REASON = "torch is not installed in this environment"

# Computed once, via a static check with no import side effect -- see
# module docstring's DEFERRED IMPORT section. Tests may monkeypatch this
# module-level flag directly to exercise the torch-unavailable path
# without requiring an actually torch-free environment.
TORCH_AVAILABLE = importlib.util.find_spec("torch") is not None


@dataclass(frozen=True)
class DQNAugmentedDiagnosticReport:
    """The combined, scenario-separated report -- see module docstring.
    ``baseline_results`` is always populated (the two deterministic
    baselines, unchanged from ``edge.eval.u06_diagnostic_report``).
    ``dqn_results`` is ``None`` iff torch is unavailable (see
    ``dqn_evaluation_skipped_reason``); otherwise it is always populated
    -- DQN evaluation is never silently skipped for any other reason.
    Neither tuple is pooled, averaged, or otherwise cross-seed-summarized
    -- no such computation exists anywhere in this module."""

    baseline_results: tuple[ScenarioBaselineResult, ...]
    dqn_results: tuple[DQNScenarioResult, ...] | None
    dqn_evaluation_skipped_reason: str | None
    dqn_diagnostic_seed: int | None
    dqn_reward_weights_fixture_name: str | None

    execution_mode: str = EXECUTION_MODE
    data_source: str = DATA_SOURCE
    model_status: str = MODEL_STATUS


def build_dqn_augmented_diagnostic_report() -> DQNAugmentedDiagnosticReport:
    """Build the combined baseline + (optional) DQN diagnostic report --
    see module docstring. Always computes ``baseline_results`` via the
    existing, unmodified ``build_diagnostic_report()``. Computes
    ``dqn_results`` via the existing, unmodified
    ``build_dqn_diagnostic_report()`` ONLY if ``TORCH_AVAILABLE`` -- the
    import of ``edge.eval.u06_dqn_evaluation_report`` happens here,
    deferred, never at this module's own import time.
    """
    baseline_report = build_diagnostic_report()

    if not TORCH_AVAILABLE:
        return DQNAugmentedDiagnosticReport(
            baseline_results=baseline_report.results,
            dqn_results=None,
            dqn_evaluation_skipped_reason=TORCH_UNAVAILABLE_REASON,
            dqn_diagnostic_seed=None,
            dqn_reward_weights_fixture_name=None,
        )

    from edge.eval.u06_dqn_evaluation_report import build_dqn_diagnostic_report

    dqn_report = build_dqn_diagnostic_report()
    return DQNAugmentedDiagnosticReport(
        baseline_results=baseline_report.results,
        dqn_results=dqn_report.results,
        dqn_evaluation_skipped_reason=None,
        dqn_diagnostic_seed=dqn_report.diagnostic_seed,
        dqn_reward_weights_fixture_name=dqn_report.reward_weights_fixture_name,
    )


def main() -> None:
    """Diagnostic entry point:
    ``python -m edge.eval.u06_dqn_augmented_diagnostic_report``. Prints the
    combined baseline + (optional) DQN report. NOT a validation claim, NOT
    a pass/fail judgment, NOT a reward-weight decision -- see module
    docstring."""
    print("=== U06 DQN-augmented aggregate diagnostic report (simulation-only) ===")
    report = build_dqn_augmented_diagnostic_report()

    print(f"torch available: {TORCH_AVAILABLE}")
    if report.dqn_evaluation_skipped_reason is not None:
        print(f"DQN evaluation skipped: {report.dqn_evaluation_skipped_reason}")
    else:
        print(
            f"DQN diagnostic configuration: seed={report.dqn_diagnostic_seed}, "
            f"reward_weights={report.dqn_reward_weights_fixture_name} "
            "(a fixed diagnostic fixture, NOT an approved U06 reward-weight decision)"
        )

    for result in report.baseline_results:
        print(f"[{result.scenario_name}] {result.baseline_name}: (baseline, with intervals)")

    if report.dqn_results is not None:
        for result in report.dqn_results:
            print(f"[{result.scenario_name}] {result.baseline_name}: (DQN, no intervals)")

    print(
        "NOTE: every number in either section is diagnostic, simulation-only, and "
        "scenario-specific (data_source=synthetic, execution_mode=simulation, "
        "model_status=diagnostic_unvalidated). No number here is pooled across "
        "scenarios or baselines, is a threshold, is a verdict, or is a real-world "
        "accuracy, safety, effectiveness, validation, or production-readiness "
        "claim. The DQN reward fixture, when used, is a fixed diagnostic fixture "
        "only, not an approved U06 reward-weight decision."
    )


if __name__ == "__main__":
    main()
