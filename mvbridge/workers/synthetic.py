"""Moving test pattern with scripted faults. Needs no hardware."""

from __future__ import annotations

import math
import os
import time

import numpy as np

from ..audio.meter import BlockMeter
from ..config import SyntheticConfig
from ..protocol import MeterMsg
from .base import Worker

_GLYPHS = {
    "0": "01110 10001 10011 10101 11001 10001 01110",
    "1": "00100 01100 00100 00100 00100 00100 01110",
    "2": "01110 10001 00001 00010 00100 01000 11111",
    "3": "11110 00001 00001 01110 00001 00001 11110",
    "4": "00010 00110 01010 10010 11111 00010 00010",
    "5": "11111 10000 11110 00001 00001 10001 01110",
    "6": "00110 01000 10000 11110 10001 10001 01110",
    "7": "11111 00001 00010 00100 01000 01000 01000",
    "8": "01110 10001 10001 01110 10001 10001 01110",
    "9": "01110 10001 10001 01111 00001 00010 01100",
}
_GLYPH_BITS = {
    char: np.array([[c == "1" for c in row] for row in rows.split()], dtype=bool)
    for char, rows in _GLYPHS.items()
}


def draw_number(image: np.ndarray, value: int, x: int, y: int, scale: int) -> None:
    for index, char in enumerate(str(value)):
        glyph = _GLYPH_BITS[char].repeat(scale, axis=0).repeat(scale, axis=1)
        left = x + index * 6 * scale
        region = image[y : y + glyph.shape[0], left : left + glyph.shape[1]]
        if region.shape[:2] == glyph.shape:
            region[glyph] = (255, 255, 255)


def fault_active(start: float | None, duration: float, elapsed: float, repeat: float | None) -> bool:
    if start is None or elapsed < start:
        return False
    offset = elapsed - start
    if repeat is not None:
        offset %= repeat
    return offset < duration


class SyntheticWorker(Worker):
    def __init__(self, spec, channel) -> None:
        super().__init__(spec, channel)
        self._cfg = spec.feed.synthetic or SyntheticConfig()
        self._started = time.monotonic()
        self._frame_number = 0
        self._frozen: np.ndarray | None = None
        self._last_meter = 0.0

    def _active(self, start, duration, elapsed) -> bool:
        return fault_active(start, duration, elapsed, self._cfg.repeat_every_s)

    def step(self) -> None:
        cfg = self._cfg
        elapsed = time.monotonic() - self._started
        self._emit_meter(elapsed)

        if cfg.crash_after_s is not None and elapsed >= cfg.crash_after_s:
            os._exit(3)  # Simulates a hard crash for the supervisor tests.
        if self._active(cfg.dropout_after_s, cfg.dropout_for_s, elapsed):
            self.set_state("disconnected", "scripted dropout")
            self.idle(0.02)
            return
        if self._active(cfg.stall_after_s, cfg.stall_for_s, elapsed):
            self.set_state("stalled", "scripted stall")
            self.idle(0.02)
            return

        wait = self.throttle.wait_time(time.monotonic())
        if wait > 0:
            self.idle(min(wait, 0.02))
            return
        if not self.throttle.ready(time.monotonic()):
            return

        self.set_state("connected")
        self._frame_number += 1
        width, height = self.target_size()
        if self._active(cfg.black_picture_after_s, cfg.black_picture_for_s, elapsed):
            picture = np.zeros((height, width, 3), dtype=np.uint8)
        elif self._active(cfg.freeze_picture_after_s, cfg.freeze_picture_for_s, elapsed):
            if self._frozen is None or self._frozen.shape[:2] != (height, width):
                self._frozen = self._render(width, height, elapsed)
            picture = self._frozen
        else:
            self._frozen = None
            picture = self._render(width, height, elapsed)
        self.publish(picture, time.time_ns())

    def _render(self, width: int, height: int, elapsed: float) -> np.ndarray:
        image = np.empty((height, width, 3), dtype=np.uint8)
        image[:] = self._cfg.background
        phase = elapsed % 1.0
        if self._cfg.motion == "horizontal":
            bar = max(4, width // 16)
            left = int(phase * (width - bar))
            image[:, left : left + bar] = (255, 255, 255)
        else:
            bar = max(4, height // 16)
            top = int(phase * (height - bar))
            image[top : top + bar, :] = (255, 255, 255)
        scale = max(2, height // 60)
        draw_number(image, self._frame_number, width // 2 - 12 * scale, height // 2 - 4 * scale, scale)
        return image

    def _emit_meter(self, elapsed: float) -> None:
        mode = self._cfg.audio_meter
        now = time.monotonic()
        if mode is None or now - self._last_meter < 0.05:
            return
        self._last_meter = now
        if mode == "no_track":
            self.emit_meter(MeterMsg("cam", state="no_track"))
            return
        level = -24.0 + 12.0 * math.sin(elapsed * 2.1)
        self.emit_meter(MeterMsg("cam", peak_db=level, rms_db=level - 6, hold_db=level + 2))


class SyntheticAudioWorker(Worker):
    """Stands in for the show audio device with a -12 dBFS tone."""

    def __init__(self, spec, channel) -> None:
        super().__init__(spec, channel)
        self._meter = BlockMeter(48_000, 1, time.monotonic)
        self._phase = 0

    def target_fps(self) -> int:
        return 20

    def step(self) -> None:
        self.set_state("connected")
        positions = np.arange(self._phase, self._phase + 2400)
        self._phase += 2400
        tone = 10 ** (-12 / 20) * np.sin(2 * np.pi * 440 * positions / 48_000)
        for reading in self._meter.push(tone):
            self.emit_meter(MeterMsg("show", "ok", *reading))
        self.idle(0.05)

    def release(self) -> None:
        self.emit_meter(MeterMsg("show", state="paused"))
