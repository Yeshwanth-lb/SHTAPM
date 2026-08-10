"""C4 tests — deadman watchdog (injected clock, no real waiting)."""

import pytest

from edge.actuation.relay import FakeActuator, RelayController, RelayState
from edge.actuation.watchdog import Watchdog


class ManualClock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


def _wire(timeout_s=5.0):
    clock = ManualClock()
    controller = RelayController(FakeActuator())
    fired = {"n": 0}

    def on_expire():
        fired["n"] += 1
        controller.safe_off()

    wd = Watchdog(timeout_s=timeout_s, on_expire=on_expire, clock=clock)
    return clock, controller, wd, fired


def test_timeout_must_be_positive():
    for bad in (0.0, -1.0):
        with pytest.raises(ValueError):
            Watchdog(timeout_s=bad, on_expire=lambda: None)


def test_kick_before_timeout_keeps_on():
    clock, c, wd, fired = _wire(timeout_s=5.0)
    c.on()
    clock.advance(3.0)
    wd.kick()
    clock.advance(3.0)  # 3s since last kick < 5s timeout
    assert wd.check() is False
    assert c.state is RelayState.ON and fired["n"] == 0


def test_expiry_forces_off():
    clock, c, wd, fired = _wire(timeout_s=5.0)
    c.on()
    clock.advance(6.0)  # no kick, past timeout
    assert wd.check() is True
    assert c.state is RelayState.OFF and fired["n"] == 1


def test_deadman_process_failure_forces_off():
    # "process died" == kick() stops being called; the next check drives OFF
    clock, c, wd, _f = _wire(timeout_s=2.0)
    c.on()
    for _ in range(3):
        clock.advance(1.0)  # 3s elapsed, never kicked
    assert wd.check() is True and c.state is RelayState.OFF


def test_check_idempotent_fires_once():
    clock, c, wd, fired = _wire(timeout_s=5.0)
    c.on()
    clock.advance(6.0)
    assert wd.check() is True
    clock.advance(10.0)
    assert wd.check() is True  # still expired
    assert fired["n"] == 1  # on_expire fired only once


def test_kick_after_expiry_is_noop():
    clock, c, wd, _f = _wire(timeout_s=5.0)
    c.on()
    clock.advance(6.0)
    wd.check()  # expired → OFF
    wd.kick()  # must NOT revive a tripped safety timer
    assert wd.expired is True and c.state is RelayState.OFF


def test_reset_recovers_then_can_run_again():
    clock, c, wd, fired = _wire(timeout_s=5.0)
    c.on()
    clock.advance(6.0)
    wd.check()  # expired → OFF
    assert c.state is RelayState.OFF

    wd.reset()  # explicit recovery, re-arm from now
    assert wd.expired is False
    c.on()  # operator re-enables explicitly
    clock.advance(3.0)
    wd.kick()
    clock.advance(3.0)
    assert wd.check() is False  # stays alive in the new window
    assert c.state is RelayState.ON and fired["n"] == 1  # still only the first expiry


def test_boundary_not_expired_at_exactly_timeout():
    clock, c, wd, _f = _wire(timeout_s=5.0)
    c.on()
    clock.advance(5.0)  # exactly timeout → not > timeout
    assert wd.check() is False and c.state is RelayState.ON
    clock.advance(0.001)  # just past
    assert wd.check() is True and c.state is RelayState.OFF
