"""Dev seeds: admin user + the per-device sensor registry (P4-M2, P5).

Idempotent throughout -- re-running is a no-op for rows that already match.
The admin password is read from ``SEED_ADMIN_PASSWORD``: never hardcoded,
never logged. Intended for local/offline demo bring-up, not production
provisioning.

    PYTHONPATH=backend python -m app.core.seed

SENSOR REGISTRY (Doc05 section 05.2 ``sensors``) is the AUTHORITATIVE record of
which physical part backs each frozen channel. Everything seeded below is
transcribed from what this repository documents -- ``edge/main.py``'s
``_DEFAULT_CHANNEL_SPECS``, ``edge/drivers/registry.py``, PRD section 12.1 and
``DECISIONS.md`` D028 -- and nothing else. Where the repository does not
establish a fact, the column is left NULL rather than filled with a plausible
guess; see ``_UNKNOWNS`` for the explicit list.

Registering a part is NOT a claim that the part is currently wired and
powered. It records what the bench is documented to use. Whether a channel is
believed to be physically connected right now is a separate declaration
(``SHTAPM_CHANNEL_SOURCES``), and the API requires BOTH before it will report a
channel as live -- see ``app.api.devices.resolve_channel_source``.
"""

from __future__ import annotations

import os

from sqlalchemy.orm import Session

from app.core.config import AuthSettings, DatabaseSettings
from app.core.db import make_engine, make_session_factory
from app.core.security import hash_password
from app.models import Device, Sensor, User
from app.models.enums import UserRole
from app.schemas.contracts import CHANNELS, Channel


def seed_admin(db: Session, settings: AuthSettings) -> User:
    email = os.environ.get("SEED_ADMIN_EMAIL", "admin@shtapm.local")
    existing = db.query(User).filter(User.email == email).one_or_none()
    if existing is not None:
        return existing

    password = os.environ.get("SEED_ADMIN_PASSWORD")
    if not password:
        raise RuntimeError("SEED_ADMIN_PASSWORD is required to seed the admin user")

    admin = User(
        email=email,
        password_hash=hash_password(password, settings),
        full_name="Admin",
        role=UserRole.admin,
    )
    db.add(admin)
    db.commit()
    db.refresh(admin)
    return admin


# ---------------------------------------------------------------------------
# Documented pump-01 sensor registry
# ---------------------------------------------------------------------------

# Facts this repository establishes, and NOTHING further. Sources per row:
#   temperature/humidity  DECISIONS.md D028 + PRD 12.1 (one DHT22 on GPIO17,
#                         ambient air; humidity is the same physical part)
#   vibration             IMPLEMENTATION_LOG 2026-09-03 + edge/drivers/adxl335.py
#   pressure              edge/drivers/bmp280.py; commit 554066f records it as
#                         implemented but NOT currently connected
#   gas                   edge/drivers/registry.py: "no MQ-135 driver exists yet"
#   current               edge/drivers/ina219.py; implemented, not connected
#
# `part` is the PART THE BENCH IS DOCUMENTED TO USE, not an assertion that it is
# plugged in today. `is_proxy` follows Doc05 section 05.2's own note
# ("pressure/gas = true (honest labelling)") and PRD 12.1's Proxy column: it
# describes what the channel can physically represent, which is INDEPENDENT of
# whether a sensor is attached. A connected BMP280 would still be a proxy.
_PUMP01_SENSORS: dict[str, dict[str, object]] = {
    "temperature": {"part": "DHT22", "unit": "\u00b0C", "is_proxy": False},
    "vibration": {"part": "ADXL335", "unit": "g", "is_proxy": False},
    "pressure": {"part": "BMP280", "unit": "hPa", "is_proxy": True},
    "humidity": {"part": "DHT22", "unit": "%", "is_proxy": False},
    # part=None on purpose. No MQ-135 driver exists and no wiring is documented
    # anywhere in this repository, so there is no part to register. The column
    # is nullable precisely so "we do not know" is representable; writing
    # "MQ-135" here would assert hardware nobody has established.
    "gas": {"part": None, "unit": "ppm", "is_proxy": True},
    "current": {"part": "INA219", "unit": "A", "is_proxy": False},
}

# Left deliberately unset, with the reason. Listed so a future reader can see
# these are open questions rather than oversights.
_UNKNOWNS = {
    "display_hue": "Doc04 section 04.5 asks for a per-channel hue but assigns none.",
    "gas.part": "No MQ-135 driver and no documented wiring exist.",
    "calibration": "adxl335.py uses nominal datasheet sensitivity, not per-chip calibration.",
    "location": "No location is documented for pump-01.",
}

SEED_DEVICE_ID = "pump-01"


def seed_sensor_registry(db: Session, device_id: str = SEED_DEVICE_ID) -> list[Sensor]:
    """Create or correct the documented ``sensors`` rows for one device.

    Idempotent via the Doc05 ``UNIQUE(device_id, channel)`` constraint: an
    existing row is UPDATED in place to the documented values rather than
    duplicated, so running this twice is a no-op and running it after a manual
    edit restores the documented state.

    ``display_hue`` is never written -- it is not documented (see ``_UNKNOWNS``)
    and an existing operator-set value must not be clobbered by a seed that has
    nothing better to put there.

    The device row must already exist; telemetry ingestion creates it on the
    first frame. Raising here is deliberate: silently creating a device would
    let a typo'd id seed a registry nothing ever reads.
    """
    device = db.query(Device).filter(Device.device_id == device_id).one_or_none()
    if device is None:
        raise RuntimeError(
            f"device {device_id!r} does not exist -- it is created when telemetry "
            "first arrives; start the edge publisher before seeding its registry"
        )

    existing = {
        row.channel.value if hasattr(row.channel, "value") else str(row.channel): row
        for row in db.query(Sensor).filter(Sensor.device_id == device.id).all()
    }

    seeded: list[Sensor] = []
    for channel in CHANNELS:
        spec = _PUMP01_SENSORS[channel]
        row = existing.get(channel)
        if row is None:
            row = Sensor(
                device_id=device.id,
                channel=Channel(channel),
                part=spec["part"],
                unit=spec["unit"],
                is_proxy=spec["is_proxy"],
            )
            db.add(row)
        else:
            row.part = spec["part"]
            row.unit = spec["unit"]
            row.is_proxy = spec["is_proxy"]
        seeded.append(row)

    db.commit()
    return seeded


def main() -> None:
    db_settings = DatabaseSettings.from_env()
    auth_settings = AuthSettings.from_env()
    engine = make_engine(db_settings.url)
    session_factory = make_session_factory(engine)
    with session_factory() as db:
        admin = seed_admin(db, auth_settings)
        print(f"admin user ready: {admin.email}")
        try:
            rows = seed_sensor_registry(db)
        except RuntimeError as exc:
            # Not fatal: the admin seed above is independently useful, and the
            # device simply may not have published yet.
            print(f"sensor registry SKIPPED: {exc}")
        else:
            print(f"sensor registry ready: {len(rows)} channels for {SEED_DEVICE_ID}")
            for row in rows:
                channel = row.channel.value if hasattr(row.channel, "value") else row.channel
                print(
                    f"  {channel:<12} part={row.part or '(none registered)':<10} "
                    f"unit={row.unit:<4} proxy={row.is_proxy}"
                )


if __name__ == "__main__":
    main()
