"""Peak and RMS metering. Audio samples are measured here and never leave the server."""

from __future__ import annotations

import math
from typing import Callable, Iterator, NamedTuple

import numpy as np

SILENCE_DB = -120.0
PEAK_HOLD_S = 1.5


def to_dbfs(linear: float) -> float:
    return SILENCE_DB if linear <= 1e-6 else max(SILENCE_DB, 20.0 * math.log10(linear))


def measure(samples: np.ndarray) -> tuple[float, float]:
    """Return (peak_db, rms_db) for float samples where full scale is 1.0."""
    if samples.size == 0:
        return SILENCE_DB, SILENCE_DB
    peak = float(np.max(np.abs(samples)))
    rms = math.sqrt(float(np.mean(np.square(samples, dtype=np.float64))))
    return to_dbfs(peak), to_dbfs(rms)


class PeakHold:
    def __init__(self, hold_s: float = PEAK_HOLD_S) -> None:
        self._hold_s = hold_s
        self._value = SILENCE_DB
        self._at = 0.0

    def update(self, peak_db: float, now: float) -> float:
        if peak_db >= self._value or now - self._at >= self._hold_s:
            self._value = peak_db
            self._at = now
        return self._value


class Reading(NamedTuple):
    peak_db: float
    rms_db: float
    hold_db: float


class BlockMeter:
    """Turns a stream of samples into one reading per 50 ms block."""

    def __init__(self, sample_rate: int, channels: int, clock: Callable[[], float]) -> None:
        self._block = max(1, int(sample_rate * channels * 0.05))
        self._buffer = np.empty(0, dtype=np.float32)
        self._hold = PeakHold()
        self._clock = clock

    def push(self, samples: np.ndarray) -> Iterator[Reading]:
        self._buffer = np.concatenate((self._buffer, samples.astype(np.float32).ravel()))
        while self._buffer.size >= self._block:
            block, self._buffer = self._buffer[: self._block], self._buffer[self._block :]
            yield self.reading(block)

    def reading(self, block: np.ndarray) -> Reading:
        peak_db, rms_db = measure(block)
        return Reading(peak_db, rms_db, self._hold.update(peak_db, self._clock()))
