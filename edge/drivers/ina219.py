"""Real INA219 power monitor driver over I²C (P1 · C1).

Communicates over /dev/i2c-1 at address 0x40 (configurable). Returns current
in amperes as a healthy Reading, or unhealthy if the I²C transaction fails.
Wraps the raw I²C read in a Sensor for calibration/clamp/health handling.

The INA219 is a 16-bit power monitor with current, voltage, and power channels;
this driver exposes current only, consistent with the frozen six-channel contract.
"""

from __future__ import annotations

try:
    import smbus2
except ImportError:
    smbus2 = None  # type: ignore

from edge.drivers.base import RawRead, Sensor, SensorDriver


class INA219CurrentReader:
    """Encapsulates INA219 I²C register access and current (A) extraction.

    INA219 register map (relevant):
      0x02: Config (R/W)
      0x04: I_SHUNT_VOLTAGE (read-only, mV * 10)
      0x05: BUS_VOLTAGE (read-only, V * 2, bit 0 is OVF flag)
      0x06: POWER (read-only, mW * 20)
      0x07: CURRENT (read-only, mA signed int16)

    Current = (CURRENT register * CURRENT_LSB) in amperes.
    CURRENT_LSB is set via config; default/typical is 10 mA/LSB.
    """

    def __init__(self, bus_num: int = 1, address: int = 0x40, current_lsb_ma: float = 10.0):
        """Initialize I²C bus and INA219 address.

        Args:
            bus_num: I²C bus number (e.g. 1 for /dev/i2c-1). Default: 1 (Pi 5).
            address: INA219 7-bit address (0x40 for default, 0x41-0x43 possible). Default: 0x40.
            current_lsb_ma: Current LSB in mA (1 LSB = X mA). Default: 10 mA/LSB.
        """
        self._bus_num = bus_num
        self._address = address
        self._current_lsb_ma = current_lsb_ma
        self._bus = None

    def _open_bus(self) -> object:
        """Lazy-open I²C bus (smbus2). Called once per read; simplifies cleanup."""
        if smbus2 is None:
            raise ImportError("smbus2 not installed; install: pip install smbus2")
        try:
            return smbus2.SMBus(self._bus_num)
        except Exception as e:
            raise OSError(f"failed to open I²C bus {self._bus_num}: {e}")

    def read_current_amps(self) -> float:
        """Read current (A) from INA219 CURRENT register (0x07).

        Returns the raw 16-bit signed integer interpreted as mA, then
        scaled by CURRENT_LSB to amperes.

        Raises OSError on I²C failure (bus, register read, device not found).
        """
        bus = self._open_bus()
        try:
            # INA219 CURRENT register is 0x07 (read two bytes, big-endian)
            raw_bytes = bus.read_i2c_block_data(self._address, 0x07, 2)
            # Reconstruct 16-bit signed integer (big-endian)
            raw_ma = int.from_bytes(bytes(raw_bytes), byteorder="big", signed=True)
            # Convert mA → A using LSB
            amps = (raw_ma * self._current_lsb_ma) / 1000.0
            return amps
        finally:
            bus.close()


def ina219_raw_read(
    bus_num: int = 1, address: int = 0x40, current_lsb_ma: float = 10.0
) -> RawRead:
    """Factory: create a RawRead callable from an INA219.

    Args:
        bus_num: I²C bus (e.g. 1 for /dev/i2c-1).
        address: INA219 7-bit address (0x40 default).
        current_lsb_ma: Current LSB in mA.

    Returns a callable that reads the INA219 current register and returns
    amperes, or raises OSError on failure.
    """
    reader = INA219CurrentReader(bus_num=bus_num, address=address, current_lsb_ma=current_lsb_ma)

    def _read() -> float:
        return reader.read_current_amps()

    return _read


class INA219Driver(SensorDriver):
    """Real INA219 hardware driver conforming to SensorDriver interface.

    Wraps ina219_raw_read() in a Sensor (P1 base.py) for robust
    calibration/clamp/health handling. Never raises; unhealthy reads
    return healthy=False, value=None (firmware discipline §02.8).
    """

    def __init__(
        self, *, bus_num: int = 1, address: int = 0x40, current_lsb_ma: float = 10.0
    ) -> None:
        self._sensor = Sensor(
            unit="A",
            raw_read=ina219_raw_read(bus_num=bus_num, address=address, current_lsb_ma=current_lsb_ma),
        )

    def read(self):
        """Read INA219 current (A). Never raises; returns healthy=False on failure."""
        return self._sensor.read()
