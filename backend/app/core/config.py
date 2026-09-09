"""Backend configuration (P0 M3.3 MQTT; P4 adds DB + auth).

Reads env vars (TRD §02.7). No secrets are logged. Credentials
(MQTT_USERNAME/PASSWORD) remain unused (anonymous dev broker, per
``.env.example``'s own P4 TODO note) and never printed.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import ClassVar
from urllib.parse import quote

from app.schemas.contracts import CHANNELS


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


# Placeholder shipped in .env.example. Reaching the database layer means it was
# never replaced, and the resulting failure ("password authentication failed")
# points at the database rather than at the config, so name it explicitly.
_PLACEHOLDER_PASSWORD = "CHANGE_ME"


@dataclass(frozen=True)
class DatabaseSettings:
    """Connection URL, either given directly or composed from the POSTGRES_* parts.

    WHY BOTH: ``.env.example`` used to carry the password twice — once as
    ``POSTGRES_PASSWORD`` (which initialises the container) and once embedded in
    a literal ``DATABASE_URL`` (which the backend authenticates with) — kept in
    step by a comment asking the operator to do it manually. Setting one and not
    the other produced ``FATAL: password authentication failed for user
    "shtapm"``, which reads as a database problem rather than a config typo, and
    cost real debugging time during P5 bring-up.

    ``DATABASE_URL`` still wins when set, so nothing that already exports it
    changes behaviour (including tests using ``sqlite://``). When it is absent
    the URL is composed from the same variables Compose uses, so the two cannot
    disagree.
    """

    url: str

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> DatabaseSettings:
        env = os.environ if env is None else env
        url = env.get("DATABASE_URL")
        if url:
            if _PLACEHOLDER_PASSWORD in url:
                raise RuntimeError(
                    f"DATABASE_URL still contains the {_PLACEHOLDER_PASSWORD!r} placeholder "
                    "from .env.example. Either set a real password in it, or unset "
                    "DATABASE_URL entirely and let it be composed from POSTGRES_USER/"
                    "POSTGRES_PASSWORD/POSTGRES_HOST/POSTGRES_PORT/POSTGRES_DB."
                )
            return cls(url=url)
        return cls(url=cls._compose(env))

    @staticmethod
    def _compose(env: Mapping[str, str]) -> str:
        password = env.get("POSTGRES_PASSWORD")
        if not password:
            raise RuntimeError(
                "Set DATABASE_URL, or POSTGRES_PASSWORD so it can be composed "
                "from the POSTGRES_* variables (see .env.example)"
            )
        if password == _PLACEHOLDER_PASSWORD:
            raise RuntimeError(
                f"POSTGRES_PASSWORD is still the {_PLACEHOLDER_PASSWORD!r} placeholder"
            )
        user = env.get("POSTGRES_USER", "shtapm")
        host = env.get("POSTGRES_HOST", "localhost")
        port = env.get("POSTGRES_PORT", "5432")
        database = env.get("POSTGRES_DB", "shtapm")
        # quote(): a password may legally contain @ : / # ? — unescaped, any of
        # them silently corrupts the URL into a different host or database.
        return (
            f"postgresql+psycopg://{quote(user, safe='')}:{quote(password, safe='')}"
            f"@{host}:{port}/{database}"
        )


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


@dataclass(frozen=True)
class ChannelSourceSettings:
    """Which frozen channels are fed by a physically-connected sensor on the
    edge, and which are placeholder constants.

    NOT DERIVABLE FROM THE DATA. The frozen telemetry contract carries six
    plain floats and no provenance marker, so a placeholder constant is
    byte-identical on the wire to a real reading — the backend cannot infer
    this and must be told. It is declared here rather than guessed.

    ``SHTAPM_CHANNEL_SOURCES`` is a comma-separated ``<channel>=<source>``
    list, e.g.::

        SHTAPM_CHANNEL_SOURCES=temperature=live,humidity=live,vibration=live

    Recognised sources are ``live`` (physically connected sensor) and
    ``placeholder`` (fake constant, no sensor). Any channel not named is
    reported as ``unknown`` — deliberately NOT defaulted to either value,
    because "we were not told" and "we know it is fake" are different claims
    and a dashboard must not present the first as the second.

    This mirrors the edge's own ``SHTAPM_DRIVER_<CHANNEL>`` convention
    (edge/drivers/registry.py) but is a SEPARATE declaration on a separate
    machine: it is what this backend has been told, not what the edge is
    actually running. Keep the two in step when the bench is rewired.
    """

    sources: Mapping[str, str]

    VALID_SOURCES: ClassVar[frozenset[str]] = frozenset({"live", "placeholder"})
    UNKNOWN: ClassVar[str] = "unknown"

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> ChannelSourceSettings:
        raw = (os.environ if env is None else env).get("SHTAPM_CHANNEL_SOURCES", "").strip()
        if not raw:
            return cls(sources={})
        parsed: dict[str, str] = {}
        for item in raw.split(","):
            item = item.strip()
            if not item:
                continue
            channel, _, source = item.partition("=")
            channel, source = channel.strip(), source.strip()
            if channel not in CHANNELS:
                raise RuntimeError(
                    f"SHTAPM_CHANNEL_SOURCES names unknown channel {channel!r} "
                    f"(expected one of {sorted(CHANNELS)})"
                )
            if source not in cls.VALID_SOURCES:
                raise RuntimeError(
                    f"SHTAPM_CHANNEL_SOURCES={channel}={source!r} must be "
                    f"one of {sorted(cls.VALID_SOURCES)}"
                )
            parsed[channel] = source
        return cls(sources=parsed)

    def source_for(self, channel: str) -> str:
        """Declared source for one channel, or ``"unknown"`` when undeclared."""
        return self.sources.get(channel, self.UNKNOWN)


@dataclass(frozen=True)
class CorsSettings:
    """Browser origins allowed to call this API.

    ``CORS_ALLOWED_ORIGINS`` has been documented in ``.env.example`` since P0
    but was never read by anything — so a browser served from any origin other
    than the API's own was blocked, and the failure surfaced in the UI as a
    generic network error rather than as a CORS message (a blocked
    cross-origin fetch rejects with a TypeError, not an HTTP status).

    Comma-separated absolute origins, e.g.::

        CORS_ALLOWED_ORIGINS=http://localhost:5173,http://192.168.1.20:5173

    Origins are matched exactly by the browser (scheme + host + port), so the
    Pi's LAN origin must be listed explicitly — ``localhost`` does not cover it.

    ``"*"`` is accepted but deliberately NOT the default: this API is a
    credential-bearing admin surface. Note the wildcard also cannot be combined
    with ``allow_credentials=True`` per the CORS spec; this project sends bearer
    tokens in a header rather than cookies, so credentials stay off and the
    wildcard remains usable for a throwaway demo.
    """

    allowed_origins: tuple[str, ...]

    DEFAULT: ClassVar[str] = "http://localhost:5173"

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> CorsSettings:
        raw = (os.environ if env is None else env).get("CORS_ALLOWED_ORIGINS")
        if raw is None:
            raw = cls.DEFAULT
        origins = tuple(item.strip() for item in raw.split(",") if item.strip())
        return cls(allowed_origins=origins)
