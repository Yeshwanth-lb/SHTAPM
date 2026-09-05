"""RL fallback gate (FR-RL4) -- sits between a future RL policy and any
system action. No RL policy, training, or reward weights exist yet (see
edge/rl/state.py, edge/rl/environment.py) -- this module only decides
whether a REQUESTED action (from whatever produces one, today only tests)
may be approved, or must be replaced by the existing deterministic
fallback.

PRD FR-RL4: "The agent shall be replaceable by a deterministic rule-based
fallback if the trained policy is unavailable (fail-safe)." Acceptance
criterion P3-RL-S1: "Trained policy file missing -> Rule-based fallback
engages; safety preserved." No DECISIONS.md entry adds a confidence
threshold, reward weight, or any other numeric policy-safety value -- U06
(RL reward shaping) is fully open. This module invents none: every numeric
value below is an explicit, named, overridable simulation fixture, never a
project specification, and every consuming function REQUIRES it as an
explicit argument (no default baked into the function itself) -- the same
"named canonical fixture, never silently applied" discipline already used
for ``UNCERTAINTY_CAP_D020`` (``edge/pipeline/self_heal.py``) and
``SYNTHETIC_HEALTH_WARNING_THRESHOLD``/``SYNTHETIC_HEALTH_CRITICAL_
THRESHOLD`` (``edge/eval/synthetic_prognosis_training.py``).

DETERMINISTIC FALLBACK SOURCE: this module calls no isolation logic of its
own. It consumes an already-computed
``edge.pipeline.isolation_tracker.IsolationTrackerResult`` (the caller
runs ``IsolationFallbackTracker.update(outcome)`` once per cycle, exactly
as ``edge/main.py``'s ``_log_window_outcome`` already does for logging) and
derives the fallback action from it: ``RLAction.isolate`` if any channel is
currently tracked, else ``RLAction.continue_``. ``decide_isolation()``/
``IsolationFallbackTracker`` only ever distinguish "isolate" from "not" --
they have no rule for ``RLAction.reduce_weight`` or ``RLAction.alert``, so
the deterministic fallback this module can produce is limited to exactly
{Continue, Isolate, Safe Pump-Stop} (the last coming from the safe-stop
condition below, not from isolation tracking). This is an honest
reflection of what already exists, not a limitation invented here.

SAFE-STOP IS NEVER OVERRIDDEN, IN EITHER DIRECTION:
  - If the system is ALREADY in a safe-stop condition (caller-reported,
    e.g. derived from ``edge.actuation.watchdog.Watchdog.expired`` or the
    relay controller's own current state), this gate ALWAYS approves
    ``RLAction.safe_stop`` and marks fallback as used -- matching the
    existing relay/watchdog module's own "no auto-restart" design (an
    operator must explicitly reset/re-arm; nothing here, or anywhere in
    this project, un-does a safe-stop automatically).
  - If the REQUESTED action is itself ``RLAction.safe_stop``, this gate
    approves it immediately, bypassing every other check below -- a
    request for the maximally conservative action is never second-guessed
    by an uncertain policy's own unavailability/low confidence, since
    overriding it could only make the outcome less safe, never more.

This module performs no actuation, publishes nothing, and imports no
actuator, general-purpose I/O, or network/decision-publishing code (see
``edge/tests/test_rl_fallback_gate.py``'s structural check).
"""

from __future__ import annotations

from dataclasses import dataclass

from app.schemas.contracts import RLAction

from edge.pipeline.isolation_tracker import IsolationTrackerResult
from edge.rl.state import RLState

EXECUTION_MODE = "simulation"

# Provisional simulation fixture ONLY -- see module docstring. Not a
# DECISIONS.md value; U06 (RL confidence/reward policy) is fully open.
# Every caller of evaluate_rl_action() must pass a threshold explicitly
# (no default in the function itself) -- this constant exists solely as a
# canonical, importable value so callers/tests share one copy.
RL_CONFIDENCE_THRESHOLD_FIXTURE = 0.8

# The only two actions the existing deterministic logic can produce from
# isolation tracking alone (see module docstring) -- RLAction.reduce_weight/
# alert have no deterministic rule anywhere in this repo.
_DETERMINISTIC_ISOLATE_ACTION = RLAction.isolate
_DETERMINISTIC_CONTINUE_ACTION = RLAction.continue_


@dataclass(frozen=True)
class GateDecision:
    """One cycle's fallback-gate decision.

    ``safety_status``: ``"safe_stop_active"`` | ``"isolation_active"`` |
    ``"nominal"`` -- the deterministic, already-existing safety condition,
    independent of what RL requested.

    ``policy_status``: ``"unavailable"`` | ``"unvalidated"`` |
    ``"validated_low_confidence"`` | ``"validated"`` -- describes the RL
    policy input this gate was given, not whether its action was approved.

    ``confidence``/``confidence_threshold`` are ``None`` unless a
    confidence score was supplied/relevant this cycle -- never fabricated.
    """

    requested_action: RLAction | None
    approved_action: RLAction
    fallback_used: bool
    fallback_reason: str | None
    safety_status: str
    policy_status: str
    confidence: float | None
    confidence_threshold: float | None
    execution_mode: str = EXECUTION_MODE


def _deterministic_fallback_action(isolation_status: IsolationTrackerResult) -> RLAction:
    if isolation_status.tracked_channels:
        return _DETERMINISTIC_ISOLATE_ACTION
    return _DETERMINISTIC_CONTINUE_ACTION


def _policy_status(
    *,
    policy_available: bool,
    policy_validated: bool,
    confidence: float | None,
    confidence_threshold: float,
) -> str:
    if not policy_available:
        return "unavailable"
    if not policy_validated:
        return "unvalidated"
    if confidence is not None and confidence < confidence_threshold:
        return "validated_low_confidence"
    return "validated"


def evaluate_rl_action(
    *,
    requested_action: RLAction | None,
    state: RLState | None,
    isolation_status: IsolationTrackerResult,
    policy_available: bool,
    policy_validated: bool,
    confidence_threshold: float,
    confidence: float | None = None,
    already_safe_stopped: bool = False,
) -> GateDecision:
    """Decide whether ``requested_action`` may be approved, or must be
    replaced by the existing deterministic fallback.

    ``confidence_threshold`` is REQUIRED -- no default (see module
    docstring); pass ``RL_CONFIDENCE_THRESHOLD_FIXTURE`` explicitly for the
    named simulation fixture, or any other caller-chosen value.

    Never raises for an invalid/missing ``requested_action`` or ``state``
    -- those are exactly the conditions this gate exists to catch, and
    catching them safely (falling back) is the whole point; only a
    genuinely programmer-error input (e.g. a malformed
    ``IsolationTrackerResult``) would propagate an exception, and none is
    special-cased here.
    """
    safety_status = "nominal"
    if already_safe_stopped:
        safety_status = "safe_stop_active"
    elif isolation_status.tracked_channels:
        safety_status = "isolation_active"

    policy_status = _policy_status(
        policy_available=policy_available,
        policy_validated=policy_validated,
        confidence=confidence,
        confidence_threshold=confidence_threshold,
    )

    # 1. Already safe-stopped: never resumed by RL, regardless of what was
    #    requested -- see module docstring.
    if already_safe_stopped:
        return GateDecision(
            requested_action=requested_action,
            approved_action=RLAction.safe_stop,
            fallback_used=True,
            fallback_reason=(
                "system is already in a safe-stop condition; RL cannot resume operation"
            ),
            safety_status=safety_status,
            policy_status=policy_status,
            confidence=confidence,
            confidence_threshold=confidence_threshold,
        )

    # 2. A request for the maximally conservative action is never blocked
    #    -- see module docstring.
    if requested_action is RLAction.safe_stop:
        return GateDecision(
            requested_action=requested_action,
            approved_action=RLAction.safe_stop,
            fallback_used=False,
            fallback_reason=None,
            safety_status=safety_status,
            policy_status=policy_status,
            confidence=confidence,
            confidence_threshold=confidence_threshold,
        )

    def _fallback(reason: str) -> GateDecision:
        return GateDecision(
            requested_action=requested_action,
            approved_action=_deterministic_fallback_action(isolation_status),
            fallback_used=True,
            fallback_reason=reason,
            safety_status=safety_status,
            policy_status=policy_status,
            confidence=confidence,
            confidence_threshold=confidence_threshold,
        )

    # 3. State unavailable/invalid.
    if state is None:
        return _fallback("state is unavailable")

    # 4. Requested action missing or not a real RLAction member.
    if requested_action is None:
        return _fallback("no RL action was provided")
    if not isinstance(requested_action, RLAction):
        return _fallback(f"requested_action is not a valid RLAction: {requested_action!r}")

    # 5. Policy unavailable (FR-RL4 / P3-RL-S1's exact scenario).
    if not policy_available:
        return _fallback("RL policy is unavailable (no trained policy loaded)")

    # 6. Policy unvalidated -- true for every policy in this repo today.
    if not policy_validated:
        return _fallback("RL policy has not been validated for production use")

    # 7. Confidence required (policy is validated) but missing.
    if confidence is None:
        return _fallback("policy is validated but supplied no confidence score")

    # 8. Confidence below the (explicitly provisional) threshold.
    if confidence < confidence_threshold:
        return _fallback(
            f"confidence {confidence} is below the required threshold {confidence_threshold}"
        )

    # 9. Deterministic safety-constraint check: never resume a channel the
    #    existing tracker still holds as an isolation candidate (mirrors
    #    IsolationFallbackTracker's own "no confirmed recovery" invariant).
    if isolation_status.tracked_channels and requested_action is RLAction.continue_:
        return _fallback(
            "requested action would resume normal operation while channel(s) "
            f"{sorted(isolation_status.tracked_channels)} remain tracked isolation "
            "candidates with no confirmed recovery"
        )

    # All checks passed: approve the RL policy's own requested action.
    return GateDecision(
        requested_action=requested_action,
        approved_action=requested_action,
        fallback_used=False,
        fallback_reason=None,
        safety_status=safety_status,
        policy_status=policy_status,
        confidence=confidence,
        confidence_threshold=confidence_threshold,
    )
