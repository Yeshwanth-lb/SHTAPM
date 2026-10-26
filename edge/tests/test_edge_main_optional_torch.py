"""edge/main.py must run without torch.

Regression for a crash loop found on the bench Pi on 2026-09-24: ``torch`` was
missing from the venv, and edge/main.py imported the self-heal runtime (which
imports torch) at module top. The whole edge service crashed on boot, taking
telemetry, P2 detection and trust scoring down with it. Self-healing is an
optional layer. Losing it must not stop the rest of the pipeline.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import edge.main as edge_main

REPO_ROOT = Path(__file__).resolve().parents[2]

_BLOCK_TORCH_AND_IMPORT_MAIN = textwrap.dedent(
    """
    import importlib.abc
    import sys

    class _BlockTorch(importlib.abc.MetaPathFinder):
        def find_spec(self, name, path, target=None):
            if name == "torch" or name.startswith("torch."):
                raise ModuleNotFoundError("No module named 'torch'")
            return None

    sys.meta_path.insert(0, _BlockTorch())
    import edge.main as m

    assert m._load_self_heal("./does-not-exist", 30) is None
    assert "torch" not in sys.modules
    print("OK")
    """
)


def test_edge_main_imports_and_runs_self_heal_loader_without_torch():
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(REPO_ROOT / "backend"), str(REPO_ROOT)])
    result = subprocess.run(
        [sys.executable, "-c", _BLOCK_TORCH_AND_IMPORT_MAIN],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    assert "OK" in result.stdout
    assert "self-heal DISABLED" in result.stderr


def test_load_self_heal_returns_none_and_warns_when_runtime_unimportable(monkeypatch, caplog):
    # A None entry in sys.modules makes the import raise ImportError.
    monkeypatch.setitem(sys.modules, "edge.pipeline.self_heal_runtime", None)
    with caplog.at_level(logging.WARNING, logger="shtapm.edge.main"):
        assert edge_main._load_self_heal("./models", 30) is None
    assert any("self-heal DISABLED" in r.getMessage() for r in caplog.records)
