"""Persisted clean baseline for the live P2 monitor (D031).

WHY: ``LiveP2Monitor`` used to learn "normal" from ``P2_FIT_WINDOW_COUNT`` live
windows at every start. The bench Pi ran with 5 windows (about 2.5 minutes).
Replaying the real 7.18 h idle capture through the exact live composition
(2026-10-26) showed what that costs on genuinely clean data: `current` judged
Malicious in 25% of windows and four of six channels tracked as isolated within
30 minutes, so the dashboard showed VIRTUAL with no attack anywhere. Fitting on
30 minutes of the same capture removed the false isolations (no Malicious
`current` or `vibration` window, one spurious pressure candidate).

WHAT IS STORED: the clean frames themselves -- raw engineering-unit values per
contiguous segment -- not fitted model objects. At startup the four fitted P2
components (``ConsistencyProvider``, ``IsolationForestDetector``,
``SeverityThresholdFlagPolicy``, ``TrendSignPhysicsRule``) are refit from these
frames. Two reasons, both deliberate:

  * Safety. ``np.load(..., allow_pickle=False)`` plus JSON metadata never
    executes code on load, matching ``edge/models/twin_bundle.py``'s refusal of
    arbitrary-object unpickling.
  * Portability. A pickled scikit-learn model is tied to the version that wrote
    it; the dev laptop and the Pi run different versions. Refitting from data
    is version-independent, and deterministic because the detector's
    ``random_state`` is fixed in ``edge/main.py``.

SEGMENTS: frames are split wherever consecutive timestamps are more than
``max_gap_s`` apart, and windows are built per segment. A window spanning an
outage would pair samples minutes apart as if consecutive -- the bug class
``bench_fault_injection_eval.py`` and ``bench_twin_training.py`` each found
independently. ``LiveP2Monitor``'s rolling buffer cannot span an outage either,
so segmenting reproduces deployed behaviour.

Files: ``<model_dir>/p2_baseline.npz`` and ``<model_dir>/p2_baseline.json``.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
from app.schemas.build import build_telemetry
from app.schemas.contracts import CHANNELS, TelemetryMessage

from edge.anomaly.preprocess import Preprocessor, Window

log = logging.getLogger("shtapm.edge.p2_baseline")

FORMAT_VERSION = 1
BASELINE_STEM = "p2_baseline"
KIND = "p2_baseline"
DEFAULT_MAX_GAP_S = 5.0
# Measured, not chosen: 30 minutes is the shortest fit in the 2026-10-26
# replay that produced no false Malicious `current`/`vibration` window. Shorter
# baselines are still accepted, with a warning naming this evidence.
RECOMMENDED_MIN_SECONDS = 30 * 60

_SYNTHETIC_TS = "1970-01-01T00:00:00.000Z"


@dataclass(frozen=True)
class CaptureParseResult:
    messages: tuple[TelemetryMessage, ...]
    rejected_line_count: int


@dataclass(frozen=True)
class P2Baseline:
    """Clean frames, split into contiguous segments, plus provenance."""

    segments: tuple[np.ndarray, ...]
    device_id: str
    source: str
    created_at: str
    max_gap_s: float
    window_size: int
    step: int
    duration_s: float

    @property
    def frame_count(self) -> int:
        return int(sum(seg.shape[0] for seg in self.segments))

    def window_count(self) -> int:
        return int(
            sum(
                (seg.shape[0] - self.window_size) // self.step + 1
                for seg in self.segments
                if seg.shape[0] >= self.window_size
            )
        )

    def windows(self, preprocessor: Preprocessor) -> list[Window]:
        """Rebuild the clean P2 windows with ``preprocessor``.

        Raises ``ValueError`` if the preprocessor's windowing differs from the
        one this baseline was built for: fitting on differently-shaped windows
        would silently calibrate against the wrong distribution."""
        if preprocessor.window_size != self.window_size or preprocessor.step != self.step:
            raise ValueError(
                f"baseline built for window_size={self.window_size}, step={self.step}; "
                f"preprocessor has window_size={preprocessor.window_size}, "
                f"step={preprocessor.step}"
            )
        windows: list[Window] = []
        for segment in self.segments:
            frames = [
                build_telemetry(
                    self.device_id,
                    _SYNTHETIC_TS,
                    {ch: float(segment[row, col]) for col, ch in enumerate(CHANNELS)},
                    row,
                )
                for row in range(segment.shape[0])
            ]
            windows.extend(preprocessor.process(frames))
        return windows


def parse_capture(lines: Iterable[str]) -> CaptureParseResult:
    """Parse ``mosquitto_sub`` output: one telemetry JSON payload per line.

    Tolerates a leading ``<topic> `` prefix (``mosquitto_sub -v``). Malformed or
    contract-violating lines are counted and skipped, never raised: a capture
    cut off mid-line by stopping the recorder must still be usable."""
    messages: list[TelemetryMessage] = []
    rejected = 0
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        start = line.find("{")
        if start < 0:
            rejected += 1
            continue
        try:
            messages.append(TelemetryMessage.model_validate_json(line[start:]))
        except Exception:
            rejected += 1
    return CaptureParseResult(messages=tuple(messages), rejected_line_count=rejected)


def _parse_ts(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def split_segments(
    messages: Sequence[TelemetryMessage], max_gap_s: float = DEFAULT_MAX_GAP_S
) -> list[list[TelemetryMessage]]:
    """Order by ``sample_seq`` and split wherever the timestamp gap exceeds
    ``max_gap_s``, or time runs backwards (a service restart resets
    ``sample_seq`` while the wall clock keeps going)."""
    if max_gap_s <= 0:
        raise ValueError(f"max_gap_s must be > 0, got {max_gap_s}")
    ordered = sorted(messages, key=lambda m: (_parse_ts(m.ts), m.sample_seq))
    segments: list[list[TelemetryMessage]] = []
    current: list[TelemetryMessage] = []
    previous: datetime | None = None
    for message in ordered:
        ts = _parse_ts(message.ts)
        if previous is not None:
            gap = (ts - previous).total_seconds()
            if gap > max_gap_s or gap < 0:
                segments.append(current)
                current = []
        current.append(message)
        previous = ts
    if current:
        segments.append(current)
    return segments


def build_baseline(
    messages: Sequence[TelemetryMessage],
    *,
    source: str,
    preprocessor: Preprocessor,
    max_gap_s: float = DEFAULT_MAX_GAP_S,
) -> P2Baseline:
    """Build a baseline from clean telemetry. Segments shorter than one window
    contribute no window and are dropped. Raises ``ValueError`` if nothing
    usable remains, or if the capture mixes devices."""
    if not messages:
        raise ValueError("capture contains no valid telemetry messages")
    devices = {m.device_id for m in messages}
    if len(devices) != 1:
        raise ValueError(f"capture mixes devices {sorted(devices)}; record one device per file")

    usable = [
        seg for seg in split_segments(messages, max_gap_s) if len(seg) >= preprocessor.window_size
    ]
    if not usable:
        raise ValueError(
            f"no contiguous segment reaches one window ({preprocessor.window_size} frames)"
        )

    arrays = tuple(
        np.array(
            [[float(getattr(m.sensors, ch)) for ch in CHANNELS] for m in seg], dtype=np.float64
        )
        for seg in usable
    )
    duration = sum((_parse_ts(seg[-1].ts) - _parse_ts(seg[0].ts)).total_seconds() for seg in usable)
    return P2Baseline(
        segments=arrays,
        device_id=devices.pop(),
        source=source,
        created_at=datetime.now(UTC).isoformat(timespec="seconds"),
        max_gap_s=max_gap_s,
        window_size=preprocessor.window_size,
        step=preprocessor.step,
        duration_s=float(duration),
    )


def save_baseline(baseline: P2Baseline, model_dir: str | Path) -> tuple[Path, Path]:
    """Write ``p2_baseline.npz`` + ``p2_baseline.json``; returns both paths."""
    directory = Path(model_dir)
    directory.mkdir(parents=True, exist_ok=True)
    npz_path = directory / f"{BASELINE_STEM}.npz"
    json_path = directory / f"{BASELINE_STEM}.json"
    np.savez_compressed(
        npz_path, **{f"segment_{i}": seg for i, seg in enumerate(baseline.segments)}
    )
    metadata = {
        "kind": KIND,
        "format_version": FORMAT_VERSION,
        "channels": list(CHANNELS),
        "device_id": baseline.device_id,
        "source": baseline.source,
        "created_at": baseline.created_at,
        "max_gap_s": baseline.max_gap_s,
        "window_size": baseline.window_size,
        "step": baseline.step,
        "segment_count": len(baseline.segments),
        "frame_count": baseline.frame_count,
        "window_count": baseline.window_count(),
        "duration_s": baseline.duration_s,
    }
    json_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return npz_path, json_path


def load_baseline(model_dir: str | Path) -> P2Baseline | None:
    """Load the baseline from ``model_dir``.

    Returns None when no baseline exists, or -- having logged why -- when it is
    unreadable or incompatible. The caller then falls back to live warm-up
    fitting, so a bad file can degrade calibration but never stop telemetry."""
    directory = Path(model_dir)
    json_path = directory / f"{BASELINE_STEM}.json"
    npz_path = directory / f"{BASELINE_STEM}.npz"
    if not json_path.is_file() and not npz_path.is_file():
        return None
    try:
        metadata = json.loads(json_path.read_text(encoding="utf-8"))
        if metadata.get("kind") != KIND:
            raise ValueError(f"kind is {metadata.get('kind')!r}, expected {KIND!r}")
        if metadata.get("format_version") != FORMAT_VERSION:
            raise ValueError(
                f"format_version {metadata.get('format_version')!r} unsupported "
                f"(expected {FORMAT_VERSION})"
            )
        if metadata.get("channels") != list(CHANNELS):
            raise ValueError(f"channel order {metadata.get('channels')!r} != {list(CHANNELS)}")
        count = int(metadata["segment_count"])
        with np.load(npz_path, allow_pickle=False) as data:
            segments = tuple(
                np.asarray(data[f"segment_{i}"], dtype=np.float64) for i in range(count)
            )
        for i, seg in enumerate(segments):
            if seg.ndim != 2 or seg.shape[1] != len(CHANNELS):
                raise ValueError(f"segment_{i} has shape {seg.shape}")
            if not np.all(np.isfinite(seg)):
                raise ValueError(f"segment_{i} contains non-finite values")
        return P2Baseline(
            segments=segments,
            device_id=str(metadata["device_id"]),
            source=str(metadata["source"]),
            created_at=str(metadata["created_at"]),
            max_gap_s=float(metadata["max_gap_s"]),
            window_size=int(metadata["window_size"]),
            step=int(metadata["step"]),
            duration_s=float(metadata["duration_s"]),
        )
    except Exception as e:
        log.error(
            "P2 baseline in %s is unusable (%s) -- falling back to live warm-up fitting",
            directory,
            e,
        )
        return None
