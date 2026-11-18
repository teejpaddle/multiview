"""PTZ camera preview: low-latency RTSP over TCP, decoded with PyAV."""

from __future__ import annotations

import logging
import time

import av
import numpy as np

from ..audio.meter import BlockMeter
from ..protocol import MeterMsg
from .base import Backoff, Worker, redact

_BACKLOG_LIMIT_S = 0.15
_BASELINE_DRIFT = 0.001  # Lets the baseline follow slow camera clock drift.


class BacklogGate:
    """Spots frames that are behind real time, such as a burst after a network hiccup."""

    def __init__(self) -> None:
        self._baseline: float | None = None
        self._last_now = 0.0

    def is_stale(self, pts_s: float, now: float) -> bool:
        offset = now - pts_s
        if self._baseline is None:
            self._baseline = offset
        else:
            self._baseline += (now - self._last_now) * _BASELINE_DRIFT
            self._baseline = min(self._baseline, offset)
        self._last_now = now
        return offset - self._baseline > _BACKLOG_LIMIT_S


class RtspWorker(Worker):
    def __init__(self, spec, channel) -> None:
        super().__init__(spec, channel)
        self._cfg = spec.feed.rtsp
        self._container = None
        self._packets = None
        self._video = None
        self._audio = None
        self._resampler = None
        self._meter: BlockMeter | None = None
        self._gate = BacklogGate()
        self._backoff = Backoff(
            spec.health.reconnect_interval_ms / 1000, spec.health.reconnect_max_interval_ms / 1000
        )
        self._next_attempt = 0.0

    def step(self) -> None:
        if self._container is None:
            wait = self._next_attempt - time.monotonic()
            if wait > 0:
                self.idle(min(wait, 0.25))
            else:
                self._open()
            return
        self._read_packet()

    def _open(self) -> None:
        if self.state not in ("stalled", "disconnected"):
            self.set_state("connecting")
        try:
            container = av.open(
                self._cfg.url,
                options={
                    "rtsp_transport": self._cfg.transport,
                    "fflags": "nobuffer",
                    "max_delay": "0",
                },
                timeout=(self._cfg.open_timeout_ms / 1000, self._cfg.read_timeout_ms / 1000),
            )
        except (av.FFmpegError, OSError) as exc:
            self._lost(f"camera not reachable: {exc}")
            return

        if not container.streams.video:
            container.close()
            self._lost("stream has no video track")
            return
        self._container = container
        self._video = container.streams.video[0]
        self._video.codec_context.flags |= av.codec.context.Flags.low_delay
        self._gate = BacklogGate()
        self._setup_audio(container)
        streams = [self._video] + ([self._audio] if self._audio is not None else [])
        self._packets = container.demux(streams)

    def _setup_audio(self, container) -> None:
        self._audio = None
        self._meter = None
        if not self._cfg.audio_meter:
            return
        if not container.streams.audio:
            self.emit_meter(MeterMsg("cam", state="no_track"))
            return
        self._audio = container.streams.audio[0]
        self._resampler = av.AudioResampler(format="flt")
        channels = self._audio.codec_context.channels or 1
        self._meter = BlockMeter(self._audio.codec_context.sample_rate, channels, time.monotonic)

    def _read_packet(self) -> None:
        try:
            packet = next(self._packets)
        except StopIteration:
            self._lost("camera closed the stream")
            return
        except (av.ExitError, av.TimeoutError):
            # Try once more straight away. A failed reopen then reports disconnected.
            self._close()
            self.set_state("stalled", f"no packets for {self._cfg.read_timeout_ms} ms")
            self._next_attempt = 0.0
            return
        except (av.FFmpegError, OSError) as exc:
            self._lost(f"stream error: {exc}")
            return

        try:
            frames = packet.decode()
        except av.InvalidDataError:
            return  # A damaged packet. The next keyframe repairs the picture.
        except av.FFmpegError as exc:
            self._lost(f"decode error: {exc}")
            return

        if packet.stream is self._video:
            # Only the newest picture from this packet is worth encoding.
            if frames:
                self._handle_video(frames[-1])
        else:
            for frame in frames:
                self._handle_audio(frame)

    def _handle_video(self, frame) -> None:
        now = time.monotonic()
        capture_ts_ns = time.time_ns()
        self.set_state("connected")
        self._backoff.reset()
        if frame.pts is not None and frame.time_base is not None:
            if self._gate.is_stale(float(frame.pts * frame.time_base), now):
                return
        if not self.throttle.ready(now):
            return
        width, height = self.target_size()
        rgb = frame.reformat(width=width, height=height, format="rgb24").to_ndarray()
        self.publish(rgb, capture_ts_ns)

    def _handle_audio(self, frame) -> None:
        for resampled in self._resampler.resample(frame):
            samples: np.ndarray = resampled.to_ndarray()
            for reading in self._meter.push(samples):
                self.emit_meter(MeterMsg("cam", "ok", *reading))

    def _lost(self, reason: str) -> None:
        self._close()
        self.set_state("disconnected", redact(reason))
        if self._cfg.audio_meter:
            self.emit_meter(MeterMsg("cam", state="offline"))
        self._next_attempt = time.monotonic() + self._backoff.next_delay()

    def _close(self) -> None:
        container, self._container = self._container, None
        self._packets = None
        self._video = None
        self._audio = None
        if container is not None:
            try:
                container.close()
            except (av.FFmpegError, OSError) as exc:
                self.log(logging.DEBUG, f"closing camera stream: {exc}")

    def release(self) -> None:
        self._close()
        self._next_attempt = 0.0
        if self._cfg.audio_meter:
            self.emit_meter(MeterMsg("cam", state="paused"))
