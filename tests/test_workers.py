"""Worker building blocks, including the Spout logic against a stand-in for SpoutGL."""

import queue
import sys
import types

import numpy as np
import pytest
import simplejpeg

from mvbridge.audio.meter import BlockMeter, PeakHold, measure, to_dbfs
from mvbridge.config import FeedConfig, HealthConfig, PerfLevel, SpoutConfig
from mvbridge.protocol import FrameMsg, LogMsg, StateMsg
from mvbridge.workers.base import Backoff, Channel, Throttle, WorkerSpec, redact, resize_area
from mvbridge.workers.rtsp import BacklogGate
from mvbridge.workers.spout import SpoutWorker, rgba_to_rgb


def count_passed(source_fps, target_fps, seconds=10, jitter=0.0):
    rng = np.random.default_rng(1)
    throttle = Throttle(target_fps)
    passed = 0
    for index in range(int(source_fps * seconds)):
        noise = rng.uniform(-jitter, jitter) if jitter else 0.0
        passed += throttle.ready(100 + index / source_fps + noise)
    return passed / seconds


@pytest.mark.parametrize(
    "source,target",
    [(30, 30), (60, 30), (30, 15), (30, 10), (30, 5)],
)
def test_throttle_reaches_the_target_rate(source, target):
    assert count_passed(source, target) == pytest.approx(target, abs=1)


def test_throttle_keeps_30_fps_with_network_jitter():
    assert count_passed(30, 30, jitter=0.012) >= 28


def test_backoff_doubles_to_the_limit_and_resets():
    backoff = Backoff(2, 6)
    assert [backoff.next_delay() for _ in range(4)] == [2, 4, 6, 6]
    backoff.reset()
    assert backoff.next_delay() == 2


def test_backlog_gate_passes_real_time_frames():
    gate = BacklogGate()
    assert not any(gate.is_stale(i / 30, 50 + i / 30) for i in range(300))


def test_backlog_gate_catches_a_burst_of_old_frames():
    gate = BacklogGate()
    for index in range(30):
        gate.is_stale(index / 30, 50 + index / 30)
    assert gate.is_stale(1.0, 50 + 1.0 + 0.5)


def test_redact_hides_credentials():
    assert redact("rtsp://admin:secret@10.0.0.5:554/2 failed") == "rtsp://***@10.0.0.5:554/2 failed"


def test_resize_area_returns_requested_size():
    image = np.zeros((536, 1152, 3), dtype=np.uint8)
    assert resize_area(image, 576, 268).shape == (268, 576, 3)


def test_rgba_opaque_keeps_colors():
    rgba = np.full((16, 16, 4), 255, dtype=np.uint8)
    rgba[..., 0] = 200
    assert rgba_to_rgb(rgba)[0, 0].tolist() == [200, 255, 255]


def test_rgba_transparent_composites_on_black():
    rgba = np.full((16, 16, 4), 200, dtype=np.uint8)
    rgba[..., 3] = 0
    assert rgba_to_rgb(rgba).max() == 0


def test_measure_full_scale_sine():
    samples = np.sin(np.linspace(0, 200 * np.pi, 48_000, endpoint=False))
    peak, rms = measure(samples)
    assert peak == pytest.approx(0, abs=0.01)
    assert rms == pytest.approx(-3.01, abs=0.05)


def test_measure_minus_12_dbfs_tone():
    tone = 10 ** (-12 / 20) * np.sin(np.linspace(0, 200 * np.pi, 48_000, endpoint=False))
    assert measure(tone)[0] == pytest.approx(-12, abs=0.05)


def test_silence_is_the_floor():
    assert measure(np.zeros(100))[0] == to_dbfs(0)


def test_peak_hold_lasts_1_5_seconds():
    hold = PeakHold()
    assert hold.update(-6, 0.0) == -6
    assert hold.update(-30, 1.4) == -6
    assert hold.update(-30, 1.6) == -30


def test_block_meter_makes_20_readings_per_second():
    meter = BlockMeter(48_000, 2, lambda: 0.0)
    assert len(list(meter.push(np.zeros(96_000, dtype=np.float32)))) == 20


# ----- Spout worker against a stand-in for the Windows library -----


class FakeReceiver:
    def __init__(self):
        self.senders = ["MV Center"]
        self.width, self.height = 960, 540
        self.updated = True
        self.counting = True
        self.frame = 1
        self.receive_ok = True
        self.released = 0

    def setReceiverName(self, name):
        self.name = name

    def getSenderList(self):
        return list(self.senders)

    def receiveImage(self, buffer, gl_format, invert, fbo):
        if buffer is not None:
            buffer[..., :3] = 90
            buffer[..., 3] = 255
        return self.receive_ok

    def isUpdated(self):
        updated, self.updated = self.updated, False
        return updated

    def getSenderWidth(self):
        return self.width

    def getSenderHeight(self):
        return self.height

    def isFrameCountEnabled(self):
        return self.counting

    def getSenderFrame(self):
        return self.frame

    def releaseReceiver(self):
        self.released += 1


class ListQueue(queue.Queue):
    def cancel_join_thread(self):
        pass


@pytest.fixture
def spout(monkeypatch):
    receiver = FakeReceiver()
    fake_glfw = types.SimpleNamespace(
        VISIBLE=1, FALSE=0, init=lambda: True, window_hint=lambda *a: None,
        create_window=lambda *a: object(), make_context_current=lambda w: None,
        destroy_window=lambda w: None,
    )
    fake_spout = types.SimpleNamespace(SpoutReceiver=lambda: receiver)
    monkeypatch.setattr("mvbridge.workers.spout._load_backend", lambda: (fake_glfw, fake_spout, 6408))
    feed = FeedConfig(id="center", label="C", type="spout", spout=SpoutConfig(sender="MV Center"))
    spec = WorkerSpec("center", "spout", HealthConfig(), (PerfLevel(fps=30, q=75, scale=1.0),), feed=feed)
    frames, events = ListQueue(), ListQueue()
    worker = SpoutWorker(spec, Channel(frames, events, None))
    return worker, receiver, frames, events


def drain(target):
    items = []
    while not target.empty():
        items.append(target.get_nowait())
    return items


def pump(worker, receiver=None, passes=3, advance=True):
    for _ in range(passes):
        worker.throttle._next = 0.0
        worker.step()
        if receiver is not None and advance:
            receiver.frame += 1


def test_spout_delivers_a_valid_jpeg(spout):
    worker, receiver, frames, _ = spout
    pump(worker, receiver)
    delivered = drain(frames)
    assert delivered and isinstance(delivered[0], FrameMsg)
    picture = simplejpeg.decode_jpeg(delivered[0].jpeg, colorspace="RGB")
    assert picture.shape == (540, 960, 3)
    assert worker.state == "connected"


def test_spout_missing_sender_reports_disconnected(spout):
    worker, receiver, frames, _ = spout
    receiver.senders = []
    worker.step()
    assert worker.state == "disconnected"
    assert "not found" in worker.detail
    assert not drain(frames)


def test_spout_sender_disappearing_is_detected(spout):
    worker, receiver, _, _ = spout
    pump(worker, receiver)
    receiver.senders = []
    worker._next_sender_check = 0.0
    worker.step()
    assert worker.state == "disconnected"
    assert receiver.released == 1


def test_spout_returns_when_the_sender_comes_back(spout):
    worker, receiver, frames, _ = spout
    receiver.senders = []
    worker.step()
    receiver.senders = ["MV Center"]
    receiver.updated = True
    worker._next_attempt = 0.0
    pump(worker, receiver, passes=4)
    assert worker.state == "connected"
    assert drain(frames)


def test_spout_hung_sender_goes_stalled_in_frame_count_mode(spout):
    worker, receiver, frames, _ = spout
    pump(worker, receiver)
    worker._next_sender_check = float("inf")
    pump(worker, receiver, passes=1, advance=False)  # Consume the last new frame.
    drain(frames)
    worker._last_new_frame = -100.0
    pump(worker, receiver, passes=2, advance=False)
    assert worker.state == "stalled"
    assert not drain(frames)


def test_spout_without_frame_count_keeps_publishing(spout):
    worker, receiver, frames, events = spout
    receiver.counting = False
    pump(worker, receiver, advance=False)
    assert worker.state == "connected"
    assert len(drain(frames)) >= 2
    logs = [item.message for item in drain(events) if isinstance(item, LogMsg)]
    assert any("frame-detect mode=none" in message for message in logs)


def test_spout_logs_frame_count_mode(spout):
    worker, receiver, _, events = spout
    pump(worker, receiver)
    logs = [item.message for item in drain(events) if isinstance(item, LogMsg)]
    assert any("frame-detect mode=frame-count" in message for message in logs)


def test_spout_release_lets_go_of_the_sender(spout):
    worker, receiver, _, events = spout
    pump(worker, receiver)
    worker.release()
    assert receiver.released == 1
    assert worker._receiver is None
    assert any(isinstance(item, StateMsg) for item in drain(events))


def test_no_windows_library_is_needed_to_import_the_worker():
    assert "SpoutGL" not in sys.modules
