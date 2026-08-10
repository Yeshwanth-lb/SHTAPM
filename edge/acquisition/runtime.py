"""Edge acquisition runtime (P1 · C2→C3 integration).

Small supervisor that connects the C2 ``Sampler`` to the C3
``ResilientTelemetryPublisher``. It owns the sampling loop (D1) and per tick:

    result = sampler.sample_once()
    if result.frame is not None:      # unhealthy tick → no frame → skip (D3)
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
"""

from __future__ import annotations

import time
from collections.abc import Callable

from edge.acquisition.mqtt_publisher import ResilientTelemetryPublisher
from edge.acquisition.sampler import MAX_RATE_HZ, MIN_RATE_HZ, Sampler, SampleResult


class AcquisitionRuntime:
    def __init__(
        self,
        *,
        sampler: Sampler,
        publisher: ResilientTelemetryPublisher,
        rate_hz: float,
    ) -> None:
        if not (MIN_RATE_HZ <= rate_hz <= MAX_RATE_HZ):
            raise ValueError(f"rate_hz must be in [{MIN_RATE_HZ}, {MAX_RATE_HZ}], got {rate_hz}")
        self._sampler = sampler
        self._publisher = publisher
        self._period = 1.0 / rate_hz

    def tick(self) -> SampleResult:
        """One sample tick: sample, and publish only if a frame was produced.
        Publish exceptions propagate (no silent swallow)."""
        result = self._sampler.sample_once()
        if result.frame is not None:
            self._publisher.publish(result.frame)
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
