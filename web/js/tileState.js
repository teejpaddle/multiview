// What each tile shows. Must match TileMachine in mvbridge/health.py.
// Both are checked against tests/vectors/tile_states.json.

export const State = Object.freeze({
  CONNECTING: "CONNECTING",
  LIVE: "LIVE",
  LIVE_STILL: "LIVE_STILL",
  LIVE_BLACK: "LIVE_BLACK",
  LATE: "LATE",
  NO_SIGNAL: "NO_SIGNAL",
  RESTORED: "RESTORED",
  PAUSED: "PAUSED",
  SERVER_OFFLINE: "SERVER_OFFLINE",
});

export class TileMachine {
  constructor({ late_ms, lost_ms, restored_flash_ms }, nowMs) {
    this.lateMs = late_ms;
    this.lostMs = lost_ms;
    this.flashMs = restored_flash_ms;
    this.base = nowMs;
    this.lastFrame = null;
    this.wasLost = false;
    this.wasPaused = false;
    this.restoredUntil = null;
    this.lostSince = null;
    this.state = State.CONNECTING;
  }

  onOpen(nowMs) {
    if (this.lastFrame === null) this.base = nowMs;
  }

  onFrame(nowMs) {
    this.lastFrame = nowMs;
  }

  ageMs(nowMs) {
    return this.lastFrame === null ? null : nowMs - this.lastFrame;
  }

  markLost() {
    this.wasLost = true;
    if (this.lostSince === null) {
      this.lostSince = this.lastFrame !== null ? this.lastFrame : this.base;
    }
  }

  update(nowMs, input = {}) {
    this.state = this.evaluate(nowMs, input);
    return this.state;
  }

  evaluate(now, { sourceState = "connecting", isStatic = false, black = false, paused = false, offline = false }) {
    if (offline) {
      this.markLost();
      return State.SERVER_OFFLINE;
    }
    if (paused) {
      this.wasPaused = true;
      return State.PAUSED;
    }
    if (this.wasPaused) {
      // Frames from before the pause say nothing about the feed now.
      this.wasPaused = false;
      this.lastFrame = null;
      this.base = now;
      this.wasLost = false;
      this.restoredUntil = null;
      this.lostSince = null;
    }

    const sourceLost = sourceState === "disconnected" || sourceState === "error";
    if (this.lastFrame === null) {
      if (sourceLost || now - this.base >= this.lostMs) {
        this.markLost();
        return State.NO_SIGNAL;
      }
      return State.CONNECTING;
    }

    const age = now - this.lastFrame;
    if (sourceLost || age >= this.lostMs) {
      this.markLost();
      return State.NO_SIGNAL;
    }
    if (age >= this.lateMs || sourceState === "stalled") return State.LATE;

    if (this.wasLost) {
      this.wasLost = false;
      this.lostSince = null;
      this.restoredUntil = now + this.flashMs;
    }
    if (this.restoredUntil !== null) {
      if (now < this.restoredUntil) return State.RESTORED;
      this.restoredUntil = null;
    }
    if (black) return State.LIVE_BLACK;
    if (isStatic) return State.LIVE_STILL;
    return State.LIVE;
  }
}

export function formatElapsed(ms) {
  const total = Math.max(0, Math.floor(ms / 1000));
  const minutes = Math.floor(total / 60);
  return `${minutes}:${String(total % 60).padStart(2, "0")}`;
}

// The CSS state name for each tile state.
export const STYLE = Object.freeze({
  CONNECTING: "connecting",
  LIVE: "live",
  LIVE_STILL: "still",
  LIVE_BLACK: "black",
  LATE: "late",
  NO_SIGNAL: "lost",
  RESTORED: "restored",
  PAUSED: "paused",
  SERVER_OFFLINE: "lost",
});

// Status is always written out, because the test content itself is red and blue.
export function chipText(state, { fps = 0, pipelineMs = 0, ageMs = 0, stillS = 0, lostMs = 0, detail = "" } = {}) {
  switch (state) {
    case State.LIVE:
      return `LIVE · ${Math.round(fps)} fps · ${Math.round(pipelineMs)} ms`;
    case State.LIVE_STILL:
      return `LIVE · STILL ${formatElapsed(stillS * 1000)}`;
    case State.LIVE_BLACK:
      return "LIVE · BLACK";
    case State.LATE:
      return `LATE ${(ageMs / 1000).toFixed(1)} s`;
    case State.NO_SIGNAL: {
      const base = `NO SIGNAL · lost ${formatElapsed(lostMs)} · retrying`;
      return detail ? `${base} · ${detail}` : base;
    }
    case State.RESTORED:
      return "RESTORED";
    case State.PAUSED:
      return "PAUSED";
    case State.SERVER_OFFLINE:
      return "NO SIGNAL · server offline";
    default:
      return "CONNECTING…";
  }
}
