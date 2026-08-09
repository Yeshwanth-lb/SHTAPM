"""Backend configuration (P0 M3.3) — MQTT connection only.

Reads env vars (TRD §02.7). No secrets are logged; DB/auth config is deferred
to P4. Credentials (MQTT_USERNAME/PASSWORD) are intentionally not used yet
(anonymous dev broker) and never printed.
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
