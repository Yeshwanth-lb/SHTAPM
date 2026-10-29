"""Latest physics reading and twin values per device, for display (D054).

The edge reports, with every decision, what current and vibration each said
about the motor and the digital twin's reconstructed value for any substituted
channel. Neither is persisted (the decisions table has no such columns and the
ledger records actions, not readings); the dashboard reads the newest one.
"""

from __future__ import annotations

import threading

from app.schemas.decision_diagnostic import DecisionDiagnosticMessage


class LiveStateRegistry:
    def __init__(self) -> None:
        self._latest: dict[str, DecisionDiagnosticMessage] = {}
        self._lock = threading.Lock()

    def update(self, message: DecisionDiagnosticMessage) -> None:
        with self._lock:
            self._latest[message.device_id] = message

    def get(self, device_id: str) -> DecisionDiagnosticMessage | None:
        with self._lock:
            return self._latest.get(device_id)
