"""Latest-only fan-out from capture threads to asyncio WebSocket senders.

Each subscriber holds at most one pending message per key. A slow client therefore
skips frames instead of building a backlog.
"""

from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class StoredFrame:
    payload: bytes  # header + JPEG, ready to send
    jpeg: bytes
    seq: int
    capture_ts_ms: int
    width: int
    height: int


class Subscriber:
    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop
        self._lock = threading.Lock()
        self._pending: dict[str, bytes | str] = {}
        self._event = asyncio.Event()
        self._closed = False
        self.replaced = 0

    def offer(self, payload: bytes | str, key: str = "frame") -> None:
        """Store the newest message for this key. Safe to call from any thread."""
        with self._lock:
            if self._closed:
                return
            if key in self._pending:
                self.replaced += 1
            self._pending[key] = payload
        self._wake()

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._pending.clear()
        self._wake()

    def _wake(self) -> None:
        try:
            self._loop.call_soon_threadsafe(self._event.set)
        except RuntimeError:
            pass  # The event loop has already shut down.

    async def next(self) -> bytes | str | None:
        """Wait for the next message. Returns None once the subscriber is closed."""
        while True:
            with self._lock:
                if self._closed:
                    return None
                if self._pending:
                    key = next(iter(self._pending))
                    return self._pending.pop(key)
                self._event.clear()
            await self._event.wait()


class FrameBus:
    def __init__(self, feed_ids: list[str]) -> None:
        self._lock = threading.Lock()
        self._latest: dict[str, StoredFrame | None] = {feed_id: None for feed_id in feed_ids}
        self._subscribers: dict[str, set[Subscriber]] = {feed_id: set() for feed_id in feed_ids}

    def __contains__(self, feed_id: str) -> bool:
        return feed_id in self._latest

    def publish(self, feed_id: str, frame: StoredFrame) -> None:
        with self._lock:
            self._latest[feed_id] = frame
            subscribers = list(self._subscribers[feed_id])
        for subscriber in subscribers:
            subscriber.offer(frame.payload)

    def latest(self, feed_id: str) -> StoredFrame | None:
        with self._lock:
            return self._latest[feed_id]

    def subscribe(self, feed_id: str, loop: asyncio.AbstractEventLoop) -> Subscriber:
        # The stored frame is not replayed: the browser times health from frame arrival,
        # so a stale frame would make a lost feed look live.
        subscriber = Subscriber(loop)
        with self._lock:
            self._subscribers[feed_id].add(subscriber)
        return subscriber

    def unsubscribe(self, feed_id: str, subscriber: Subscriber) -> None:
        with self._lock:
            self._subscribers[feed_id].discard(subscriber)
        subscriber.close()
