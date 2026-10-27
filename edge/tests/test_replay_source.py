"""Recorded-session fallback profile (D040) and named boot errors (AC10 P1-2/P1-4)."""

from __future__ import annotations

import json

import pytest
from app.schemas.contracts import CHANNELS

from edge.acquisition.replay import ReplaySampler, ReplaySourceError, load_replay_frames
from edge.acquisition.runtime import AcquisitionRuntime


def _row(i: int, current: float) -> dict:
    return {
        "device_id": "pump-01",
        "ts": f"2026-10-27T06:06:{i:02d}.000Z",
        "sensors": {
            "temperature": 26.0,
            "vibration": 0.1 * i,
            "pressure": 916.6,
            "humidity": 45.0,
            "gas": 150.0,
            "current": current,
        },
        "sample_seq": 1900 + i,
    }


def _capture(tmp_path, rows, extra_lines=()):
    path = tmp_path / "session.jsonl"
    lines = [json.dumps(r) for r in rows] + list(extra_lines)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _clock():
    ticks = iter(range(10_000))
    return lambda: f"2026-12-01T10:00:{next(ticks) % 60:02d}.000Z"


# --- happy ------------------------------------------------------------------


def test_replays_recorded_values_with_fresh_stamps_and_sequence(tmp_path):
    frames = load_replay_frames(_capture(tmp_path, [_row(i, 0.7) for i in range(3)]))
    sampler = ReplaySampler(device_id="pump-01", frames=frames, clock=_clock())
    out = [sampler.sample_once() for _ in range(3)]
    assert all(r.healthy for r in out)
    assert [r.frame.sample_seq for r in out] == [0, 1, 2]  # not the recorded 1900+
    assert [r.frame.ts for r in out] == [
        "2026-12-01T10:00:00.000Z",
        "2026-12-01T10:00:01.000Z",
        "2026-12-01T10:00:02.000Z",
    ]
    assert [r.frame.sensors.vibration for r in out] == pytest.approx([0.0, 0.1, 0.2])
    assert set(out[0].readings) == set(CHANNELS)


def test_loops_at_the_end_of_the_recording(tmp_path):
    frames = load_replay_frames(_capture(tmp_path, [_row(i, 0.7) for i in range(2)]))
    sampler = ReplaySampler(device_id="pump-01", frames=frames, clock=_clock())
    values = [sampler.sample_once().frame.sensors.vibration for _ in range(5)]
    assert values == pytest.approx([0.0, 0.1, 0.0, 0.1, 0.0])
    assert sampler.loops == 2


def test_runs_through_the_unchanged_acquisition_runtime(tmp_path):
    class Publisher:
        def __init__(self):
            self.frames = []

        def publish(self, frame):
            self.frames.append(frame)

    seen = []
    frames = load_replay_frames(_capture(tmp_path, [_row(i, 0.7) for i in range(4)]))
    publisher = Publisher()
    runtime = AcquisitionRuntime(
        sampler=ReplaySampler(device_id="pump-01", frames=frames, clock=_clock()),
        publisher=publisher,
        rate_hz=1.0,
        on_healthy_frame=seen.append,
        frame_transform=lambda f: f,  # the scenario-injection seam still applies
    )
    for _ in range(4):
        runtime.tick()
    assert len(publisher.frames) == 4
    assert seen == publisher.frames


# --- edge / sad -------------------------------------------------------------


def test_skips_malformed_lines_in_the_recording(tmp_path):
    path = _capture(tmp_path, [_row(0, 0.7)], extra_lines=["not json", '{"half": '])
    assert len(load_replay_frames(path)) == 1


def test_missing_file_fails_loudly_naming_the_variable(tmp_path):
    with pytest.raises(ReplaySourceError, match="FALLBACK_REPLAY_PATH"):
        load_replay_frames(tmp_path / "absent.jsonl")


def test_file_without_any_frame_fails_loudly(tmp_path):
    with pytest.raises(ReplaySourceError, match="no valid telemetry frame"):
        load_replay_frames(_capture(tmp_path, [], extra_lines=["garbage"]))


# --- boot configuration (edge/main.py) ---------------------------------------


def test_edge_source_defaults_to_sensors():
    from edge.main import _edge_source

    assert _edge_source({}) == ("sensors", None)


def test_replay_source_requires_a_path():
    from edge.main import _edge_source

    with pytest.raises(RuntimeError, match="FALLBACK_REPLAY_PATH"):
        _edge_source({"EDGE_SOURCE": "replay"})
    assert _edge_source({"EDGE_SOURCE": "replay", "FALLBACK_REPLAY_PATH": "x.jsonl"}) == (
        "replay",
        "x.jsonl",
    )


def test_unknown_edge_source_is_a_named_boot_error():
    from edge.main import _edge_source

    with pytest.raises(RuntimeError, match="EDGE_SOURCE"):
        _edge_source({"EDGE_SOURCE": "camera"})


def test_malformed_sample_rate_names_the_variable():
    """AC10 P1-4: SAMPLE_RATE_HZ="x" -> a boot error naming the variable."""
    from edge.main import _env_number

    with pytest.raises(RuntimeError, match="SAMPLE_RATE_HZ"):
        _env_number("SAMPLE_RATE_HZ", "1", float, env={"SAMPLE_RATE_HZ": "x"})
    assert _env_number("SAMPLE_RATE_HZ", "1", float, env={}) == 1.0


def test_missing_fit_window_count_names_the_variable(monkeypatch):
    """AC10 P1-2 (edge): without a baseline, P2_FIT_WINDOW_COUNT is required."""
    from edge.main import _required_env_int

    monkeypatch.delenv("P2_FIT_WINDOW_COUNT", raising=False)
    with pytest.raises(RuntimeError, match="P2_FIT_WINDOW_COUNT"):
        _required_env_int("P2_FIT_WINDOW_COUNT")
    monkeypatch.setenv("P2_FIT_WINDOW_COUNT", "five")
    with pytest.raises(RuntimeError, match="P2_FIT_WINDOW_COUNT"):
        _required_env_int("P2_FIT_WINDOW_COUNT")
