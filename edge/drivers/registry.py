"""Configuration-driven sensor-driver registry (P1 · C1 follow-up).

Replaces the previous approach in ``edge/main.py`` — literally importing a
real driver class per physically-connected sensor and hand-writing
``drivers[channel] = XDriver()`` — with a declarative per-channel
``DriverSpec`` table. Reconnecting or disconnecting a real sensor becomes
changing which spec a channel resolves to (a config value, optionally set
via environment variables — see ``resolve_channel_specs_from_env``), not
editing imports and construction code.

Real-driver and fake-driver construction are deliberately kept in two
separate, single-purpose functions (``_build_real_driver`` /
``_build_fake_driver``): neither path can silently fall through into the
other, and adding a new real driver never touches fake-construction logic
or vice versa. An unsupported/unavailable choice (an unimplemented real
driver, an unknown kind/fake_mode, invalid constructor parameters) raises
``UnsupportedDriverError`` immediately — never a silent substitution.

This module holds only the generic selection/construction mechanics; it is
intentionally free of any specific bench's configuration. What today's
default bench state actually is (DS18B20 real, five fake) remains
``edge/main.py``'s own concern, exactly as before this change — this module
does not know or assume which channels are "supposed to" be real.

No frozen wire contract, Sampler, AcquisitionRuntime, or downstream consumer
is touched or depended on here — this module only builds ``SensorDriver``
instances; every ``Reading``/``Sensor``/health/staleness behavior is
entirely unchanged (see ``edge/drivers/base.py``).
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from app.schemas.contracts import CHANNELS

from edge.drivers.adxl335 import ADXL335Driver
from edge.drivers.base import Clock, Sensor, SensorDriver, now_iso_ms
from edge.drivers.bmp280 import BMP280Driver
from edge.drivers.dht22_adafruit import DHT22AdafruitDriver, DHT22AdafruitTemperatureDriver
from edge.drivers.ds18b20 import DS18B20Driver
from edge.drivers.fake import constant_raw, realistic_raw
from edge.drivers.ina219 import INA219Driver

# Cosmetic only (never carried on the frozen wire frame) — matches each real
# driver's own ``unit=`` value.
_UNITS: dict[str, str] = {
    "temperature": "°C",
    "vibration": "g",
    "pressure": "hPa",
    "humidity": "%",
    "gas": "ppm",
    "current": "A",
}

# Exactly one real driver class per channel this project has actually
# implemented. "gas" is deliberately absent — no MQ-135 driver exists yet
# (see project-state/IMPLEMENTATION_LOG.md); requesting kind="real" for it
# raises UnsupportedDriverError immediately, never a silent fallback to fake.
_REAL_DRIVER_CLASSES: dict[str, type[SensorDriver]] = {
    "temperature": DS18B20Driver,
    "vibration": ADXL335Driver,
    "pressure": BMP280Driver,
    "humidity": DHT22AdafruitDriver,
    "current": INA219Driver,
}

# Explicitly-named stand-ins for a channel whose REAL sensor is unavailable,
# used when a fake constant would be less useful than a real-but-different
# measurement. Deliberately a separate mapping from _REAL_DRIVER_CLASSES
# above, which is never edited to accommodate one: the canonical real driver
# for a channel stays canonical, so restoring it is deleting the
# substitution rather than reversing an overwrite.
#
# A substitute is NEVER selected implicitly. There is no fallback path from
# kind="real" to kind="substitute" — an absent real sensor raises/reads
# unhealthy exactly as before (see this module's "never a silent
# substitution" contract above). Choosing one is always an explicit
# DriverSpec(kind="substitute") or SHTAPM_DRIVER_<CHANNEL>=substitute, and
# edge/main.py names it in its startup line so a running bench cannot hide
# that it is substituted.
#
# temperature: DHT22 ambient air temp standing in for the undetected DS18B20
# motor/bearing probe. A DIFFERENT PHYSICAL QUANTITY, not a drop-in — see
# edge/drivers/dht22_adafruit.py's docstring and the DHT22-ambient-
# temperature record in project-state/DECISIONS.md.
_SUBSTITUTE_DRIVER_CLASSES: dict[str, type[SensorDriver]] = {
    "temperature": DHT22AdafruitTemperatureDriver,
}

# Illustrative, hardware-free engineering fixtures for "realistic" fake
# signal generation — NOT measured/calibrated sensor specifications, NOT a
# hardware-validation claim (see edge/drivers/fake.py's realistic_raw()
# docstring). Baselines match the pre-existing dev constants that
# edge/main.py has used since before this change; noise_std/drift_std/
# value_range/seed are illustrative only, chosen to be physically plausible
# in shape (bounded, slow-drifting, per-channel-appropriate magnitude), not
# derived from any real sensor's actual noise characteristics.
_REALISTIC_FAKE_PARAMS_FIXTURE: dict[str, dict[str, Any]] = {
    "temperature": {
        "baseline": 26.0,
        "noise_std": 0.05,
        "drift_std": 0.01,
        "value_range": (-20.0, 150.0),
        "seed": 1_000_001,
    },
    "vibration": {
        "baseline": 0.03,
        "noise_std": 0.01,
        "drift_std": 0.002,
        "value_range": (0.0, 5.0),
        "seed": 1_000_002,
    },
    "pressure": {
        "baseline": 1013.0,
        "noise_std": 0.3,
        "drift_std": 0.05,
        "value_range": (800.0, 1100.0),
        "seed": 1_000_003,
    },
    "humidity": {
        "baseline": 45.0,
        "noise_std": 0.5,
        "drift_std": 0.1,
        "value_range": (0.0, 100.0),
        "seed": 1_000_004,
    },
    "gas": {
        "baseline": 150.0,
        "noise_std": 2.0,
        "drift_std": 0.5,
        "value_range": (0.0, 1000.0),
        "seed": 1_000_005,
    },
    "current": {
        "baseline": 0.0,
        "noise_std": 0.02,
        "drift_std": 0.005,
        "value_range": (0.0, 5.0),
        "seed": 1_000_006,
    },
}


class UnsupportedDriverError(ValueError):
    """Raised when a ``DriverSpec`` can't be built: an unknown channel/kind/
    fake_mode, a channel with no implemented real driver, invalid real-driver
    constructor parameters, or an invalid environment-variable override.
    Never silently substituted for a different driver."""


@dataclass(frozen=True)
class DriverSpec:
    """Declarative description of one channel's driver, resolved by
    ``build_driver()``/``build_drivers()``. Three kinds:

    - ``kind="real"``: ``params`` are forwarded as ``**kwargs`` to that
      channel's real driver class (see ``_REAL_DRIVER_CLASSES``); empty
      params use the driver's own hardware defaults (e.g.
      ``BMP280Driver()``'s ``bus_num=1``/``address=0x76``).
    - ``kind="substitute"``: same, against ``_SUBSTITUTE_DRIVER_CLASSES`` —
      a real sensor deliberately standing in for a different, unavailable
      one. Always an explicit choice, never reached by fallback, and never
      equivalent to the channel's real driver (it may measure a different
      physical quantity — see that mapping's own comment).
    - ``kind="fake"``: ``fake_mode`` selects ``constant_raw`` (``"constant"``,
      ``params={"value": <float>}``) or ``realistic_raw`` (``"realistic"``,
      ``params={"baseline", "noise_std", "drift_std", "seed"}``, optionally
      ``"value_range"``). ``value_range`` (either fake_mode) is forwarded to
      ``Sensor`` for clamping — the existing P1-ACQ-E2 mechanism, not a new
      clamping concept.
    """

    kind: str  # "real" | "substitute" | "fake"
    fake_mode: str | None = None  # "constant" | "realistic" (kind="fake" only)
    params: Mapping[str, Any] = field(default_factory=dict)


def _validate_covers_channels(specs: Mapping[str, DriverSpec], *, label: str) -> None:
    missing = set(CHANNELS) - set(specs)
    extra = set(specs) - set(CHANNELS)
    if missing or extra:
        raise ValueError(
            f"{label} must cover exactly the frozen channels; "
            f"missing={sorted(missing)} extra={sorted(extra)}"
        )


def _build_real_driver(channel: str, spec: DriverSpec) -> SensorDriver:
    driver_cls = _REAL_DRIVER_CLASSES.get(channel)
    if driver_cls is None:
        raise UnsupportedDriverError(
            f"no real driver is implemented for channel {channel!r} "
            f"(implemented real channels: {sorted(_REAL_DRIVER_CLASSES)})"
        )
    try:
        return driver_cls(**spec.params)
    except TypeError as e:
        raise UnsupportedDriverError(
            f"invalid real-driver parameters {dict(spec.params)!r} for channel "
            f"{channel!r} ({driver_cls.__name__}): {e}"
        ) from e


def _build_substitute_driver(channel: str, spec: DriverSpec) -> SensorDriver:
    driver_cls = _SUBSTITUTE_DRIVER_CLASSES.get(channel)
    if driver_cls is None:
        raise UnsupportedDriverError(
            f"no substitute driver is registered for channel {channel!r} "
            f"(channels with a substitute: {sorted(_SUBSTITUTE_DRIVER_CLASSES)})"
        )
    try:
        return driver_cls(**spec.params)
    except TypeError as e:
        raise UnsupportedDriverError(
            f"invalid substitute-driver parameters {dict(spec.params)!r} for channel "
            f"{channel!r} ({driver_cls.__name__}): {e}"
        ) from e


def _build_fake_driver(channel: str, spec: DriverSpec, *, clock: Clock) -> SensorDriver:
    value_range = spec.params.get("value_range")
    if spec.fake_mode == "constant":
        if "value" not in spec.params:
            raise UnsupportedDriverError(
                f"fake_mode='constant' for channel {channel!r} requires params['value']"
            )
        raw_read = constant_raw(spec.params["value"])
    elif spec.fake_mode == "realistic":
        try:
            raw_read = realistic_raw(
                baseline=spec.params["baseline"],
                noise_std=spec.params["noise_std"],
                drift_std=spec.params["drift_std"],
                seed=spec.params["seed"],
            )
        except KeyError as e:
            raise UnsupportedDriverError(
                f"fake_mode='realistic' for channel {channel!r} is missing required param {e}"
            ) from e
    else:
        raise UnsupportedDriverError(
            f"unknown fake_mode {spec.fake_mode!r} for channel {channel!r} "
            "(expected 'constant' or 'realistic')"
        )
    return Sensor(
        unit=_UNITS.get(channel, ""), raw_read=raw_read, value_range=value_range, clock=clock
    )


def build_driver(channel: str, spec: DriverSpec, *, clock: Clock = now_iso_ms) -> SensorDriver:
    """Construct one channel's driver from its ``DriverSpec``. Real- and
    fake-driver construction are fully separate code paths (see module
    docstring); an unsupported/unavailable choice raises
    ``UnsupportedDriverError`` immediately, never a silent fallback."""
    if spec.kind == "real":
        return _build_real_driver(channel, spec)
    if spec.kind == "substitute":
        return _build_substitute_driver(channel, spec)
    if spec.kind == "fake":
        return _build_fake_driver(channel, spec, clock=clock)
    raise UnsupportedDriverError(
        f"unknown driver kind {spec.kind!r} for channel {channel!r} "
        "(expected 'real', 'substitute' or 'fake')"
    )


def build_drivers(
    specs: Mapping[str, DriverSpec], *, clock: Clock = now_iso_ms
) -> dict[str, SensorDriver]:
    """Build one driver per frozen channel from an explicit specs mapping.
    ``specs`` must cover exactly ``CHANNELS`` — same validation shape as
    ``edge.drivers.fake.fake_drivers()``."""
    _validate_covers_channels(specs, label="specs")
    return {channel: build_driver(channel, specs[channel], clock=clock) for channel in CHANNELS}


# Environment-variable override convention (both optional; unset = no
# change, so existing behavior is preserved whenever no new configuration
# is supplied).
# + upper-cased channel -> "real" | "substitute" | "fake"
_DRIVER_KIND_ENV_PREFIX = "SHTAPM_DRIVER_"
_FAKE_SIGNAL_MODE_ENV = "SHTAPM_FAKE_SIGNAL_MODE"  # "constant" | "realistic"


def resolve_channel_specs_from_env(
    defaults: Mapping[str, DriverSpec], *, env: Mapping[str, str] | None = None
) -> dict[str, DriverSpec]:
    """Apply optional environment overrides on top of ``defaults`` (a
    complete per-channel spec mapping, e.g. today's bench state) — the
    mechanism that makes driver selection a configuration change instead of
    a code edit:

    - ``SHTAPM_DRIVER_<CHANNEL>`` = ``"real"``, ``"substitute"`` or
      ``"fake"`` overrides that channel's ``kind`` only. Switching to
      ``"real"`` (or ``"substitute"``) uses that channel's real (or
      substitute) driver class with its own hardware defaults (empty
      params) — this does not expose per-parameter (bus/address/etc.)
      overrides; ``"substitute"`` requires that channel to have one
      registered, and fails clearly if it does not. Switching
      to ``"fake"`` falls back to ``fake_mode="constant"``, ``value=0.0`` —
      an explicit, visible placeholder, never a fabricated "plausible"
      reading — unless ``defaults`` already had that channel as fake, in
      which case its existing fake spec is kept unchanged.
    - ``SHTAPM_FAKE_SIGNAL_MODE`` = ``"constant"`` or ``"realistic"``
      overrides ``fake_mode`` for every channel that resolves to ``"fake"``
      (after the per-channel override above), using this module's own
      ``_REALISTIC_FAKE_PARAMS_FIXTURE`` when switching to ``"realistic"``,
      or that channel's already-configured constant ``value`` (default
      ``0.0`` if none) when switching to ``"constant"``.

    Neither variable is required — with neither set, this returns a copy of
    ``defaults`` unchanged, which is how existing behavior is preserved when
    no new configuration is supplied.
    """
    env = os.environ if env is None else env
    _validate_covers_channels(defaults, label="defaults")

    resolved: dict[str, DriverSpec] = dict(defaults)

    for channel in CHANNELS:
        override = env.get(f"{_DRIVER_KIND_ENV_PREFIX}{channel.upper()}")
        if override is None or override == resolved[channel].kind:
            continue
        if override not in ("real", "substitute", "fake"):
            raise UnsupportedDriverError(
                f"{_DRIVER_KIND_ENV_PREFIX}{channel.upper()}={override!r} must be "
                "'real', 'substitute' or 'fake'"
            )
        if override in ("real", "substitute"):
            resolved[channel] = DriverSpec(kind=override)
        else:
            resolved[channel] = DriverSpec(kind="fake", fake_mode="constant", params={"value": 0.0})

    signal_mode = env.get(_FAKE_SIGNAL_MODE_ENV)
    if signal_mode is not None:
        if signal_mode not in ("constant", "realistic"):
            raise UnsupportedDriverError(
                f"{_FAKE_SIGNAL_MODE_ENV}={signal_mode!r} must be 'constant' or 'realistic'"
            )
        for channel in CHANNELS:
            spec = resolved[channel]
            if spec.kind != "fake" or spec.fake_mode == signal_mode:
                continue
            if signal_mode == "realistic":
                resolved[channel] = DriverSpec(
                    kind="fake",
                    fake_mode="realistic",
                    params=_REALISTIC_FAKE_PARAMS_FIXTURE[channel],
                )
            else:
                value = spec.params.get("value", 0.0) if spec.fake_mode == "constant" else 0.0
                resolved[channel] = DriverSpec(
                    kind="fake", fake_mode="constant", params={"value": value}
                )

    return resolved
