"""Edge acquisition runtime (P1 · C2→C3 integration).

Small supervisor that connects the C2 ``Sampler`` to the C3
``ResilientTelemetryPublisher``. It owns the sampling loop (D1) and per tick:

    result = sampler.sample_once()
    if result.frame is not None:      # unhealthy tick → no frame → skip (D3)
        on_healthy_frame(result.frame)  # optional monitoring hook, see below
        publisher.publish(result.frame)
    sleep(1 / rate_hz)

It does NOT modify or wrap ``Sampler.run`` / the publisher, does not build
frames, and does not create a second publisher.

Two buffers coexist by design (D2), each with a distinct role — not to be
merged:
  * ``Sampler.buffer`` (C2): a bounded overwrite ring of recent samples
    (backpressure / local history).
  * publisher's FR-Q4 buffer (C3): a bounded resume buffer that holds frames
    while the broker is disconnected and replays them in order on reconnect.

Publish failures are NOT swallowed — an unexpected exception from
``publisher.publish`` propagates out of the loop rather than falsely reporting a
successful transmission.

An unhealthy tick (any channel's ``Reading.healthy`` is False) is, by design,
silent on the wire — no frame, nothing published (C2's decision C: the frozen
contract has no per-channel health field). ``Sensor.read()`` (P1 base.py) also
swallows the underlying exception for the same never-throws-into-the-loop
discipline, so without a local log line an unhealthy tick is invisible from
the running process's output — undiagnosable without reading source and adding
print statements. ``tick()`` logs a WARNING naming the unhealthy channel(s) so
this is visible at the point it happens, without changing the health gate, the
wire contract, or hiding/downgrading the underlying failure.

``on_healthy_frame`` (P0 gap-closure item 1, monitoring-only P2 wiring):
optional, defaults to ``None`` — every existing caller/test that doesn't pass
it gets byte-identical behavior to before this parameter existed. When
supplied, it is called with the same ``TelemetryMessage`` about to be
published, BEFORE ``publisher.publish()`` — so monitoring never depends on,
or can delay, telemetry delivery. Any exception it raises is caught and
logged here, never propagated: a bug in monitoring must not be able to stop
or crash telemetry publishing (the same "a sink failure must not break
ingestion" discipline already used by the backend's MQTT consumer sinks).
This runtime does not know or care what the hook does with the frame — it
does not isolate channels, actuate, publish a decision, or write a ledger
entry; see ``edge/pipeline/monitor.py`` for the current (monitoring-only)
use of this seam.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable

from app.schemas.contracts import TelemetryMessage

from edge.acquisition.mqtt_publisher import ResilientTelemetryPublisher
from edge.acquisition.sampler import MAX_RATE_HZ, MIN_RATE_HZ, Sampler, SampleResult

log = logging.getLogger("shtapm.edge.runtime")


class AcquisitionRuntime:
    def __init__(
        self,
        *,
        sampler: Sampler,
        publisher: ResilientTelemetryPublisher,
        rate_hz: float,
        on_healthy_frame: Callable[[TelemetryMessage], None] | None = None,
    ) -> None:
        if not (MIN_RATE_HZ <= rate_hz <= MAX_RATE_HZ):
            raise ValueError(f"rate_hz must be in [{MIN_RATE_HZ}, {MAX_RATE_HZ}], got {rate_hz}")
        self._sampler = sampler
        self._publisher = publisher
        self._period = 1.0 / rate_hz
        self._on_healthy_frame = on_healthy_frame

    def tick(self) -> SampleResult:
        """One sample tick: sample, and publish only if a frame was produced.
        Publish exceptions propagate (no silent swallow). An unhealthy tick logs
        a WARNING naming the unhealthy channel(s) — see module docstring."""
        result = self._sampler.sample_once()
        if result.frame is not None:
            if self._on_healthy_frame is not None:
                try:
                    self._on_healthy_frame(result.frame)
                except Exception:  # monitoring must never break telemetry publishing
                    log.warning("on_healthy_frame hook raised; continuing", exc_info=True)
            self._publisher.publish(result.frame)
        else:
            unhealthy = sorted(ch for ch, r in result.readings.items() if not r.healthy)
            log.warning(
                "unhealthy tick at ts=%s — no frame published; unhealthy channels=%s",
                result.ts,
                unhealthy,
            )
        return result

    def run(
        self,
        *,
        should_continue: Callable[[], bool],
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        """Loop ``tick`` at the configured rate until ``should_continue()`` is
        False. ``sleep`` is injectable so tests never block."""
        while should_continue():
            self.tick()
            sleep(self._period)

    def stop(self) -> None:
        """Clean shutdown: stop the publisher (publishes retained offline,
        disconnects, joins its loop)."""
        self._publisher.stop()
