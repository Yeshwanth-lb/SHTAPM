"""Edge listener for backend scenario-injection commands (FR-A4, D032).

Subscribes to ``shtapm/{device_id}/command`` (TRD §02.3, QoS 1) and hands each
valid command to the ``LiveInjector``. Its own MQTT client and thread, fully
independent of the telemetry publisher: a broker or payload problem here can
never delay or stop telemetry.

Invalid payloads are rejected and counted, never applied. A command can only
alter the telemetry stream for a bounded time (``MAX_DURATION_S``); nothing in
this module can reach the relay, the watchdog or any actuation path.

TRUST BOUNDARY. Commands are authorised at the backend (JWT + analyst/admin
role, audited and ledger-chained). The broker itself is unauthenticated on the
bench (Mosquitto auth is an open TODO), so anyone on the same network could
publish to this topic directly. Recorded as a limitation in D032.
"""

from __future__ import annotations

import logging
from typing import Any

from app.schemas.command import CancelCommand, InjectCommand, command_topic, parse_command

from edge.injection.live import LiveInjector

log = logging.getLogger("shtapm.edge.command_listener")


class CommandListener:
    def __init__(self, *, device_id: str, injector: LiveInjector) -> None:
        self.topic = command_topic(device_id)
        self._injector = injector
        self._client: Any | None = None
        self.rejected_count = 0
        self.applied_count = 0

    # ---- paho callbacks (attachable to a fake client in tests) -----------------

    def attach(self, client: Any) -> None:
        self._client = client
        client.on_connect = self._on_connect
        client.on_message = self._on_message

    def _on_connect(self, client: Any, userdata: Any, flags: Any, rc: Any) -> None:
        client.subscribe(self.topic, qos=1)
        log.info("command listener subscribed to %s", self.topic)

    def _on_message(self, client: Any, userdata: Any, msg: Any) -> None:
        self.handle(getattr(msg, "payload", b""))

    # ---- handling (unit-testable without paho) ---------------------------------

    def handle(self, payload: bytes | str) -> bool:
        """Validate and apply one command. Never raises."""
        try:
            command = parse_command(payload)
        except Exception as e:
            self.rejected_count += 1
            # Reason only -- never echo an untrusted payload into the log.
            log.warning("rejected command on %s: %s", self.topic, type(e).__name__)
            return False
        try:
            if isinstance(command, InjectCommand):
                applied = self._injector.submit(command)
            elif isinstance(command, CancelCommand):
                applied = self._injector.cancel(command)
            else:  # unreachable: parse_command returns one of the two
                applied = False
        except Exception:
            log.exception("command %s could not be applied", command.command_id)
            applied = False
        if applied:
            self.applied_count += 1
        else:
            self.rejected_count += 1
        return applied

    # ---- lifecycle (real broker) -----------------------------------------------

    def start(self, host: str, port: int) -> None:
        """Best-effort: a failure leaves injection unavailable, logged once,
        and telemetry unaffected."""
        try:
            import paho.mqtt.client as mqtt

            client = mqtt.Client()
            self.attach(client)
            client.connect_async(host, port)
            client.loop_start()
        except Exception:
            log.warning("command listener failed to start; scenario injection unavailable")
            self._client = None

    def stop(self) -> None:
        if self._client is None:
            return
        try:
            self._client.loop_stop()
            self._client.disconnect()
        except Exception:
            log.debug("command listener did not stop cleanly", exc_info=False)
        self._client = None
