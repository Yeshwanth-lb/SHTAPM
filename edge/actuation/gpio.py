"""Physical relay driver for the Raspberry Pi (FR-R1, AC4; D041).

Drives one GPIO output through ``pinctrl`` -- Raspberry Pi OS's own pin tool
(raspi-utils, present on the bench Pi: it reported GPIO17's state on
2026-10-26). No Python GPIO package is added, and a pin set by ``pinctrl``
keeps its level, which is exactly why shutdown must drive it OFF explicitly
(``python -m edge.actuation.gpio off`` from systemd ``ExecStopPost``, below).

POLARITY IS REQUIRED, NEVER GUESSED. Cheap relay boards are often active-LOW
(input pulled low = coil energised); others are active-HIGH. A wrong guess
would switch the pump ON when the software means OFF, so
``SHTAPM_RELAY_ACTIVE_LOW`` has no default: configure the pin without it and
the edge refuses to start.

WIRING FOR FAIL-SAFE: use the relay's normally-open (NO) contact in the motor
supply, so a de-energised coil -- Pi powered off, cable pulled -- means pump OFF.

Pins the bench already uses are refused: GPIO2/3 (I2C: BMP280, INA219),
GPIO7-11 (SPI0: MCP3008 for the ADXL335), GPIO17 (DHT22).
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable, Mapping

from edge.actuation.relay import Actuator, RelayState

RESERVED_PINS: dict[int, str] = {
    2: "I2C SDA (BMP280, INA219)",
    3: "I2C SCL (BMP280, INA219)",
    7: "SPI0 CE1",
    8: "SPI0 CE0 (MCP3008)",
    9: "SPI0 MISO (MCP3008)",
    10: "SPI0 MOSI (MCP3008)",
    11: "SPI0 SCLK (MCP3008)",
    17: "DHT22",
}
RELAY_GPIO_ENV = "SHTAPM_RELAY_GPIO"
RELAY_ACTIVE_LOW_ENV = "SHTAPM_RELAY_ACTIVE_LOW"

Runner = Callable[..., subprocess.CompletedProcess]


class RelayConfigError(ValueError):
    """The relay configuration is incomplete or unsafe."""


def _check_pin(pin: int) -> None:
    if not 0 <= pin <= 27:
        raise RelayConfigError(f"GPIO{pin} is not a BCM header pin (0-27)")
    if pin in RESERVED_PINS:
        raise RelayConfigError(f"GPIO{pin} is already used by {RESERVED_PINS[pin]}")


def _level(state: RelayState, active_low: bool) -> str:
    energise = state is RelayState.ON
    high = energise != active_low  # active-low energises on a LOW level
    return "dh" if high else "dl"


class PinctrlActuator(Actuator):
    """One relay on one BCM GPIO pin, driven with ``pinctrl set <pin> op dh|dl``."""

    def __init__(
        self,
        pin: int,
        *,
        active_low: bool,
        run: Runner | None = None,
        executable: str = "pinctrl",
    ) -> None:
        _check_pin(pin)
        self.pin = pin
        self.active_low = active_low
        self._run = run if run is not None else subprocess.run
        self._executable = executable
        self._state: RelayState | None = None

    def set_state(self, state: RelayState) -> None:
        if not isinstance(state, RelayState):
            raise TypeError(f"state must be RelayState, got {type(state).__name__}")
        command = [self._executable, "set", str(self.pin), "op", _level(state, self.active_low)]
        try:
            result = self._run(command, capture_output=True, text=True, timeout=5, check=False)
        except (OSError, subprocess.SubprocessError) as e:
            raise OSError(f"relay GPIO{self.pin}: {' '.join(command)} failed: {e}") from e
        if result.returncode != 0:
            raise OSError(
                f"relay GPIO{self.pin}: {' '.join(command)} exited {result.returncode}: "
                f"{(result.stderr or '').strip()}"
            )
        self._state = state

    def get_state(self) -> RelayState:
        # The level last driven successfully. Unknown before the first write,
        # which RelayController always makes (OFF) at construction.
        return self._state if self._state is not None else RelayState.OFF


def relay_config_from_env(env: Mapping[str, str] | None = None) -> tuple[int, bool] | None:
    """(pin, active_low) when a physical relay is configured, else None.

    Raises ``RelayConfigError`` naming the variable when the configuration is
    present but unusable -- an unsafe relay must stop the edge at boot."""
    env = os.environ if env is None else env
    raw_pin = env.get(RELAY_GPIO_ENV, "").strip()
    if not raw_pin:
        return None
    try:
        pin = int(raw_pin)
    except ValueError:
        raise RelayConfigError(f"{RELAY_GPIO_ENV}={raw_pin!r} is not a GPIO number") from None
    raw_polarity = env.get(RELAY_ACTIVE_LOW_ENV, "").strip().lower()
    if raw_polarity not in ("true", "false"):
        raise RelayConfigError(
            f"{RELAY_ACTIVE_LOW_ENV} must be 'true' or 'false' when {RELAY_GPIO_ENV} is set "
            "(relay polarity is never guessed: a wrong guess switches the pump ON)"
        )
    _check_pin(pin)
    return pin, raw_polarity == "true"


def main(argv: list[str] | None = None) -> int:
    """``python -m edge.actuation.gpio off``: drive the configured relay OFF.

    For systemd ``ExecStopPost`` -- runs after the edge stops or crashes, so a
    pin left energised by a dead process is released. No relay configured is
    not an error (exit 0)."""
    args = sys.argv[1:] if argv is None else argv
    if args != ["off"]:
        print("usage: python -m edge.actuation.gpio off", file=sys.stderr)
        return 2
    config = relay_config_from_env()
    if config is None:
        print("no relay configured; nothing to switch off")
        return 0
    pin, active_low = config
    PinctrlActuator(pin, active_low=active_low).set_state(RelayState.OFF)
    print(f"relay GPIO{pin} driven OFF")
    return 0


if __name__ == "__main__":
    sys.exit(main())
