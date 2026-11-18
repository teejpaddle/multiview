"""Show countdown. Computed from the wall clock and saved on every change."""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Callable

log = logging.getLogger("mvbridge.timer")

DEFAULT_DURATION_MS = 10 * 60 * 1000


class TimerError(ValueError):
    """The requested action does not apply to the timer's current state."""


class CountdownTimer:
    def __init__(
        self,
        path: Path | None = None,
        clock_ms: Callable[[], int] = lambda: time.time_ns() // 1_000_000,
    ) -> None:
        self._path = path
        self._clock = clock_ms
        self._lock = threading.Lock()
        self._mode = "idle"  # idle | running | paused (overrun is derived from running)
        self._duration_ms = DEFAULT_DURATION_MS
        self._remaining_ms = DEFAULT_DURATION_MS
        self._target_ms: int | None = None
        self._restore()

    def _restore(self) -> None:
        if self._path is None or not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            mode = data["mode"]
            if mode not in ("idle", "running", "paused"):
                raise ValueError(f"unknown mode {mode!r}")
            duration = int(data["duration_ms"])
            remaining = int(data["remaining_ms"])
            target = None if data["target_epoch_ms"] is None else int(data["target_epoch_ms"])
            if mode == "running" and target is None:
                raise ValueError("running timer has no target")
        except (OSError, ValueError, KeyError, TypeError) as exc:
            log.warning("Ignoring unreadable timer state: %s", exc)
            return
        self._mode, self._duration_ms, self._remaining_ms, self._target_ms = (
            mode, duration, remaining, target,
        )

    def _save(self) -> None:
        if self._path is None:
            return
        data = {
            "mode": self._mode,
            "duration_ms": self._duration_ms,
            "remaining_ms": self._remaining_ms,
            "target_epoch_ms": self._target_ms,
        }
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            temp = self._path.with_suffix(".tmp")
            temp.write_text(json.dumps(data), encoding="utf-8")
            os.replace(temp, self._path)
        except OSError as exc:
            log.warning("Could not save timer state: %s", exc)

    def apply(self, action: str, value: float | None = None) -> dict:
        with self._lock:
            now = self._clock()
            if action == "start":
                self._start(now)
            elif action == "pause":
                self._pause(now)
            elif action == "reset":
                self._mode = "idle"
                self._target_ms = None
                self._remaining_ms = self._duration_ms
            elif action == "set_duration":
                self._set_duration(value)
            elif action == "set_target":
                self._set_target(now, value)
            else:
                raise TimerError(f"unknown timer action '{action}'")
            self._save()
            return self._snapshot(now)

    def _start(self, now: int) -> None:
        if self._mode == "running":
            return
        if self._remaining_ms <= 0:
            raise TimerError("set a duration before starting")
        self._target_ms = now + self._remaining_ms
        self._mode = "running"

    def _pause(self, now: int) -> None:
        if self._mode != "running":
            raise TimerError("the countdown is not running")
        if self._target_ms <= now:
            raise TimerError("the countdown has already finished")
        self._remaining_ms = self._target_ms - now
        self._target_ms = None
        self._mode = "paused"

    def _require_stopped(self) -> None:
        # Guards a running countdown against a stray preset click during the show.
        if self._mode == "running":
            raise TimerError("reset the running countdown first")

    def _set_duration(self, value: float | None) -> None:
        self._require_stopped()
        if value is None or value <= 0:
            raise TimerError("duration must be greater than zero")
        self._duration_ms = int(value)
        self._remaining_ms = self._duration_ms
        self._target_ms = None
        self._mode = "idle"

    def _set_target(self, now: int, value: float | None) -> None:
        self._require_stopped()
        if value is None or value <= now:
            raise TimerError("target time must be in the future")
        self._target_ms = int(value)
        self._duration_ms = self._target_ms - now
        self._remaining_ms = self._duration_ms
        self._mode = "running"

    def snapshot(self) -> dict:
        with self._lock:
            return self._snapshot(self._clock())

    def _snapshot(self, now: int) -> dict:
        mode = self._mode
        remaining = self._remaining_ms
        if mode == "running":
            remaining = self._target_ms - now
            if remaining <= 0:
                mode = "overrun"
        return {
            "mode": mode,
            "duration_ms": self._duration_ms,
            "remaining_ms": remaining,
            "target_epoch_ms": self._target_ms,
        }
