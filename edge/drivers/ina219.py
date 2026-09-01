"""Real INA219 power monitor driver over I²C (P1 · C1).

Communicates over /dev/i2c-1 at address 0x40 (configurable). Properly configures
the INA219 calibration register (0x05) based on expected max current and shunt
resistance, then reads current from register 0x04 and returns amperes as a
healthy Reading, or unhealthy if the I²C transaction fails.

Wraps the raw I²C read in a Sensor for calibration/clamp/health handling.

The INA219 is a 16-bit power monitor; this driver exposes current only,
consistent with the frozen six-channel contract.

INA219 Register Map (per datasheet):
  0x00: Configuration (R/W)
  0x01: Shunt Voltage (Read-only, V)
  0x02: Bus Voltage (Read-only, V)
  0x03: Power (Read-only, W)
  0x04: Current (Read-only, A) — MUST calibrate via 0x05 first
  0x05: Calibration (R/W) — Sets current measurement scaling
"""

from __future__ import annotations

try:
    import smbus2
except ImportError:
    smbus2 = None  # type: ignore

from edge.drivers.base import RawRead, Sensor, SensorDriver


class INA219CurrentReader:
    """Encapsulates INA219 I²C register access, calibration, and current (A) extraction.

    The INA219 measures shunt voltage across a known resistor and converts it to
    current via a calibration constant stored in register 0x05. Without proper
    calibration, raw register reads are meaningless.

    Calibration formula (from datasheet):
      Calibration = 0.04096 / (Current_LSB × Rshunt)
      Current_LSB = Max_Expected_Current / 32767

    Example: 5A max, 0.1Ω shunt
      Current_LSB = 5.0 / 32767 ≈ 0.0001526 A
      Calibration = 0.04096 / (0.0001526 × 0.1) ≈ 2686
    """

    def __init__(
        self,
        bus_num: int = 1,
        address: int = 0x40,
        max_expected_amps: float = 5.0,
        shunt_ohms: float = 0.1,
    ):
        """Initialize I²C bus, address, and calibration parameters.

        Args:
            bus_num: I²C bus number (e.g. 1 for /dev/i2c-1). Default: 1 (Pi 5).
            address: INA219 7-bit address (0x40 default). Default: 0x40.
            max_expected_amps: Expected maximum current for calibration. Default: 5.0 A.
            shunt_ohms: Shunt resistor value. Default: 0.1 Ω (common value).
        """
        self._bus_num = bus_num
        self._address = address
        self._max_amps = max_expected_amps
        self._shunt_ohms = shunt_ohms
        self._calibrated = False

        # Calculate calibration constant
        # Current_LSB = max_current / 2^15 (max signed 16-bit value)
        self._current_lsb = max_expected_amps / 32767.0
        # Calibration register = 0.04096 / (Current_LSB × Rshunt)
        self._calibration = int(0.04096 / (self._current_lsb * shunt_ohms))

    def _open_bus(self) -> object:
        """Lazy-open I²C bus (smbus2). Called once per read; simplifies cleanup."""
        if smbus2 is None:
            raise ImportError("smbus2 not installed; install: pip install smbus2")
        try:
            return smbus2.SMBus(self._bus_num)
        except Exception as e:
            raise OSError(f"failed to open I²C bus {self._bus_num}: {e}")

    def _calibrate_once(self, bus: object) -> None:
        """Write calibration constant to register 0x05 (one-time setup).

        This must be done before any meaningful current reads. The calibration
        value is not volatile, so it persists across power cycles on many
        INA219 modules, but we write it on first read to ensure correctness.
        """
        if self._calibrated:
            return
        try:
            # Write calibration as 16-bit big-endian to register 0x05
            high = (self._calibration >> 8) & 0xFF
            low = self._calibration & 0xFF
            bus.write_i2c_block_data(self._address, 0x05, [high, low])
            self._calibrated = True
        except Exception as e:
            raise OSError(f"failed to calibrate INA219 at 0x{self._address:02x}: {e}")

    def read_current_amps(self) -> float:
        """Read current (A) from INA219 CURRENT register (0x04).

        Reads the 16-bit signed current value from register 0x04, scales it
        by the previously-configured Current_LSB, and returns amperes.

        Raises OSError on I²C failure (bus, calibration, register read, device not found).
        """
        bus = self._open_bus()
        try:
            # Calibrate on first read (ensures calibration is set)
            self._calibrate_once(bus)

            # INA219 CURRENT register is 0x04 (read two bytes, big-endian)
            raw_bytes = bus.read_i2c_block_data(self._address, 0x04, 2)
            # Reconstruct 16-bit signed integer (big-endian)
            raw_counts = int.from_bytes(bytes(raw_bytes), byteorder="big", signed=True)
            # Current (A) = raw_counts × Current_LSB
            amps = raw_counts * self._current_lsb
            return amps
        finally:
            bus.close()


def ina219_raw_read(
    bus_num: int = 1,
    address: int = 0x40,
    max_expected_amps: float = 5.0,
    shunt_ohms: float = 0.1,
) -> RawRead:
    """Factory: create a RawRead callable from an INA219.

    Args:
        bus_num: I²C bus (e.g. 1 for /dev/i2c-1). Default: 1.
        address: INA219 7-bit address (0x40 default). Default: 0x40.
        max_expected_amps: Expected maximum current for calibration. Default: 5.0 A.
        shunt_ohms: Shunt resistor value (Ω). Default: 0.1 Ω.

    Returns a callable that configures calibration on first read, then reads
    the INA219 current register and returns amperes, or raises OSError on failure.
    """
    reader = INA219CurrentReader(
        bus_num=bus_num,
        address=address,
        max_expected_amps=max_expected_amps,
        shunt_ohms=shunt_ohms,
    )

    def _read() -> float:
        return reader.read_current_amps()

    return _read


class INA219Driver(SensorDriver):
    """Real INA219 hardware driver conforming to SensorDriver interface.

    Configures the INA219 calibration register (0x05) on first read based on
    expected max current and shunt resistance, then reads and scales the
    current register (0x04). Wraps in a Sensor (P1 base.py) for robust
    calibration/clamp/health handling. Never raises; unhealthy reads
    return healthy=False, value=None (firmware discipline §02.8).
    """

    def __init__(
        self,
        *,
        bus_num: int = 1,
        address: int = 0x40,
        max_expected_amps: float = 5.0,
        shunt_ohms: float = 0.1,
    ) -> None:
        """Initialize the INA219 driver with calibration parameters.

        Args:
            bus_num: I²C bus number. Default: 1 (/dev/i2c-1).
            address: INA219 7-bit I²C address. Default: 0x40.
            max_expected_amps: Expected maximum current for calibration scaling. Default: 5.0 A.
            shunt_ohms: Shunt resistor value (Ω). Default: 0.1 Ω.
        """
        self._sensor = Sensor(
            unit="A",
            raw_read=ina219_raw_read(
                bus_num=bus_num,
                address=address,
                max_expected_amps=max_expected_amps,
                shunt_ohms=shunt_ohms,
            ),
        )

    def read(self):
        """Read INA219 current (A). Never raises; returns healthy=False on failure."""
        return self._sensor.read()
