// Page start-up and the render loop.

import { ClockPanel } from "./clock.js";
import { Meter } from "./meter.js";
import { StatusSocket } from "./statusSocket.js";
import { Tile } from "./tile.js";

const OFFLINE_TEXT = "MULTIVIEW SERVER OFFLINE – reconnecting";

async function loadConfig() {
  const status = document.getElementById("server-status");
  for (;;) {
    try {
      const response = await fetch("/api/config", { cache: "no-store" });
      if (response.ok) return await response.json();
    } catch {
      // The bridge is still starting.
    }
    document.getElementById("bar").dataset.offline = "true";
    status.textContent = OFFLINE_TEXT;
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }
}

function formatPercent(label, value) {
  return value === null || value === undefined ? "" : `${label} ${Math.round(value)}%`;
}

async function start() {
  const config = await loadConfig();
  document.title = config.title;
  document.getElementById("title").textContent = config.title;

  const bar = document.getElementById("bar");
  const serverStatus = document.getElementById("server-status");
  const levelBadge = document.getElementById("level");
  const perfText = document.getElementById("perf");
  const pauseButton = document.getElementById("pause");
  const grid = document.getElementById("grid");
  const clockPanel = document.getElementById("clock");

  const tiles = config.feeds.map((feed) => new Tile(feed));
  tiles.forEach((tile) => grid.insertBefore(tile.element, clockPanel));

  const meters = {};
  for (const [key, name] of [["show", "SHOW"], ["cam", "CAM"]]) {
    const tile = tiles.find((item) => item.feed.id === config.meters[key]);
    if (tile) {
      meters[key] = new Meter(name);
      tile.addMeter(meters[key]);
      meters[key].update(null);
    }
  }

  const clock = new ClockPanel({ use24h: config.clock_24h, warnSeconds: config.countdown_warn_s });
  let paused = false;
  let pauseRequests = 0;
  let pauseHoldUntil = 0;

  const updateMeters = (values) => {
    for (const [key, meter] of Object.entries(meters)) meter.update(values[key]);
  };

  const applyPaused = (value) => {
    paused = value;
    pauseButton.setAttribute("aria-pressed", String(value));
    pauseButton.firstChild.textContent = value ? "Resume Previews " : "Pause Previews ";
  };

  const status = new StatusSocket({
    onMeters: updateMeters,
    onStatus: (message) => {
      tiles.forEach((tile) => tile.setSource(message.feeds[tile.feed.id]));
      updateMeters(message.meters);
      clock.setTimer(message.timer);
      // A status sent before the operator's click must not undo that click.
      if (pauseRequests === 0 && performance.now() >= pauseHoldUntil) applyPaused(message.perf.paused);
      const level = message.perf.level;
      levelBadge.hidden = level === 0;
      levelBadge.textContent = `PREVIEW REDUCED – L${level}`;
      perfText.textContent = [
        formatPercent("CPU", message.perf.cpu),
        formatPercent("GPU", message.perf.gpu3d),
      ].filter(Boolean).join("  ");
    },
  });

  const togglePause = async () => {
    const next = !paused;
    applyPaused(next);
    pauseRequests += 1;
    try {
      const response = await fetch("/api/previews", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ paused: next }),
      });
      if (!response.ok) applyPaused(!next);
    } catch {
      applyPaused(!next);
    } finally {
      pauseRequests -= 1;
      pauseHoldUntil = performance.now() + 300;
    }
  };
  pauseButton.addEventListener("click", () => {
    pauseButton.blur();
    togglePause();
  });

  document.addEventListener("keydown", (event) => {
    if (event.repeat || event.ctrlKey || event.metaKey || event.altKey) return;
    if (event.target instanceof HTMLInputElement) return;
    if (event.code === "Space") {
      event.preventDefault();
      clock.toggle();
    } else if (event.key === "r" || event.key === "R") {
      clock.reset();
    } else if (event.key === "p" || event.key === "P") {
      togglePause();
    }
  });

  const frame = () => {
    const now = Date.now();
    const offline = status.offline;
    if (offline && bar.dataset.offline !== "true") {
      Object.values(meters).forEach((meter) => meter.update(null));
      perfText.textContent = "";
    }
    bar.dataset.offline = String(offline);
    const text = offline ? OFFLINE_TEXT : "SERVER OK";
    if (serverStatus.textContent !== text) serverStatus.textContent = text;
    serverStatus.dataset.ok = String(!offline);
    tiles.forEach((tile) => tile.render(now, { paused, offline }));
    clock.render(now);
    requestAnimationFrame(frame);
  };
  requestAnimationFrame(frame);
}

start();
