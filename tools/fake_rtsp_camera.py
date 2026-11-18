"""A small RTSP-over-TCP test camera, used to rehearse camera loss without hardware.

Run it on its own and point a feed at the printed URL:
    python tools/fake_rtsp_camera.py --port 8554
"""

from __future__ import annotations

import argparse
import math
import socket
import struct
import threading
import time
from fractions import Fraction

import av
import numpy as np

_MAX_PAYLOAD = 1400


def _ulaw(sample: float) -> int:
    value = int(sample * 32635)
    sign = 0x80 if value < 0 else 0
    value = min(abs(value), 32635) + 0x84
    exponent = 7
    mask = 0x4000
    while exponent > 0 and not value & mask:
        exponent -= 1
        mask >>= 1
    mantissa = (value >> (exponent + 3)) & 0x0F
    return ~(sign | (exponent << 4) | mantissa) & 0xFF


# 20 ms of a 400 Hz tone at -12 dBFS.
_TONE = bytes(_ulaw(10 ** (-12 / 20) * math.sin(2 * math.pi * 400 * n / 8000)) for n in range(160))


def split_annexb(data: bytes) -> list[bytes]:
    nals = []
    position = data.find(b"\x00\x00\x01")
    while position != -1:
        start = position + 3
        following = data.find(b"\x00\x00\x01", start)
        end = len(data) if following == -1 else following
        nals.append(data[start:end].rstrip(b"\x00"))
        position = following
    return [nal for nal in nals if nal]


class _Session:
    def __init__(self, camera: "FakeCamera", connection: socket.socket) -> None:
        self.camera = camera
        self.connection = connection
        self.send_lock = threading.Lock()
        self.channels: dict[str, int] = {}
        self.playing = threading.Event()
        self.closed = threading.Event()

    def send(self, data: bytes) -> None:
        with self.send_lock:
            self.connection.sendall(data)

    def close(self) -> None:
        self.closed.set()
        try:
            self.connection.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.connection.close()

    def serve(self) -> None:
        streamer = threading.Thread(target=self._stream, daemon=True)
        streamer.start()
        buffer = b""
        try:
            while not self.closed.is_set():
                chunk = self.connection.recv(65536)
                if not chunk:
                    break
                buffer = self._consume(buffer + chunk)
        except OSError:
            pass
        finally:
            self.close()

    def _consume(self, buffer: bytes) -> bytes:
        while buffer:
            if buffer[0] == 0x24:  # Interleaved RTCP from the client.
                if len(buffer) < 4:
                    return buffer
                length = struct.unpack(">H", buffer[2:4])[0]
                if len(buffer) < 4 + length:
                    return buffer
                buffer = buffer[4 + length :]
                continue
            end = buffer.find(b"\r\n\r\n")
            if end == -1:
                return buffer
            self._answer(buffer[:end].decode("latin-1"))
            buffer = buffer[end + 4 :]
        return buffer

    def _answer(self, request: str) -> None:
        lines = request.split("\r\n")
        method, url = lines[0].split(" ")[:2]
        headers = {}
        for line in lines[1:]:
            key, _, value = line.partition(":")
            headers[key.strip().lower()] = value.strip()
        reply = [f"CSeq: {headers.get('cseq', '0')}"]
        body = ""
        status = "200 OK"
        if method == "OPTIONS":
            reply.append("Public: OPTIONS, DESCRIBE, SETUP, PLAY, TEARDOWN, GET_PARAMETER")
        elif method == "DESCRIBE":
            body = self.camera.sdp()
            reply += ["Content-Type: application/sdp", f"Content-Base: {url}/"]
        elif method == "SETUP":
            transport = headers.get("transport", "")
            if "TCP" not in transport.upper():
                status = "461 Unsupported Transport"
            else:
                interleaved = transport.split("interleaved=")[1].split(";")[0]
                track = "audio" if "trackID=1" in url else "video"
                self.channels[track] = int(interleaved.split("-")[0])
                reply += [f"Transport: RTP/AVP/TCP;unicast;interleaved={interleaved}", "Session: 1"]
        elif method == "PLAY":
            reply += ["Session: 1", "Range: npt=0.000-"]
        elif method == "TEARDOWN":
            reply.append("Session: 1")
        if body:
            reply.append(f"Content-Length: {len(body)}")
        text = f"RTSP/1.0 {status}\r\n" + "\r\n".join(reply) + "\r\n\r\n" + body
        self.send(text.encode("latin-1"))
        if method == "PLAY":
            self.playing.set()
        elif method == "TEARDOWN":
            self.closed.set()

    def _rtp(self, channel: int, payload_type: int, marker: bool, seq: int, stamp: int, ssrc: int,
             payload: bytes) -> None:
        second = payload_type | (0x80 if marker else 0)
        header = struct.pack(">BBHII", 0x80, second, seq & 0xFFFF, stamp & 0xFFFFFFFF, ssrc)
        packet = header + payload
        self.send(b"$" + bytes([channel]) + struct.pack(">H", len(packet)) + packet)

    def _stream(self) -> None:
        if not self.playing.wait(10):
            return
        cam = self.camera
        encoder = av.CodecContext.create("libx264", "w")
        encoder.width, encoder.height = cam.width, cam.height
        encoder.pix_fmt = "yuv420p"
        encoder.time_base = Fraction(1, cam.fps)
        encoder.framerate = Fraction(cam.fps, 1)
        encoder.options = {
            "preset": "ultrafast",
            "tune": "zerolatency",
            "x264-params": "keyint=15:min-keyint=15:scenecut=0:repeat-headers=1:annexb=1",
        }
        video_seq = audio_seq = 0
        audio_sent = 0
        started = time.monotonic()
        index = 0
        try:
            while not self.closed.is_set() and not cam.stopping.is_set():
                target = started + index / cam.fps
                delay = target - time.monotonic()
                if delay > 0:
                    time.sleep(delay)
                if cam.frozen.is_set():
                    index += 1
                    continue
                picture = np.full((cam.height, cam.width, 3), 60, dtype=np.uint8)
                left = int((index % cam.fps) / cam.fps * (cam.width - 40))
                picture[:, left : left + 40] = 255
                frame = av.VideoFrame.from_ndarray(picture, format="rgb24").reformat(format="yuv420p")
                frame.pts = index
                frame.time_base = encoder.time_base
                stamp = int(index * 90000 / cam.fps)
                for packet in encoder.encode(frame):
                    nals = split_annexb(bytes(packet))
                    for position, nal in enumerate(nals):
                        video_seq = self._send_nal(nal, position == len(nals) - 1, video_seq, stamp)
                if cam.audio and "audio" in self.channels:
                    due = int((time.monotonic() - started) * 50)
                    while audio_sent < due:
                        self._rtp(self.channels["audio"], 0, False, audio_seq, audio_sent * 160, 2, _TONE)
                        audio_seq += 1
                        audio_sent += 1
                index += 1
        except OSError:
            pass

    def _send_nal(self, nal: bytes, last: bool, seq: int, stamp: int) -> int:
        channel = self.channels["video"]
        if len(nal) <= _MAX_PAYLOAD:
            self._rtp(channel, 96, last, seq, stamp, 1, nal)
            return seq + 1
        indicator = (nal[0] & 0xE0) | 28
        kind = nal[0] & 0x1F
        body = nal[1:]
        for offset in range(0, len(body), _MAX_PAYLOAD):
            piece = body[offset : offset + _MAX_PAYLOAD]
            first = offset == 0
            final = offset + _MAX_PAYLOAD >= len(body)
            fu_header = kind | (0x80 if first else 0) | (0x40 if final else 0)
            self._rtp(channel, 96, last and final, seq, stamp, 1, bytes([indicator, fu_header]) + piece)
            seq += 1
        return seq


class FakeCamera:
    def __init__(self, port: int = 0, width: int = 640, height: int = 360, fps: int = 30,
                 audio: bool = True) -> None:
        self.port = port
        self.width, self.height, self.fps = width, height, fps
        self.audio = audio
        self.frozen = threading.Event()
        self.stopping = threading.Event()
        self._listener: socket.socket | None = None
        self._sessions: list[_Session] = []

    @property
    def url(self) -> str:
        return f"rtsp://127.0.0.1:{self.port}/2"

    def sdp(self) -> str:
        lines = [
            "v=0", "o=- 0 0 IN IP4 127.0.0.1", "s=Fake PTZ", "c=IN IP4 0.0.0.0", "t=0 0", "a=control:*",
            "m=video 0 RTP/AVP 96", "a=rtpmap:96 H264/90000", "a=fmtp:96 packetization-mode=1",
            "a=control:trackID=0",
        ]
        if self.audio:
            lines += ["m=audio 0 RTP/AVP 0", "a=rtpmap:0 PCMU/8000", "a=control:trackID=1"]
        return "\r\n".join(lines) + "\r\n"

    def start(self) -> "FakeCamera":
        self.stopping.clear()
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", self.port))
        listener.listen(4)
        self.port = listener.getsockname()[1]
        self._listener = listener
        threading.Thread(target=self._accept, args=(listener,), daemon=True).start()
        return self

    def _accept(self, listener: socket.socket) -> None:
        while not self.stopping.is_set():
            try:
                connection, _ = listener.accept()
            except OSError:
                return
            connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            session = _Session(self, connection)
            self._sessions.append(session)
            threading.Thread(target=session.serve, daemon=True).start()

    def stop(self) -> None:
        """Behaves like a camera losing power: every connection drops at once."""
        self.stopping.set()
        if self._listener is not None:
            self._listener.close()
            self._listener = None
        for session in self._sessions:
            session.close()
        self._sessions.clear()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8554)
    parser.add_argument("--no-audio", action="store_true")
    args = parser.parse_args()
    camera = FakeCamera(port=args.port, audio=not args.no_audio).start()
    print(f"Fake camera ready at {camera.url} (Ctrl+C to stop)")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        camera.stop()


if __name__ == "__main__":
    main()
