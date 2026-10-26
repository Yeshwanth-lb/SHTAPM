"""Scenario-injection command contract: backend -> edge (U14, resolved by D032).

TRD §02.3 names the topic ``shtapm/{device_id}/command`` (QoS 1, backend ->
edge, advisory) but no document specified the payload. This module is that
payload, shared verbatim by the backend publisher and the edge listener so the
two can never disagree about field names (D006).

ADVISORY ONLY. A command alters the telemetry the edge publishes and monitors
for a bounded time, exactly as a real false-data-injection attacker or a
failing sensor would. It never reaches actuation, the relay, or the safety
loop's own state: the edge applies it to frames before P2 sees them and
nowhere else.

NO INVENTED MAGNITUDES. Every scenario's magnitude is a required, operator-
supplied parameter, mirroring ``edge/injection``'s own rule that injections
take no spec defaults. The only bound this module adds is
``MAX_DURATION_S``, a demo-safety policy cap (D032) so an injection left
running by mistake ends on its own.
"""

from __future__ import annotations

import math
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

from app.schemas.contracts import Channel

COMMAND_TOPIC = "shtapm/{device_id}/command"
MAX_DURATION_S = 600

InjectionScenario = Literal[
    "drift",
    "spike",
    "stuck_at",
    "bias_fdi",
    "ramp_fdi",
    "replay",
    "constant_spoof",
    "adaptive_stealth_fdi",
]

# Required parameters per scenario, in the units of the target channel (per
# second where a rate). Names match the edge.injection constructor arguments
# except ``lookback_s``, which the edge converts into Replay's source offset.
SCENARIO_PARAMS: dict[str, tuple[str, ...]] = {
    "drift": ("rate",),
    "spike": ("amplitude",),
    "stuck_at": (),
    "bias_fdi": ("bias",),
    "ramp_fdi": ("slope",),
    "replay": ("lookback_s",),
    "constant_spoof": ("value",),
    "adaptive_stealth_fdi": ("rate", "residual_cap"),
}
# Optional parameters per scenario. stuck_at holds the value at onset unless
# the operator pins an explicit one.
SCENARIO_OPTIONAL_PARAMS: dict[str, tuple[str, ...]] = {"stuck_at": ("held_value",)}

ATTACK_SCENARIOS = frozenset(
    {"bias_fdi", "ramp_fdi", "replay", "constant_spoof", "adaptive_stealth_fdi"}
)
FAULT_SCENARIOS = frozenset({"drift", "spike", "stuck_at"})


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class InjectCommand(_Strict):
    action: Literal["inject"]
    command_id: str = Field(min_length=1, max_length=64)
    device_id: str = Field(min_length=1)
    scenario: InjectionScenario
    channel: Channel
    duration_s: int = Field(ge=1, le=MAX_DURATION_S)
    params: dict[str, float] = Field(default_factory=dict)
    issued_by: str = Field(min_length=1)
    issued_at: str = Field(min_length=1)

    @model_validator(mode="after")
    def _check_params(self) -> InjectCommand:
        required = set(SCENARIO_PARAMS[self.scenario])
        allowed = required | set(SCENARIO_OPTIONAL_PARAMS.get(self.scenario, ()))
        given = set(self.params)
        missing = required - given
        if missing:
            raise ValueError(f"{self.scenario} requires params {sorted(missing)}")
        unknown = given - allowed
        if unknown:
            raise ValueError(f"{self.scenario} does not accept params {sorted(unknown)}")
        for name, value in self.params.items():
            if not math.isfinite(value):
                raise ValueError(f"param {name} must be finite")
        if self.scenario == "adaptive_stealth_fdi" and self.params["residual_cap"] <= 0:
            raise ValueError("residual_cap must be > 0")
        if self.scenario == "replay":
            lookback = self.params["lookback_s"]
            if lookback != int(lookback):
                raise ValueError("lookback_s must be a whole number of seconds")
            # Replay copies the window that ended `lookback_s` ago; it must not
            # overlap the injected span itself (edge.injection.Replay's rule).
            if lookback < self.duration_s:
                raise ValueError("lookback_s must be >= duration_s (no overlap with the replay)")
        return self

    @property
    def kind(self) -> str:
        return "attack" if self.scenario in ATTACK_SCENARIOS else "fault"


class CancelCommand(_Strict):
    action: Literal["cancel"]
    command_id: str = Field(min_length=1, max_length=64)
    device_id: str = Field(min_length=1)
    issued_by: str = Field(min_length=1)
    issued_at: str = Field(min_length=1)


Command = Annotated[InjectCommand | CancelCommand, Field(discriminator="action")]
_COMMAND_ADAPTER: TypeAdapter[InjectCommand | CancelCommand] = TypeAdapter(Command)


def parse_command(payload: bytes | str) -> InjectCommand | CancelCommand:
    """Validate a raw MQTT payload. Raises ``pydantic.ValidationError``."""
    return _COMMAND_ADAPTER.validate_json(payload)


def command_topic(device_id: str) -> str:
    return COMMAND_TOPIC.format(device_id=device_id)
