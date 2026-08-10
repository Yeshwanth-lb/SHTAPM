"""C4 tests — relay safe-state machine (fake actuator, no hardware)."""

import pytest

from edge.actuation.relay import Actuator, FakeActuator, RelayController, RelayState


def test_fake_actuator_starts_off():
    a = FakeActuator()
    assert a.get_state() is RelayState.OFF
    assert a.history == [RelayState.OFF]


def test_controller_enforces_off_at_startup():
    a = FakeActuator()
    c = RelayController(a)
    assert c.state is RelayState.OFF and c.is_on() is False


def test_on_sets_on():
    c = RelayController(FakeActuator())
    c.on()
    assert c.state is RelayState.ON and c.is_on() is True


def test_off_sets_off():
    c = RelayController(FakeActuator())
    c.on()
    c.off()
    assert c.state is RelayState.OFF


def test_safe_off_forces_off_from_on():
    c = RelayController(FakeActuator())
    c.on()
    c.safe_off()
    assert c.state is RelayState.OFF


def test_safe_off_idempotent():
    a = FakeActuator()
    c = RelayController(a)
    c.safe_off()
    c.safe_off()
    assert c.state is RelayState.OFF


def test_repeated_transitions():
    a = FakeActuator()
    c = RelayController(a)
    c.on()
    c.off()
    c.on()
    c.off()
    assert c.state is RelayState.OFF
    # history: startup OFF, controller-init OFF, then on/off/on/off
    assert a.history[-4:] == [RelayState.ON, RelayState.OFF, RelayState.ON, RelayState.OFF]


def test_fake_actuator_rejects_non_enum_state():
    with pytest.raises(TypeError):
        FakeActuator().set_state("on")  # type: ignore[arg-type]


def test_actuator_is_abstract():
    with pytest.raises(TypeError):
        Actuator()  # type: ignore[abstract]
