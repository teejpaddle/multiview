// Time of day and show countdown. The seconds digit doubles as the page-alive heartbeat.

const pad = (value) => String(value).padStart(2, "0");

function hms(totalSeconds) {
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  return hours > 0 ? `${hours}:${pad(minutes)}:${pad(seconds)}` : `${pad(minutes)}:${pad(seconds)}`;
}

export function formatCountdown(remainingMs) {
  if (remainingMs > 0) return hms(Math.ceil(remainingMs / 1000));
  return `+${hms(Math.floor(-remainingMs / 1000))} OVER`;
}

export function formatTimeOfDay(date, use24h) {
  const hours = date.getHours();
  const shown = use24h ? pad(hours) : String(hours % 12 || 12);
  const suffix = use24h ? "" : hours < 12 ? " AM" : " PM";
  return `${shown}:${pad(date.getMinutes())}:${pad(date.getSeconds())}${suffix}`;
}

export function displayMode(timer, remainingMs, warnSeconds) {
  if (timer.mode === "idle" || timer.mode === "paused") return timer.mode;
  if (remainingMs <= 0) return "overrun";
  return remainingMs <= warnSeconds * 1000 ? "warn" : "running";
}

// The next time the clock reads HH:MM, today if still ahead and otherwise tomorrow.
export function nextOccurrence(timeText, now = new Date()) {
  const [hours, minutes] = timeText.split(":").map(Number);
  const target = new Date(now);
  target.setHours(hours, minutes, 0, 0);
  if (target <= now) target.setDate(target.getDate() + 1);
  return target.getTime();
}

export class ClockPanel {
  constructor({ use24h, warnSeconds }) {
    this.use24h = use24h;
    this.warnSeconds = warnSeconds;
    this.timer = { mode: "idle", remaining_ms: 0, target_epoch_ms: null };
    this.nowElement = document.getElementById("clock-now");
    this.countdown = document.getElementById("countdown");
    this.message = document.getElementById("timer-message");
    this.startButton = document.getElementById("timer-start");
    this.pauseButton = document.getElementById("timer-pause");
    this.setupControls();
  }

  setupControls() {
    for (const button of document.querySelectorAll("[data-preset]")) {
      button.addEventListener("click", () =>
        this.send("set_duration", Number(button.dataset.preset) * 60_000),
      );
    }
    this.startButton.addEventListener("click", () => this.send("start"));
    this.pauseButton.addEventListener("click", () => this.send("pause"));
    document.getElementById("timer-reset").addEventListener("click", () => this.send("reset"));

    document.getElementById("custom-form").addEventListener("submit", (event) => {
      event.preventDefault();
      const input = document.getElementById("custom-minutes");
      const minutes = Number(input.value);
      if (minutes > 0) this.send("set_duration", Math.round(minutes * 60_000));
      input.blur();
    });
    document.getElementById("target-form").addEventListener("submit", (event) => {
      event.preventDefault();
      const input = document.getElementById("target-time");
      if (input.value) this.send("set_target", nextOccurrence(input.value));
      input.blur();
    });

    // A button that kept focus would also react to the Space shortcut.
    document.querySelector(".clock__controls").addEventListener("click", (event) => {
      event.target.closest("button")?.blur();
    });
  }

  async send(action, value = null) {
    this.message.textContent = "";
    try {
      const response = await fetch("/api/timer", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action, value }),
      });
      const body = await response.json();
      if (response.ok) this.setTimer(body);
      else this.message.textContent = body.detail ?? "The countdown did not accept that.";
    } catch {
      this.message.textContent = "The server is not responding.";
    }
  }

  toggle() {
    const running = this.timer.mode === "running";
    this.send(running ? "pause" : "start");
  }

  reset() {
    this.send("reset");
  }

  setTimer(timer) {
    this.timer = timer;
    const running = timer.mode === "running" || timer.mode === "overrun";
    this.startButton.disabled = running;
    this.pauseButton.disabled = timer.mode !== "running";
    const locked = running;
    for (const control of document.querySelectorAll(
      "[data-preset], #custom-form button, #custom-form input, #target-form button, #target-form input",
    )) {
      control.disabled = locked;
    }
  }

  render(now) {
    const clockText = formatTimeOfDay(new Date(now), this.use24h);
    if (this.nowElement.textContent !== clockText) this.nowElement.textContent = clockText;

    const { timer } = this;
    const remaining = timer.target_epoch_ms !== null ? timer.target_epoch_ms - now : timer.remaining_ms;
    const mode = displayMode(timer, remaining, this.warnSeconds);
    if (this.countdown.dataset.mode !== mode) this.countdown.dataset.mode = mode;
    const text = formatCountdown(remaining);
    if (this.countdown.textContent !== text) this.countdown.textContent = text;
  }
}
