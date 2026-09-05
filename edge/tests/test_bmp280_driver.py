"""Real BMP280 driver tests (P1 · C1) — hardware-free with mocks.

Tests BMP280Reader/bmp280_raw_read/BMP280Driver with mocked smbus2.SMBus
(read_i2c_block_data/write_byte_data), following the same module-level-mock
pattern as edge/tests/test_ina219_driver.py.

Compensation-formula correctness is cross-checked against an independently
transcribed second implementation of the same Bosch 64-bit-integer formula
(not imported from the driver module), using the calibration/raw-ADC values
from Bosch's widely published BMP280 self-test vector as test fixture
inputs. This catches a transcription bug in the driver without relying on a
memorized "expected output" number.
"""

from __future__ import annotations

import itertools
import struct
from unittest.mock import MagicMock

import pytest

import edge.drivers.bmp280 as bmp280_module
from edge.drivers.bmp280 import (
    BMP280Calibration,
    BMP280Driver,
    BMP280Reader,
    bmp280_raw_read,
)

# Bosch's widely published BMP280 self-test calibration + raw-ADC vector
# (used across many independent driver ports as a sanity-check fixture) —
# used here purely as realistic input values, not as a source of a
# memorized "expected" output.
_DIG_T1, _DIG_T2, _DIG_T3 = 27504, 26435, -1000
_DIG_P1, _DIG_P2, _DIG_P3 = 36477, -10685, 3024
_DIG_P4, _DIG_P5, _DIG_P6 = 2855, 140, -7
_DIG_P7, _DIG_P8, _DIG_P9 = 15500, -14600, 6000
_ADC_T = 519888
_ADC_P = 415148


def _reference_compensate_temperature(adc_T, dig_T1, dig_T2, dig_T3):
    """Independently transcribed Bosch 64-bit-integer temperature formula."""
    var1 = (((adc_T >> 3) - (dig_T1 << 1)) * dig_T2) >> 11
    var2 = (((((adc_T >> 4) - dig_T1) * ((adc_T >> 4) - dig_T1)) >> 12) * dig_T3) >> 14
    t_fine = var1 + var2
    temperature_c = ((t_fine * 5 + 128) >> 8) / 100.0
    return temperature_c, t_fine


def _reference_compensate_pressure(
    adc_P, t_fine, dig_P1, dig_P2, dig_P3, dig_P4, dig_P5, dig_P6, dig_P7, dig_P8, dig_P9
):
    """Independently transcribed Bosch 64-bit-integer pressure formula."""
    var1 = t_fine - 128000
    var2 = var1 * var1 * dig_P6
    var2 = var2 + ((var1 * dig_P5) << 17)
    var2 = var2 + (dig_P4 << 35)
    var1 = ((var1 * var1 * dig_P3) >> 8) + ((var1 * dig_P2) << 12)
    var1 = (((1 << 47) + var1) * dig_P1) >> 33
    assert var1 != 0
    p = 1048576 - adc_P
    p = (((p << 31) - var2) * 3125) // var1
    var1 = (dig_P9 * (p >> 13) * (p >> 13)) >> 25
    var2 = (dig_P8 * p) >> 19
    p = ((p + var1 + var2) >> 8) + (dig_P7 << 4)
    return p / 256.0


def _pack_calibration(
    dig_T1=_DIG_T1, dig_T2=_DIG_T2, dig_T3=_DIG_T3,
    dig_P1=_DIG_P1, dig_P2=_DIG_P2, dig_P3=_DIG_P3, dig_P4=_DIG_P4,
    dig_P5=_DIG_P5, dig_P6=_DIG_P6, dig_P7=_DIG_P7, dig_P8=_DIG_P8, dig_P9=_DIG_P9,
) -> list[int]:
    packed = struct.pack(
        "<HhhHhhhhhhhh",
        dig_T1, dig_T2, dig_T3,
        dig_P1, dig_P2, dig_P3, dig_P4, dig_P5, dig_P6, dig_P7, dig_P8, dig_P9,
    )
    return list(packed)


def _pack_data(raw_pressure: int, raw_temperature: int) -> list[int]:
    press_msb = (raw_pressure >> 12) & 0xFF
    press_lsb = (raw_pressure >> 4) & 0xFF
    press_xlsb = (raw_pressure & 0x0F) << 4
    temp_msb = (raw_temperature >> 12) & 0xFF
    temp_lsb = (raw_temperature >> 4) & 0xFF
    temp_xlsb = (raw_temperature & 0x0F) << 4
    return [press_msb, press_lsb, press_xlsb, temp_msb, temp_lsb, temp_xlsb]


def _mock_bus(*, chip_id=0x58, calib_bytes=None, data_bytes=None, status_sequence=None):
    """Mock SpiDev-like smbus2.SMBus whose read_i2c_block_data() routes by
    register address, matching the driver's exclusive use of block reads."""
    bus = MagicMock()
    calib_bytes = calib_bytes if calib_bytes is not None else _pack_calibration()
    data_bytes = data_bytes if data_bytes is not None else _pack_data(_ADC_P, _ADC_T)
    # Default repeats indefinitely so tests can call read_pressure_hpa() more
    # than once without exhausting the status-register reply sequence.
    status_iter = iter(status_sequence) if status_sequence is not None else itertools.repeat([0x00])

    def _read_block(address, register, length):
        if register == 0xD0:
            return [chip_id]
        if register == 0x88:
            return list(calib_bytes)
        if register == 0xF3:
            return next(status_iter)
        if register == 0xF7:
            return list(data_bytes)
        raise AssertionError(f"unexpected register read: 0x{register:02x}")

    bus.read_i2c_block_data.side_effect = _read_block
    return bus


class TestBMP280Calibration:
    def test_parses_signed_and_unsigned_fields(self):
        raw = bytes(_pack_calibration())
        cal = BMP280Calibration(raw)
        assert cal.dig_T1 == _DIG_T1
        assert cal.dig_T2 == _DIG_T2
        assert cal.dig_T3 == _DIG_T3
        assert cal.dig_P1 == _DIG_P1
        assert cal.dig_P2 == _DIG_P2
        assert cal.dig_P9 == _DIG_P9


class TestCompensationFormulas:
    """Cross-check the driver's compensation math against an independently
    transcribed second implementation of the same Bosch formula."""

    def test_temperature_matches_independent_reference(self):
        cal = BMP280Calibration(bytes(_pack_calibration()))
        driver_temp, driver_t_fine = bmp280_module._compensate_temperature(_ADC_T, cal)
        ref_temp, ref_t_fine = _reference_compensate_temperature(_ADC_T, _DIG_T1, _DIG_T2, _DIG_T3)
        assert driver_t_fine == ref_t_fine
        assert driver_temp == pytest.approx(ref_temp)
        # Sanity: result is a plausible room-temperature reading
        assert 20.0 < driver_temp < 30.0

    def test_pressure_matches_independent_reference(self):
        cal = BMP280Calibration(bytes(_pack_calibration()))
        _, t_fine = bmp280_module._compensate_temperature(_ADC_T, cal)
        driver_pressure_pa = bmp280_module._compensate_pressure(_ADC_P, t_fine, cal)
        ref_pressure_pa = _reference_compensate_pressure(
            _ADC_P,
            t_fine,
            _DIG_P1,
            _DIG_P2,
            _DIG_P3,
            _DIG_P4,
            _DIG_P5,
            _DIG_P6,
            _DIG_P7,
            _DIG_P8,
            _DIG_P9,
        )
        assert driver_pressure_pa == pytest.approx(ref_pressure_pa)
        # Sanity: result is a plausible sea-level-ish atmospheric pressure
        assert 80000.0 < driver_pressure_pa < 120000.0

    def test_pressure_division_by_zero_raises_oserror(self):
        """A degenerate dig_P1 compensation term (var1 == 0) must not crash
        with ZeroDivisionError — must raise OSError (caught upstream by Sensor)."""
        cal = BMP280Calibration(bytes(_pack_calibration(dig_P1=0)))
        with pytest.raises(OSError, match="division by zero"):
            bmp280_module._compensate_pressure(_ADC_P, -128000, cal)


class TestBMP280Reader:
    def test_read_pressure_hpa_end_to_end(self):
        mock_bus = _mock_bus()
        mock_smbus2 = MagicMock()
        mock_smbus2.SMBus.return_value = mock_bus

        original_smbus2 = bmp280_module.smbus2
        try:
            bmp280_module.smbus2 = mock_smbus2
            reader = BMP280Reader(bus_num=1, address=0x76)
            pressure_hpa = reader.read_pressure_hpa()

            cal = BMP280Calibration(bytes(_pack_calibration()))
            _, t_fine = bmp280_module._compensate_temperature(_ADC_T, cal)
            expected_pa = bmp280_module._compensate_pressure(_ADC_P, t_fine, cal)
            assert pressure_hpa == pytest.approx(expected_pa / 100.0)
            mock_bus.close.assert_called_once()
        finally:
            bmp280_module.smbus2 = original_smbus2

    def test_triggers_forced_mode_with_correct_registers(self):
        mock_bus = _mock_bus()
        mock_smbus2 = MagicMock()
        mock_smbus2.SMBus.return_value = mock_bus

        original_smbus2 = bmp280_module.smbus2
        try:
            bmp280_module.smbus2 = mock_smbus2
            reader = BMP280Reader(bus_num=1, address=0x76)
            reader.read_pressure_hpa()

            calls = {call.args[1]: call.args[2] for call in mock_bus.write_byte_data.call_args_list}
            assert calls[0xF5] == 0x00  # config: no filter, I2C
            assert calls[0xF4] == 0x25  # ctrl_meas: osrs_t=x1, osrs_p=x1, forced
        finally:
            bmp280_module.smbus2 = original_smbus2

    def test_calibration_and_chip_id_read_only_once(self):
        mock_bus = _mock_bus()
        mock_smbus2 = MagicMock()
        mock_smbus2.SMBus.return_value = mock_bus

        original_smbus2 = bmp280_module.smbus2
        try:
            bmp280_module.smbus2 = mock_smbus2
            reader = BMP280Reader(bus_num=1, address=0x76)
            reader.read_pressure_hpa()
            reader.read_pressure_hpa()

            all_reads = mock_bus.read_i2c_block_data.call_args_list
            chip_id_reads = [c for c in all_reads if c.args[1] == 0xD0]
            calib_reads = [c for c in all_reads if c.args[1] == 0x88]
            assert len(chip_id_reads) == 1
            assert len(calib_reads) == 1
        finally:
            bmp280_module.smbus2 = original_smbus2

    def test_wrong_chip_id_raises_oserror(self):
        mock_bus = _mock_bus(chip_id=0x60)  # not BMP280
        mock_smbus2 = MagicMock()
        mock_smbus2.SMBus.return_value = mock_bus

        original_smbus2 = bmp280_module.smbus2
        try:
            bmp280_module.smbus2 = mock_smbus2
            reader = BMP280Reader(bus_num=1, address=0x76)
            with pytest.raises(OSError, match="unexpected chip ID"):
                reader.read_pressure_hpa()
        finally:
            bmp280_module.smbus2 = original_smbus2

    def test_bus_open_failure_raises_oserror(self):
        mock_smbus2 = MagicMock()
        mock_smbus2.SMBus.side_effect = OSError("Permission denied")

        original_smbus2 = bmp280_module.smbus2
        try:
            bmp280_module.smbus2 = mock_smbus2
            reader = BMP280Reader(bus_num=1, address=0x76)
            with pytest.raises(OSError, match="failed to open I²C bus"):
                reader.read_pressure_hpa()
        finally:
            bmp280_module.smbus2 = original_smbus2

    def test_data_block_read_failure_raises_oserror(self):
        mock_bus = _mock_bus()
        mock_bus.read_i2c_block_data.side_effect = None

        def _read_block(address, register, length):
            if register == 0xD0:
                return [0x58]
            if register == 0x88:
                return _pack_calibration()
            if register == 0xF3:
                return [0x00]
            if register == 0xF7:
                raise OSError("Remote I/O error")
            raise AssertionError(register)

        mock_bus.read_i2c_block_data.side_effect = _read_block
        mock_smbus2 = MagicMock()
        mock_smbus2.SMBus.return_value = mock_bus

        original_smbus2 = bmp280_module.smbus2
        try:
            bmp280_module.smbus2 = mock_smbus2
            reader = BMP280Reader(bus_num=1, address=0x76)
            with pytest.raises(OSError, match="failed to read BMP280 measurement data"):
                reader.read_pressure_hpa()
            mock_bus.close.assert_called_once()  # cleaned up despite failure
        finally:
            bmp280_module.smbus2 = original_smbus2

    def test_status_poll_timeout_still_reads_data(self):
        """If the measuring bit never clears within the timeout, the driver
        proceeds to read data anyway rather than hanging (matches
        bmp280_hwtest.py's documented behavior)."""
        mock_bus = _mock_bus(status_sequence=[[0x08]] * 100)  # always "measuring"
        mock_smbus2 = MagicMock()
        mock_smbus2.SMBus.return_value = mock_bus

        original_smbus2 = bmp280_module.smbus2
        try:
            bmp280_module.smbus2 = mock_smbus2
            reader = BMP280Reader(bus_num=1, address=0x76)
            pressure_hpa = reader.read_pressure_hpa()  # should not raise/hang
            assert pressure_hpa > 0
        finally:
            bmp280_module.smbus2 = original_smbus2

    def test_smbus2_not_installed_raises_import_error(self):
        original_smbus2 = bmp280_module.smbus2
        try:
            bmp280_module.smbus2 = None
            reader = BMP280Reader(bus_num=1, address=0x76)
            with pytest.raises(ImportError, match="pip install smbus2"):
                reader.read_pressure_hpa()
        finally:
            bmp280_module.smbus2 = original_smbus2


class TestBMP280RawRead:
    def test_returns_callable(self):
        mock_smbus2 = MagicMock()
        mock_smbus2.SMBus.return_value = _mock_bus()

        original_smbus2 = bmp280_module.smbus2
        try:
            bmp280_module.smbus2 = mock_smbus2
            raw_read = bmp280_raw_read(bus_num=1, address=0x76)
            assert callable(raw_read)
        finally:
            bmp280_module.smbus2 = original_smbus2

    def test_invokes_reader(self):
        mock_smbus2 = MagicMock()
        mock_smbus2.SMBus.return_value = _mock_bus()

        original_smbus2 = bmp280_module.smbus2
        try:
            bmp280_module.smbus2 = mock_smbus2
            raw_read = bmp280_raw_read(bus_num=1, address=0x76)
            assert raw_read() > 0
        finally:
            bmp280_module.smbus2 = original_smbus2

    def test_failure_raises(self):
        mock_smbus2 = MagicMock()
        mock_smbus2.SMBus.side_effect = OSError("no bus")

        original_smbus2 = bmp280_module.smbus2
        try:
            bmp280_module.smbus2 = mock_smbus2
            raw_read = bmp280_raw_read(bus_num=1, address=0x76)
            with pytest.raises(OSError):
                raw_read()
        finally:
            bmp280_module.smbus2 = original_smbus2


class TestBMP280Driver:
    def test_driver_read_healthy(self):
        mock_smbus2 = MagicMock()
        mock_smbus2.SMBus.return_value = _mock_bus()

        original_smbus2 = bmp280_module.smbus2
        try:
            bmp280_module.smbus2 = mock_smbus2
            driver = BMP280Driver(bus_num=1, address=0x76)
            reading = driver.read()

            assert reading.healthy is True
            assert reading.value > 0
            assert reading.unit == "hPa"
            assert reading.ts is not None
        finally:
            bmp280_module.smbus2 = original_smbus2

    def test_driver_read_i2c_failure_returns_unhealthy(self):
        mock_smbus2 = MagicMock()
        mock_smbus2.SMBus.side_effect = OSError("Remote I/O error")

        original_smbus2 = bmp280_module.smbus2
        try:
            bmp280_module.smbus2 = mock_smbus2
            driver = BMP280Driver(bus_num=1, address=0x76)
            reading = driver.read()

            assert reading.healthy is False
            assert reading.value is None
            assert reading.unit == "hPa"
            assert reading.ts is not None
        finally:
            bmp280_module.smbus2 = original_smbus2

    def test_driver_read_recovers_after_failure(self):
        mock_smbus2_fail = MagicMock()
        mock_smbus2_fail.SMBus.side_effect = OSError("Remote I/O error")

        mock_smbus2_ok = MagicMock()
        mock_smbus2_ok.SMBus.return_value = _mock_bus()

        original_smbus2 = bmp280_module.smbus2
        try:
            bmp280_module.smbus2 = mock_smbus2_fail
            driver = BMP280Driver(bus_num=1, address=0x76)

            reading1 = driver.read()
            assert reading1.healthy is False

            bmp280_module.smbus2 = mock_smbus2_ok
            reading2 = driver.read()
            assert reading2.healthy is True
            assert reading2.value > 0
        finally:
            bmp280_module.smbus2 = original_smbus2

    def test_driver_implements_sensor_driver(self):
        from edge.drivers.base import SensorDriver

        driver = BMP280Driver()
        assert isinstance(driver, SensorDriver)

    def test_driver_reading_shape(self):
        mock_smbus2 = MagicMock()
        mock_smbus2.SMBus.return_value = _mock_bus()

        original_smbus2 = bmp280_module.smbus2
        try:
            bmp280_module.smbus2 = mock_smbus2
            driver = BMP280Driver()
            reading = driver.read()

            assert hasattr(reading, "value")
            assert hasattr(reading, "unit")
            assert hasattr(reading, "ts")
            assert hasattr(reading, "healthy")
            assert isinstance(reading.as_dict(), dict)
            assert set(reading.as_dict().keys()) == {"value", "unit", "ts", "healthy"}
        finally:
            bmp280_module.smbus2 = original_smbus2
