"""WebSocket frame builders (P0 M3.4).

Wraps a canonical payload in the Doc05 §05.8 WS envelope: a flat object with a
``type`` discriminator plus the payload fields (ruling E — ``type`` is the WS
concern; the payload fields are the frozen M2 contract, unchanged). Only the
telemetry frame is built in M3.4; decision/ledger/etc. frames come with their
milestones.
"""

from __future__ import annotations

from typing import Any

from app.schemas.contracts import TelemetryMessage, WSFrameType


def telemetry_frame(message: TelemetryMessage) -> dict[str, Any]:
    """{"type":"telemetry", device_id, ts, sensors:{...}, sample_seq} (Doc05 §05.8)."""
    return {"type": WSFrameType.telemetry.value, **message.model_dump()}
