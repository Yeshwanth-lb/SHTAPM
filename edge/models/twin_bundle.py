"""Deployable digital-twin artifact: weights + scale + residual statistics.

A trained twin is useless on its own. Reproducing what it learned also needs:

  * the D029 ``ChannelScaler`` it was trained under -- a reconstruction is only
    meaningful, and only invertible to engineering units, on the same fixed
    scale the targets were expressed in;
  * the residual mean/std observed on clean training data -- what
    ``DivergenceScorer`` must be fitted with to score new residuals the same
    way they were scored during evaluation;
  * ``hidden_size``, which ``LSTMTwinReconstructor.from_checkpoint`` requires
    and cannot infer from a state dict alone.

Keeping them in one bundle stops a checkpoint being loaded against a scale or
residual distribution it was never trained with -- which would produce
confident, plausible, meaningless numbers rather than an error.

Weights go to ``<path>.pt`` (``torch.save``/``torch.load(weights_only=True)``,
state dict only, no arbitrary-object unpickling) and metadata to ``<path>.json``
so the scale and residual statistics stay human-readable and reviewable.

No bundle is committed to this repository: a trained twin is an artifact of a
specific bench capture, and the capture itself is gitignored evidence.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from app.schemas.contracts import CHANNELS

from edge.models.lstm_twin import LSTMTwinReconstructor
from edge.models.scaling import ChannelScaler

BUNDLE_FORMAT_VERSION = 1


@dataclass(frozen=True)
class TwinBundle:
    """A trained twin and everything needed to use it consistently."""

    channel: str
    reconstructor: LSTMTwinReconstructor
    scaler: ChannelScaler
    residual_mean: float
    residual_std: float
    hidden_size: int
    skill: float
    trained_on: str

    def divergence_fit(self) -> dict[str, list[float]]:
        """Residual sample for ``DivergenceScorer.fit()``.

        The scorer fits mean/std from a sequence, so two points placed
        symmetrically about the recorded mean at ±std reproduce exactly the
        distribution measured at training time, without shipping every residual.
        """
        return {
            self.channel: [
                self.residual_mean - self.residual_std,
                self.residual_mean + self.residual_std,
            ]
        }


def save_bundle(
    path: str | Path,
    *,
    channel: str,
    reconstructor: LSTMTwinReconstructor,
    scaler: ChannelScaler,
    residual_mean: float,
    residual_std: float,
    hidden_size: int,
    skill: float,
    trained_on: str,
) -> None:
    """Write ``<path>.pt`` + ``<path>.json``."""
    base = Path(path)
    reconstructor.save(str(base.with_suffix(".pt")))
    metadata = {
        "format_version": BUNDLE_FORMAT_VERSION,
        "channel": channel,
        "hidden_size": hidden_size,
        "residual_mean": residual_mean,
        "residual_std": residual_std,
        # Recorded so a deployed twin can be traced to the evidence behind it
        # rather than being an anonymous binary.
        "skill_vs_mean_baseline": skill,
        "trained_on": trained_on,
        "scale": {
            ch: {
                "mean": scaler.denormalize(ch, 0.0),
                "std": scaler.denormalize(ch, 1.0) - scaler.denormalize(ch, 0.0),
            }
            for ch in sorted(scaler.fitted_channels)
        },
    }
    base.with_suffix(".json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")


def load_bundle(path: str | Path) -> TwinBundle:
    """Read a bundle written by ``save_bundle``.

    Raises:
        FileNotFoundError: if either file is missing.
        ValueError: on an unknown format version or an unknown channel -- a
            silently mismatched bundle is worse than a refusal.
    """
    base = Path(path)
    metadata = json.loads(base.with_suffix(".json").read_text(encoding="utf-8"))

    version = metadata.get("format_version")
    if version != BUNDLE_FORMAT_VERSION:
        raise ValueError(
            f"twin bundle {base}: format_version {version!r}, expected {BUNDLE_FORMAT_VERSION}"
        )
    channel = metadata["channel"]
    if channel not in CHANNELS:
        raise ValueError(f"twin bundle {base}: unknown channel {channel!r}")

    scaler = ChannelScaler()
    for ch, stats in metadata["scale"].items():
        # fit() derives mean/std from samples; two points at mean±std reproduce
        # the recorded scale exactly.
        mean, std = float(stats["mean"]), float(stats["std"])
        scaler.fit({ch: [mean - std, mean + std]})

    reconstructor = LSTMTwinReconstructor.from_checkpoint(
        str(base.with_suffix(".pt")), hidden_size=int(metadata["hidden_size"])
    )
    return TwinBundle(
        channel=channel,
        reconstructor=reconstructor,
        scaler=scaler,
        residual_mean=float(metadata["residual_mean"]),
        residual_std=float(metadata["residual_std"]),
        hidden_size=int(metadata["hidden_size"]),
        skill=float(metadata.get("skill_vs_mean_baseline", 0.0)),
        trained_on=str(metadata.get("trained_on", "unknown")),
    )
