"""Acceptance test T6: records system load and per-feed health to a CSV once a second."""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

import psutil


def fetch(base_url: str, path: str) -> dict:
    with urllib.request.urlopen(base_url + path, timeout=2) as response:
        return json.load(response)


def bridge_rss_mb(pid: int) -> float:
    try:
        parent = psutil.Process(pid)
        processes = [parent, *parent.children(recursive=True)]
    except psutil.Error:
        return 0.0
    total = 0
    for process in processes:
        try:
            total += process.memory_info().rss
        except psutil.Error:
            pass
    return total / 1_048_576


def main() -> int:
    default_out = Path("logs") / f"perf-{datetime.now():%Y%m%d-%H%M%S}.csv"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8090")
    parser.add_argument("--out", type=Path, default=default_out)
    parser.add_argument("--duration", type=float, default=0, help="seconds to record (0 = until Ctrl+C)")
    args = parser.parse_args()

    try:
        health = fetch(args.url, "/healthz")
        feeds = sorted(fetch(args.url, "/api/status")["feeds"])
    except (urllib.error.URLError, OSError) as exc:
        print(f"The bridge is not reachable at {args.url}: {exc}")
        return 1

    columns = ["time", "cpu_pct", "gpu3d_pct", "level", "paused", "bridge_rss_mb"]
    for feed in feeds:
        columns += [f"{feed}_fps", f"{feed}_age_ms", f"{feed}_state"]

    args.out.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    print(f"Recording to {args.out} (Ctrl+C to stop)")
    with args.out.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(columns)
        try:
            while not args.duration or time.monotonic() - started < args.duration:
                tick = time.monotonic()
                try:
                    status = fetch(args.url, "/api/status")
                except (urllib.error.URLError, OSError):
                    writer.writerow([datetime.now().isoformat(timespec="seconds"), "BRIDGE UNREACHABLE"])
                else:
                    perf = status["perf"]
                    row = [
                        datetime.now().isoformat(timespec="seconds"), perf["cpu"], perf["gpu3d"],
                        perf["level"], perf["paused"], f"{bridge_rss_mb(health['pid']):.1f}",
                    ]
                    for feed in feeds:
                        item = status["feeds"][feed]
                        age = status["t"] - item["last_capture_ms"] if item["last_capture_ms"] else ""
                        row += [item["fps"], age, item["tile_state"]]
                    writer.writerow(row)
                handle.flush()
                time.sleep(max(0.0, 1.0 - (time.monotonic() - tick)))
        except KeyboardInterrupt:
            pass
    print("Finished.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
