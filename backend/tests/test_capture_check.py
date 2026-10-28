"""In-recording capture check (scripts/capture_check.py)."""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

_PATH = Path(__file__).resolve().parents[2] / "scripts" / "capture_check.py"
_spec = importlib.util.spec_from_file_location("capture_check", _PATH)
capture_check = importlib.util.module_from_spec(_spec)
sys.modules["capture_check"] = capture_check
_spec.loader.exec_module(capture_check)

T0 = datetime(2026, 10, 28, 6, 0, tzinfo=UTC)


def _write(path: Path, rows: list[tuple[float, float]], step_s: float = 1.0) -> Path:
    """rows: (current A, vibration g) per frame, one frame per ``step_s``."""
    with path.open("w", encoding="utf-8") as handle:
        for i, (current, vibration) in enumerate(rows):
            ts = (T0 + timedelta(seconds=i * step_s)).isoformat().replace("+00:00", "Z")
            sensors = dict.fromkeys(capture_check.CHANNELS, 1.0)
            sensors.update(current=current, vibration=vibration)
            handle.write(json.dumps({"ts": ts, "sensors": sensors}) + "\n")
        handle.write('{"ts": "2026-10-28T07')  # partly written last line
    return path


def _cycling(idle_g: float, running_g: float, minutes: int = 10) -> list[tuple[float, float]]:
    rows = []
    for second in range(minutes * 60):
        on = (second // 60) % 2 == 1
        rows.append((0.75, running_g) if on else (0.0, idle_g))
    return rows


def test_healthy_capture_passes(tmp_path, capsys):
    path = _write(tmp_path / "c.jsonl", _cycling(idle_g=0.1, running_g=0.6))
    assert capture_check.main([str(path)]) == 0
    assert "OK" in capsys.readouterr().out


def test_shifted_sensor_is_flagged(tmp_path):
    # 2026-10-28: idle 2.7 g, running 2.7 g after the ADXL moved.
    path = _write(tmp_path / "c.jsonl", _cycling(idle_g=2.7, running_g=2.75))
    _, problems = capture_check.check(capture_check.load_frames(path))
    assert any("ADXL moved" in p for p in problems)
    assert any("cannot tell on from off" in p for p in problems)


def test_gaps_and_missing_values_are_flagged(tmp_path):
    path = _write(tmp_path / "c.jsonl", _cycling(0.1, 0.6, minutes=1), step_s=5.0)
    frames = capture_check.load_frames(path)
    del frames[3]["sensors"]["humidity"]
    _, problems = capture_check.check(frames)
    assert any("gap" in p for p in problems)
    assert any(p.startswith("humidity: 1 frame") for p in problems)


def test_empty_capture_is_a_problem():
    assert capture_check.check([]) == ([], ["no readable frames yet"])
