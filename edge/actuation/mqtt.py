"""MQTT plumbing for the safety supervisor (D041).

``ActuationPublisher``     retained ``ActuationStatus`` on ``shtapm/{id}/actuation``;
                           the latest status is re-sent on every (re)connect, so
                           the backend never shows a stale relay state.
``RelayCommandListener``   ``RelayCommand`` on ``shtapm/{id}/relay_command`` ->
                           ``SafetySupervisor.command``.

Each has its own client and thread, independent of telemetry: a broker or
payload problem here can never delay or stop telemetry. Neither ever raises
into the caller. The broker is unauthenticated on the bench (D032's recorded
limitation applies to this topic too); commands are authorised at the backend.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from app.schemas.actuation import (
    ActuationStatus,
    actuation_topic,
    parse_relay_command,
    relay_command_topic,
)

from edge.actuation.supervisor import SafetySupervisor

log = logging.getLogger("shtapm.edge.actuation")


class ActuationPublisher:
    def __init__(self, *, device_id: str) -> None:
        self.topic = actuation_topic(device_id)
        self._client: Any | None = None
        self._latest: ActuationStatus | None = None
        self._lock = threading.Lock()

    def attach(self, client: Any) -> None:
        self._client = client
        client.on_connect = self._on_connect

    def _on_connect(self, client: Any, userdata: Any, flags: Any, rc: Any) -> None:
        if self._latest is not None:
            self._send(self._latest)

    def publish(self, status: ActuationStatus) -> None:
        self._latest = status
        self._send(status)

    def _send(self, status: ActuationStatus) -> None:
        client = self._client
        if client is None:
            return
        try:
            with self._lock:
                client.publish(self.topic, status.model_dump_json(), qos=1, retain=True)
        except Exception:
            log.warning("actuation status not published", exc_info=False)

    def start(self, host: str, port: int) -> None:
        try:
            import paho.mqtt.client as mqtt

            client = mqtt.Client()
            self.attach(client)
            client.connect_async(host, port)
            client.loop_start()
        except Exception:
            log.warning("actuation publisher failed to start; relay status not reported")
            self._client = None

    def stop(self) -> None:
        client, self._client = self._client, None
        if client is None:
            return
        try:
            client.loop_stop()
            client.disconnect()
        except Exception:
            log.debug("actuation publisher did not stop cleanly", exc_info=False)


class RelayCommandListener:
    def __init__(self, *, device_id: str, supervisor: SafetySupervisor) -> None:
        self.topic = relay_command_topic(device_id)
        self._supervisor = supervisor
        self._client: Any | None = None
        self.applied_count = 0
        self.rejected_count = 0

    def attach(self, client: Any) -> None:
        self._client = client
        client.on_connect = self._on_connect
        client.on_message = self._on_message

    def _on_connect(self, client: Any, userdata: Any, flags: Any, rc: Any) -> None:
        client.subscribe(self.topic, qos=1)
        log.info("relay command listener subscribed to %s", self.topic)

    def _on_message(self, client: Any, userdata: Any, msg: Any) -> None:
        self.handle(getattr(msg, "payload", b""))

    def handle(self, payload: bytes | str) -> bool:
        """Validate and apply one relay command. Never raises."""
        try:
            command = parse_relay_command(payload)
        except Exception as e:
            self.rejected_count += 1
            log.warning("rejected relay command on %s: %s", self.topic, type(e).__name__)
            return False
        try:
            applied = self._supervisor.command(command)
        except Exception:
            log.exception("relay command %s could not be applied", command.command_id)
            applied = False
        if applied:
            self.applied_count += 1
        else:
            self.rejected_count += 1
        return applied

    def start(self, host: str, port: int) -> None:
        try:
            import paho.mqtt.client as mqtt

            client = mqtt.Client()
            self.attach(client)
            client.connect_async(host, port)
            client.loop_start()
        except Exception:
            log.warning("relay command listener failed to start; remote start/stop unavailable")
            self._client = None

    def stop(self) -> None:
        client, self._client = self._client, None
        if client is None:
            return
        try:
            client.loop_stop()
            client.disconnect()
        except Exception:
            log.debug("relay command listener did not stop cleanly", exc_info=False)
