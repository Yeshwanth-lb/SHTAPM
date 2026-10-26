"""Persisted P2 clean baseline (D031): build, save/load, windowing, the
prefitted live monitor, edge.main wiring, the twin-loader exclusion, and the
fit_p2_baseline.py command-line tool."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest
from app.schemas.contracts import CHANNELS

from edge.anomaly.preprocess import Preprocessor
from edge.models.p2_baseline import (
    BASELINE_STEM,
    FORMAT_VERSION,
    build_baseline,
    load_baseline,
    parse_capture,
    save_baseline,
    split_segments,
)
from simulator.generator import TelemetrySimulator

pytest.importorskip("sklearn")

T0 = datetime(2026, 10, 26, 6, 0, 0, tzinfo=UTC)


def _ts(seconds: float) -> str:
    return (
        (T0 + timedelta(seconds=seconds)).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    )


def _frames(count: int, *, start_s: float = 0.0, seed: int = 7, device: str = "pump-01"):
    sim = TelemetrySimulator(device_id=device, seed=seed)
    return sim.generate(count, [_ts(start_s + i) for i in range(count)])


def _preprocessor(window_size: int = 30) -> Preprocessor:
    return Preprocessor(median_kernel=1, low_pass_alpha=1.0, window_size=window_size)


# --- parsing and segmentation -------------------------------------------------


def test_parse_capture_skips_malformed_and_tolerates_topic_prefix():
    good = _frames(2)
    lines = [
        good[0].model_dump_json(),
        "",
        f"shtapm/pump-01/telemetry {good[1].model_dump_json()}",
        '96},"sample_seq":4520}',  # truncated line, as a stopped recorder leaves
        "not json at all",
    ]
    result = parse_capture(lines)
    assert [m.sample_seq for m in result.messages] == [0, 1]
    assert result.rejected_line_count == 2


def test_split_segments_breaks_on_gap_and_on_time_going_backwards():
    a = _frames(5, start_s=0)
    b = _frames(5, start_s=100)  # 96 s gap
    c = _frames(5, start_s=50)  # wall clock earlier than b's end -> restart artefact
    segments = split_segments(a + b + c, max_gap_s=5.0)
    # Sorted by timestamp: a (0-4), c (50-54), b (100-104) -- three runs.
    assert [len(s) for s in segments] == [5, 5, 5]
    assert [s[0].ts for s in segments] == [_ts(0), _ts(50), _ts(100)]


def test_split_segments_rejects_non_positive_gap():
    with pytest.raises(ValueError):
        split_segments(_frames(3), max_gap_s=0)


# --- build ----------------------------------------------------------------------


def test_build_baseline_drops_segments_shorter_than_one_window():
    frames = _frames(40, start_s=0) + _frames(10, start_s=500)
    baseline = build_baseline(frames, source="t", preprocessor=_preprocessor())
    assert len(baseline.segments) == 1
    assert baseline.frame_count == 40
    assert baseline.window_count() == 11
    assert baseline.duration_s == pytest.approx(39.0)


def test_build_baseline_refuses_empty_mixed_or_too_short_input():
    pre = _preprocessor()
    with pytest.raises(ValueError, match="no valid telemetry"):
        build_baseline([], source="t", preprocessor=pre)
    with pytest.raises(ValueError, match="mixes devices"):
        build_baseline(
            _frames(40) + _frames(40, start_s=40, device="pump-02"), source="t", preprocessor=pre
        )
    with pytest.raises(ValueError, match="reaches one window"):
        build_baseline(_frames(20), source="t", preprocessor=pre)


# --- save / load --------------------------------------------------------------


def test_save_load_round_trip_reproduces_identical_windows(tmp_path):
    frames = _frames(60)
    pre = _preprocessor()
    baseline = build_baseline(frames, source="capture.jsonl", preprocessor=pre)
    npz_path, json_path = save_baseline(baseline, tmp_path)
    assert npz_path.name == f"{BASELINE_STEM}.npz"
    metadata = json.loads(json_path.read_text(encoding="utf-8"))
    assert metadata["kind"] == "p2_baseline"
    assert metadata["format_version"] == FORMAT_VERSION
    assert metadata["channels"] == list(CHANNELS)
    assert metadata["window_count"] == 31

    loaded = load_baseline(tmp_path)
    assert loaded is not None
    assert loaded.source == "capture.jsonl"
    np.testing.assert_array_equal(loaded.segments[0], baseline.segments[0])

    direct = pre.process(frames)
    rebuilt = loaded.windows(pre)
    assert len(rebuilt) == len(direct)
    for got, want in zip(rebuilt, direct, strict=True):
        assert got.features == want.features


def test_windows_refuse_a_preprocessor_with_different_windowing(tmp_path):
    baseline = build_baseline(_frames(60), source="t", preprocessor=_preprocessor(30))
    with pytest.raises(ValueError, match="window_size=30"):
        baseline.windows(_preprocessor(20))


def test_load_returns_none_when_absent(tmp_path):
    assert load_baseline(tmp_path) is None
    assert load_baseline(tmp_path / "missing") is None


@pytest.mark.parametrize(
    "mutate",
    [
        lambda m: m.update(kind="twin"),
        lambda m: m.update(format_version=FORMAT_VERSION + 1),
        lambda m: m.update(channels=list(reversed(CHANNELS))),
    ],
)
def test_load_rejects_incompatible_metadata(tmp_path, caplog, mutate):
    save_baseline(build_baseline(_frames(40), source="t", preprocessor=_preprocessor()), tmp_path)
    json_path = tmp_path / f"{BASELINE_STEM}.json"
    metadata = json.loads(json_path.read_text(encoding="utf-8"))
    mutate(metadata)
    json_path.write_text(json.dumps(metadata), encoding="utf-8")
    with caplog.at_level("ERROR", logger="shtapm.edge.p2_baseline"):
        assert load_baseline(tmp_path) is None
    assert "falling back to live warm-up" in caplog.text


def test_load_rejects_corrupt_or_non_finite_data(tmp_path):
    save_baseline(build_baseline(_frames(40), source="t", preprocessor=_preprocessor()), tmp_path)
    npz_path = tmp_path / f"{BASELINE_STEM}.npz"
    npz_path.write_bytes(b"not an npz")
    assert load_baseline(tmp_path) is None

    bad = np.full((40, len(CHANNELS)), np.nan)
    np.savez_compressed(npz_path, segment_0=bad)
    assert load_baseline(tmp_path) is None


def test_load_never_unpickles(tmp_path):
    save_baseline(build_baseline(_frames(40), source="t", preprocessor=_preprocessor()), tmp_path)
    npz_path = tmp_path / f"{BASELINE_STEM}.npz"
    # An object array can only be read back with allow_pickle=True.
    np.savez(npz_path, segment_0=np.array([object()] * 3, dtype=object))
    assert load_baseline(tmp_path) is None


# --- prefitted live monitor ----------------------------------------------------


def _wired_monitor(baseline, publisher):
    from edge.main import _build_p2_monitor

    return _build_p2_monitor(
        fit_window_count=None,
        device_id="pump-01",
        decision_publisher=publisher,
        baseline=baseline,
    )


class _Capture:
    def __init__(self) -> None:
        self.messages: list = []

    def publish(self, message) -> None:
        self.messages.append(message)


def test_build_p2_monitor_with_baseline_scores_from_the_first_full_window():
    baseline = build_baseline(_frames(200, seed=3), source="t", preprocessor=_preprocessor())
    publisher = _Capture()
    monitor = _wired_monitor(baseline, publisher)
    live = _frames(32, start_s=1000, seed=4)
    for frame in live[:29]:
        monitor.on_frame(frame)
    assert publisher.messages == []  # no warm-up, but no partial window either
    monitor.on_frame(live[29])
    assert len(publisher.messages) == 1
    for frame in live[30:]:
        monitor.on_frame(frame)
    assert len(publisher.messages) == 3  # then one outcome per frame
    assert publisher.messages[-1].sample_seq == live[-1].sample_seq


def test_build_p2_monitor_without_baseline_keeps_live_warm_up():
    from edge.main import _build_p2_monitor

    publisher = _Capture()
    monitor = _build_p2_monitor(
        fit_window_count=3, device_id="pump-01", decision_publisher=publisher
    )
    frames = _frames(33)
    for frame in frames[:31]:
        monitor.on_frame(frame)
    assert publisher.messages == []  # warm-up needs 30 + 2 frames
    monitor.on_frame(frames[31])
    assert len(publisher.messages) == 1


def test_prefitted_monitor_refuses_unfitted_components():
    from edge.anomaly.attribution import AttributionEngine
    from edge.anomaly.detector import NullDetector
    from edge.anomaly.physics_rule import TrendSignPhysicsRule
    from edge.anomaly.pipeline import P2Pipeline
    from edge.anomaly.policy import SeverityThresholdFlagPolicy
    from edge.pipeline.monitor import LiveP2Monitor
    from edge.trust.c_consistency import ConsistencyProvider
    from edge.trust.engine import TrustEngine
    from edge.trust.h_reliability import HReliabilityProvider
    from edge.trust.k_correlation import CorrelationProvider

    pre = _preprocessor()
    c = ConsistencyProvider()
    pipeline = P2Pipeline(
        preprocessor=pre,
        detector=NullDetector(),
        trust_engine=TrustEngine(),
        attribution_engine=AttributionEngine(TrendSignPhysicsRule()),
        c_provider=c,
        k_provider=CorrelationProvider(),
        h_provider=HReliabilityProvider(),
        flag_policy=SeverityThresholdFlagPolicy(),
    )
    with pytest.raises(ValueError, match="has not been fit"):
        LiveP2Monitor(preprocessor=pre, pipeline=pipeline, c_provider=c, prefitted=True)
    with pytest.raises(ValueError, match="fit_window_count"):
        LiveP2Monitor(preprocessor=pre, pipeline=pipeline, c_provider=c)


# --- edge.main loader and the twin-loader exclusion ---------------------------


def test_load_p2_baseline_warns_when_shorter_than_recommended(tmp_path, caplog):
    from edge.main import _load_p2_baseline

    save_baseline(build_baseline(_frames(60), source="t", preprocessor=_preprocessor()), tmp_path)
    with caplog.at_level("WARNING", logger="shtapm.edge.main"):
        assert _load_p2_baseline(str(tmp_path)) is not None
    assert "covers only" in caplog.text


def test_load_p2_baseline_falls_back_when_absent(tmp_path, caplog):
    from edge.main import _load_p2_baseline

    with caplog.at_level("WARNING", logger="shtapm.edge.main"):
        assert _load_p2_baseline(str(tmp_path)) is None
    assert "falling back to live warm-up" in caplog.text


def test_twin_loader_ignores_the_p2_baseline_metadata(tmp_path, caplog):
    pytest.importorskip("torch")
    from edge.pipeline.self_heal_runtime import load_self_heal_runtime

    save_baseline(build_baseline(_frames(40), source="t", preprocessor=_preprocessor()), tmp_path)
    with caplog.at_level("INFO", logger="shtapm.edge.self_heal_runtime"):
        assert load_self_heal_runtime(tmp_path, window_size=30) is None
    assert "no twin bundle" in caplog.text
    assert "could not be loaded" not in caplog.text


# --- command-line tool ---------------------------------------------------------


def test_fit_p2_baseline_cli_builds_checks_and_saves(tmp_path, capsys):
    from edge.scripts.fit_p2_baseline import main

    capture = tmp_path / "baseline_capture.jsonl"
    capture.write_text(
        "\n".join(m.model_dump_json() for m in _frames(400, seed=11)) + "\n{truncated",
        encoding="utf-8",
    )
    model_dir = tmp_path / "models"
    assert main([str(capture), "--model-dir", str(model_dir)]) == 0
    out = capsys.readouterr().out
    assert "400 valid frames, 1 malformed lines skipped" in out
    assert "HOLD-OUT CHECK" in out
    assert "WARNING: under 30 min" in out
    loaded = load_baseline(model_dir)
    assert loaded is not None and loaded.frame_count == 400


def test_fit_p2_baseline_cli_reports_missing_capture(tmp_path, capsys):
    from edge.scripts.fit_p2_baseline import main

    assert main([str(tmp_path / "nope.jsonl"), "--no-check"]) == 2
    assert "capture not found" in capsys.readouterr().err
