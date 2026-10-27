"""MQ-135 gas sensor driver via the MCP3008 the ADXL335 already uses (D044).

READY BUT OFF. ``gas`` stays simulated until the sensor is wired and
``SHTAPM_DRIVER_GAS=real`` is set; then this driver simply replaces the
simulated values -- same channel, same pipeline.

WHAT IS MEASURED, HONESTLY. The MQ-135 module's analog output (AO) voltage,
in volts. Gas is a labelled PROXY (PRD §12.1: VOC/CO2, not H2S), and turning
the voltage into ppm needs a per-sensor clean-air calibration (R0) and a gas
curve that this project has not performed, so no ppm figure is invented. The
detector, trust and attribution layers are scale-free (they learn "normal"
from the baseline), so volts work exactly as the simulated values did -- a new
baseline is recorded after switching, as for any real/simulated change (D038).

WIRING. The module runs on 5 V and its AO can approach 5 V, above the
MCP3008's 3.3 V reference -- so AO goes through a resistor divider to a free
MCP3008 input (CH3 by default; CH0-2 are the ADXL335):

    AO --[R_top]--+--[R_bottom]-- GND        divider ratio = (R_top + R_bottom) / R_bottom
                  +--> MCP3008 CH3           bench: 10 kOhm top, 13 kOhm bottom -> 23/13 = 1.769

``SHTAPM_GAS_DIVIDER_RATIO`` is REQUIRED (measured from the fitted resistors,
never guessed); ``SHTAPM_GAS_ADC_CHANNEL`` defaults to 3.

HEALTH. A count of 0 (sensor unpowered or AO disconnected -- a heated MQ-135
never outputs 0 V) or 1023 (input at or above the reference: wrong divider) is
an unhealthy read, never a value.
"""

from __future__ import annotations

import os
from collections.abc import Mapping

from edge.drivers.adxl335 import _ADC_MAX_COUNT, _MCP3008_VREF_VOLTS, ADXL335MCP3008Reader
from edge.drivers.base import RawRead, Sensor, SensorDriver

GAS_DIVIDER_ENV = "SHTAPM_GAS_DIVIDER_RATIO"
GAS_CHANNEL_ENV = "SHTAPM_GAS_ADC_CHANNEL"
DEFAULT_GAS_CHANNEL = 3
_ADXL_CHANNELS = (0, 1, 2)


class GasConfigError(ValueError):
    """The MQ-135 configuration is missing or unusable."""


def gas_config_from_env(env: Mapping[str, str] | None = None) -> tuple[float, int]:
    """(divider ratio, MCP3008 channel). Raises ``GasConfigError`` naming the
    variable when the configuration is missing or unusable."""
    env = os.environ if env is None else env
    raw_ratio = env.get(GAS_DIVIDER_ENV, "").strip()
    if not raw_ratio:
        raise GasConfigError(
            f"{GAS_DIVIDER_ENV} is required for a real MQ-135: (R_top + R_bottom) / R_bottom "
            "of the divider on its AO line (bench 10k/13k -> 1.769); never guessed"
        )
    try:
        ratio = float(raw_ratio)
    except ValueError:
        raise GasConfigError(f"{GAS_DIVIDER_ENV}={raw_ratio!r} is not a number") from None
    if not ratio >= 1.0:
        raise GasConfigError(f"{GAS_DIVIDER_ENV}={ratio} must be >= 1 (a divider only divides)")
    raw_channel = env.get(GAS_CHANNEL_ENV, str(DEFAULT_GAS_CHANNEL)).strip()
    try:
        channel = int(raw_channel)
    except ValueError:
        raise GasConfigError(f"{GAS_CHANNEL_ENV}={raw_channel!r} is not a channel") from None
    if channel in _ADXL_CHANNELS or not 0 <= channel <= 7:
        raise GasConfigError(
            f"{GAS_CHANNEL_ENV}={channel}: use a free MCP3008 input 3-7 (0-2 are the ADXL335)"
        )
    return ratio, channel


def counts_to_ao_volts(count: int, divider_ratio: float) -> float:
    """MCP3008 count -> MQ-135 AO voltage, undoing the divider. Raises
    OSError at either rail (unpowered/disconnected, or saturated)."""
    if count <= 0:
        raise OSError("MQ-135 reads 0 counts: sensor unpowered or AO disconnected")
    if count >= _ADC_MAX_COUNT:
        raise OSError("MQ-135 input saturated at the ADC reference: check the divider")
    return count / _ADC_MAX_COUNT * _MCP3008_VREF_VOLTS * divider_ratio


def mq135_raw_read(
    *, divider_ratio: float, channel: int, reader: ADXL335MCP3008Reader | None = None
) -> RawRead:
    adc = reader if reader is not None else ADXL335MCP3008Reader()

    def _read() -> float:
        return counts_to_ao_volts(adc.read_channel(channel), divider_ratio)

    return _read


class MQ135Driver(SensorDriver):
    """Real MQ-135 driver. Constructed with no arguments by the registry; the
    configuration comes from the environment (see module docstring)."""

    def __init__(
        self,
        *,
        divider_ratio: float | None = None,
        channel: int | None = None,
        reader: ADXL335MCP3008Reader | None = None,
    ) -> None:
        if divider_ratio is None or channel is None:
            env_ratio, env_channel = gas_config_from_env()
            divider_ratio = env_ratio if divider_ratio is None else divider_ratio
            channel = env_channel if channel is None else channel
        self._sensor = Sensor(
            unit="V",
            raw_read=mq135_raw_read(divider_ratio=divider_ratio, channel=channel, reader=reader),
        )

    def read(self):
        """MQ-135 AO voltage (V). Never raises; healthy=False on failure."""
        return self._sensor.read()
