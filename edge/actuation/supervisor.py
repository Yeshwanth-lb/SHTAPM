"""Edge safety supervisor: the one owner of the pump relay (FR-R1..R3, AC4; D041).

Every path that can switch the pump goes through ``SafetySupervisor``:

  operator   ``command()``  -- RelayCommand from the dashboard (admin, audited)
  self-heal  ``safe_stop("safe_stop")`` -- D018 escalation: divergence over its
             threshold, or a channel still isolated after 60 s of substitution
  dry-run    ``on_frame()`` -> ``DryRunDetector`` (FR-R2)
  watchdog   no healthy frame for ``watchdog_timeout_s`` while the pump is ON
             (FR-R3): the edge is stalled, or running blind
  shutdown   ``stop()`` -- the edge stopping drives the relay OFF; systemd's
             ``ExecStopPost`` covers a crash (``edge/actuation/gpio.py``)

AUTONOMOUS STOPS LATCH. After safe_stop / dry_run / watchdog the relay stays OFF
until an operator explicitly starts it again; nothing restarts the pump on its
own (PRD US-06). Every state change is published as a retained
``ActuationStatus`` with its cause, so the dashboard and the ledger always say
WHY the pump is stopped.

THE DRY-RUN BAND. A dry-running pump keeps spinning but loses its hydraulic
load, so its current falls -- yet stays above "motor off". The detector fires
when the pump is commanded ON, past a spin-up grace, and current sits inside
(``CURRENT_IDLE_MAX_A``, ``threshold_a``] for ``hold_samples`` consecutive
frames. ``threshold_a`` has NO default: it must be measured on the real pump
(``SHTAPM_DRY_RUN_CURRENT_A``); unset, dry-run protection is off and says so.
A reading at motor-off level (a spoof to 0 A, a cut wire) is outside the band:
it is the physics rule's case (D034), not a dry run.

RESIDUAL RISK (recorded in D041): the detector reads the current channel, so a
spoof INTO the dry-run band forces a safe stop (lost availability, never lost
safety), and a spoof of normal current during a genuine dry run would hide it
-- the same single-sensor limit the PRD's R3 names.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable

from app.schemas.actuation import ActuationCause, ActuationStatus, RelayCommand
from app.schemas.contracts import TelemetryMessage

from edge.actuation.relay import RelayController
from edge.actuation.watchdog import Watchdog
from edge.anomaly.operating_state_rule import BENCH_CURRENT_BANDS
from edge.drivers.base import now_iso_ms

log = logging.getLogger("shtapm.edge.safety")

# Motor-off current: the motor-state rule's idle band (D034). Below it the
# motor is not turning, which is not a dry run.
CURRENT_IDLE_MAX_A = BENCH_CURRENT_BANDS.idle_max
# Spin-up: measured on the bench 2026-10-27, current reaches its running level
# within ~2 s of switch-on (cycling capture); 5 s leaves margin.
SPIN_UP_GRACE_S = 5.0
DRY_RUN_HOLD_SAMPLES = 3  # ~3 s at 1 Hz: a single low sample is not a dry run
# 10 missed 1 Hz frames while the pump runs = the edge is stalled or blind.
WATCHDOG_TIMEOUT_S = 10.0
WATCHDOG_POLL_S = 1.0


class DryRunDetector:
    def __init__(
        self,
        threshold_a: float,
        *,
        grace_s: float = SPIN_UP_GRACE_S,
        hold_samples: int = DRY_RUN_HOLD_SAMPLES,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not threshold_a > CURRENT_IDLE_MAX_A:
            raise ValueError(
                f"dry-run threshold {threshold_a} A must exceed motor-off current "
                f"{CURRENT_IDLE_MAX_A} A"
            )
        self.threshold_a = threshold_a
        self._grace_s = grace_s
        self._hold = hold_samples
        self._clock = clock
        self._started_at: float | None = None
        self._streak = 0

    def reset(self) -> None:
        """The pump was just switched on: restart the spin-up grace."""
        self._started_at = self._clock()
        self._streak = 0

    def observe(self, current_a: float, relay_on: bool) -> bool:
        """True when this frame completes a dry-run detection."""
        if not relay_on or self._started_at is None:
            self._streak = 0
            return False
        if self._clock() - self._started_at < self._grace_s:
            return False
        in_band = CURRENT_IDLE_MAX_A < current_a <= self.threshold_a
        self._streak = self._streak + 1 if in_band else 0
        return self._streak >= self._hold


class SafetySupervisor:
    def __init__(
        self,
        *,
        device_id: str,
        relay: RelayController,
        hardware: bool,
        publish: Callable[[ActuationStatus], None],
        dry_run: DryRunDetector | None = None,
        watchdog_timeout_s: float = WATCHDOG_TIMEOUT_S,
        clock: Callable[[], float] = time.monotonic,
        now_iso: Callable[[], str] = now_iso_ms,
    ) -> None:
        self._device_id = device_id
        self._relay = relay
        self._hardware = hardware
        self._publish = publish
        self._dry_run = dry_run
        self._now_iso = now_iso
        self._lock = threading.RLock()
        self._latched = False
        self._last: ActuationStatus | None = None
        self._watchdog = Watchdog(
            timeout_s=watchdog_timeout_s, on_expire=self._on_watchdog, clock=clock
        )
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    # ---- lifecycle -----------------------------------------------------------
    def start(self, *, watchdog_thread: bool = True) -> None:
        """Announce the safe startup state (the controller already forced OFF)."""
        with self._lock:
            self._emit("startup", "edge started; relay forced OFF (safe default)")
        if watchdog_thread:
            self._thread = threading.Thread(target=self._watch, name="relay-watchdog", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        with self._lock:
            self._switch_off()
            self._emit("shutdown", "edge stopped; relay forced OFF")

    # ---- inputs ----------------------------------------------------------------
    def on_frame(self, frame: TelemetryMessage) -> None:
        """Every healthy frame: feed the watchdog and the dry-run detector."""
        with self._lock:
            self._watchdog.kick()
            if self._dry_run is None:
                return
            current = float(frame.sensors.current)
            if self._dry_run.observe(current, self._relay.is_on()):
                self.safe_stop(
                    "dry_run",
                    f"dry run: current {current:.3f} A in the dry-run band "
                    f"({CURRENT_IDLE_MAX_A}-{self._dry_run.threshold_a} A) while commanded ON",
                )

    def command(self, command: RelayCommand) -> bool:
        """An operator's explicit start/stop. Starting clears a safe-stop latch."""
        if command.device_id != self._device_id:
            log.warning("relay command %s for another device ignored", command.command_id)
            return False
        with self._lock:
            if command.state == "on":
                self._relay.on()
                self._latched = False
                self._watchdog.reset()
                if self._dry_run is not None:
                    self._dry_run.reset()
                self._emit("command", f"started by {command.issued_by}")
            else:
                self._switch_off()
                self._emit("command", f"stopped by {command.issued_by}")
        return True

    def safe_stop(self, cause: ActuationCause, reason: str) -> None:
        """Autonomous stop: relay OFF and latched until an operator starts it."""
        with self._lock:
            was_on = self._relay.is_on()
            self._switch_off()
            if was_on or not self._latched:
                self._latched = True
                self._emit(cause, reason)
            log.warning("SAFE STOP (%s): %s", cause, reason)

    # ---- state -----------------------------------------------------------------
    @property
    def latched(self) -> bool:
        return self._latched

    @property
    def last_status(self) -> ActuationStatus | None:
        return self._last

    # ---- internals -------------------------------------------------------------
    def _switch_off(self) -> None:
        try:
            self._relay.safe_off()
        except Exception:
            # A relay that cannot be driven is reported, never hidden: the
            # status still says OFF was commanded and the log carries the error.
            log.exception("relay could not be driven OFF")

    def _on_watchdog(self) -> None:
        if self._relay.is_on():
            self.safe_stop(
                "watchdog",
                "no healthy telemetry frame within the watchdog timeout while the pump ran",
            )

    def _watch(self) -> None:
        while not self._stop_event.wait(WATCHDOG_POLL_S):
            with self._lock:
                self.check_watchdog()

    def check_watchdog(self) -> None:
        """One watchdog evaluation (the thread calls this; tests call it directly)."""
        with self._lock:
            if self._watchdog.check():
                self._watchdog.reset()  # re-arm; the latch, not the timer, holds OFF

    def _emit(self, cause: ActuationCause, reason: str) -> None:
        status = ActuationStatus(
            device_id=self._device_id,
            ts=self._now_iso(),
            relay="on" if self._relay.is_on() else "off",
            cause=cause,
            reason=reason,
            latched=self._latched,
            hardware=self._hardware,
        )
        self._last = status
        try:
            self._publish(status)
        except Exception:
            log.warning("actuation status publish failed", exc_info=False)
