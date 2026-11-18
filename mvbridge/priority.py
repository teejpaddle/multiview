"""Keep every bridge process below Resolume in the scheduler."""

from __future__ import annotations

import logging
import sys

import psutil

log = logging.getLogger("mvbridge.priority")


def set_below_normal() -> None:
    try:
        process = psutil.Process()
        if sys.platform == "win32":
            process.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
        else:
            process.nice(10)
    except (psutil.Error, OSError) as exc:
        log.warning("Could not lower process priority: %s", exc)
