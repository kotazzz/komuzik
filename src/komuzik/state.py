"""Bounded, self-expiring in-memory state for bot sessions.

Every short-lived thing the bot remembers between updates — inline jobs, search
sessions, callback URLs, pending admin input — used to live in a bare module
level ``dict`` that was only ever cleaned when the user completed the flow.
Abandoned flows are the common case (inline search creates an entry per
keystroke and the user picks at most one result), so those dicts grew without
bound for the whole uptime of the process.

``TTLCache`` bounds both dimensions: entries expire after ``ttl`` seconds and the
oldest are evicted once ``maxsize`` is reached.

Access is expected from the asyncio event loop thread only; there is no locking,
matching how the rest of the bot touches shared state.
"""

from __future__ import annotations

import logging
import time
from collections import OrderedDict
from collections.abc import Callable, Iterator, MutableMapping
from typing import TypeVar

logger = logging.getLogger(__name__)

K = TypeVar("K")
V = TypeVar("V")

_MISSING = object()


class TTLCache(MutableMapping[K, V]):
    """Mapping whose entries expire and whose size is capped.

    Args:
        maxsize: Hard cap on live entries; the oldest entry is evicted on insert.
        ttl: Lifetime in seconds.
        sliding: When True (default) a successful read refreshes the deadline, so
            a session stays alive while the user is still interacting with it.
        timer: Monotonic clock, injectable for tests.
        name: Used in eviction log messages.

    """

    def __init__(
        self,
        *,
        maxsize: int,
        ttl: float,
        sliding: bool = True,
        timer: Callable[[], float] = time.monotonic,
        name: str = "cache",
    ) -> None:
        if maxsize < 1:
            raise ValueError("maxsize must be >= 1")
        if ttl <= 0:
            raise ValueError("ttl must be > 0")
        self.maxsize = maxsize
        self.ttl = ttl
        self.sliding = sliding
        self._timer = timer
        self._name = name
        self._data: OrderedDict[K, tuple[float, V]] = OrderedDict()
        self.evictions = 0

    # --- internals ---

    def _purge_expired(self) -> None:
        """Drop expired entries from the front (they are in deadline order)."""
        now = self._timer()
        while self._data:
            key, (deadline, _) = next(iter(self._data.items()))
            if deadline > now:
                break
            del self._data[key]

    def _evict_oldest(self) -> None:
        key, _ = self._data.popitem(last=False)
        self.evictions += 1
        logger.debug("%s: evicted %r to stay within maxsize=%d", self._name, key, self.maxsize)

    # --- MutableMapping ---

    def __setitem__(self, key: K, value: V) -> None:
        self._purge_expired()
        self._data.pop(key, None)
        self._data[key] = (self._timer() + self.ttl, value)
        while len(self._data) > self.maxsize:
            self._evict_oldest()

    def __getitem__(self, key: K) -> V:
        entry = self._data.get(key)
        if entry is None:
            raise KeyError(key)
        deadline, value = entry
        if deadline <= self._timer():
            del self._data[key]
            raise KeyError(key)
        if self.sliding:
            # Re-insert at the tail so deadline order (used by _purge_expired) holds.
            del self._data[key]
            self._data[key] = (self._timer() + self.ttl, value)
        return value

    def __delitem__(self, key: K) -> None:
        del self._data[key]

    def __iter__(self) -> Iterator[K]:
        self._purge_expired()
        return iter(list(self._data.keys()))

    def __len__(self) -> int:
        self._purge_expired()
        return len(self._data)

    def __contains__(self, key: object) -> bool:
        try:
            self[key]  # type: ignore[index]
        except KeyError:
            return False
        return True

    def get(self, key, default=None):
        try:
            return self[key]
        except KeyError:
            return default

    def pop(self, key, default=_MISSING):
        try:
            value = self[key]
        except KeyError:
            if default is _MISSING:
                raise KeyError(key) from None
            return default
        del self._data[key]
        return value

    def clear(self) -> None:
        self._data.clear()
