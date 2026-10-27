"""Relay actuation contract: backend <-> edge (FR-R1..R3, AC4; D041).

Two topics, both separate from the advisory scenario-injection topic
(``shtapm/{id}/command``, D032), so an injection command can still never reach
the relay -- D032's guarantee is kept by construction, not by code review:

``shtapm/{device_id}/relay_command``  backend -> edge, QoS 1
    ``RelayCommand``: an operator's explicit start/stop. Authorised at the
    backend (admin only, audited, ledger-chained).

``shtapm/{device_id}/actuation``      edge -> backend, QoS 1, RETAINED
    ``ActuationStatus``: the relay's actual state and WHY it is in it. Retained,
    so a backend that restarts learns the current state immediately.

SAFE-STOP IS A LATCH. After an autonomous stop (self-heal escalation, dry-run,
watchdog) the relay stays OFF -- ``latched`` -- until an operator explicitly
starts it again. Nothing restarts the pump by itself (PRD US-06, D041).

``hardware`` says whether a physical relay is configured on the edge. False
means the edge runs the identical safety logic against an in-memory relay and
nothing is switched -- reported so no dashboard can claim a stop that did not
physically happen.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

RELAY_COMMAND_TOPIC = "shtapm/{device_id}/relay_command"
ACTUATION_TOPIC = "shtapm/{device_id}/actuation"
ACTUATION_SUBSCRIPTION = "shtapm/+/actuation"

RelayState = Literal["on", "off"]
# startup   the edge started; the relay is forced OFF (safe default)
# command   an operator's RelayCommand
# safe_stop self-heal escalation (D018: divergence, or 60 s substitution expiry)
# dry_run   the pump is commanded on but draws dry-run current (FR-R2)
# watchdog  the edge's acquisition loop stalled (FR-R3)
# shutdown  the edge stopped; the relay is forced OFF
ActuationCause = Literal["startup", "command", "safe_stop", "dry_run", "watchdog", "shutdown"]
AUTONOMOUS_CAUSES: frozenset[str] = frozenset({"safe_stop", "dry_run", "watchdog"})


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RelayCommand(_Strict):
    action: Literal["relay"]
    command_id: str = Field(min_length=1, max_length=64)
    device_id: str = Field(min_length=1)
    state: RelayState
    issued_by: str = Field(min_length=1)
    issued_at: str = Field(min_length=1)


class ActuationStatus(_Strict):
    device_id: str = Field(min_length=1)
    ts: str = Field(min_length=1)
    relay: RelayState
    cause: ActuationCause
    reason: str
    latched: bool
    hardware: bool


def relay_command_topic(device_id: str) -> str:
    return RELAY_COMMAND_TOPIC.format(device_id=device_id)


def actuation_topic(device_id: str) -> str:
    return ACTUATION_TOPIC.format(device_id=device_id)


def device_from_actuation_topic(topic: str) -> str | None:
    parts = topic.split("/")
    if len(parts) == 3 and parts[0] == "shtapm" and parts[2] == "actuation":
        return parts[1]
    return None


def parse_relay_command(payload: bytes | str) -> RelayCommand:
    """Validate a raw MQTT payload. Raises ``pydantic.ValidationError``."""
    return RelayCommand.model_validate_json(payload)


def parse_actuation_status(payload: bytes | str) -> ActuationStatus:
    """Validate a raw MQTT payload. Raises ``pydantic.ValidationError``."""
    return ActuationStatus.model_validate_json(payload)
