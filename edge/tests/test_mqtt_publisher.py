"""C3 unit tests — resilient publisher via a fake MQTT client (no broker)."""

import json

import pytest
from app.schemas.build import build_telemetry

from edge.acquisition.mqtt_publisher import (
    STATUS_OFFLINE,
    STATUS_ONLINE,
    ResilientTelemetryPublisher,
    buffer_capacity,
)

SENSORS = {
    "temperature": 26.0,
    "vibration": 0.03,
    "pressure": 1013.0,
    "humidity": 45.0,
    "gas": 150.0,
    "current": 0.42,
}


def _msg(seq: int):
    return build_telemetry("pump-01", "2026-08-10T12:00:00.000Z", SENSORS, seq)


class FakeClient:
    def __init__(self):
        self.on_connect = None
        self.on_disconnect = None
        self.will = None
        self.published = []  # (topic, payload, qos, retain)
        self.disconnected = False

    def will_set(self, topic, payload, qos=0, retain=False):
        self.will = (topic, payload, qos, retain)

    def publish(self, topic, payload, qos=0, retain=False):
        self.published.append((topic, payload, qos, retain))

    def disconnect(self):
        self.disconnected = True

    # helpers to drive the state machine deterministically
    def fire_connect(self):
        self.on_connect(self, None, None, 0)

    def fire_disconnect(self):
        self.on_disconnect(self, None, 0)


def _pub(rate_hz=1, retention_seconds=60):
    c = FakeClient()
    p = ResilientTelemetryPublisher(
        device_id="pump-01", rate_hz=rate_hz, retention_seconds=retention_seconds, client=c
    )
    return p, c


def _telemetry_payloads(client):
    return [json.loads(pl) for (t, pl, *_) in client.published if t == "shtapm/pump-01/telemetry"]


# ---- capacity ---------------------------------------------------------------


def test_capacity_calculation():
    assert buffer_capacity(1) == 60
    assert buffer_capacity(5) == 300
    assert buffer_capacity(10) == 600
    assert buffer_capacity(1, 2) == 2


def test_rate_out_of_range_rejected():
    for bad in (0.0, 0.5, 10.5, 20):
        with pytest.raises(ValueError):
            ResilientTelemetryPublisher(device_id="pump-01", rate_hz=bad, client=FakeClient())


# ---- LWT / status -----------------------------------------------------------


def test_lwt_offline_configured_on_attach():
    _p, c = _pub()
    assert c.will == ("shtapm/pump-01/status", STATUS_OFFLINE, 1, True)


def test_online_published_retained_on_connect():
    _p, c = _pub()
    c.fire_connect()
    assert ("shtapm/pump-01/status", STATUS_ONLINE, 1, True) in c.published


def test_graceful_stop_publishes_offline_then_disconnects():
    p, c = _pub()
    c.fire_connect()
    p.stop()
    assert ("shtapm/pump-01/status", STATUS_OFFLINE, 1, True) in c.published
    assert c.disconnected is True


# ---- buffering / replay / ordering -----------------------------------------


def test_buffers_while_disconnected():
    p, c = _pub()  # not connected yet
    p.publish(_msg(0))
    p.publish(_msg(1))
    assert _telemetry_payloads(c) == []  # nothing sent live
    assert len(p.buffer) == 2


def test_fifo_replay_in_order_on_reconnect():
    p, c = _pub()
    for i in range(3):
        p.publish(_msg(i))  # buffered (disconnected)
    c.fire_connect()  # drains
    seqs = [m["sample_seq"] for m in _telemetry_payloads(c)]
    assert seqs == [0, 1, 2]
    assert len(p.buffer) == 0


def test_buffered_drain_before_new_live_message():
    p, c = _pub()
    p.publish(_msg(0))
    p.publish(_msg(1))  # buffered
    c.fire_connect()  # drains 0,1
    p.publish(_msg(2))  # live
    assert [m["sample_seq"] for m in _telemetry_payloads(c)] == [0, 1, 2]


def test_live_publish_when_connected_and_empty():
    p, c = _pub()
    c.fire_connect()
    p.publish(_msg(0))
    assert [m["sample_seq"] for m in _telemetry_payloads(c)] == [0]


def test_oldest_dropped_past_retention_window():
    # capacity = ceil(1 * 2) = 2; buffer 3 while disconnected → keep last 2
    p, c = _pub(rate_hz=1, retention_seconds=2)
    for i in range(3):
        p.publish(_msg(i))
    assert len(p.buffer) == 2
    c.fire_connect()
    assert [m["sample_seq"] for m in _telemetry_payloads(c)] == [1, 2]  # 0 overwritten


def test_disconnect_then_reconnect_state_and_replay():
    p, c = _pub()
    c.fire_connect()
    p.publish(_msg(0))  # live
    c.fire_disconnect()
    assert p.is_connected() is False
    p.publish(_msg(1))  # buffered
    p.publish(_msg(2))  # buffered
    c.fire_connect()  # reconnect → drain 1,2
    assert p.is_connected() is True
    assert [m["sample_seq"] for m in _telemetry_payloads(c)] == [0, 1, 2]


def test_telemetry_qos0_status_qos1():
    p, c = _pub()
    c.fire_connect()
    p.publish(_msg(0))
    tel = [(t, qos, retain) for (t, _pl, qos, retain) in c.published if t.endswith("/telemetry")]
    stat = [(t, qos, retain) for (t, _pl, qos, retain) in c.published if t.endswith("/status")]
    assert tel == [("shtapm/pump-01/telemetry", 0, False)]
    assert ("shtapm/pump-01/status", 1, True) in stat


def test_published_telemetry_is_frozen_contract_no_type():
    p, c = _pub()
    c.fire_connect()
    p.publish(_msg(7))
    payload = _telemetry_payloads(c)[0]
    assert "type" not in payload
    assert set(payload.keys()) == {"device_id", "ts", "sensors", "sample_seq"}
