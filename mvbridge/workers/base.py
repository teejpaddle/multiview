"""Common worker behaviour: run loop, pacing, encoding and the link to the supervisor.

Each worker runs in its own process, so a crash in one feed cannot affect the others.
"""

from __future__ import annotations

import logging
import multiprocessing
import queue
import re
import signal
import sys
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Callable, Optional

import numpy as np
import simplejpeg

from ..config import AudioShowConfig, FeedConfig, HealthConfig, PerfLevel
from ..health import PictureAnalyzer
from ..priority import set_below_normal
from ..protocol import FrameMsg, HeartbeatMsg, LogMsg, MeterMsg, StateMsg

_URL_CREDENTIALS = re.compile(r"(\w+://)[^/@\s]+@")


def redact(text: str) -> str:
    """Remove any user:password from a URL before it reaches a log or the browser."""
    return _URL_CREDENTIALS.sub(r"\1***@", text)


@dataclass(frozen=True)
class WorkerSpec:
    worker_id: str
    kind: str  # synthetic | rtsp | spout | wasapi_loopback | synthetic_audio
    health: HealthConfig
    levels: tuple[PerfLevel, ...]
    feed: Optional[FeedConfig] = None
    audio: Optional[AudioShowConfig] = None
    level: int = 0
    paused: bool = False


class Throttle:
    """Limits output to a target rate while tolerating normal arrival jitter."""

    def __init__(self, fps: float) -> None:
        self._period = 1.0 / fps
        self._next = 0.0

    def set_fps(self, fps: float) -> None:
        self._period = 1.0 / fps

    def wait_time(self, now: float) -> float:
        return max(0.0, self._next - now)

    def ready(self, now: float) -> bool:
        if now < self._next - self._period / 2:
            return False
        self._next = max(self._next + self._period, now)
        return True


class Backoff:
    """Reconnect delay that doubles from the first interval up to the maximum."""

    def __init__(self, first_s: float, max_s: float) -> None:
        self._first = first_s
        self._max = max_s
        self._current = first_s

    def next_delay(self) -> float:
        delay = self._current
        self._current = min(self._current * 2, self._max)
        return delay

    def reset(self) -> None:
        self._current = self._first


def even_size(width: float, height: float) -> tuple[int, int]:
    return max(2, int(width) & ~1), max(2, int(height) & ~1)


def resize_area(rgb: np.ndarray, width: int, height: int) -> np.ndarray:
    import av

    frame = av.VideoFrame.from_ndarray(rgb, format="rgb24")
    return frame.reformat(width=width, height=height, interpolation="AREA").to_ndarray()


class Channel:
    """The worker's end of its queues and control pipe."""

    def __init__(self, frames, events, control) -> None:
        self._frames = frames
        self._events = events
        self.control = control

    def send_frame(self, frame: FrameMsg) -> None:
        self._put_latest(self._frames, frame)

    def send_event(self, event) -> None:
        self._put_latest(self._events, event)

    @staticmethod
    def _put_latest(target, item) -> None:
        try:
            target.put_nowait(item)
            return
        except queue.Full:
            pass
        try:
            target.get_nowait()
            target.put_nowait(item)
        except (queue.Empty, queue.Full):
            pass  # The supervisor is mid-read. Skipping one item is harmless.

    def close(self) -> None:
        for target in (self._frames, self._events):
            target.cancel_join_thread()


class Worker(ABC):
    def __init__(self, spec: WorkerSpec, channel: Channel) -> None:
        self.spec = spec
        self.channel = channel
        self.health = spec.health
        self.paused = spec.paused
        self.stopping = False
        self.state = "connecting"
        self.detail = ""
        self._level_index = spec.level
        self._seq = 0
        self._last_heartbeat = 0.0
        self._analyzer = PictureAnalyzer(spec.health)
        self.throttle = Throttle(self.target_fps())

    # ----- Subclass interface -----

    @abstractmethod
    def step(self) -> None:
        """Do one short unit of work. Must return within the source's timeouts."""

    def release(self) -> None:
        """Let go of the source. Called on pause and at shutdown."""

    def on_level_changed(self) -> None:
        """The preview size or rate changed."""

    # ----- Preview parameters -----

    @property
    def level(self) -> PerfLevel:
        return self.spec.levels[min(self._level_index, len(self.spec.levels) - 1)]

    def target_fps(self) -> int:
        preview = self.spec.feed.preview if self.spec.feed else None
        return min(preview.fps, self.level.fps) if preview else self.level.fps

    def target_size(self) -> tuple[int, int]:
        preview = self.spec.feed.preview
        if self.level.scale >= 1.0:
            return preview.width, preview.height
        return even_size(preview.width * self.level.scale, preview.height * self.level.scale)

    def target_quality(self) -> int:
        return min(self.spec.feed.preview.jpeg_quality, self.level.q)

    # ----- Output -----

    def set_state(self, state: str, detail: str = "") -> None:
        detail = redact(detail)
        if state != self.state or detail != self.detail:
            self.state = state
            self.detail = detail
            self.channel.send_event(StateMsg(state, detail))

    def log(self, level: int, message: str) -> None:
        self.channel.send_event(LogMsg(level, redact(message)))

    def emit_meter(self, meter: MeterMsg) -> None:
        self.channel.send_event(meter)

    def publish(self, rgb: np.ndarray, capture_ts_ns: int) -> None:
        """Analyze, scale and encode one picture and hand it to the supervisor."""
        width, height = self.target_size()
        if rgb.shape[1] != width or rgb.shape[0] != height:
            rgb = resize_area(rgb, width, height)
        rgb = np.ascontiguousarray(rgb)  # The encoder rejects views such as RGBA without alpha.
        flags = self._analyzer.update(rgb)
        jpeg = simplejpeg.encode_jpeg(
            rgb,
            quality=self.target_quality(),
            colorspace="RGB",
            colorsubsampling="420",
            fastdct=True,
        )
        self._seq += 1
        self.channel.send_frame(
            FrameMsg(self._seq, capture_ts_ns, width, height, jpeg, *flags)
        )

    # ----- Run loop -----

    def run_forever(self) -> None:
        self.channel.send_event(StateMsg(self.state, self.detail))
        was_paused = False
        try:
            while not self.stopping:
                self.pump(0.0)
                if self.stopping:
                    break
                if self.paused:
                    if not was_paused:
                        self.release()
                        self._analyzer.reset()
                        self.set_state("paused")
                        was_paused = True
                    self.pump(0.2)
                    continue
                if was_paused:
                    was_paused = False
                    self.set_state("connecting")
                self.step()
        finally:
            self.release()

    def idle(self, seconds: float) -> None:
        """Wait without missing a control message."""
        deadline = time.monotonic() + seconds
        while not self.stopping:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            was_paused = self.paused
            self.pump(min(remaining, 0.25))
            if self.paused != was_paused:
                return

    def pump(self, timeout: float) -> None:
        """Handle control messages and send the heartbeat."""
        try:
            while self.channel.control.poll(timeout):
                timeout = 0.0
                self._handle(self.channel.control.recv())
        except (EOFError, OSError):
            self.stopping = True  # The bridge has gone away.
            return
        now = time.monotonic()
        if now - self._last_heartbeat >= 1.0:
            self._last_heartbeat = now
            parent = multiprocessing.parent_process()
            if parent is not None and not parent.is_alive():
                self.stopping = True
                return
            self.channel.send_event(HeartbeatMsg(self.state, self.detail))

    def _handle(self, message: tuple) -> None:
        command = message[0]
        if command == "stop":
            self.stopping = True
        elif command == "pause":
            self.paused = bool(message[1])
        elif command == "level":
            self._level_index = int(message[1])
            self.throttle.set_fps(self.target_fps())
            self.on_level_changed()


def _create_worker(spec: WorkerSpec, channel: Channel) -> Worker:
    # Imported here so each process loads only the libraries its source needs.
    if spec.kind == "synthetic":
        from .synthetic import SyntheticWorker as worker_class
    elif spec.kind == "synthetic_audio":
        from .synthetic import SyntheticAudioWorker as worker_class
    elif spec.kind == "rtsp":
        from .rtsp import RtspWorker as worker_class
    elif spec.kind == "spout":
        from .spout import SpoutWorker as worker_class
    elif spec.kind == "wasapi_loopback":
        from ..audio.wasapi_loopback import WasapiLoopbackWorker as worker_class
    else:
        raise ValueError(f"unknown worker kind '{spec.kind}'")
    return worker_class(spec, channel)


def worker_main(spec: WorkerSpec, frames, events, control) -> None:
    """Entry point of each worker process."""
    signal.signal(signal.SIGINT, signal.SIG_IGN)  # The bridge coordinates shutdown.
    set_below_normal()
    channel = Channel(frames, events, control)
    exit_code = 0
    try:
        _create_worker(spec, channel).run_forever()
    except Exception as exc:
        exit_code = 1
        channel.send_event(StateMsg("error", redact(f"{type(exc).__name__}: {exc}")))
        channel.send_event(LogMsg(logging.ERROR, redact(f"worker {spec.worker_id} failed: {exc!r}")))
        time.sleep(0.2)  # Give the queue's feeder thread time to deliver the error.
    finally:
        channel.close()
    sys.exit(exit_code)


Clock = Callable[[], float]
