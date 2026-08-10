"""P2 tests — synthetic §12.4 injection shape/semantics (hardware-free).

Validate ONLY the transform mechanics (which samples/channels change and how),
NOT detection, physics, or dataset behaviour. All numeric injection parameters
below are **TEST FIXTURES ONLY — arbitrary values, not project specifications.**
"""

import pytest
from app.schemas.build import build_telemetry
from app.schemas.contracts import CHANNELS

from edge.injection import (
    ATTACK_TYPES,
    FAULT_TYPES,
    BiasFDI,
    ConstantSpoof,
    Drift,
    InjectionType,
    Kind,
    RampFDI,
    Replay,
    Spike,
    StuckAt,
)

DEVICE = "pump-01"

# --- TEST FIXTURES ONLY (arbitrary, NOT spec magnitudes/durations) ----------
_BASE = 10.0  # fixture baseline value
_STEP = 1.0  # fixture per-sample ramp so freezes/replays are visible


def _ts(i: int) -> str:
    return f"2026-08-10T00:00:{i:02d}.000Z"


def _stream(n: int, *, base: float = _BASE, step: float = _STEP):
    """A clean stream where every channel = base + step*i (fixture data)."""
    frames = []
    for i in range(n):
        values = {ch: base + step * i for ch in CHANNELS}
        frames.append(build_telemetry(DEVICE, _ts(i), values, i))
    return frames


def _col(frames, channel):
    return [float(getattr(f.sensors, channel)) for f in frames]


# --- faults ------------------------------------------------------------------


def test_drift_cumulative_within_window_only():
    frames = _stream(6)
    rate = 2.0  # TEST FIXTURE ONLY
    res = Drift(channel="pressure", onset=2, duration=3, rate=rate).apply(frames)
    got = _col(res.frames, "pressure")
    clean = _col(frames, "pressure")
    # before onset: untouched
    assert got[:2] == clean[:2]
    # within window: base + rate*(1,2,3)
    assert got[2] == pytest.approx(clean[2] + rate * 1)
    assert got[3] == pytest.approx(clean[3] + rate * 2)
    assert got[4] == pytest.approx(clean[4] + rate * 3)
    # after window: untouched
    assert got[5] == clean[5]


def test_spike_only_active_samples():
    frames = _stream(5)
    amp = 50.0  # TEST FIXTURE ONLY
    res = Spike(channel="vibration", onset=2, duration=1, amplitude=amp).apply(frames)
    got = _col(res.frames, "vibration")
    clean = _col(frames, "vibration")
    assert got[2] == pytest.approx(clean[2] + amp)
    assert got[:2] == clean[:2] and got[3:] == clean[3:]  # single-sample spike


def test_stuck_at_freezes_to_onset_value():
    frames = _stream(6)  # varying stream so a freeze is visible
    res = StuckAt(channel="humidity", onset=2, duration=3).apply(frames)
    got = _col(res.frames, "humidity")
    frozen = _BASE + _STEP * 2  # value at onset index 2
    assert got[2] == got[3] == got[4] == pytest.approx(frozen)
    assert got[1] != got[2] and got[5] != got[4]  # only the window is frozen


def test_stuck_at_explicit_held_value():
    frames = _stream(4)
    res = StuckAt(channel="gas", onset=1, duration=2, held_value=99.0).apply(frames)
    got = _col(res.frames, "gas")
    assert got[1] == got[2] == pytest.approx(99.0)  # TEST FIXTURE ONLY


# --- attacks -----------------------------------------------------------------


def test_bias_fdi_constant_offset():
    frames = _stream(5)
    bias = 7.5  # TEST FIXTURE ONLY
    res = BiasFDI(channel="current", onset=1, duration=3, bias=bias).apply(frames)
    got = _col(res.frames, "current")
    clean = _col(frames, "current")
    for i in (1, 2, 3):
        assert got[i] == pytest.approx(clean[i] + bias)
    assert got[0] == clean[0] and got[4] == clean[4]


def test_ramp_fdi_cumulative_offset():
    frames = _stream(5)
    slope = 3.0  # TEST FIXTURE ONLY
    res = RampFDI(channel="temperature", onset=1, duration=3, slope=slope).apply(frames)
    got = _col(res.frames, "temperature")
    clean = _col(frames, "temperature")
    assert got[1] == pytest.approx(clean[1] + slope * 1)
    assert got[2] == pytest.approx(clean[2] + slope * 2)
    assert got[3] == pytest.approx(clean[3] + slope * 3)


def test_replay_copies_earlier_segment():
    frames = _stream(8)
    res = Replay(channel="pressure", onset=4, duration=3, source_onset=0).apply(frames)
    got = _col(res.frames, "pressure")
    clean = _col(frames, "pressure")
    # window [4,7) replays source [0,3)
    assert got[4] == pytest.approx(clean[0])
    assert got[5] == pytest.approx(clean[1])
    assert got[6] == pytest.approx(clean[2])
    assert got[:4] == clean[:4] and got[7] == clean[7]


def test_constant_spoof_flatlines_channel():
    frames = _stream(6)  # varying stream so the flatten is visible
    res = ConstantSpoof(channel="pressure", onset=2, duration=3, value=1013.0).apply(frames)
    got = _col(res.frames, "pressure")
    assert got[2] == got[3] == got[4] == pytest.approx(1013.0)  # TEST FIXTURE ONLY
    assert got[1] != got[2]  # unchanged before the window


# --- cross-cutting semantics -------------------------------------------------


def test_only_target_channel_changes():
    frames = _stream(5)
    res = BiasFDI(channel="pressure", onset=0, duration=5, bias=5.0).apply(frames)
    for ch in CHANNELS:
        if ch == "pressure":
            continue
        assert _col(res.frames, ch) == _col(frames, ch)  # untouched


def test_input_stream_not_mutated():
    frames = _stream(5)
    snapshot = _col(frames, "current")
    ConstantSpoof(channel="current", onset=0, duration=5, value=0.0).apply(frames)
    assert _col(frames, "current") == snapshot  # pure transform


def test_metadata_preserved_device_ts_seq():
    frames = _stream(4)
    res = Spike(channel="gas", onset=1, duration=1, amplitude=1.0).apply(frames)
    for orig, out in zip(frames, res.frames, strict=True):
        assert out.device_id == orig.device_id
        assert out.ts == orig.ts
        assert out.sample_seq == orig.sample_seq


def test_labels_mark_active_window_and_kind():
    frames = _stream(6)
    res = ConstantSpoof(channel="pressure", onset=2, duration=2, value=5.0).apply(frames)
    active = [lab.index for lab in res.labels if lab.active]
    assert active == [2, 3]
    for lab in res.labels:
        assert lab.channel == "pressure"
        assert lab.injection_type is InjectionType.CONSTANT_SPOOF
        assert lab.kind is Kind.ATTACK
        assert lab.sample_seq == lab.index  # fixture stream: seq == index


def test_kind_grouping_matches_taxonomy():
    assert FAULT_TYPES == {InjectionType.DRIFT, InjectionType.SPIKE, InjectionType.STUCK_AT}
    assert ATTACK_TYPES == {
        InjectionType.BIAS_FDI,
        InjectionType.RAMP_FDI,
        InjectionType.REPLAY,
        InjectionType.CONSTANT_SPOOF,
    }
    assert not (FAULT_TYPES & ATTACK_TYPES)
    # dry-run is intentionally absent (physical, hardware-gated)
    assert "dry_run" not in {t.value for t in InjectionType}


# --- validation --------------------------------------------------------------


def test_bad_channel_rejected():
    with pytest.raises(ValueError):
        Spike(channel="flow", onset=0, duration=1, amplitude=1.0)


@pytest.mark.parametrize("onset,duration", [(-1, 1), (0, 0), (0, -3)])
def test_bad_window_rejected(onset, duration):
    with pytest.raises(ValueError):
        Drift(channel="pressure", onset=onset, duration=duration, rate=1.0)


def test_missing_required_magnitude_is_type_error():
    # Magnitudes are genuinely required args (no spec default).
    with pytest.raises(TypeError):
        Drift(channel="pressure", onset=0, duration=1)  # type: ignore[call-arg]


def test_replay_source_out_of_range_rejected():
    frames = _stream(5)
    with pytest.raises(ValueError):
        # source [4,7) exceeds stream length 5 (onset kept past the source end)
        Replay(channel="pressure", onset=10, duration=3, source_onset=4)._validate_against(frames)


def test_replay_source_must_end_before_onset():
    frames = _stream(10)
    with pytest.raises(ValueError):
        # source [2,7) overlaps/extends past onset=4
        Replay(channel="pressure", onset=4, duration=5, source_onset=2)._validate_against(frames)
