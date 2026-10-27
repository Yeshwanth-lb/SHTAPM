"""Device condition rollup -> ``devices.health_state`` (Doc05 §05.3 rollup; D043).

Doc05 asks the decision subscriber to keep ``devices.health_state`` current
"purely as a presentation-state derivation from existing health_state /
attribution -- no new safety logic". No prognosis model exists on pump data
(D017), so this is CONDITION MONITORING from evidence the system already
produces, never a remaining-life prediction (``decisions.health_state`` and
``failure_eta`` stay NULL):

  critical  an autonomous Safe Pump-Stop is latched (D041), OR attacks were
            attributed in a majority of the recent decisions, OR a channel is
            isolated while the newest decision attributes an attack
  warning   a channel is isolated, OR a sensor is dead (D045: publishing
            its last good reading), OR faults/attacks in a majority of the
            recent decisions
  healthy   otherwise

"Recent" is the last ``WINDOW`` decisions (10 s at 1 Hz) and "majority" is
``MAJORITY`` of them: a single noisy window (the detector flags ~10% of clean
windows by construction, D037) must not flash the dashboard red. Presentation
smoothing only -- nothing here can stop, isolate or alter anything.

Thread-safe (decision and actuation consumers run on their own MQTT threads);
the database is written only when the level changes.
"""

from __future__ import annotations

import logging
import threading
from collections import deque

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.models import Device
from app.schemas.actuation import AUTONOMOUS_CAUSES, ActuationStatus
from app.schemas.contracts import Attribution, HealthState
from app.schemas.decision_diagnostic import DecisionDiagnosticMessage
from app.services.decision_diagnostic_persistence import reduce_attribution

log = logging.getLogger("shtapm.services.condition")

WINDOW = 10
MAJORITY = 5


class ConditionRollup:
    def __init__(
        self,
        session_factory: sessionmaker[Session] | None,
        *,
        window: int = WINDOW,
        majority: int = MAJORITY,
    ) -> None:
        self._session_factory = session_factory
        self._window = window
        self._majority = majority
        self._lock = threading.Lock()
        self._recent: dict[str, deque[Attribution]] = {}
        self._isolated: dict[str, bool] = {}
        self._safe_stopped: dict[str, bool] = {}
        self._level: dict[str, HealthState] = {}

    # ---- sinks ------------------------------------------------------------
    def on_decision(self, message: DecisionDiagnosticMessage) -> None:
        label, _reason = reduce_attribution(message)
        with self._lock:
            recent = self._recent.setdefault(message.device_id, deque(maxlen=self._window))
            recent.append(label)
            self._isolated[message.device_id] = bool(
                message.tracked_isolation_candidates or message.stale_channels
            )
            self._refresh(message.device_id)

    def on_actuation(self, status: ActuationStatus) -> None:
        with self._lock:
            self._safe_stopped[status.device_id] = (
                status.latched and status.cause in AUTONOMOUS_CAUSES
            )
            self._refresh(status.device_id)

    # ---- state ------------------------------------------------------------
    def level(self, device_id: str) -> HealthState:
        with self._lock:
            return self._level.get(device_id, HealthState.healthy)

    def _compute(self, device_id: str) -> HealthState:
        recent = self._recent.get(device_id, deque())
        attacks = sum(1 for a in recent if a == Attribution.attack)
        anomalies = sum(1 for a in recent if a != Attribution.none)
        isolated = self._isolated.get(device_id, False)
        newest_attack = bool(recent) and recent[-1] == Attribution.attack
        if (
            self._safe_stopped.get(device_id, False)
            or attacks >= self._majority
            or (isolated and newest_attack)
        ):
            return HealthState.critical
        if isolated or anomalies >= self._majority:
            return HealthState.warning
        return HealthState.healthy

    def _refresh(self, device_id: str) -> None:
        level = self._compute(device_id)
        if self._level.get(device_id) == level:
            return
        self._level[device_id] = level
        self._persist(device_id, level)

    def _persist(self, device_id: str, level: HealthState) -> None:
        if self._session_factory is None:
            return
        try:
            with self._session_factory() as db:
                device = db.scalar(select(Device).where(Device.device_id == device_id))
                if device is None:
                    return
                device.health_state = level
                db.commit()
            log.info("device %s condition -> %s", device_id, level.value)
        except Exception:
            log.warning("condition rollup write failed", exc_info=False)
