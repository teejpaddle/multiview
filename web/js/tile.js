// One preview tile: picture, label, status chip and frame ticker.

import { FeedSocket } from "./feedSocket.js";
import { STYLE, State, TileMachine, chipText } from "./tileState.js";

const TICKER_SEGMENTS = 8;

export class Tile {
  constructor(feed) {
    this.feed = feed;
    this.machine = new TileMachine(feed, Date.now());
    this.source = { source_state: "connecting", detail: "", static: false, black: false, static_s: 0 };
    this.bitmap = null;
    this.dirty = false;
    this.arrivals = [];
    this.pipelineMs = 0;
    this.tickerPosition = 0;
    this.tickerDirty = true;
    this.chipValue = "";

    this.element = document.createElement("section");
    this.element.className = "tile";
    this.element.dataset.feed = feed.id;
    this.element.setAttribute("aria-label", feed.label);
    this.element.innerHTML = `
      <div class="tile__stage">
        <canvas class="tile__picture"></canvas>
        <div class="tile__banner">NO SIGNAL</div>
        <div class="tile__label"></div>
        <div class="tile__chip" role="status"></div>
        <canvas class="tile__ticker" width="68" height="68" aria-hidden="true"></canvas>
        <div class="tile__glyph" aria-hidden="true">❚❚</div>
      </div>`;
    this.stage = this.element.querySelector(".tile__stage");
    this.canvas = this.element.querySelector(".tile__picture");
    this.context = this.canvas.getContext("2d", { alpha: false });
    this.chip = this.element.querySelector(".tile__chip");
    this.ticker = this.element.querySelector(".tile__ticker").getContext("2d");
    this.element.querySelector(".tile__label").textContent = feed.label;

    this.socket = new FeedSocket(feed.id, {
      onOpen: () => this.machine.onOpen(Date.now()),
      onFrame: (header) => this.frameArrived(header),
      onPicture: (bitmap) => this.showPicture(bitmap),
    });
  }

  addMeter(meter) {
    this.element.append(meter.element);
  }

  frameArrived(header) {
    const now = Date.now();
    this.machine.onFrame(now);
    this.arrivals.push(now);
    const sample = Math.max(0, now - header.captureMs);
    this.pipelineMs = this.pipelineMs ? this.pipelineMs * 0.9 + sample * 0.1 : sample;
    this.tickerPosition = (this.tickerPosition + 1) % TICKER_SEGMENTS;
    this.tickerDirty = true;
  }

  showPicture(bitmap) {
    this.bitmap?.close();
    this.bitmap = bitmap;
    this.dirty = true;
  }

  setSource(source) {
    if (source) this.source = source;
  }

  measuredFps(now) {
    while (this.arrivals.length && now - this.arrivals[0] > 1000) this.arrivals.shift();
    return this.arrivals.length;
  }

  render(now, { paused, offline }) {
    const { source } = this;
    const state = this.machine.update(now, {
      sourceState: source.source_state,
      isStatic: source.static,
      black: source.black,
      paused,
      offline,
    });

    const style = STYLE[state];
    if (this.element.dataset.state !== style) this.element.dataset.state = style;

    const text = chipText(state, {
      fps: this.measuredFps(now),
      pipelineMs: this.pipelineMs,
      ageMs: this.machine.ageMs(now) ?? 0,
      stillS: source.static_s,
      lostMs: this.machine.lostSince === null ? 0 : now - this.machine.lostSince,
      detail: state === State.NO_SIGNAL ? source.detail : "",
    });
    if (text !== this.chipValue) {
      this.chipValue = text;
      this.chip.textContent = text;
    }

    if (this.dirty) this.drawPicture();
    if (this.tickerDirty) this.drawTicker();
  }

  drawPicture() {
    const { bitmap, canvas } = this;
    this.dirty = false;
    if (canvas.width !== bitmap.width || canvas.height !== bitmap.height) {
      canvas.width = bitmap.width;
      canvas.height = bitmap.height;
    }
    this.context.drawImage(bitmap, 0, 0);
  }

  // The ring keeps turning only while frames arrive, even if the picture looks plausible.
  drawTicker() {
    this.tickerDirty = false;
    const context = this.ticker;
    const center = 34;
    context.clearRect(0, 0, 68, 68);
    context.beginPath();
    context.arc(center, center, 33, 0, Math.PI * 2);
    context.fillStyle = "#000";
    context.fill();
    context.lineWidth = 12;
    const gap = 0.14;
    for (let index = 0; index < TICKER_SEGMENTS; index += 1) {
      const start = (index / TICKER_SEGMENTS) * Math.PI * 2 - Math.PI / 2;
      context.beginPath();
      context.arc(center, center, 23, start + gap, start + (Math.PI * 2) / TICKER_SEGMENTS - gap);
      context.strokeStyle = index === this.tickerPosition ? "#ffffff" : "#3b444e";
      context.stroke();
    }
  }
}
