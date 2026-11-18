"""List Spout senders, test the camera, and run the preflight checks (--check)."""

from __future__ import annotations

import argparse
import socket
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from mvbridge.config import ConfigError, MultiviewConfig, load_config  # noqa: E402
from mvbridge.workers.base import redact  # noqa: E402


def spout_senders() -> dict[str, tuple[int, int]]:
    import SpoutGL

    with SpoutGL.SpoutReceiver() as receiver:
        senders = {}
        for name in receiver.getSenderList():
            info = receiver.getSenderInfo(name)
            senders[name] = (info.width, info.height) if info is not None else (0, 0)
        return senders


def test_camera(url: str, timeout_s: float = 3.0) -> tuple[bool, str]:
    """Open the camera and decode one video frame within the time limit."""
    import av

    deadline = time.monotonic() + timeout_s
    try:
        with av.open(url, options={"rtsp_transport": "tcp"}, timeout=(timeout_s, timeout_s)) as container:
            if not container.streams.video:
                return False, "stream has no video track"
            stream = container.streams.video[0]
            for packet in container.demux(stream):
                for frame in packet.decode():
                    audio = "audio track" if container.streams.audio else "no audio track"
                    return True, f"{stream.codec_context.name} {frame.width}x{frame.height}, {audio}"
                if time.monotonic() > deadline:
                    return False, f"no picture decoded within {timeout_s:.0f} s"
    except (av.FFmpegError, OSError) as exc:
        return False, redact(str(exc))
    return False, "stream ended before a picture arrived"


def find_audio_device(match: str) -> str | None:
    import pyaudiowpatch

    from mvbridge.audio.wasapi_loopback import find_loopback_device

    audio = pyaudiowpatch.PyAudio()
    try:
        device = find_loopback_device(audio, match)
        return None if device is None else device["name"]
    finally:
        audio.terminate()


class Report:
    def __init__(self) -> None:
        self.failed = 0

    def line(self, passed: bool, name: str, detail: str = "") -> None:
        self.failed += not passed
        suffix = f" - {detail}" if detail else ""
        print(f"{'PASS' if passed else 'FAIL'}  {name}{suffix}")


def _check_port(report: Report, cfg: MultiviewConfig) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind((cfg.server.host, cfg.server.port))
            report.line(True, f"Port {cfg.server.port} free")
        except OSError:
            report.line(False, f"Port {cfg.server.port} free", "already in use (is the bridge running?)")


def _check_spout(report: Report, cfg: MultiviewConfig) -> None:
    feeds = [feed for feed in cfg.feed if feed.type == "spout"]
    if not feeds:
        return
    try:
        senders = spout_senders()
    except Exception as exc:  # SpoutGL raises platform-specific errors.
        for feed in feeds:
            report.line(False, f"Spout sender '{feed.spout.sender}'", f"Spout unavailable: {exc}")
        return
    for feed in feeds:
        found = senders.get(feed.spout.sender)
        detail = f"{found[0]}x{found[1]}" if found else f"not found; senders seen: {sorted(senders)}"
        report.line(found is not None, f"Spout sender '{feed.spout.sender}'", detail)


def _check_audio(report: Report, cfg: MultiviewConfig) -> None:
    show = cfg.audio.show
    if not show.enabled or show.source != "wasapi_loopback":
        return
    try:
        name = find_audio_device(show.device_match)
    except Exception as exc:  # PyAudio raises platform-specific errors.
        report.line(False, f"Audio device '{show.device_match}'", str(exc))
        return
    report.line(name is not None, f"Audio device '{show.device_match}'", name or "not found")


def _check_monitor(report: Report, cfg: MultiviewConfig) -> None:
    if sys.platform != "win32":
        report.line(False, "Multiview monitor", "can only be checked on Windows")
        return
    from list_monitors import enumerate_monitors

    x, y = cfg.ui.window_x, cfg.ui.window_y
    found = any(
        m["x"] <= x < m["x"] + m["w"] and m["y"] <= y < m["y"] + m["h"] for m in enumerate_monitors()
    )
    report.line(found, f"Multiview monitor at x={x} y={y}")


def preflight(config_path: str) -> int:
    report = Report()
    version = sys.version_info
    report.line(version[:2] == (3, 12), "Python 3.12", f"found {version.major}.{version.minor}")
    try:
        cfg = load_config(config_path)
    except ConfigError as exc:
        report.line(False, "Config valid", str(exc))
        print("\nPreflight FAILED")
        return 1
    report.line(True, "Config valid", config_path)
    _check_port(report, cfg)
    _check_spout(report, cfg)
    for feed in cfg.feed:
        if feed.type == "rtsp":
            passed, detail = test_camera(feed.rtsp.url)
            report.line(passed, f"Camera '{feed.label}' decodes a frame", detail)
    _check_audio(report, cfg)
    _check_monitor(report, cfg)
    print("\nPreflight " + ("PASSED" if not report.failed else f"FAILED ({report.failed} problem(s))"))
    return 1 if report.failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=str(ROOT / "config" / "multiview.toml"))
    parser.add_argument("--check", action="store_true", help="run every preflight check")
    parser.add_argument("--camera", metavar="URL", help="test one camera URL")
    args = parser.parse_args()

    if args.check:
        return preflight(args.config)
    if args.camera:
        passed, detail = test_camera(args.camera)
        print(("PASS" if passed else "FAIL") + f"  {detail}")
        return 0 if passed else 1
    try:
        senders = spout_senders()
    except ImportError:
        print("SpoutGL is not installed. Spout is available only on the Windows show PC.")
        return 1
    if not senders:
        print("No Spout senders found. Is the Show + Multiview output preset active in Resolume?")
    for name, (width, height) in sorted(senders.items()):
        print(f'spout.sender = "{name}"    # {width}x{height}')
    return 0


if __name__ == "__main__":
    sys.exit(main())
