"""WebSocket telemetry route (P0 M3.4).

`GET /ws` (Doc05 §05.8): server→client live telemetry frames. Optional
``?device_id=<id>`` filters to one device. A ``?token=`` param is accepted for
forward-compat but NOT enforced in P0 — auth/JWT + device scoping are P4.

The route depends only on the broadcaster seam (``subscribe``/``unsubscribe``),
so the P4 gateway can replace the broadcaster without changing this route.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

log = logging.getLogger("shtapm.ws")

router = APIRouter()


@router.websocket("/ws")
async def telemetry_ws(websocket: WebSocket) -> None:
    await websocket.accept()
    device_id = websocket.query_params.get("device_id")  # optional filter
    broadcaster = websocket.app.state.telemetry_broadcaster
    queue = await broadcaster.subscribe()
    try:
        while True:
            frame = await queue.get()
            if device_id and frame.get("device_id") != device_id:
                continue
            await websocket.send_json(frame)
    except WebSocketDisconnect:
        pass
    except Exception:  # client gone / send failed — clean up, don't crash server
        log.info("ws telemetry connection closed")
    finally:
        broadcaster.unsubscribe(queue)
