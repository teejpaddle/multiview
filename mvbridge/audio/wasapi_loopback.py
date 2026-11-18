"""Show-audio meter from WASAPI loopback. Nothing is ever played back."""

from __future__ import annotations

import logging
import time

import numpy as np

from ..protocol import MeterMsg
from ..workers.base import Worker
from .meter import SILENCE_DB, BlockMeter

_RETRY_S = 2.0
_BLOCK_S = 0.05


def find_loopback_device(pa, match: str) -> dict | None:
    """Find the loopback device whose name contains `match`, ignoring case."""
    wanted = match.casefold()
    for device in pa.get_loopback_device_info_generator():
        if wanted in device["name"].casefold():
            return device
    return None


class WasapiLoopbackWorker(Worker):
    def __init__(self, spec, channel) -> None:
        super().__init__(spec, channel)
        import pyaudiowpatch

        self._pyaudio = pyaudiowpatch
        self._pa = None
        self._stream = None
        self._meter: BlockMeter | None = None
        self._channels = 2
        self._block_frames = 2400
        self._next_attempt = 0.0
        self._last_data = 0.0

    def target_fps(self) -> int:
        return 20

    def step(self) -> None:
        if self._stream is None:
            wait = self._next_attempt - time.monotonic()
            if wait > 0:
                self.idle(min(wait, 0.25))
            else:
                self._open()
            return
        try:
            self._read()
        except OSError as exc:
            self._fail(f"audio device stopped: {exc}")

    def _open(self) -> None:
        match = self.spec.audio.device_match
        try:
            self._pa = self._pyaudio.PyAudio()
            device = find_loopback_device(self._pa, match)
            if device is None:
                self._fail(f"no loopback device matching '{match}'")
                return
            self._channels = int(device["maxInputChannels"])
            rate = int(device["defaultSampleRate"])
            self._block_frames = int(rate * _BLOCK_S)
            self._stream = self._pa.open(
                format=self._pyaudio.paFloat32,
                channels=self._channels,
                rate=rate,
                input=True,
                input_device_index=device["index"],
                frames_per_buffer=self._block_frames,
            )
        except OSError as exc:
            self._fail(f"cannot open audio device: {exc}")
            return
        self._meter = BlockMeter(rate, self._channels, time.monotonic)
        self._last_data = time.monotonic()
        self.set_state("connected", device["name"])
        self.log(logging.INFO, f"AUDIO show meter on '{device['name']}'")

    def _read(self) -> None:
        # WASAPI loopback delivers nothing while the device is silent, so a blocking
        # read would hang. Poll instead and report silence when no data is flowing.
        if self._stream.get_read_available() < self._block_frames:
            now = time.monotonic()
            if now - self._last_data >= _BLOCK_S * 2:
                self._last_data = now
                hold = self._meter.reading(np.zeros(1, dtype=np.float32)).hold_db
                self.emit_meter(MeterMsg("show", "ok", SILENCE_DB, SILENCE_DB, hold))
            self.idle(_BLOCK_S / 4)
            return
        data = self._stream.read(self._block_frames, exception_on_overflow=False)
        self._last_data = time.monotonic()
        for reading in self._meter.push(np.frombuffer(data, dtype=np.float32)):
            self.emit_meter(MeterMsg("show", "ok", *reading))

    def _fail(self, reason: str) -> None:
        self._close()
        self.set_state("disconnected", reason)
        self.emit_meter(MeterMsg("show", state="no_device"))
        self._next_attempt = time.monotonic() + _RETRY_S

    def _close(self) -> None:
        stream, self._stream = self._stream, None
        pa, self._pa = self._pa, None
        try:
            if stream is not None:
                stream.stop_stream()
                stream.close()
        except OSError:
            pass
        if pa is not None:
            pa.terminate()

    def release(self) -> None:
        self._close()
        self._next_attempt = 0.0
        self.emit_meter(MeterMsg("show", state="paused"))
