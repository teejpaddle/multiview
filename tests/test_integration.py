"""End-to-end tests with real worker processes, sockets and a fake RTSP camera."""

import time

import pytest
import simplejpeg
from fastapi.testclient import TestClient

from fake_rtsp_camera import FakeCamera
from mvbridge.app import create_app
from mvbridge.config import parse_config
from mvbridge.protocol import unpack_frame

BASE = "http://127.0.0.1:8090"


def synthetic(feed_id, **options):
    return {
        "id": feed_id,
        "label": feed_id.upper(),
        "type": "synthetic",
        "synthetic": options,
        "preview": {"width": 320, "height": 180, "fps": 30, "jpeg_quality": 60},
    }


def make_config(feeds):
    return parse_config(
        {"audio": {"show": {"source": "synthetic", "attach_to_feed": feeds[0]["id"]}}, "feed": feeds}
    )


@pytest.fixture
def client_for(tmp_path, monkeypatch):
    monkeypatch.setattr("mvbridge.app.PROJECT_ROOT", tmp_path)
    clients = []

    def start(feeds):
        client = TestClient(create_app(make_config(feeds)), base_url=BASE)
        client.__enter__()
        clients.append(client)
        return client

    yield start
    for client in clients:
        client.__exit__(None, None, None)


def wait_for(client, predicate, timeout=20.0):
    deadline = time.monotonic() + timeout
    status = None
    while time.monotonic() < deadline:
        status = client.get("/api/status").json()
        if predicate(status):
            return status
        time.sleep(0.05)
    raise AssertionError(f"condition not met within {timeout} s; last status: {status}")


def tile(feed_id, *states):
    return lambda status: status["feeds"][feed_id]["tile_state"] in states


def three(**first):
    return [synthetic("center", **first), synthetic("side"), synthetic("ptz", audio_meter="cam")]


def test_page_api_frames_and_pause(client_for):
    client = client_for(three())
    for feed_id in ("center", "side", "ptz"):
        wait_for(client, tile(feed_id, "LIVE"))

    assert "<title>" in client.get("/").text
    assert client.get("/js/main.js").status_code == 200
    config = client.get("/api/config").json()
    assert [feed["id"] for feed in config["feeds"]] == ["center", "side", "ptz"]
    assert client.get("/healthz").json()["ok"] is True

    snapshot = client.get("/api/snapshot/center.jpg")
    assert simplejpeg.decode_jpeg(snapshot.content, colorspace="RGB").shape == (180, 320, 3)
    assert client.get("/api/snapshot/nope.jpg").status_code == 404

    with client.websocket_connect("/ws/feed/side", headers={"host": "127.0.0.1:8090"}) as socket:
        first, jpeg = unpack_frame(socket.receive_bytes())
        second, _ = unpack_frame(socket.receive_bytes())
    assert (first.width, first.height) == (320, 180)
    assert second.seq > first.seq
    assert jpeg[:2] == b"\xff\xd8"

    status = wait_for(client, lambda s: s["feeds"]["center"]["fps"] >= 25)
    assert status["feeds"]["center"]["fps"] <= 35
    meters = wait_for(client, lambda s: "show" in s["meters"] and "cam" in s["meters"])["meters"]
    assert meters["show"]["peak_db"] == pytest.approx(-12, abs=0.5)

    assert client.post("/api/previews", json={"paused": True}).json() == {"paused": True}
    wait_for(client, tile("center", "PAUSED"), timeout=1.0)
    wait_for(client, lambda s: s["feeds"]["center"]["source_state"] == "paused", timeout=2.0)
    client.post("/api/previews", json={"paused": False})
    wait_for(client, tile("center", "LIVE"), timeout=3.0)


def test_timer_api(client_for):
    client = client_for(three())
    assert client.post("/api/timer", json={"action": "set_duration", "value": 60000}).status_code == 200
    assert client.post("/api/timer", json={"action": "start"}).json()["mode"] == "running"
    refused = client.post("/api/timer", json={"action": "set_duration", "value": 1000})
    assert refused.status_code == 409
    assert client.post("/api/timer", json={"action": "bogus"}).status_code == 422
    assert client.post("/api/timer", json={"action": "reset"}).json()["mode"] == "idle"


def test_other_websites_cannot_control_the_bridge(client_for):
    client = client_for(three())
    hostile = client.post(
        "/api/previews", json={"paused": True}, headers={"Origin": "https://example.com"}
    )
    assert hostile.status_code == 403
    assert client.get("/healthz", headers={"Host": "evil.example:8090"}).status_code == 403
    assert client.get("/healthz").json()["paused"] is False


def test_config_never_exposes_camera_url(client_for, monkeypatch):
    feeds = [
        synthetic("center"),
        synthetic("side"),
        {"id": "ptz", "label": "PTZ", "type": "rtsp",
         "rtsp": {"url": "rtsp://admin:hunter2@127.0.0.1:9/2"},
         "preview": {"width": 320, "height": 180}},
    ]
    client = client_for(feeds)
    assert "hunter2" not in client.get("/api/config").text
    status = wait_for(client, lambda s: s["feeds"]["ptz"]["source_state"] == "disconnected")
    assert "hunter2" not in str(status)


def test_scripted_dropout_goes_lost_then_restored(client_for):
    client = client_for(three(dropout_after_s=3, dropout_for_s=4))
    wait_for(client, tile("center", "LIVE"))
    wait_for(client, tile("center", "NO_SIGNAL"))
    wait_for(client, tile("center", "RESTORED"), timeout=8)
    wait_for(client, tile("center", "LIVE"), timeout=5)
    status = client.get("/api/status").json()
    assert status["feeds"]["side"]["tile_state"] == "LIVE"


def test_frozen_and_black_pictures_stay_green(client_for):
    feeds = [
        synthetic("center", freeze_picture_after_s=1, freeze_picture_for_s=30),
        synthetic("side", black_picture_after_s=1, black_picture_for_s=30),
        synthetic("ptz"),
    ]
    client = client_for(feeds)
    wait_for(client, tile("side", "LIVE_BLACK"), timeout=12)
    wait_for(client, tile("center", "LIVE_STILL"), timeout=20)


def test_crashed_worker_is_restarted(client_for):
    client = client_for(three(crash_after_s=2))
    wait_for(client, tile("center", "LIVE"))
    status = wait_for(client, lambda s: s["feeds"]["center"]["source_state"] == "error")
    assert "exited" in status["feeds"]["center"]["detail"]
    assert status["feeds"]["side"]["source_state"] == "connected"
    wait_for(client, tile("center", "RESTORED", "LIVE"), timeout=12)


def test_camera_loss_and_recovery_meet_t2_limits(client_for):
    camera = FakeCamera().start()
    feeds = [
        synthetic("center"),
        synthetic("side"),
        {"id": "ptz", "label": "PTZ", "type": "rtsp", "rtsp": {"url": camera.url},
         "preview": {"width": 320, "height": 180, "fps": 30}},
    ]
    client = client_for(feeds)
    try:
        wait_for(client, tile("ptz", "LIVE"), timeout=15)
        status = wait_for(client, lambda s: s["feeds"]["ptz"]["fps"] >= 25, timeout=10)
        assert status["feeds"]["ptz"]["w"] == 320
        cam = wait_for(client, lambda s: s["meters"].get("cam", {}).get("state") == "ok", timeout=10)
        assert cam["meters"]["cam"]["peak_db"] == pytest.approx(-12, abs=2)

        camera.stop()
        lost_at = time.monotonic()
        wait_for(client, tile("ptz", "LATE", "NO_SIGNAL"), timeout=1.5)
        wait_for(client, tile("ptz", "NO_SIGNAL"), timeout=3.5)
        assert time.monotonic() - lost_at <= 3.6
        assert client.get("/api/status").json()["feeds"]["center"]["tile_state"] == "LIVE"

        time.sleep(8)  # Long enough for the retry delay to reach its maximum.
        camera.start()
        restored_at = time.monotonic()
        wait_for(client, tile("ptz", "RESTORED", "LIVE"), timeout=10)
        assert time.monotonic() - restored_at <= 10
    finally:
        camera.stop()


def test_camera_frozen_stream_is_detected_and_recovers(client_for):
    camera = FakeCamera(audio=False).start()
    feeds = [
        synthetic("center"),
        synthetic("side"),
        {"id": "ptz", "label": "PTZ", "type": "rtsp", "rtsp": {"url": camera.url},
         "preview": {"width": 320, "height": 180}},
    ]
    client = client_for(feeds)
    try:
        wait_for(client, tile("ptz", "LIVE"), timeout=15)
        assert wait_for(client, lambda s: "cam" in s["meters"], timeout=5)["meters"]["cam"]["state"] == "no_track"
        camera.frozen.set()
        wait_for(client, tile("ptz", "LATE"), timeout=2)
        wait_for(client, tile("ptz", "NO_SIGNAL"), timeout=5)
        camera.frozen.clear()
        wait_for(client, tile("ptz", "RESTORED", "LIVE"), timeout=12)
    finally:
        camera.stop()
