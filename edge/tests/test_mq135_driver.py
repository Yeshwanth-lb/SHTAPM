"""MQ-135 gas driver (D044): ready but off; volts, not invented ppm."""

from __future__ import annotations

import pytest

from edge.drivers.mq135 import (
    GasConfigError,
    MQ135Driver,
    counts_to_ao_volts,
    gas_config_from_env,
)
from edge.drivers.registry import (
    DriverSpec,
    UnsupportedDriverError,
    build_driver,
    resolve_channel_specs_from_env,
)


class FakeReader:
    def __init__(self, count: int | Exception) -> None:
        self.count = count
        self.channels: list[int] = []

    def read_channel(self, channel: int) -> int:
        self.channels.append(channel)
        if isinstance(self.count, Exception):
            raise self.count
        return self.count


def test_config_requires_a_measured_divider_ratio():
    with pytest.raises(GasConfigError, match="SHTAPM_GAS_DIVIDER_RATIO"):
        gas_config_from_env({})
    with pytest.raises(GasConfigError, match="not a number"):
        gas_config_from_env({"SHTAPM_GAS_DIVIDER_RATIO": "big"})
    with pytest.raises(GasConfigError, match=">= 1"):
        gas_config_from_env({"SHTAPM_GAS_DIVIDER_RATIO": "0.5"})
    assert gas_config_from_env({"SHTAPM_GAS_DIVIDER_RATIO": "1.769"}) == (1.769, 3)


@pytest.mark.parametrize("channel", ["0", "1", "2", "8", "x"])
def test_config_refuses_the_adxl_inputs_and_bad_channels(channel):
    with pytest.raises(GasConfigError):
        gas_config_from_env(
            {"SHTAPM_GAS_DIVIDER_RATIO": "1.769", "SHTAPM_GAS_ADC_CHANNEL": channel}
        )


def test_counts_become_the_sensor_output_voltage():
    # Half scale through the bench 10k/13k divider: 1.65 V at the ADC = 2.92 V at AO.
    assert counts_to_ao_volts(512, 23 / 13) == pytest.approx(512 / 1023 * 3.3 * 23 / 13)


@pytest.mark.parametrize("count", [0, 1023])
def test_either_rail_is_an_unhealthy_read(count):
    with pytest.raises(OSError):
        counts_to_ao_volts(count, 1.769)
    driver = MQ135Driver(divider_ratio=1.769, channel=3, reader=FakeReader(count))
    reading = driver.read()
    assert reading.healthy is False and reading.value is None


def test_driver_reads_its_channel_in_volts():
    reader = FakeReader(310)
    reading = MQ135Driver(divider_ratio=1.769, channel=3, reader=reader).read()
    assert reading.healthy is True and reading.unit == "V"
    assert reading.value == pytest.approx(310 / 1023 * 3.3 * 1.769)
    assert reader.channels == [3]


def test_a_failed_spi_read_is_unhealthy_never_raised():
    reading = MQ135Driver(
        divider_ratio=1.769, channel=3, reader=FakeReader(OSError("spi"))
    ).read()
    assert reading.healthy is False


def test_switching_gas_to_real_without_configuration_fails_loudly(monkeypatch):
    monkeypatch.delenv("SHTAPM_GAS_DIVIDER_RATIO", raising=False)
    with pytest.raises(UnsupportedDriverError, match="SHTAPM_GAS_DIVIDER_RATIO"):
        build_driver("gas", DriverSpec(kind="real"))


def test_switching_gas_to_real_is_a_configuration_change(monkeypatch):
    """The whole switch: two environment variables, no code edit."""
    monkeypatch.setenv("SHTAPM_GAS_DIVIDER_RATIO", "1.769")
    from edge.main import _DEFAULT_CHANNEL_SPECS

    specs = resolve_channel_specs_from_env(
        _DEFAULT_CHANNEL_SPECS, env={"SHTAPM_DRIVER_GAS": "real"}
    )
    assert specs["gas"].kind == "real"
    assert isinstance(build_driver("gas", specs["gas"]), MQ135Driver)
