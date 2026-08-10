"""Deadman watchdog (P1 · C4) — hardware-free.

Software deadman timer: if not ``kick()``-ed within ``timeout_s``, ``check()``
latches expired and fires ``on_expire`` ONCE — wired to force the actuator to a
safe OFF (``RelayController.safe_off``). The clock is injectable so tests need no
real waiting.

The **physical** hardware/software watchdog that defaults the pump OFF on
edge-node process death (FR-R3) is HARDWARE-BLOCKED; this is the deadman-timer
logic only. A dead process simply stops calling ``kick()`` → the next ``check()``
(or the real hardware watchdog) drives OFF.
"""

from __future__ import annotations

import time
from collections.abc import Callable


class Watchdog:
    def __init__(
        self,
        *,
        timeout_s: float,
        on_expire: Callable[[], None],
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if timeout_s <= 0:
            raise ValueError("timeout_s must be > 0")
        self._timeout = timeout_s
        self._on_expire = on_expire
        self._clock = clock
        self._last_kick = clock()
        self._expired = False

    def kick(self) -> None:
        """Feed the watchdog (process alive). No effect once expired — recovery
        is explicit via ``reset()`` (a tripped safety timer must not self-clear)."""
        if not self._expired:
            self._last_kick = self._clock()

    def check(self) -> bool:
        """Evaluate the deadman. If overdue, latch expired and fire ``on_expire``
        exactly once. Returns whether it is expired."""
        if self._expired:
            return True
        if self._clock() - self._last_kick > self._timeout:
            self._expired = True
            self._on_expire()
        return self._expired

    def reset(self) -> None:
        """Explicit recovery: clear expiry and re-arm from now."""
        self._last_kick = self._clock()
        self._expired = False

    @property
    def expired(self) -> bool:
        return self._expired

    @property
    def timeout_s(self) -> float:
        return self._timeout
