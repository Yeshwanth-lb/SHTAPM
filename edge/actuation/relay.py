"""Relay/actuator safe-state abstraction (P1 · C4) — hardware-free.

State machine + interface only. The **physical safe-stop** (driving a real GPIO
relay that clicks the pump off) is HARDWARE-BLOCKED and intentionally NOT
implemented here. A real ``Actuator`` (GPIO) plugs in later behind this
interface without changing consumers.

Safety: the actuator defaults to OFF, and ``safe_off()`` forces OFF (used by the
watchdog on expiry). This module has no C1/C2/C3 dependency.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum


class RelayState(str, Enum):
    OFF = "off"
    ON = "on"


class Actuator(ABC):
    """Drives a relay. Real GPIO implementation is out of scope (hardware-blocked)."""

    @abstractmethod
    def set_state(self, state: RelayState) -> None: ...

    @abstractmethod
    def get_state(self) -> RelayState: ...


class FakeActuator(Actuator):
    """Deterministic in-memory actuator for tests/dev. Starts OFF; records history."""

    def __init__(self) -> None:
        self._state = RelayState.OFF
        self.history: list[RelayState] = [RelayState.OFF]

    def set_state(self, state: RelayState) -> None:
        if not isinstance(state, RelayState):
            raise TypeError(f"state must be RelayState, got {type(state).__name__}")
        self._state = state
        self.history.append(state)

    def get_state(self) -> RelayState:
        return self._state


class RelayController:
    """Safe-state relay controller.

    Default **OFF** at construction; explicit ``on()`` / ``off()``; ``safe_off()``
    forces OFF (idempotent) — the watchdog calls this on expiry. Decoupled from
    the watchdog: after a safe-off, an operator must ``reset()`` the watchdog and
    then explicitly ``on()`` again (no auto-restart). Physical safe-stop remains
    HARDWARE-BLOCKED — this is state-machine/safety logic only.
    """

    def __init__(self, actuator: Actuator) -> None:
        self._actuator = actuator
        self._actuator.set_state(RelayState.OFF)  # enforce safe default at startup

    def on(self) -> None:
        self._actuator.set_state(RelayState.ON)

    def off(self) -> None:
        self._actuator.set_state(RelayState.OFF)

    def safe_off(self) -> None:
        """Force the safe (OFF) state. Idempotent."""
        self._actuator.set_state(RelayState.OFF)

    @property
    def state(self) -> RelayState:
        return self._actuator.get_state()

    def is_on(self) -> bool:
        return self._actuator.get_state() is RelayState.ON
