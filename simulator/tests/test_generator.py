"""M3.1 tests — deterministic telemetry generator + frozen-contract conformance."""

from app.schemas.contracts import CHANNELS, TelemetryMessage

from simulator.generator import BASELINES, RANGES, TelemetrySimulator

TS = [f"2026-08-09T12:00:{s:02d}.000Z" for s in range(5)]


def test_output_is_frozen_contract():
    msg = TelemetrySimulator(seed=1).next(TS[0])
    assert isinstance(msg, TelemetryMessage)
    # exactly the six frozen channels, no more/less
    assert set(msg.sensors.model_dump().keys()) == set(CHANNELS)
    # round-trips through the canonical validator
    TelemetryMessage.model_validate(msg.model_dump())


def test_all_six_channels_present():
    msg = TelemetrySimulator(seed=1).next(TS[0])
    dumped = msg.sensors.model_dump()
    for ch in CHANNELS:
        assert ch in dumped and isinstance(dumped[ch], float)


def test_deterministic_same_seed():
    a = [m.model_dump() for m in TelemetrySimulator(seed=42).generate(5, TS)]
    b = [m.model_dump() for m in TelemetrySimulator(seed=42).generate(5, TS)]
    assert a == b


def test_different_seed_differs():
    a = [m.sensors.model_dump() for m in TelemetrySimulator(seed=1).generate(5, TS)]
    b = [m.sensors.model_dump() for m in TelemetrySimulator(seed=2).generate(5, TS)]
    assert a != b


def test_sample_seq_monotonic_from_zero():
    msgs = TelemetrySimulator(seed=7).generate(5, TS)
    assert [m.sample_seq for m in msgs] == [0, 1, 2, 3, 4]


def test_timestamp_passthrough():
    msgs = TelemetrySimulator(seed=7).generate(5, TS)
    assert [m.ts for m in msgs] == TS


def test_values_within_declared_ranges():
    for m in TelemetrySimulator(seed=99).generate(50, [TS[0]] * 50):
        s = m.sensors.model_dump()
        for ch in CHANNELS:
            lo, hi = RANGES[ch]
            assert lo <= s[ch] <= hi


def test_values_near_baseline_mean():
    # over many samples the mean stays close to the declared baseline mean
    n = 500
    msgs = TelemetrySimulator(seed=3).generate(n, [TS[0]] * n)
    for ch in CHANNELS:
        mean = BASELINES[ch][0]
        avg = sum(m.sensors.model_dump()[ch] for m in msgs) / n
        assert abs(avg - mean) < BASELINES[ch][1]  # within one noise sd


def test_generate_length_mismatch_raises():
    import pytest

    with pytest.raises(ValueError):
        TelemetrySimulator().generate(3, TS)  # 3 != len(TS)==5
