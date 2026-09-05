"""Tests for edge/models/degradation_generator.py (synthetic gradual-
degradation trajectories -- simulation-only, no real dataset/hardware).

All numeric config values below are TEST FIXTURES ONLY -- arbitrary, not
project specifications or claims about real pump behavior.
"""

from __future__ import annotations

import pytest
from app.schemas.contracts import CHANNELS

from edge.models.degradation_generator import (
    DATA_SOURCE,
    EXECUTION_MODE,
    TRAJECTORY_TYPE,
    ChannelDegradationConfig,
    DegradationTrajectory,
    SyntheticDegradationGenerator,
)

DEVICE = "pump-01"


def _ts(n: int) -> list[str]:
    return [f"2026-08-10T00:00:{i:02d}.000Z" for i in range(n)]


def _generator(**overrides) -> SyntheticDegradationGenerator:
    config = {
        "device_id": DEVICE,
        "length": 10,
        "start_health": 1.0,
        "end_health": 0.0,
        "degradation_rate": 1.0,
        "seed": 1337,
        "channels": {
            "vibration": ChannelDegradationConfig(healthy_value=0.03, degraded_value=1.2),
        },
    }
    config.update(overrides)
    return SyntheticDegradationGenerator(**config)


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_same_seed_produces_identical_output():
    gen_a = _generator(seed=42)
    gen_b = _generator(seed=42)
    traj_a = gen_a.generate(_ts(10))
    traj_b = gen_b.generate(_ts(10))

    assert traj_a.health == traj_b.health
    assert traj_a.per_channel_health == traj_b.per_channel_health
    for frame_a, frame_b in zip(traj_a.frames, traj_b.frames, strict=True):
        assert frame_a.model_dump() == frame_b.model_dump()


def test_different_seed_changes_noisy_values_but_not_health_curve():
    noisy = {
        "vibration": ChannelDegradationConfig(
            healthy_value=0.03, degraded_value=1.2, noise_std=0.5
        ),
    }
    traj_a = _generator(seed=1, channels=noisy).generate(_ts(10))
    traj_b = _generator(seed=2, channels=noisy).generate(_ts(10))

    # Ground-truth health is a pure function of config, never of seed.
    assert traj_a.health == traj_b.health
    assert traj_a.per_channel_health == traj_b.per_channel_health
    # But the noisy telemetry values themselves differ.
    vib_a = [f.sensors.vibration for f in traj_a.frames]
    vib_b = [f.sensors.vibration for f in traj_b.frames]
    assert vib_a != vib_b


# ---------------------------------------------------------------------------
# Health progression
# ---------------------------------------------------------------------------


def test_overall_health_decreases_monotonically_from_start_to_end():
    traj = _generator(start_health=1.0, end_health=0.2, length=20).generate(_ts(20))

    assert traj.health[0] == pytest.approx(1.0)
    assert traj.health[-1] == pytest.approx(0.2)
    for earlier, later in zip(traj.health, traj.health[1:], strict=False):
        assert later <= earlier  # non-increasing


def test_configured_channel_health_reaches_configured_end_health():
    traj = _generator(start_health=0.9, end_health=0.1, length=15).generate(_ts(15))

    vib_health = traj.per_channel_health["vibration"]
    assert vib_health[0] == pytest.approx(0.9)
    assert vib_health[-1] == pytest.approx(0.1)


def test_unconfigured_channel_stays_flat_and_healthy():
    """A channel with no ChannelDegradationConfig does not degrade at all --
    explicit non-participation, never a fabricated drift."""
    traj = _generator().generate(_ts(10))  # only "vibration" is configured

    temp_health = traj.per_channel_health["temperature"]
    assert all(h == temp_health[0] for h in temp_health)
    temp_values = [f.sensors.temperature for f in traj.frames]
    assert len(set(temp_values)) == 1  # perfectly flat, zero noise by default


# ---------------------------------------------------------------------------
# Trajectory length
# ---------------------------------------------------------------------------


def test_trajectory_length_is_respected():
    traj = _generator(length=37).generate(_ts(37))
    assert len(traj.frames) == 37
    assert len(traj.health) == 37
    for values in traj.per_channel_health.values():
        assert len(values) == 37


def test_timestamps_length_mismatch_raises():
    gen = _generator(length=10)
    with pytest.raises(ValueError, match="timestamps length"):
        gen.generate(_ts(5))


# ---------------------------------------------------------------------------
# Configuration validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "overrides",
    [
        {"length": 1},
        {"length": 0},
        {"start_health": 0.5, "end_health": 0.5},  # end must be strictly < start
        {"start_health": 0.3, "end_health": 0.6},  # end > start
        {"start_health": 1.5},  # out of [0,1]
        {"end_health": -0.1},  # out of [0,1]
        {"degradation_rate": 0.0},
        {"degradation_rate": -1.0},
        {
            "channels": {
                "not_a_channel": ChannelDegradationConfig(healthy_value=0.0, degraded_value=1.0)
            }
        },
    ],
)
def test_invalid_configuration_raises(overrides):
    with pytest.raises(ValueError):
        _generator(**overrides)


def test_channel_config_rejects_non_positive_rate_override():
    with pytest.raises(ValueError, match="degradation_rate"):
        ChannelDegradationConfig(healthy_value=0.0, degraded_value=1.0, degradation_rate=0.0)


def test_channel_config_rejects_negative_noise():
    with pytest.raises(ValueError, match="noise_std"):
        ChannelDegradationConfig(healthy_value=0.0, degraded_value=1.0, noise_std=-0.1)


# ---------------------------------------------------------------------------
# Noise: bounded / configurable
# ---------------------------------------------------------------------------


def test_zero_noise_is_perfectly_deterministic_across_seeds():
    silent = {
        "vibration": ChannelDegradationConfig(healthy_value=0.03, degraded_value=1.2, noise_std=0.0)
    }
    traj_a = _generator(seed=1, channels=silent).generate(_ts(10))
    traj_b = _generator(seed=999, channels=silent).generate(_ts(10))

    vib_a = [f.sensors.vibration for f in traj_a.frames]
    vib_b = [f.sensors.vibration for f in traj_b.frames]
    assert vib_a == vib_b  # no noise_std -> seed cannot matter


def test_higher_noise_std_increases_observed_spread():
    low = {
        "vibration": ChannelDegradationConfig(healthy_value=1.0, degraded_value=1.0, noise_std=0.01)
    }
    high = {
        "vibration": ChannelDegradationConfig(healthy_value=1.0, degraded_value=1.0, noise_std=5.0)
    }
    # healthy_value == degraded_value so all variation is noise, isolating its effect.
    traj_low = _generator(seed=7, length=200, channels=low).generate(_ts(200))
    traj_high = _generator(seed=7, length=200, channels=high).generate(_ts(200))

    vib_low = [f.sensors.vibration for f in traj_low.frames]
    vib_high = [f.sensors.vibration for f in traj_high.frames]
    spread_low = max(vib_low) - min(vib_low)
    spread_high = max(vib_high) - min(vib_high)
    assert spread_high > spread_low


# ---------------------------------------------------------------------------
# Per-channel degradation: different channels, different rates
# ---------------------------------------------------------------------------


def test_different_channels_can_have_different_degradation_rates():
    channels = {
        "vibration": ChannelDegradationConfig(
            healthy_value=0.0, degraded_value=1.0, degradation_rate=0.5
        ),
        "current": ChannelDegradationConfig(
            healthy_value=0.0, degraded_value=1.0, degradation_rate=3.0
        ),
    }
    traj = _generator(length=11, channels=channels).generate(_ts(11))

    mid = 5  # an interior tick, strictly between the shared start/end anchors
    vib_mid = traj.frames[mid].sensors.vibration
    current_mid = traj.frames[mid].sensors.current
    # Same healthy/degraded endpoints and same overall span, but different
    # shape exponents -> different values at the same interior tick.
    assert vib_mid != pytest.approx(current_mid)
    # The slower-shaping (rate<1) channel should have progressed further by
    # the midpoint than the faster-shaping (rate>1) one (see module
    # docstring's HEALTH CURVE SHAPE section).
    assert vib_mid > current_mid


def test_per_channel_health_independent_of_other_channels():
    channels = {
        "vibration": ChannelDegradationConfig(
            healthy_value=0.0, degraded_value=1.0, degradation_rate=2.0
        ),
        # No override -> uses the trajectory's own global rate.
        "current": ChannelDegradationConfig(healthy_value=0.0, degraded_value=1.0),
    }
    traj = _generator(degradation_rate=1.0, length=11, channels=channels).generate(_ts(11))

    assert traj.per_channel_health["vibration"] != traj.per_channel_health["current"]
    # "current" used no override, so it matches the global rate/curve exactly.
    assert traj.per_channel_health["current"] == traj.health


# ---------------------------------------------------------------------------
# Simulation metadata
# ---------------------------------------------------------------------------


def test_trajectory_carries_explicit_simulation_metadata():
    traj = _generator().generate(_ts(10))
    assert traj.data_source == "synthetic"
    assert traj.execution_mode == "simulation"
    assert traj.trajectory_type == "gradual_degradation"
    assert isinstance(traj, DegradationTrajectory)
    # Module-level constants match the instance metadata exactly.
    expected = ("synthetic", "simulation", "gradual_degradation")
    assert (DATA_SOURCE, EXECUTION_MODE, TRAJECTORY_TYPE) == expected


# ---------------------------------------------------------------------------
# Structural isolation: no hardware/network/real-dataset coupling
# ---------------------------------------------------------------------------


def test_all_frames_are_valid_frozen_telemetry_messages():
    traj = _generator().generate(_ts(10))
    for i, frame in enumerate(traj.frames):
        assert frame.device_id == DEVICE
        assert frame.sample_seq == i
        assert set(CHANNELS).issubset(frame.model_dump()["sensors"].keys())


def test_module_has_no_hardware_network_or_real_dataset_imports():
    import edge.models.degradation_generator as module

    with open(module.__file__, encoding="utf-8") as f:
        content = f.read()
    for forbidden in ("RPi", "gpiozero", "paho", "AnomalyResult", "DecisionMessage"):
        assert forbidden not in content
    assert "GPIO" not in content.upper()
    assert "MQTT" not in content.upper()
    # No coupling to the fault/attack injection framework's types, and no
    # actual import of the real PRONOSTIA dataset loader (mentioning its
    # module path in prose, to explain the separation, is fine).
    assert "Injection" not in content
    assert "pronostia_prep import" not in content
