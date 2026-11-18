"""Wire format for browser frames and the messages workers send to the supervisor."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import NamedTuple

MAGIC = b"MVF1"
# magic | uint32 seq | uint64 capture_ts_ms | uint16 w | uint16 h | uint32 jpeg_len
_HEADER = struct.Struct("<4sIQHHI")
HEADER_SIZE = _HEADER.size

SOURCE_STATES = frozenset(
    {"connecting", "connected", "stalled", "disconnected", "error", "paused"}
)
METER_STATES = frozenset({"ok", "no_track", "no_device", "offline", "paused"})


class FrameHeader(NamedTuple):
    seq: int
    capture_ts_ms: int
    width: int
    height: int
    jpeg_len: int


def pack_frame(seq: int, capture_ts_ms: int, width: int, height: int, jpeg: bytes) -> bytes:
    """Build one binary WebSocket message: 24-byte header followed by the JPEG."""
    header = _HEADER.pack(MAGIC, seq & 0xFFFFFFFF, capture_ts_ms, width, height, len(jpeg))
    return header + jpeg


def unpack_frame(message: bytes) -> tuple[FrameHeader, bytes]:
    """Parse a binary frame message. Raises ValueError when it is malformed."""
    if len(message) < HEADER_SIZE:
        raise ValueError("frame message shorter than header")
    magic, seq, ts_ms, width, height, jpeg_len = _HEADER.unpack_from(message)
    if magic != MAGIC:
        raise ValueError(f"bad frame magic {magic!r}")
    if len(message) != HEADER_SIZE + jpeg_len:
        raise ValueError("frame length does not match header")
    return FrameHeader(seq, ts_ms, width, height, jpeg_len), message[HEADER_SIZE:]


@dataclass(frozen=True, slots=True)
class FrameMsg:
    seq: int
    capture_ts_ns: int
    width: int
    height: int
    jpeg: bytes
    static: bool = False
    black: bool = False
    static_s: float = 0.0


@dataclass(frozen=True, slots=True)
class StateMsg:
    state: str
    detail: str = ""


@dataclass(frozen=True, slots=True)
class MeterMsg:
    key: str
    state: str = "ok"
    peak_db: float = -120.0
    rms_db: float = -120.0
    hold_db: float = -120.0


@dataclass(frozen=True, slots=True)
class HeartbeatMsg:
    """Sent once a second. Carries the current state so a lost update heals itself."""

    state: str
    detail: str = ""


@dataclass(frozen=True, slots=True)
class LogMsg:
    level: int
    message: str
