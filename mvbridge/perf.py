"""CPU and GPU sampling, plus the controller that lowers preview quality under load."""

from __future__ import annotations

import logging
import re
import sys
import threading
import time
from collections import defaultdict
from typing import Callable

import psutil

from .config import PerfConfig

log = logging.getLogger("mvbridge.perf")

_GPU_COUNTER = r"\GPU Engine(*engtype_3D)\Utilization Percentage"
_LUID = re.compile(r"luid_(0x[0-9a-f]+_0x[0-9a-f]+)", re.IGNORECASE)


def aggregate_gpu(instances: dict[str, float]) -> float | None:
    """Sum 3D engine use per adapter and return the busiest adapter."""
    totals: dict[str, float] = defaultdict(float)
    for name, value in instances.items():
        match = _LUID.search(name)
        totals[match.group(1).lower() if match else "unknown"] += value
    return min(max(totals.values()), 100.0) if totals else None


class GpuSampler:
    """Windows GPU 3D utilization. Reports None where the counter is unavailable."""

    def __init__(self) -> None:
        self._pdh = None
        if sys.platform != "win32":
            return
        try:
            import win32pdh

            self._query = win32pdh.OpenQuery()
            self._counter = win32pdh.AddEnglishCounter(self._query, _GPU_COUNTER)
            win32pdh.CollectQueryData(self._query)
            self._pdh = win32pdh
        except Exception as exc:  # pywin32 raises its own error type
            log.warning("GPU counter unavailable, using CPU only: %s", exc)

    def sample(self) -> float | None:
        if self._pdh is None:
            return None
        try:
            self._pdh.CollectQueryData(self._query)
            values = self._pdh.GetFormattedCounterArray(self._counter, self._pdh.PDH_FMT_DOUBLE)
        except Exception as exc:  # Instances come and go as processes start and stop.
            log.debug("GPU sample skipped: %s", exc)
            return None
        return aggregate_gpu(values)


class DegradeController:
    """Steps down one level after sustained load, and back up after sustained calm."""

    def __init__(self, cfg: PerfConfig) -> None:
        self._cfg = cfg
        self._max_level = len(cfg.levels) - 1
        self.level = 0
        self._high_since: float | None = None
        self._calm_since: float | None = None

    def update(self, now: float, cpu: float | None, gpu: float | None) -> int:
        if not self._cfg.auto_degrade:
            self.level = 0
            return 0
        high = (cpu is not None and cpu > self._cfg.cpu_high_pct) or (
            gpu is not None and gpu > self._cfg.gpu_3d_high_pct
        )
        if high:
            self._calm_since = None
            if self._high_since is None:
                self._high_since = now
            if now - self._high_since >= self._cfg.sustain_s and self.level < self._max_level:
                self.level += 1
                self._high_since = now
        else:
            self._high_since = None
            if self._calm_since is None:
                self._calm_since = now
            if now - self._calm_since >= self._cfg.recover_s and self.level > 0:
                self.level -= 1
                self._calm_since = now
        return self.level


class PerfMonitor:
    def __init__(self, cfg: PerfConfig, on_level: Callable[[int], None]) -> None:
        self._controller = DegradeController(cfg)
        self._on_level = on_level
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="perf-monitor", daemon=True)
        self._lock = threading.Lock()
        self._cpu: float | None = None
        self._gpu: float | None = None
        self._level = 0

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout=2)

    def snapshot(self) -> dict:
        with self._lock:
            return {"cpu": self._cpu, "gpu3d": self._gpu, "level": self._level}

    def _run(self) -> None:
        gpu_sampler = GpuSampler()
        psutil.cpu_percent(interval=None)
        while not self._stop.wait(1.0):
            cpu = psutil.cpu_percent(interval=None)
            gpu = gpu_sampler.sample()
            level = self._controller.update(time.monotonic(), cpu, gpu)
            with self._lock:
                changed = level != self._level
                self._cpu = round(cpu, 1)
                self._gpu = None if gpu is None else round(gpu, 1)
                self._level = level
            if changed:
                log.warning("PERF preview level=%d cpu=%.0f gpu3d=%s", level, cpu, gpu)
                self._on_level(level)
