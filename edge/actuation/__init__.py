"""Edge actuation (P1 · C4): relay safe-state machine + deadman watchdog.

Hardware-free logic only; physical GPIO relay + real safe-stop are
hardware-blocked. No dependency on C1/C2/C3.
"""

from edge.actuation.relay import Actuator, FakeActuator, RelayController, RelayState
from edge.actuation.watchdog import Watchdog

__all__ = [
    "Actuator",
    "FakeActuator",
    "RelayController",
    "RelayState",
    "Watchdog",
]
