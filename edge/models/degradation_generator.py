"""Synthetic gradual-degradation trajectory generator (simulation-only).

data_source=synthetic · execution_mode=simulation · trajectory_type=gradual_degradation

Produces a smoothly worsening, deterministic ``TelemetryMessage`` stream plus
an aligned per-tick ground-truth health signal (overall and per-channel, both
in ``[end_health, start_health] subset of [0, 1]``, 1.0 = fully healthy). This
is a CONTINUOUS WEAR-OUT trajectory, not a discrete event -- the opposite
shape from the existing fault/attack transforms in
``edge/injection/injections.py`` (drift/spike/stuck-at/FDI/replay/spoof),
which stamp a bounded onset/duration event onto an otherwise-clean stream.
Both exist and are used independently; this module does not modify, import
from, or duplicate the injection framework's types.

This module is entirely independent of, and does not read from, the real
PRONOSTIA/FEMTO bearing dataset (``edge/eval/pronostia_prep.py`` and
siblings) -- that pipeline consumes real, on-disk, measured run-to-failure
recordings; this one manufactures a health curve from caller-supplied
numeric parameters, with no claim that it resembles any specific real
bearing or pump's actual degradation behavior. It also has no dependency on,
and never talks to, any physical sensor, actuator, or message-broker
publishing path -- it only builds in-memory ``TelemetryMessage`` values, the
same frozen wire type ``simulator/generator.py`` and ``edge/injection/``
already build, via the same shared ``build_telemetry`` helper.

WHY A HEALTH CURVE EXISTS AT ALL: PRD FR-M1/M2 (prognosis) and FR-RL1 (the
RL state vector's ``health``/``failure_ETA`` fields) both need a source of
gradually-changing ground truth to train/exercise against before real bench
or field degradation data exists. Every numeric shape/rate/noise/value below
is a caller-supplied simulation parameter -- nothing here is a project
specification, an approved DECISIONS.md value, or a claim about real pump
wear. Unlike ``edge/eval/pronostia_prognosis_targets.py``'s D025/D026
(explicit, documented policy values for a REAL dataset's labels), this
module makes no policy claim at all: every value is a required or
explicitly-defaulted constructor argument the caller chooses per run.

HEALTH CURVE SHAPE: for a trajectory of ``length`` ticks, tick ``i``'s
normalized position is ``fraction = i / (length - 1)`` (so tick 0 is exactly
``start_health`` and the final tick is exactly ``end_health``, regardless of
``degradation_rate``). ``degradation_rate`` reshapes progress within that
span via ``fraction ** degradation_rate`` -- 1.0 is linear, greater than 1.0
degrades slowly at first then accelerates (a common qualitative wear-out
shape), less than 1.0 the reverse. This is a simulation convenience for
producing varied, configurable curve shapes, not a fitted or cited physical
wear law.

PER-CHANNEL BEHAVIOR: a channel with no ``ChannelDegradationConfig`` supplied
does not participate in the trajectory at all -- it stays flat at
``simulator.generator.BASELINES``' existing plausible baseline mean (reused,
not duplicated) with zero injected noise, an explicit "this channel is
unaffected by this run's degradation" choice, never a fabricated drift. A
configured channel's own value is linearly interpolated between its
``healthy_value`` and ``degraded_value`` by that channel's own (optionally
overridden) degradation-rate-shaped progress, then has independent Gaussian
noise added if ``noise_std > 0`` -- so different channels may degrade at
different rates and reach the same overall trajectory length with different
value trajectories, reflecting that a real sensor's raw reading and the
"true" underlying health need not move in lockstep.

DETERMINISM: the health curve itself (overall and per-channel) is a pure
function of the config -- it never depends on ``seed``. Only the additive
per-channel noise is drawn from ``random.Random(seed)``, so two generators
with the same config and seed produce byte-identical output, and two with
the same config but different seeds share the same ground-truth health
curve with different noise realizations -- useful for training multiple
episodes at the same difficulty.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from random import Random

from app.schemas.build import build_telemetry
from app.schemas.contracts import CHANNELS, TelemetryMessage

from simulator.generator import BASELINES

DATA_SOURCE = "synthetic"
EXECUTION_MODE = "simulation"
TRAJECTORY_TYPE = "gradual_degradation"


@dataclass(frozen=True)
class ChannelDegradationConfig:
    """One channel's participation in a degradation trajectory. Both values
    are REQUIRED simulation choices -- no default magnitude is invented for
    what a fully-degraded channel reads (mirrors this project's existing
    "no invented spec value" discipline, e.g. ``edge/injection/injections.py``'s
    required per-type magnitudes).

    ``degradation_rate``: ``None`` (default) means "use the trajectory's own
    global ``degradation_rate``"; a supplied value overrides it for this
    channel only, so different channels can degrade at different rates.
    """

    healthy_value: float
    degraded_value: float
    degradation_rate: float | None = None
    noise_std: float = 0.0

    def __post_init__(self) -> None:
        if self.degradation_rate is not None and self.degradation_rate <= 0:
            raise ValueError(f"degradation_rate must be > 0, got {self.degradation_rate}")
        if self.noise_std < 0:
            raise ValueError(f"noise_std must be >= 0, got {self.noise_std}")


@dataclass(frozen=True)
class DegradationTrajectory:
    """One generated run's output: the telemetry stream plus aligned
    ground-truth health (overall and per-channel), and explicit simulation
    metadata -- never to be presented as, or mistaken for, real hardware
    validation or a real measured dataset."""

    frames: tuple[TelemetryMessage, ...]
    health: tuple[float, ...]
    per_channel_health: Mapping[str, tuple[float, ...]]
    data_source: str = DATA_SOURCE
    execution_mode: str = EXECUTION_MODE
    trajectory_type: str = TRAJECTORY_TYPE


@dataclass
class SyntheticDegradationGenerator:
    """Deterministic generator of one gradual-degradation trajectory.

    Mirrors ``simulator.generator.TelemetrySimulator``'s shape (a small
    configured object exposing a ``generate`` method that builds frozen
    ``TelemetryMessage``s via the shared ``build_telemetry``), extended with
    a health curve and per-channel degradation config. Channels absent from
    ``channels`` stay flat at their existing simulator baseline (see module
    docstring) -- passing an empty mapping degrades no channel at all.
    """

    device_id: str = "pump-01"
    length: int = 100
    start_health: float = 1.0
    end_health: float = 0.0
    degradation_rate: float = 1.0
    seed: int = 1337
    channels: Mapping[str, ChannelDegradationConfig] = field(default_factory=dict)
    _rng: Random = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if self.length < 2:
            raise ValueError(
                f"length must be >= 2 (need a start and an end tick), got {self.length}"
            )
        if not (0.0 <= self.end_health < self.start_health <= 1.0):
            raise ValueError(
                "health must satisfy 0.0 <= end_health < start_health <= 1.0, "
                f"got start_health={self.start_health}, end_health={self.end_health}"
            )
        if self.degradation_rate <= 0:
            raise ValueError(f"degradation_rate must be > 0, got {self.degradation_rate}")
        unknown = sorted(set(self.channels) - set(CHANNELS))
        if unknown:
            raise ValueError(
                f"channels contains unknown channel(s) {unknown}; must be one of {CHANNELS}"
            )
        self._rng = Random(self.seed)

    def _shaped_progress(self, i: int, rate: float) -> float:
        """Tick ``i``'s [0, 1] position, reshaped by ``rate`` (see module
        docstring's HEALTH CURVE SHAPE section). Exactly 0.0 at ``i == 0``
        and exactly 1.0 at ``i == length - 1``, for any ``rate > 0``."""
        fraction = i / (self.length - 1)
        return fraction**rate

    def _health_at(self, progress: float) -> float:
        return self.start_health - (self.start_health - self.end_health) * progress

    def _channel_sample(self, channel: str, i: int) -> tuple[float, float]:
        """Returns ``(value, channel_health)`` for ``channel`` at tick ``i``."""
        config = self.channels.get(channel)
        if config is None:
            # Unconfigured: flat at the existing simulator's own plausible
            # baseline mean, no drift, no noise -- explicitly not
            # participating in this run's degradation (see module docstring).
            return BASELINES[channel][0], self.start_health

        rate = self.degradation_rate if config.degradation_rate is None else config.degradation_rate
        progress = self._shaped_progress(i, rate)
        channel_health = self._health_at(progress)
        value = config.healthy_value + (config.degraded_value - config.healthy_value) * progress
        if config.noise_std > 0:
            value += self._rng.gauss(0.0, config.noise_std)
        return value, channel_health

    def generate(self, timestamps: list[str]) -> DegradationTrajectory:
        """Deterministically generate the full ``length``-tick trajectory
        using the given timestamps (caller-supplied, like
        ``TelemetrySimulator.generate`` -- no wall clock is read).

        Raises:
            ValueError: if ``len(timestamps) != self.length``.
        """
        if len(timestamps) != self.length:
            raise ValueError(
                f"timestamps length ({len(timestamps)}) must equal length ({self.length})"
            )

        frames: list[TelemetryMessage] = []
        health: list[float] = []
        per_channel_health: dict[str, list[float]] = {ch: [] for ch in CHANNELS}

        for i in range(self.length):
            overall_progress = self._shaped_progress(i, self.degradation_rate)
            health.append(self._health_at(overall_progress))

            readings: dict[str, float] = {}
            for ch in CHANNELS:
                value, ch_health = self._channel_sample(ch, i)
                readings[ch] = value
                per_channel_health[ch].append(ch_health)

            frames.append(build_telemetry(self.device_id, timestamps[i], readings, i))

        return DegradationTrajectory(
            frames=tuple(frames),
            health=tuple(health),
            per_channel_health={ch: tuple(values) for ch, values in per_channel_health.items()},
        )
