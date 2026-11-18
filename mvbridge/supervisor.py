"""Runs one process per feed, restarts any that fail and routes their output."""

from __future__ import annotations

import logging
import multiprocessing
import queue
import threading
import time
from dataclasses import dataclass, field, replace

from .framebus import FrameBus, StoredFrame
from .health import StatusStore
from .protocol import FrameMsg, HeartbeatMsg, LogMsg, MeterMsg, StateMsg, pack_frame
from .workers.base import WorkerSpec, worker_main

log = logging.getLogger("mvbridge.supervisor")

HEARTBEAT_TIMEOUT_S = 5.0
RESTART_FIRST_S = 2.0
RESTART_MAX_S = 10.0
STABLE_AFTER_S = 30.0

_context = multiprocessing.get_context("spawn")


@dataclass
class _Handle:
    spec: WorkerSpec
    process: object = None
    frames: object = None
    events: object = None
    control: object = None
    generation: int = 0
    started_at: float = 0.0
    last_seen: float = 0.0
    restart_at: float | None = None
    backoff: float = RESTART_FIRST_S
    threads: list = field(default_factory=list)


class Supervisor:
    def __init__(self, specs: list[WorkerSpec], bus: FrameBus, store: StatusStore) -> None:
        self._handles = {spec.worker_id: _Handle(spec) for spec in specs}
        self._bus = bus
        self._store = store
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._paused = False
        self._level = 0
        self._watchdog = threading.Thread(target=self._watch, name="supervisor", daemon=True)

    def start(self) -> None:
        for handle in self._handles.values():
            self._spawn(handle)
        self._watchdog.start()

    def stop(self) -> None:
        self._stop.set()
        if self._watchdog.is_alive():
            self._watchdog.join(timeout=2)
        for handle in self._handles.values():
            self._send(handle, ("stop",))
        deadline = time.monotonic() + 2.0
        for handle in self._handles.values():
            if handle.process is not None:
                handle.process.join(max(0.0, deadline - time.monotonic()))
            self._discard(handle)

    def set_paused(self, paused: bool) -> None:
        with self._lock:
            self._paused = paused
            handles = list(self._handles.values())
        for handle in handles:
            self._send(handle, ("pause", paused))

    def set_level(self, level: int) -> None:
        with self._lock:
            self._level = level
            handles = list(self._handles.values())
        for handle in handles:
            self._send(handle, ("level", level))

    @staticmethod
    def _send(handle: _Handle, message: tuple) -> None:
        if handle.control is None:
            return
        try:
            handle.control.send(message)
        except (BrokenPipeError, EOFError, OSError):
            pass  # The watchdog will restart this worker.

    def _spawn(self, handle: _Handle) -> None:
        with self._lock:
            spec = replace(handle.spec, paused=self._paused, level=self._level)
        # Fresh queues every time: a killed process can leave the old ones locked.
        frames = _context.Queue(maxsize=3)
        events = _context.Queue(maxsize=128)
        parent_end, child_end = _context.Pipe()
        process = _context.Process(
            target=worker_main,
            args=(spec, frames, events, child_end),
            name=f"mv-{spec.worker_id}",
            daemon=True,
        )
        process.start()
        child_end.close()

        now = time.monotonic()
        handle.process, handle.frames, handle.events, handle.control = (
            process, frames, events, parent_end,
        )
        handle.generation += 1
        handle.started_at = handle.last_seen = now
        handle.restart_at = None
        generation = handle.generation
        handle.threads = [
            threading.Thread(
                target=self._read_queue,
                args=(handle, generation, source),
                name=f"reader-{spec.worker_id}",
                daemon=True,
            )
            for source in (frames, events)
        ]
        for thread in handle.threads:
            thread.start()
        log.info("WORKER id=%s started pid=%s", spec.worker_id, process.pid)

    def _discard(self, handle: _Handle) -> None:
        process = handle.process
        if process is not None and process.is_alive():
            process.kill()
            process.join(1.0)
        handle.generation += 1
        for thread in handle.threads:
            thread.join(timeout=1.0)
        handle.threads = []
        for source in (handle.frames, handle.events):
            if source is not None:
                source.close()
                source.cancel_join_thread()
        if handle.control is not None:
            handle.control.close()
        handle.process = handle.frames = handle.events = handle.control = None

    def _read_queue(self, handle: _Handle, generation: int, source) -> None:
        while handle.generation == generation and not self._stop.is_set():
            try:
                item = source.get(timeout=0.25)
            except queue.Empty:
                continue
            except (EOFError, OSError, ValueError):
                return
            handle.last_seen = time.monotonic()
            self._route(handle.spec.worker_id, handle.spec.feed is not None, item)

    def _route(self, worker_id: str, is_feed: bool, item) -> None:
        if isinstance(item, FrameMsg):
            capture_ms = item.capture_ts_ns // 1_000_000
            payload = pack_frame(item.seq, capture_ms, item.width, item.height, item.jpeg)
            self._store.on_frame(worker_id, item)
            self._bus.publish(
                worker_id,
                StoredFrame(payload, item.jpeg, item.seq, capture_ms, item.width, item.height),
            )
        elif isinstance(item, MeterMsg):
            self._store.on_meter(item)
        elif isinstance(item, (StateMsg, HeartbeatMsg)):
            if is_feed:
                self._store.on_state(worker_id, item.state, item.detail)
        elif isinstance(item, LogMsg):
            log.log(item.level, item.message)

    def _watch(self) -> None:
        while not self._stop.wait(0.25):
            now = time.monotonic()
            for handle in self._handles.values():
                self._check(handle, now)

    def _check(self, handle: _Handle, now: float) -> None:
        if handle.restart_at is not None:
            if now >= handle.restart_at:
                self._spawn(handle)
            return

        reason = None
        if not handle.process.is_alive():
            reason = f"capture process exited (code {handle.process.exitcode})"
        elif now - handle.last_seen > HEARTBEAT_TIMEOUT_S:
            reason = f"capture process stopped responding for {HEARTBEAT_TIMEOUT_S:.0f} s"
        if reason is None:
            return

        worker_id = handle.spec.worker_id
        if now - handle.started_at >= STABLE_AFTER_S:
            handle.backoff = RESTART_FIRST_S
        delay = handle.backoff
        handle.backoff = min(handle.backoff * 2, RESTART_MAX_S)
        log.error("WORKER id=%s failed: %s; restarting in %.0f s", worker_id, reason, delay)
        self._discard(handle)
        if handle.spec.feed is not None:
            self._store.on_state(worker_id, "error", reason)
        handle.restart_at = now + delay
