"""Offline loader for real-hardware MQTT telemetry captures (U05 bench
evidence preparation).

Reads a newline-delimited capture of already-published telemetry payloads
(see ``project-state/REPRODUCIBILITY.md`` §5 and the bench-capture
procedure this loader supports), validates each line against the frozen,
UNMODIFIED ``TelemetryMessage`` contract, and builds the same P2-consistent
``Window`` objects the live path produces -- via the existing, unmodified
``edge.anomaly.preprocess.Preprocessor``, no new windowing logic.

Hardware-free, diagnostic-only, offline analysis tooling -- same status as
every other ``edge/eval/*.py`` module (not production, not on any
acceptance path, not imported by ``edge/main.py`` or any live/actuation
code). This module loads and windows data; it computes no residual, no
divergence score, no threshold, no fault label, and no calibration value
-- see ``edge/eval/u05_divergence_analysis.py`` for the next step, and
``project-state/DECISIONS.md``'s U05 entries for why no numeric threshold
exists anywhere in this repo.

Malformed/non-JSON/contract-violating lines are skipped and counted, never
raised -- mirrors ``app.mqtt.consumer.TelemetryConsumer.handle()``'s own
reject-safely discipline (a bad line in a capture file must not crash
offline analysis any more than a bad MQTT message crashes live ingestion).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from app.schemas.contracts import CHANNELS, TelemetryMessage

from edge.anomaly.preprocess import Preprocessor, Window

EXECUTION_MODE = "offline_analysis"
MODEL_STATUS = "diagnostic_unvalidated"


@dataclass(frozen=True)
class CaptureLoadResult:
    """Everything loaded from one capture file. ``rejected_line_count`` is
    reported so a reviewer can see how much of a real capture failed to
    parse -- never silently dropped without a count."""

    messages: tuple[TelemetryMessage, ...]
    rejected_line_count: int
    execution_mode: str = EXECUTION_MODE
    model_status: str = MODEL_STATUS


def _extract_json_payload(line: str) -> str:
    """Tolerates an optional leading ``<topic> `` prefix (e.g. from
    ``mosquitto_sub -v``) ahead of the JSON payload -- the payload itself
    always starts with ``{`` per the frozen contract's JSON object shape.
    The recommended capture command (REPRODUCIBILITY.md §5) subscribes to
    one topic per file WITHOUT ``-v``, so this is a defensive fallback,
    not the expected format."""
    idx = line.find("{")
    return line[idx:] if idx > 0 else line


def load_telemetry_capture(lines: Iterable[str]) -> CaptureLoadResult:
    """Parse a captured telemetry stream: one JSON ``TelemetryMessage``
    payload per line (blank lines skipped). Never raises on bad input."""
    messages: list[TelemetryMessage] = []
    rejected = 0
    for raw_line in lines:
        stripped = raw_line.strip()
        if not stripped:
            continue
        try:
            messages.append(TelemetryMessage.model_validate_json(_extract_json_payload(stripped)))
        except Exception:
            rejected += 1
    return CaptureLoadResult(messages=tuple(messages), rejected_line_count=rejected)


def ordered_messages(result: CaptureLoadResult) -> list[TelemetryMessage]:
    """Capture order is not guaranteed (retry/reconnect can reorder a real
    MQTT stream) -- always sort by ``sample_seq`` before windowing."""
    return sorted(result.messages, key=lambda m: m.sample_seq)


def windows_from_capture(result: CaptureLoadResult, preprocessor: Preprocessor) -> list[Window]:
    """Build P2-consistent windows from a loaded capture, using the
    caller-supplied, already-existing ``Preprocessor`` unmodified -- no new
    windowing logic. Returns an empty list if the capture is shorter than
    one window (same behavior as ``Preprocessor.process()`` itself)."""
    return preprocessor.process(ordered_messages(result))


def raw_channel_values_for_window(
    window: Window, messages: Sequence[TelemetryMessage]
) -> dict[str, float]:
    """The exact raw (pre-normalization) per-channel values for the same
    frame ``LiveP2Monitor``/``edge.pipeline.monitor.RawChannelValues``
    would treat as this window's current reading -- the last message in
    the window's own index range (``window.end_index`` is exclusive).
    ``messages`` MUST be the same ordered list ``windows_from_capture``
    built the window from."""
    latest = messages[window.end_index - 1]
    return {ch: getattr(latest.sensors, ch) for ch in CHANNELS}
