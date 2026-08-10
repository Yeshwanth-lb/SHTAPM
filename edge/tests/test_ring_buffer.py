"""C2 tests — bounded ring buffer (overwrite-oldest)."""

import pytest

from edge.acquisition.ring_buffer import RingBuffer


def test_bounded_and_overwrites_oldest():
    rb: RingBuffer[int] = RingBuffer(3)
    rb.extend([1, 2, 3])
    assert rb.snapshot() == [1, 2, 3] and len(rb) == 3 and rb.is_full()
    rb.append(4)  # overwrites oldest (1)
    assert rb.snapshot() == [2, 3, 4] and len(rb) == 3
    rb.append(5)
    assert rb.snapshot() == [3, 4, 5]


def test_len_never_exceeds_capacity():
    rb: RingBuffer[int] = RingBuffer(2)
    rb.extend(range(100))
    assert len(rb) == 2 and rb.snapshot() == [98, 99]


def test_not_full_until_capacity():
    rb: RingBuffer[int] = RingBuffer(2)
    assert not rb.is_full()
    rb.append(1)
    assert not rb.is_full()
    rb.append(2)
    assert rb.is_full()


def test_clear():
    rb: RingBuffer[int] = RingBuffer(3)
    rb.extend([1, 2])
    rb.clear()
    assert len(rb) == 0 and rb.snapshot() == []


def test_capacity_must_be_positive():
    with pytest.raises(ValueError):
        RingBuffer(0)
