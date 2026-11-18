"""Feed health: picture analysis, the tile state machine and the shared status store.

TileMachine must behave exactly like web/js/tileState.js. Both are checked against
tests/vectors/tile_states.json.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Callable, NamedTuple

import numpy as np

from .config import HealthConfig
from .protocol import FrameMsg, MeterMsg

log = logging.getLogger("mvbridge.health")

CONNECTING = "CONNECTING"
LIVE = "LIVE"
LIVE_STILL = "LIVE_STILL"
LIVE_BLACK = "LIVE_BLACK"
LATE = "LATE"
NO_SIGNAL = "NO_SIGNAL"
RESTORED = "RESTORED"
PAUSED = "PAUSED"
SERVER_OFFLINE = "SERVER_OFFLINE"

_THUMB_W = 64
_THUMB_H = 36


class PictureFlags(NamedTuple):
    static: bool
    black: bool
    static_s: float


class PictureAnalyzer:
    """Detects a frozen or black picture from a small luma thumbnail."""

    def __init__(self, cfg: HealthConfig, clock: Callable[[], float] = time.monotonic) -> None:
        self._cfg = cfg
        self._clock = clock
        self._reference: np.ndarray | None = None
        self._still_since = 0.0
        self._black_since: float | None = None

    def reset(self) -> None:
        self._reference = None
        self._black_since = None

    def update(self, rgb: np.ndarray) -> PictureFlags:
        now = self._clock()
        height, width = rgb.shape[:2]
        thumb = rgb[:: max(1, height // _THUMB_H), :: max(1, width // _THUMB_W), :3]
        thumb = thumb[:_THUMB_H, :_THUMB_W].astype(np.float32)
        luma = 0.299 * thumb[..., 0] + 0.587 * thumb[..., 1] + 0.114 * thumb[..., 2]

        # Compare against the last picture that counted as different, so a very slow
        # fade still registers as motion once it has moved far enough.
        if self._reference is None or self._reference.shape != luma.shape:
            self._reference = luma
            self._still_since = now
        elif float(np.abs(luma - self._reference).mean()) >= self._cfg.static_mad_threshold:
            self._reference = luma
            self._still_since = now

        if float(luma.mean()) < self._cfg.black_luma_threshold:
            if self._black_since is None:
                self._black_since = now
        else:
            self._black_since = None

        still_for = now - self._still_since
        static = still_for >= self._cfg.static_after_s
        black = self._black_since is not None and now - self._black_since >= self._cfg.black_after_s
        return PictureFlags(static, black, still_for if static else 0.0)


class TileMachine:
    """Computes what a tile shows. All times are milliseconds on one clock."""

    def __init__(self, cfg: HealthConfig, now_ms: float) -> None:
        self._late = cfg.late_ms
        self._lost = cfg.lost_ms
        self._flash = cfg.restored_flash_ms
        self._base = now_ms
        self._last_frame: float | None = None
        self._was_lost = False
        self._was_paused = False
        self._restored_until: float | None = None
        self.lost_since: float | None = None
        self.state = CONNECTING

    def on_open(self, now_ms: float) -> None:
        """A new connection started and no frame has arrived on it yet."""
        if self._last_frame is None:
            self._base = now_ms

    def on_frame(self, now_ms: float) -> None:
        self._last_frame = now_ms

    def age_ms(self, now_ms: float) -> float | None:
        return None if self._last_frame is None else now_ms - self._last_frame

    def _mark_lost(self, now_ms: float) -> None:
        self._was_lost = True
        if self.lost_since is None:
            self.lost_since = self._last_frame if self._last_frame is not None else self._base

    def update(
        self,
        now_ms: float,
        source_state: str = "connecting",
        static: bool = False,
        black: bool = False,
        paused: bool = False,
        offline: bool = False,
    ) -> str:
        self.state = self._evaluate(now_ms, source_state, static, black, paused, offline)
        return self.state

    def _evaluate(self, now, source_state, static, black, paused, offline) -> str:
        if offline:
            self._mark_lost(now)
            return SERVER_OFFLINE
        if paused:
            self._was_paused = True
            return PAUSED
        if self._was_paused:
            # Frames from before the pause say nothing about the feed now.
            self._was_paused = False
            self._last_frame = None
            self._base = now
            self._was_lost = False
            self._restored_until = None
            self.lost_since = None

        source_lost = source_state in ("disconnected", "error")
        if self._last_frame is None:
            if source_lost or now - self._base >= self._lost:
                self._mark_lost(now)
                return NO_SIGNAL
            return CONNECTING

        age = now - self._last_frame
        if source_lost or age >= self._lost:
            self._mark_lost(now)
            return NO_SIGNAL
        if age >= self._late or source_state == "stalled":
            return LATE

        if self._was_lost:
            self._was_lost = False
            self.lost_since = None
            self._restored_until = now + self._flash
        if self._restored_until is not None:
            if now < self._restored_until:
                return RESTORED
            self._restored_until = None
        if black:
            return LIVE_BLACK
        if static:
            return LIVE_STILL
        return LIVE


class FpsMeter:
    """Frames per second over a sliding one-second window."""

    def __init__(self, window_s: float = 1.0) -> None:
        self._window = window_s
        self._times: deque[float] = deque()

    def tick(self, now: float) -> None:
        self._times.append(now)
        self._trim(now)

    def _trim(self, now: float) -> None:
        while self._times and now - self._times[0] > self._window:
            self._times.popleft()

    def value(self, now: float) -> float:
        self._trim(now)
        return len(self._times) / self._window


@dataclass(slots=True)
class FeedStatus:
    source_state: str = "connecting"
    detail: str = ""
    last_capture_ms: int = 0
    width: int = 0
    height: int = 0
    static: bool = False
    black: bool = False
    static_s: float = 0.0
    reconnects: int = 0
    ever_connected: bool = False


class StatusStore:
    """Thread-safe view of every feed and meter. Logs each state transition."""

    def __init__(
        self,
        health_by_feed: dict[str, HealthConfig],
        wall_ms: Callable[[], int] = lambda: time.time_ns() // 1_000_000,
    ) -> None:
        self._lock = threading.Lock()
        self._wall_ms = wall_ms
        now = wall_ms()
        self._feeds = {feed_id: FeedStatus() for feed_id in health_by_feed}
        self._machines = {fid: TileMachine(cfg, now) for fid, cfg in health_by_feed.items()}
        self._fps = {feed_id: FpsMeter() for feed_id in health_by_feed}
        self._tile_states = {feed_id: CONNECTING for feed_id in health_by_feed}
        self._meters: dict[str, dict] = {}
        self.paused = False

    def on_frame(self, feed_id: str, frame: FrameMsg) -> None:
        now = self._wall_ms()
        with self._lock:
            status = self._feeds[feed_id]
            status.last_capture_ms = frame.capture_ts_ns // 1_000_000
            status.width = frame.width
            status.height = frame.height
            status.static = frame.static
            status.black = frame.black
            status.static_s = frame.static_s
            self._machines[feed_id].on_frame(now)
            self._fps[feed_id].tick(now / 1000)

    def on_state(self, feed_id: str, state: str, detail: str = "") -> None:
        with self._lock:
            status = self._feeds[feed_id]
            if status.source_state == state and status.detail == detail:
                return
            previous = status.source_state
            status.source_state = state
            status.detail = detail
            if state == "connected":
                if status.ever_connected and previous != "paused":
                    status.reconnects += 1
                status.ever_connected = True
        if previous != state:
            log.info("SOURCE feed=%s from=%s to=%s reason=%s", feed_id, previous, state, detail or "-")

    def on_meter(self, meter: MeterMsg) -> None:
        with self._lock:
            self._meters[meter.key] = {
                "state": meter.state,
                "peak_db": round(meter.peak_db, 1),
                "rms_db": round(meter.rms_db, 1),
                "hold_db": round(meter.hold_db, 1),
            }

    def tick(self) -> None:
        """Advance the server's view of each tile and log any change."""
        now = self._wall_ms()
        changes = []
        with self._lock:
            for feed_id, machine in self._machines.items():
                status = self._feeds[feed_id]
                state = machine.update(
                    now, status.source_state, status.static, status.black, self.paused
                )
                previous = self._tile_states[feed_id]
                if state != previous:
                    self._tile_states[feed_id] = state
                    age = machine.age_ms(now)
                    reason = status.detail or status.source_state
                    changes.append((feed_id, previous, state, reason, age))
        for feed_id, previous, state, reason, age in changes:
            age_text = "-" if age is None else f"{age:.0f}"
            log.info(
                "TILE feed=%s from=%s to=%s reason=%s age_ms=%s",
                feed_id, previous, state, reason, age_text,
            )

    def feeds_snapshot(self) -> dict[str, dict]:
        now = self._wall_ms()
        with self._lock:
            return {
                feed_id: {
                    "source_state": status.source_state,
                    "tile_state": self._tile_states[feed_id],
                    "fps": round(self._fps[feed_id].value(now / 1000), 1),
                    "last_capture_ms": status.last_capture_ms,
                    "w": status.width,
                    "h": status.height,
                    "static": status.static,
                    "black": status.black,
                    "static_s": round(status.static_s, 1),
                    "reconnects": status.reconnects,
                    "detail": status.detail,
                }
                for feed_id, status in self._feeds.items()
            }

    def meters_snapshot(self) -> dict[str, dict]:
        with self._lock:
            return {key: dict(value) for key, value in self._meters.items()}
