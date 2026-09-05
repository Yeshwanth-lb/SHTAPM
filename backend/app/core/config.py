"""Backend configuration (P0 M3.3 MQTT; P4 adds DB + auth).

Reads env vars (TRD §02.7). No secrets are logged. Credentials
(MQTT_USERNAME/PASSWORD) remain unused (anonymous dev broker, per
``.env.example``'s own P4 TODO note) and never printed.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class MqttSettings:
    host: str
    port: int

    @classmethod
    def from_env(cls) -> MqttSettings:
        return cls(
            host=os.environ.get("MQTT_HOST", "localhost"),
            port=int(os.environ.get("MQTT_PORT", "1883")),
        )


@dataclass(frozen=True)
class DatabaseSettings:
    url: str

    @classmethod
    def from_env(cls) -> DatabaseSettings:
        url = os.environ.get("DATABASE_URL")
        if not url:
            raise RuntimeError("DATABASE_URL is required (see .env.example)")
        return cls(url=url)


@dataclass(frozen=True)
class AuthSettings:
    jwt_secret_key: str
    jwt_access_ttl_min: int
    jwt_refresh_ttl_days: int
    password_bcrypt_rounds: int

    @classmethod
    def from_env(cls) -> AuthSettings:
        secret = os.environ.get("JWT_SECRET_KEY")
        if not secret:
            raise RuntimeError("JWT_SECRET_KEY is required (see .env.example)")
        return cls(
            jwt_secret_key=secret,
            jwt_access_ttl_min=int(os.environ.get("JWT_ACCESS_TTL_MIN", "15")),
            jwt_refresh_ttl_days=int(os.environ.get("JWT_REFRESH_TTL_DAYS", "7")),
            password_bcrypt_rounds=int(os.environ.get("PASSWORD_BCRYPT_ROUNDS", "12")),
        )
