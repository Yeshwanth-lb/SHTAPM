"""WebSocket telemetry route (P0 M3.4 plumbing; P4-M6 adds auth + scoping).

``GET /ws?token=<jwt>&device_id=<id>`` (Doc05 §05.8): ``token`` is REQUIRED
and validated exactly like REST (``app.core.security.decode_access_token``);
an optional ``device_id`` filters to one device. Scoping matches the REST
API (``app.api.deps``): admins see every device; anyone else only their
own — with no ``device_id`` filter, a non-admin is now scoped to ALL of
their owned devices' frames (not every device's, as the pre-auth P0
behavior allowed).

An invalid/missing token, or a ``device_id`` the caller can't access,
closes the connection before ``accept()`` is ever called (ASGI allows
``websocket.close`` while still in the CONNECTING state to reject the
handshake outright) — no frame can leak to an unauthorized client.

The route still depends only on the broadcaster seam
(``subscribe``/``unsubscribe``) for delivery, so a future gateway swap
doesn't need to touch this auth logic.
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.concurrency import run_in_threadpool

from app.core.security import TokenError, decode_access_token
from app.models import Device, User
from app.models.enums import UserRole

log = logging.getLogger("shtapm.ws")

router = APIRouter()

WS_AUTH_FAILED = 4401  # custom close code: missing/invalid/expired token
WS_ACCESS_DENIED = 4403  # custom close code: valid token, device not accessible


def _authenticate(websocket: WebSocket) -> tuple[User, set[str] | None] | None:
    """Sync DB-touching auth check, run off the event loop via
    ``run_in_threadpool``. Returns ``(user, allowed_device_ids)`` — the set
    is ``None`` for admins (no restriction) — or ``None`` on any failure."""
    settings = websocket.app.state.auth_settings
    token = websocket.query_params.get("token")
    if not token:
        return None
    try:
        claims = decode_access_token(token, settings)
        user_id = uuid.UUID(claims.sub)
    except (TokenError, ValueError):
        return None

    session_factory = websocket.app.state.db_sessionmaker
    with session_factory() as db:
        user = db.get(User, user_id)
        if user is None or not user.is_active:
            return None
        if user.role == UserRole.admin:
            return user, None
        owned = db.query(Device.device_id).filter(Device.owner_user_id == user.id).all()
        return user, {row[0] for row in owned}


@router.websocket("/ws")
async def telemetry_ws(websocket: WebSocket) -> None:
    auth_result = await run_in_threadpool(_authenticate, websocket)
    if auth_result is None:
        await websocket.close(code=WS_AUTH_FAILED)
        return
    _user, allowed_device_ids = auth_result

    requested_device_id = websocket.query_params.get("device_id")
    if (
        requested_device_id is not None
        and allowed_device_ids is not None
        and requested_device_id not in allowed_device_ids
    ):
        await websocket.close(code=WS_ACCESS_DENIED)
        return

    await websocket.accept()
    broadcaster = websocket.app.state.telemetry_broadcaster
    queue = await broadcaster.subscribe()
    try:
        while True:
            frame = await queue.get()
            frame_device_id = frame.get("device_id")
            if requested_device_id and frame_device_id != requested_device_id:
                continue
            if allowed_device_ids is not None and frame_device_id not in allowed_device_ids:
                continue
            await websocket.send_json(frame)
    except WebSocketDisconnect:
        pass
    except Exception:  # client gone / send failed — clean up, don't crash server
        log.info("ws telemetry connection closed")
    finally:
        broadcaster.unsubscribe(queue)
