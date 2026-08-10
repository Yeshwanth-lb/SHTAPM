"""Bounded acquisition ring buffer (P1 · C2) — overwrite-oldest.

Local, in-memory, bounded. When full, appending overwrites the OLDEST item
(FIFO drop). This is C2's decoupling/backpressure buffer only.

NOT the FR-Q4 >=60 s broker-disconnect no-loss resume buffer — overwrite-oldest
loses data past capacity, so it deliberately does NOT satisfy FR-Q4. That
no-loss buffered-resume behavior belongs to C3 (publisher).
"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable
from typing import Generic, TypeVar

T = TypeVar("T")


class RingBuffer(Generic[T]):
    def __init__(self, capacity: int) -> None:
        if capacity < 1:
            raise ValueError("capacity must be >= 1")
        self._capacity = capacity
        self._items: deque[T] = deque(maxlen=capacity)  # maxlen → overwrite-oldest

    @property
    def capacity(self) -> int:
        return self._capacity

    def append(self, item: T) -> None:
        self._items.append(item)  # drops the oldest automatically when full

    def snapshot(self) -> list[T]:
        """Current contents, oldest → newest."""
        return list(self._items)

    def is_full(self) -> bool:
        return len(self._items) == self._capacity

    def clear(self) -> None:
        self._items.clear()

    def extend(self, items: Iterable[T]) -> None:
        for item in items:
            self.append(item)

    def __len__(self) -> int:
        return len(self._items)
