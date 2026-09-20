"""Run the REAL, unmodified P2 pipeline against a labelled real-fault capture
from ``edge/scripts/load_capture.py`` (U07 fault-injection session).

Diagnostic/offline tooling: not production, not imported by ``edge/main.py``,
not on any acceptance path.

WHY: ``bench_if_tuning.py`` measured the deployed detector's false-positive
rate on real CLEAN bench data, but explicitly could not measure detection
rate -- no capture contained a labelled real fault. This script consumes a
capture where real faults were physically induced (sensor unplugged/tapped/
covered, motor switched by hand) and run through the actual production
components, to find out what the pipeline really does with them.

Frame construction matches what ``edge/main.py``'s Sampler would actually
publish: a message is only built from rows where every channel it carries is
healthy. This is deliberate, not a simplification -- it means a DHT22 dropout
is correctly represented as an ABSENCE of frames (matching the real all-six-
healthy contract), never as a bad value handed to the detector.

``gas`` has no real sensor in this capture (no MQ135 driver exists). It is
filled with ``edge.drivers.fake.realistic_raw`` using the registry's own
documented fixture parameters -- the SAME fake-signal generator
``edge/main.py``'s live service already runs for this channel in production,
not an invented value. (An earlier version of this script used a constant
placeholder and found it flagged nearly every window: a fully-flat channel is
exactly the variance=0.0 pathology ``DECISIONS.md`` D013 already documents as
"the most extreme possible low value" under ChannelFlagPolicy's own-baseline
test. That was a methodology artifact of the placeholder, not a real finding,
and is the reason a constant is not used here.)

Fit/eval split is temporal: the detector, flag policy, correlation provider
and physics rule are fit ONLY on the clean lead-in segment before the first
deliberate fault, then the whole stream is evaluated -- same discipline as
``bench_if_tuning.py``/D011-F.

SEGMENT-GAP DISCIPLINE: dropping unhealthy rows can leave two samples that
were actually minutes apart sitting next to each other in the filtered list.
``Preprocessor.process()`` has no notion of a time gap and will happily build
a 30-sample window spanning one -- the same bug class ``bench_twin_training.py``
found and fixed for digital-twin training. It matters doubly here: in
production, ``LiveP2Monitor``'s rolling buffer only ever holds frames it
actually received, so a window CANNOT span a real outage there either -- the
buffer simply refills after telemetry resumes. This script therefore splits
the stream into contiguous segments at any inter-frame gap over
``--max-gap-s`` and evaluates each segment independently, never across a
break. A ``WindowOutcome``'s ``start_index``/``end_index`` are local to
whichever segment produced them, so results are tracked as
``(segment, outcome)`` pairs rather than flattened into one shared index
space -- flattening them was tried first and produced windows that silently
spanned the DHT22 outage, inflating apparent event duration.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime

from app.schemas.contracts import TelemetryMessage

from edge.anomaly.attribution import AttributionEngine
from edge.anomaly.iforest import IsolationForestDetector
from edge.anomaly.physics_rule import TrendSignPhysicsRule
from edge.anomaly.pipeline import P2Pipeline
from edge.anomaly.policy import SeverityThresholdFlagPolicy
from edge.anomaly.preprocess import Preprocessor
from edge.drivers.fake import realistic_raw
from edge.drivers.registry import _REALISTIC_FAKE_PARAMS_FIXTURE
from edge.trust.beta import TrustBand
from edge.trust.c_consistency import ConsistencyProvider
from edge.trust.engine import TrustEngine
from edge.trust.h_reliability import HReliabilityProvider
from edge.trust.k_correlation import CorrelationProvider

LIVE_THRESHOLD = 0.90  # matches edge/main.py's deployed _P2_DETECTOR_FLAG_THRESHOLD
DEFAULT_MAX_GAP_S = 5.0  # matches this project's own "no inter-frame gap > 5s" bar

_GAS_PARAMS = {k: v for k, v in _REALISTIC_FAKE_PARAMS_FIXTURE["gas"].items() if k != "value_range"}
_GAS_LO, _GAS_HI = _REALISTIC_FAKE_PARAMS_FIXTURE["gas"]["value_range"]


def _make_gas_gen():
    raw_gen = realistic_raw(**_GAS_PARAMS)

    def _gas_gen() -> float:
        # realistic_raw() itself has no clamp -- that is Sensor's job in
        # production (edge/drivers/registry.py's _build_fake_driver passes
        # value_range to Sensor). Reproduced here since no Sensor wrapper is
        # used in this script.
        return max(_GAS_LO, min(_GAS_HI, raw_gen()))

    return _gas_gen


def _load_rows(path: str) -> list[dict]:
    rows = []
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", help="load_capture.py JSONL output with real induced faults")
    parser.add_argument(
        "--max-gap-s",
        type=float,
        default=DEFAULT_MAX_GAP_S,
        help="inter-frame gap above which a new evaluation segment starts",
    )
    args = parser.parse_args()

    rows = _load_rows(args.capture)
    t0 = datetime.fromisoformat(rows[0]["ts"].replace("Z", "+00:00"))

    def rel_t(ts: str) -> float:
        return (datetime.fromisoformat(ts.replace("Z", "+00:00")) - t0).total_seconds()

    # ---- build the stream Sampler would actually have published ---------------
    gas_gen = _make_gas_gen()
    messages: list[TelemetryMessage] = []
    dropped_unhealthy = 0
    for row in rows:
        if not (
            row["temperature_healthy"]
            and row["humidity_healthy"]
            and row["pressure_healthy"]
            and row["current_healthy"]
            and row["vibration_healthy"]
        ):
            dropped_unhealthy += 1
            continue
        messages.append(
            TelemetryMessage(
                device_id="pump-01",
                ts=row["ts"],
                sensors={
                    "temperature": row["temperature_c"],
                    "vibration": row["vibration_g_driver"],
                    "pressure": row["pressure_hpa"],
                    "humidity": row["humidity_pct"],
                    "gas": gas_gen(),
                    "current": row["current_a"],
                },
                sample_seq=len(messages),
            )
        )

    print(
        f"total rows: {len(rows)}   published-equivalent frames: {len(messages)}   "
        f"dropped (unhealthy): {dropped_unhealthy}"
    )
    print(
        "Dropped frames are frames the real Sampler would never publish (an unhealthy "
        "channel withholds the whole frame) -- an architectural consequence of the "
        "all-six-healthy contract, not a gap in this analysis.\n"
    )

    if not messages:
        print("ERROR: no fully-healthy frames in this capture", file=sys.stderr)
        return 1

    # ---- split into genuinely-contiguous segments ------------------------------
    segments: list[list[TelemetryMessage]] = []
    current: list[TelemetryMessage] = [messages[0]]
    for prev, msg in zip(messages, messages[1:], strict=False):
        if rel_t(msg.ts) - rel_t(prev.ts) > args.max_gap_s:
            segments.append(current)
            current = []
        current.append(msg)
    segments.append(current)

    print(f"contiguous segments (gap > {args.max_gap_s}s starts a new one): {len(segments)}")
    for i, seg in enumerate(segments):
        print(
            f"  segment {i}: t={rel_t(seg[0].ts):>6.1f}s -> {rel_t(seg[-1].ts):>6.1f}s  "
            f"n={len(seg)}"
        )

    # ---- fit on the clean lead-in segment only ---------------------------------
    fit_messages = segments[0]
    print(f"\nfit segment: {len(fit_messages)} messages")

    preprocessor = Preprocessor(median_kernel=1, low_pass_alpha=1.0)
    fit_windows = preprocessor.process(fit_messages)
    if not fit_windows:
        print("ERROR: not enough clean lead-in to fit a single window", file=sys.stderr)
        return 1
    print(f"fit windows: {len(fit_windows)}")

    detector = IsolationForestDetector(flag_threshold=LIVE_THRESHOLD, random_state=0)
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

    # Evaluate each contiguous segment SEPARATELY (never across a gap). A
    # WindowOutcome's start_index/end_index are LOCAL to whichever segment
    # produced it, so each outcome is paired with its own segment's message
    # list rather than flattened into one shared index space.
    results = []  # [(segment_messages, outcome), ...]
    for seg in segments:
        if len(seg) < preprocessor.window_size:
            continue  # too short to form even one real window
        for outcome in pipeline.process(seg):
            results.append((seg, outcome))
    print(f"windows evaluated: {len(results)}\n")

    def window_times(seg, o):
        return rel_t(seg[o.window.start_index].ts), rel_t(seg[o.window.end_index - 1].ts)

    print("--- ALL flagged windows ---")
    print(f"{'window#':>8}{'t_start':>10}{'t_end':>10}{'severity':>10}   flagged_channels")
    any_flagged = False
    for i, (seg, o) in enumerate(results):
        if o.anomaly.flag:
            any_flagged = True
            t_start, t_end = window_times(seg, o)
            flagged_ch = [ch for ch, f in o.channel_flags.items() if f]
            print(f"{i:>8}{t_start:>10.1f}{t_end:>10.1f}{o.anomaly.severity:>10.3f}   {flagged_ch}")
    if not any_flagged:
        print("  (none)")

    def report_window_range(label: str, t_lo: float, t_hi: float) -> None:
        print(f"\n--- {label} (t={t_lo}-{t_hi}s) ---")
        hit = False
        for i, (seg, o) in enumerate(results):
            t_start, t_end = window_times(seg, o)
            if t_end < t_lo or t_start > t_hi:
                continue
            hit = True
            flagged_ch = [ch for ch, f in o.channel_flags.items() if f]
            attributions = {
                ch: o.attribution[ch].attribution.value
                for ch in o.attribution
                if o.attribution[ch].attribution.value != "none"
            }
            trust_low = {
                ch: round(o.trust[ch].trust, 3)
                for ch in o.trust
                if o.trust[ch].band != TrustBand.TRUSTED
            }
            print(
                f"  window {i:>3} t={t_start:>6.1f}-{t_end:<6.1f} "
                f"flag={o.anomaly.flag} sev={o.anomaly.severity:.3f} "
                f"channel_flags={flagged_ch} attribution={attributions or '-'} "
                f"non-trusted={trust_low or '-'}"
            )
        if not hit:
            print("  (no windows overlap this range)")

    # These two ranges are specific to the 2026-09-20 session capture
    # (project-state/FAULT_INJECTION_VALIDATION.md) -- pass different
    # values, or read the flagged-windows table above, for another capture.
    report_window_range("ADXL335 tap event", 260, 335)
    report_window_range("Motor ON + abrupt current drop", 555, 665)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
