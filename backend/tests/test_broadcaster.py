"""M3.4 unit tests — TelemetryBroadcaster (asyncio, no broker, no pytest-asyncio)."""

import asyncio

from app.schemas.contracts import SensorReadings, TelemetryMessage
from app.ws.broadcaster import TelemetryBroadcaster
from app.ws.frames import telemetry_frame


def _msg(device_id: str = "pump-01") -> TelemetryMessage:
    return TelemetryMessage(
        device_id=device_id,
        ts="2026-08-09T12:00:00.000Z",
        sensors=SensorReadings(
            temperature=26.0, vibration=0.03, pressure=1013.0,
            humidity=45.0, gas=150.0, current=0.42,
        ),
        sample_seq=0,
    )


def test_deliver_reaches_subscriber():
    async def run():
        b = TelemetryBroadcaster(asyncio.get_running_loop())
        q = await b.subscribe()
        assert b.client_count == 1
        b._deliver(telemetry_frame(_msg()))
        return await asyncio.wait_for(q.get(), 1)

    frame = asyncio.run(run())
    assert frame["type"] == "telemetry"


def test_publish_from_thread_delivers():
    async def run():
        b = TelemetryBroadcaster(asyncio.get_running_loop())
        q = await b.subscribe()
        b.publish_from_thread(_msg("pump-02"))  # schedules on the loop
        return await asyncio.wait_for(q.get(), 1)

    frame = asyncio.run(run())
    assert frame["device_id"] == "pump-02"


def test_unsubscribe_removes_client():
    async def run():
        b = TelemetryBroadcaster(asyncio.get_running_loop())
        q = await b.subscribe()
        b.unsubscribe(q)
        return b.client_count

    assert asyncio.run(run()) == 0


def test_full_queue_drops_without_error():
    async def run():
        b = TelemetryBroadcaster(asyncio.get_running_loop(), queue_maxsize=1)
        q = await b.subscribe()
        b._deliver(telemetry_frame(_msg()))
        b._deliver(telemetry_frame(_msg()))  # dropped (queue full)
        return q.qsize()

    assert asyncio.run(run()) == 1
