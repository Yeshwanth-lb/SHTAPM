"""Broker restart mid-demo (AC10 P7-10): every backend consumer re-subscribes on
reconnect and keeps ingesting.

paho's network loop (``loop_start`` after ``connect_async``) reconnects by
itself and calls ``on_connect`` again; a consumer that subscribed only once at
start-up would silently go deaf after the broker restarts. Each consumer here
subscribes inside ``on_connect``, so a reconnect restores its subscription."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from app.mqtt.actuation_consumer import ActuationConsumer
from app.mqtt.consumer import TelemetryConsumer
from app.mqtt.decision_diagnostic_consumer import DecisionDiagnosticConsumer
from app.mqtt.status_consumer import StatusConsumer
from app.services.telemetry_store import TelemetryStore


class FakeClient:
    def __init__(self) -> None:
        self.subscriptions: list[str] = []

    def subscribe(self, topic, qos=0):
        self.subscriptions.append(topic)


def _consumers():
    return [
        ("telemetry", TelemetryConsumer(TelemetryStore()), "shtapm/+/telemetry"),
        ("decision_diagnostic", DecisionDiagnosticConsumer(), "shtapm/+/decision_diagnostic"),
        ("status", StatusConsumer(), "shtapm/+/status"),
        ("actuation", ActuationConsumer(), "shtapm/+/actuation"),
    ]


@pytest.mark.parametrize("name, consumer, subscription", _consumers())
def test_reconnect_restores_the_subscription(name, consumer, subscription):
    client = FakeClient()
    consumer.attach(client)
    client.on_connect(client, None, {}, 0)  # first connect
    client.on_connect(client, None, {}, 0)  # broker restarted: paho reconnects
    assert client.subscriptions == [subscription, subscription]


def test_ingestion_continues_after_a_reconnect():
    received = []
    consumer = StatusConsumer()
    consumer.add_sink(lambda device_id, status: received.append((device_id, status)))
    client = FakeClient()
    consumer.attach(client)
    client.on_connect(client, None, {}, 0)
    online = SimpleNamespace(topic="shtapm/pump-01/status", payload=b"online")
    client.on_message(client, None, online)
    client.on_connect(client, None, {}, 0)  # reconnect
    client.on_message(
        client, None, SimpleNamespace(topic="shtapm/pump-01/status", payload=b"offline")
    )
    assert received == [("pump-01", "online"), ("pump-01", "offline")]


def test_actuation_status_survives_a_reconnect():
    statuses = []
    consumer = ActuationConsumer()
    consumer.add_sink(statuses.append)
    client = FakeClient()
    consumer.attach(client)
    payload = {
        "device_id": "pump-01",
        "ts": "2026-10-27T10:00:00.000Z",
        "relay": "off",
        "cause": "startup",
        "reason": "edge started",
        "latched": False,
        "hardware": False,
    }
    client.on_connect(client, None, {}, 0)
    client.on_connect(client, None, {}, 0)
    client.on_message(
        client, None, SimpleNamespace(topic="shtapm/pump-01/actuation", payload=json.dumps(payload))
    )
    assert [s.cause for s in statuses] == ["startup"]
