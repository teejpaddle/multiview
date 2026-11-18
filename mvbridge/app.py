"""FastAPI application: the page, the frame and status sockets, and the control API."""

from __future__ import annotations

import asyncio
import json
import os
import time
from contextlib import asynccontextmanager
from typing import Literal, Optional

from fastapi import FastAPI, HTTPException, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict

from . import PROJECT_ROOT, __version__
from .config import MultiviewConfig
from .framebus import FrameBus, Subscriber
from .health import StatusStore
from .perf import PerfMonitor
from .priority import set_below_normal
from .supervisor import Supervisor
from .timer import CountdownTimer, TimerError
from .workers.base import WorkerSpec

WEB_DIR = PROJECT_ROOT / "web"
STATUS_INTERVAL_S = 0.1
METER_INTERVAL_S = 0.05


def build_worker_specs(cfg: MultiviewConfig) -> list[WorkerSpec]:
    levels = tuple(cfg.perf.levels)
    specs = [
        WorkerSpec(feed.id, feed.type, cfg.health_for(feed), levels, feed=feed)
        for feed in cfg.feed
    ]
    show = cfg.audio.show
    if show.enabled:
        kind = "wasapi_loopback" if show.source == "wasapi_loopback" else "synthetic_audio"
        specs.append(WorkerSpec("audio-show", kind, cfg.health, levels, audio=show))
    return specs


class LocalOnlyMiddleware:
    """Rejects requests from other sites, so a web page cannot control the bridge."""

    def __init__(self, app, port: int) -> None:
        self._app = app
        self._hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
        self._origins = {f"http://{host}" for host in self._hosts}

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self._app(scope, receive, send)
            return
        headers = {key.decode("latin-1"): value.decode("latin-1") for key, value in scope["headers"]}
        origin = headers.get("origin")
        if headers.get("host") in self._hosts and (origin is None or origin in self._origins):
            await self._app(scope, receive, send)
        elif scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
        else:
            await Response("Forbidden", status_code=403)(scope, receive, send)


class _NoCacheStatic(StaticFiles):
    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


class PreviewsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    paused: bool


class TimerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["start", "pause", "reset", "set_duration", "set_target"]
    value: Optional[float] = None


class Bridge:
    """Everything the routes share while the server is running."""

    def __init__(self, cfg: MultiviewConfig) -> None:
        self.cfg = cfg
        self.started = time.monotonic()
        feed_ids = [feed.id for feed in cfg.feed]
        self.bus = FrameBus(feed_ids)
        self.store = StatusStore({feed.id: cfg.health_for(feed) for feed in cfg.feed})
        self.timer = CountdownTimer(PROJECT_ROOT / "state" / "timer.json")
        self.supervisor = Supervisor(build_worker_specs(cfg), self.bus, self.store)
        self.perf = PerfMonitor(cfg.perf, self.supervisor.set_level)
        self.clients: set[Subscriber] = set()
        self.paused = False

    def set_paused(self, paused: bool) -> None:
        self.paused = paused
        self.store.paused = paused
        self.supervisor.set_paused(paused)

    def status(self) -> dict:
        return {
            "type": "status",
            "t": time.time_ns() // 1_000_000,
            "feeds": self.store.feeds_snapshot(),
            "meters": self.store.meters_snapshot(),
            "perf": {**self.perf.snapshot(), "paused": self.paused},
            "timer": self.timer.snapshot(),
        }

    def public_config(self) -> dict:
        """What the page needs. Camera URLs and sender names stay on the server."""
        cfg = self.cfg
        cam_feed = next(
            (
                feed.id
                for feed in cfg.feed
                if (feed.rtsp and feed.rtsp.audio_meter)
                or (feed.synthetic and feed.synthetic.audio_meter)
            ),
            None,
        )
        show = cfg.audio.show
        return {
            "title": cfg.ui.title,
            "clock_24h": cfg.ui.clock_24h,
            "countdown_warn_s": cfg.ui.countdown_warn_s,
            "layout": cfg.ui.layout,
            "meters": {"show": show.attach_to_feed if show.enabled else None, "cam": cam_feed},
            "feeds": [
                {
                    "id": feed.id,
                    "label": feed.label,
                    "late_ms": cfg.health_for(feed).late_ms,
                    "lost_ms": cfg.health_for(feed).lost_ms,
                    "restored_flash_ms": cfg.health_for(feed).restored_flash_ms,
                }
                for feed in cfg.feed
            ],
        }


async def _publish_loop(bridge: Bridge) -> None:
    ticks = 0
    interval_ms = int(METER_INTERVAL_S * 1000)
    status_every = round(STATUS_INTERVAL_S / METER_INTERVAL_S)
    while True:
        await asyncio.sleep(interval_ms / 1000)
        bridge.store.tick()
        ticks += 1
        if not bridge.clients:
            continue
        meters = json.dumps({"type": "meters", "meters": bridge.store.meters_snapshot()})
        status = json.dumps(bridge.status()) if ticks % status_every == 0 else None
        for client in list(bridge.clients):
            client.offer(meters, "meters")
            if status is not None:
                client.offer(status, "status")


async def _serve_subscriber(websocket: WebSocket, subscriber: Subscriber) -> None:
    """Send messages until the browser disconnects."""

    async def watch_disconnect() -> None:
        try:
            while (await websocket.receive())["type"] != "websocket.disconnect":
                pass
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            subscriber.close()

    watcher = asyncio.create_task(watch_disconnect())
    try:
        while (message := await subscriber.next()) is not None:
            if isinstance(message, bytes):
                await websocket.send_bytes(message)
            else:
                await websocket.send_text(message)
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        watcher.cancel()


def create_app(cfg: MultiviewConfig) -> FastAPI:
    bridge = Bridge(cfg)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        set_below_normal()
        bridge.supervisor.start()
        bridge.perf.start()
        publisher = asyncio.create_task(_publish_loop(bridge))
        try:
            yield
        finally:
            publisher.cancel()
            bridge.perf.stop()
            await asyncio.to_thread(bridge.supervisor.stop)

    app = FastAPI(title="Show Multiview", version=__version__, lifespan=lifespan, docs_url=None,
                  redoc_url=None, openapi_url=None)
    app.state.bridge = bridge
    app.add_middleware(LocalOnlyMiddleware, port=cfg.server.port)

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(WEB_DIR / "index.html", headers={"Cache-Control": "no-cache"})

    @app.get("/api/config")
    async def api_config() -> dict:
        return bridge.public_config()

    @app.get("/api/status")
    async def api_status() -> dict:
        return bridge.status()

    @app.get("/healthz")
    async def healthz() -> dict:
        feeds = bridge.store.feeds_snapshot()
        return {
            "ok": True,
            "version": __version__,
            "pid": os.getpid(),
            "uptime_s": round(time.monotonic() - bridge.started, 1),
            "paused": bridge.paused,
            "feeds": {feed_id: feed["tile_state"] for feed_id, feed in feeds.items()},
        }

    @app.get("/api/snapshot/{feed_id}.jpg")
    async def snapshot(feed_id: str) -> Response:
        if feed_id not in bridge.bus:
            raise HTTPException(404, "unknown feed")
        frame = bridge.bus.latest(feed_id)
        if frame is None:
            raise HTTPException(404, "no frame received yet")
        return Response(frame.jpeg, media_type="image/jpeg", headers={"Cache-Control": "no-store"})

    @app.post("/api/previews")
    async def previews(request: PreviewsRequest) -> dict:
        await asyncio.to_thread(bridge.set_paused, request.paused)
        return {"paused": bridge.paused}

    @app.post("/api/timer")
    async def timer(request: TimerRequest) -> dict:
        try:
            return bridge.timer.apply(request.action, request.value)
        except TimerError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.websocket("/ws/feed/{feed_id}")
    async def ws_feed(websocket: WebSocket, feed_id: str) -> None:
        if feed_id not in bridge.bus:
            await websocket.close(code=4404)
            return
        await websocket.accept()
        subscriber = bridge.bus.subscribe(feed_id, asyncio.get_running_loop())
        try:
            await _serve_subscriber(websocket, subscriber)
        finally:
            bridge.bus.unsubscribe(feed_id, subscriber)

    @app.websocket("/ws/status")
    async def ws_status(websocket: WebSocket) -> None:
        await websocket.accept()
        subscriber = Subscriber(asyncio.get_running_loop())
        subscriber.offer(json.dumps(bridge.status()), "status")
        bridge.clients.add(subscriber)
        try:
            await _serve_subscriber(websocket, subscriber)
        finally:
            bridge.clients.discard(subscriber)
            subscriber.close()

    app.mount("/css", _NoCacheStatic(directory=WEB_DIR / "css"), name="css")
    app.mount("/js", _NoCacheStatic(directory=WEB_DIR / "js"), name="js")
    return app
