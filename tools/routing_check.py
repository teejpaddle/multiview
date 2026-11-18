"""Acceptance test T1: confirms each tile shows the right, moving test clip."""

from __future__ import annotations

import argparse
import sys
import time
import urllib.error
import urllib.request

import numpy as np
import simplejpeg


def snapshot(base_url: str, feed: str) -> np.ndarray:
    with urllib.request.urlopen(f"{base_url}/api/snapshot/{feed}.jpg", timeout=3) as response:
        return simplejpeg.decode_jpeg(response.read(), colorspace="RGB")


def collect(base_url: str, feed: str, count: int, interval_s: float) -> list[np.ndarray]:
    pictures = []
    for index in range(count):
        if index:
            time.sleep(interval_s)
        pictures.append(snapshot(base_url, feed))
    return pictures


def color_ok(pictures: list[np.ndarray], expected: str) -> tuple[bool, float, float]:
    mean = np.mean([picture.reshape(-1, 3).mean(axis=0) for picture in pictures], axis=0)
    red, blue = float(mean[0]), float(mean[2])
    passed = red > 2 * blue if expected == "red" else blue > 2 * red
    return passed, red, blue


def motion_ok(pictures: list[np.ndarray], threshold: float = 2.0) -> tuple[bool, float]:
    differences = [
        float(np.abs(a.astype(np.int16) - b.astype(np.int16)).mean())
        for a, b in zip(pictures, pictures[1:])
        if a.shape == b.shape
    ]
    if not differences:
        return False, 0.0
    smallest = min(differences)
    return smallest > threshold, smallest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8090")
    parser.add_argument("--center", default="center", help="feed id of the center tile")
    parser.add_argument("--side", default="side", help="feed id of the side tile")
    parser.add_argument("--expect", choices=("normal", "swapped"), default="normal")
    parser.add_argument("--count", type=int, default=10)
    parser.add_argument("--interval", type=float, default=0.2)
    args = parser.parse_args()

    colors = {args.center: "red", args.side: "blue"}
    if args.expect == "swapped":
        colors = {args.center: "blue", args.side: "red"}

    failed = False
    for feed, expected in colors.items():
        try:
            pictures = collect(args.url, feed, args.count, args.interval)
        except (urllib.error.URLError, OSError, ValueError) as exc:
            print(f"FAIL  {feed}: could not read snapshots: {exc}")
            failed = True
            continue
        color_passed, red, blue = color_ok(pictures, expected)
        print(f"{'PASS' if color_passed else 'FAIL'}  {feed}: expected {expected} (R={red:.0f}, B={blue:.0f})")
        moving, smallest = motion_ok(pictures)
        print(f"{'PASS' if moving else 'FAIL'}  {feed}: picture is moving (smallest change {smallest:.1f})")
        failed = failed or not color_passed or not moving

    print("\nRouting check " + ("FAILED" if failed else "PASSED"))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
