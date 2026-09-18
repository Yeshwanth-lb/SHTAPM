"""Measure the Isolation Forest's false-positive rate on REAL bench data (U07).

Diagnostic/offline tooling: not production, not imported by ``edge/main.py``,
not on any acceptance path.

WHY: ``edge/main.py``'s ``_P2_DETECTOR_FLAG_THRESHOLD`` is 0.90, chosen from a
full SWaT.A1 sweep (``project-state/P2_IF_SWAT_TUNING.md``). SWaT is a water
treatment plant. Its own module docstring is explicit that the value travels as
a "flag the most unusual ~10%" POLICY choice and "must be revisited once real
bench clean/faulty/spoofed data exists to validate this value directly (U07)".

That data now exists: a 7.18 h five-sensor idle capture. This measures what the
threshold actually costs on THIS rig.

WHAT THIS CAN AND CANNOT SETTLE:

  * CAN: the false-positive rate on real clean bench data, i.e. how often the
    live pipeline would flag a healthy rig.
  * CANNOT: detection rate. That needs labelled faults/attacks on real hardware,
    which no capture contains. A threshold chosen on false positives alone
    trades away sensitivity invisibly, so this reports the cost and does not
    pick a value.
  * CANNOT: flip ``P2-ANOM-H1``/``P2-ANOM-E1``. Those acceptance scenarios
    evaluate the detector on SIMULATOR streams, whose clean-vs-clean behaviour
    is a property of the simulator plus per-window min-max normalisation, not
    of this bench. Retuning here improves the deployed system; it does not
    change what those tests measure.

NO-LEAKAGE DISCIPLINE: the detector, flag policy and consistency provider are
fit on an EARLIER segment of the capture and evaluated on a LATER one, never
shuffled -- the same temporal separation D011-F requires of the SWaT harness.
"""

from __future__ import annotations

import argparse
import sys

from app.schemas.contracts import CHANNELS

from edge.anomaly.attribution import AttributionEngine
from edge.anomaly.iforest import IsolationForestDetector
from edge.anomaly.physics_rule import TrendSignPhysicsRule
from edge.anomaly.pipeline import P2Pipeline
from edge.anomaly.policy import SeverityThresholdFlagPolicy
from edge.anomaly.preprocess import Preprocessor
from edge.eval.u05_capture_loader import load_telemetry_capture, ordered_messages
from edge.trust.c_consistency import ConsistencyProvider
from edge.trust.engine import TrustEngine
from edge.trust.h_reliability import HReliabilityProvider
from edge.trust.k_correlation import CorrelationProvider

# Matches edge/main.py's own live configuration, so this measures the deployed
# pipeline rather than a differently-configured lookalike.
LIVE_THRESHOLD = 0.90
RANDOM_STATE = 0
MEDIAN_KERNEL = 1
LOW_PASS_ALPHA = 1.0

THRESHOLD_SWEEP = (0.80, 0.85, 0.90, 0.95, 0.98, 0.99)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", help="telemetry capture JSONL (mosquitto_sub output)")
    parser.add_argument(
        "--fit-fraction",
        type=float,
        default=0.5,
        help="leading fraction of the capture used to FIT; the rest is evaluated",
    )
    args = parser.parse_args()

    with open(args.capture, encoding="utf-8") as handle:
        result = load_telemetry_capture(handle)
    messages = ordered_messages(result)
    print(f"loaded {len(messages)} frames ({result.rejected_line_count} rejected)")
    if len(messages) < 2000:
        print("ERROR: need a substantially longer capture to fit and evaluate", file=sys.stderr)
        return 1

    split = int(len(messages) * args.fit_fraction)
    fit_messages, eval_messages = messages[:split], messages[split:]

    preprocessor = Preprocessor(median_kernel=MEDIAN_KERNEL, low_pass_alpha=LOW_PASS_ALPHA)
    fit_windows = preprocessor.process(fit_messages)
    eval_windows = preprocessor.process(eval_messages)
    print(f"fit windows: {len(fit_windows)}   eval windows: {len(eval_windows)}")
    print("(temporal split -- evaluation data is strictly LATER than fit data)\n")

    detector = IsolationForestDetector(flag_threshold=LIVE_THRESHOLD, random_state=RANDOM_STATE)
    flag_policy = SeverityThresholdFlagPolicy()
    physics_rule = TrendSignPhysicsRule()
    c_provider = ConsistencyProvider()
    for target in (detector, flag_policy, physics_rule, c_provider):
        target.fit(fit_windows)

    pipeline = P2Pipeline(
        preprocessor=preprocessor,
        detector=detector,
        trust_engine=TrustEngine(),
        attribution_engine=AttributionEngine(physics_rule),
        c_provider=c_provider,
        k_provider=CorrelationProvider(),
        h_provider=HReliabilityProvider(),
        flag_policy=flag_policy,
    )
    outcomes = pipeline.process(eval_messages)

    # Every evaluation window is clean (idle rig, no injected fault), so any
    # flag is a false positive by construction.
    severities = sorted(o.anomaly.severity for o in outcomes)
    n = len(severities)
    print(f"--- clean-data false positives, {n} windows, all genuinely clean ---")
    print(f"  {'threshold':>10}{'false flags':>14}{'FP rate':>10}")
    for threshold in THRESHOLD_SWEEP:
        false_flags = sum(1 for s in severities if s >= threshold)
        marker = "   <-- live value" if threshold == LIVE_THRESHOLD else ""
        print(f"  {threshold:>10.2f}{false_flags:>14}{false_flags / n:>9.1%}{marker}")

    flagged = [o for o in outcomes if o.anomaly.flag]
    print(
        f"\n  pipeline as configured ({LIVE_THRESHOLD}): {len(flagged)}/{n} flagged "
        f"({len(flagged) / n:.1%})"
    )

    print("\n--- per-channel flag rate (which channel absorbs the false positives) ---")
    for channel in CHANNELS:
        count = sum(1 for o in outcomes if o.channel_flags.get(channel))
        print(f"  {channel:<12}{count:>6}{count / n:>9.1%}")

    print(
        "\nDetection rate is NOT measured here: that needs labelled faults on real\n"
        "hardware, which no capture contains. Choosing a threshold on false\n"
        "positives alone trades away sensitivity invisibly."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
