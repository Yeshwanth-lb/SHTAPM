"""Backend -> edge command publisher (scenario injection, D032).

Publishes validated ``InjectCommand`` / ``CancelCommand`` payloads to
``shtapm/{device_id}/command`` at QoS 1 (TRD §02.3). Its own client and
network thread, independent of the three consumers, so a publish problem
cannot disturb ingestion.

HONEST DELIVERY REPORTING. ``publish`` returns False when the client is not
connected or paho refuses the message, and the REST endpoint turns that into a
503 -- a command is never reported as sent when it was not. True means the
broker accepted it for delivery at QoS 1; it does not prove the edge applied
it (the edge logs every start/reject, and the dashboard shows the result
through the telemetry itself).
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from app.schemas.command import CancelCommand, InjectCommand, command_topic

log = logging.getLogger("shtapm.mqtt.command")


class CommandPublisher:
    def __init__(self) -> None:
        self._client: Any | None = None
        self._lock = threading.Lock()

    def attach(self, client: Any) -> None:
        """Use an existing (or fake) client -- tests attach one directly."""
        self._client = client

    def start(self, host: str, port: int) -> None:
        """Non-blocking connect; tolerates the broker being down at startup."""
        try:
            import paho.mqtt.client as mqtt  # lazy: unit tests need no paho

            client = mqtt.Client()
            client.connect_async(host, port)
            client.loop_start()
            self._client = client
        except Exception:
            log.warning("command publisher failed to start; injection unavailable")
            self._client = None

    def stop(self) -> None:
        if self._client is None:
            return
        try:
            self._client.loop_stop()
            self._client.disconnect()
        except Exception:
            log.debug("command publisher did not stop cleanly", exc_info=False)
        self._client = None

    @property
    def connected(self) -> bool:
        client = self._client
        if client is None:
            return False
        try:
            return bool(client.is_connected())
        except Exception:
            return False

    def publish(self, command: InjectCommand | CancelCommand) -> bool:
        """Publish at QoS 1. Returns False -- never raises -- when the command
        could not be handed to the broker."""
        client = self._client
        if client is None or not self.connected:
            log.warning("command %s not sent: broker not connected", command.command_id)
            return False
        topic = command_topic(command.device_id)
        try:
            with self._lock:
                info = client.publish(topic, command.model_dump_json(), qos=1)
        except Exception:
            log.exception("command %s publish raised", command.command_id)
            return False
        rc = getattr(info, "rc", 0)
        if rc != 0:
            log.warning("command %s refused by client (rc=%s)", command.command_id, rc)
            return False
        log.info("command %s (%s) published to %s", command.command_id, command.action, topic)
        return True
