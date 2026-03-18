from __future__ import annotations
import threading
from typing import TypeVar, Optional, Generic

T = TypeVar("T")


class Slot(Generic[T]):

    def __init__(self, name: str = "slot"):
        self._name = name
        self._data: Optional[T] = None
        self._lock = threading.Lock()
        self._ready = threading.Event()
        self._write_count = 0
        self._read_count = 0

    def put(self, item: T) -> None:
        with self._lock:
            self._data = item
            self._write_count += 1
        self._ready.set()

    def get(self) -> Optional[T]:
        with self._lock:
            item = self._data
            if item is not None:
                self._read_count += 1
            return item

    def take(self) -> Optional[T]:
        with self._lock:
            item = self._data
            self._data = None
            if item is not None:
                self._read_count += 1
            return item

    def wait(self, timeout: float = 10.0) -> bool:
        return self._ready.wait(timeout)

    def clear(self) -> None:
        with self._lock:
            self._data = None

    @property
    def has_data(self) -> bool:
        with self._lock:
            return self._data is not None

    @property
    def writes(self) -> int:
        return self._write_count

    @property
    def reads(self) -> int:
        return self._read_count

    @property
    def drops(self) -> int:
        return max(0, self._write_count - self._read_count)

    def __repr__(self) -> str:
        return (f"Slot({self._name}: "
                f"w={self._write_count} r={self._read_count} "
                f"d={self.drops})")