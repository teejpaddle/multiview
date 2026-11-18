"""Resolume preview: receives a Spout sender inside a hidden OpenGL context.

Method names follow the SpoutGL 0.1.1 binding (src/PySpoutGL.cpp and examples/image/receiver.py
in jlai/Python-SpoutGL). getSenderName is not used because that binding returns the width.
"""

from __future__ import annotations

import logging
import time

import numpy as np

from .base import Worker

_SENDER_CHECK_S = 1.0


def rgba_to_rgb(rgba: np.ndarray) -> np.ndarray:
    """Drop alpha, compositing onto black when the picture is not fully opaque."""
    alpha = rgba[..., 3]
    if int(alpha[:: 8, :: 8].min()) == 255:
        return rgba[..., :3]
    scale = alpha[..., np.newaxis].astype(np.uint16)
    return ((rgba[..., :3].astype(np.uint16) * scale + 127) // 255).astype(np.uint8)


def _load_backend():
    import glfw
    import SpoutGL
    from SpoutGL.enums import GL_RGBA

    return glfw, SpoutGL, GL_RGBA


class SpoutWorker(Worker):
    def __init__(self, spec, channel) -> None:
        super().__init__(spec, channel)
        self._cfg = spec.feed.spout
        self._glfw, self._spout, self._gl_rgba = _load_backend()
        self._window = None
        self._receiver = None
        self._buffer: np.ndarray | None = None
        self._last_frame_number = -1
        self._last_new_frame = 0.0
        self._next_sender_check = 0.0
        self._next_attempt = 0.0
        self._attached = False
        self._mode_logged = False

    def _ensure_receiver(self) -> None:
        if self._receiver is not None:
            return
        glfw = self._glfw
        if not glfw.init():
            raise RuntimeError("could not initialize GLFW")
        glfw.window_hint(glfw.VISIBLE, glfw.FALSE)
        self._window = glfw.create_window(16, 16, "multiview-spout", None, None)
        if not self._window:
            raise RuntimeError("could not create the hidden OpenGL window")
        glfw.make_context_current(self._window)
        self._receiver = self._spout.SpoutReceiver()
        self._receiver.setReceiverName(self._cfg.sender)

    def step(self) -> None:
        self._ensure_receiver()
        now = time.monotonic()

        if not self._attached:
            if now < self._next_attempt:
                self.idle(min(self._next_attempt - now, 0.25))
                return
            if self._sender_exists():
                self._attached = True
                self._last_new_frame = now
                self._next_sender_check = now + _SENDER_CHECK_S
                self.set_state("connecting")
            else:
                self._detach(f"sender '{self._cfg.sender}' not found")
                return

        if now >= self._next_sender_check:
            self._next_sender_check = now + _SENDER_CHECK_S
            if not self._sender_exists():
                self._detach(f"sender '{self._cfg.sender}' stopped")
                return

        # GPU readback happens only at the preview rate.
        wait = self.throttle.wait_time(now)
        if wait > 0:
            self.idle(min(wait, 0.02))
            return
        if self.throttle.ready(now):
            self._receive(now)

    def _sender_exists(self) -> bool:
        return self._cfg.sender in self._receiver.getSenderList()

    def _receive(self, now: float) -> None:
        receiver = self._receiver
        received = receiver.receiveImage(
            self._buffer, self._gl_rgba, self._cfg.flip_vertical, 0
        )
        if receiver.isUpdated():
            # The sender is new or changed size. The next pass reads into this buffer.
            width, height = receiver.getSenderWidth(), receiver.getSenderHeight()
            self._buffer = np.zeros((height, width, 4), dtype=np.uint8)
            self._last_frame_number = -1
            return
        if self._buffer is None:
            return
        if not received:
            self._detach(f"sender '{self._cfg.sender}' stopped sending")
            return

        counting = bool(receiver.isFrameCountEnabled())
        if not self._mode_logged:
            self._mode_logged = True
            mode = "frame-count" if counting else "none (a hung sender shows as LIVE - STILL)"
            self.log(logging.INFO, f"SPOUT feed={self.spec.worker_id} frame-detect mode={mode}")

        if counting:
            frame_number = receiver.getSenderFrame()
            if frame_number == self._last_frame_number:
                if (now - self._last_new_frame) * 1000 >= self.health.late_ms:
                    self.set_state("stalled", "sender is open but not producing frames")
                return
            self._last_frame_number = frame_number
        self._last_new_frame = now

        self.set_state("connected")
        self.publish(rgba_to_rgb(self._buffer), time.time_ns())

    def _detach(self, reason: str) -> None:
        self._attached = False
        self._buffer = None
        self._last_frame_number = -1
        if self._receiver is not None:
            self._receiver.releaseReceiver()
            self._receiver.setReceiverName(self._cfg.sender)
        self.set_state("disconnected", reason)
        self._next_attempt = time.monotonic() + self.health.reconnect_interval_ms / 1000

    def release(self) -> None:
        self._attached = False
        self._buffer = None
        self._last_frame_number = -1
        self._next_attempt = 0.0
        if self._receiver is not None:
            self._receiver.releaseReceiver()
            self._receiver = None
        if self._window is not None:
            self._glfw.destroy_window(self._window)
            self._window = None
