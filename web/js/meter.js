// Vertical audio meter, -60 to 0 dBFS. The page only draws levels and never plays sound.

const FLOOR_DB = -60;
const MARKS = [0, -6, -18, -40, -60];
const MESSAGES = {
  no_device: "NO DEVICE",
  no_track: "NO AUDIO TRACK",
  offline: "NO SIGNAL",
  paused: "PAUSED",
};

export function dbToFraction(db) {
  return Math.min(1, Math.max(0, (db - FLOOR_DB) / -FLOOR_DB));
}

export class Meter {
  constructor(name) {
    this.element = document.createElement("div");
    this.element.className = "meter";
    this.element.setAttribute("role", "img");
    this.element.innerHTML = `
      <div class="meter__name"></div>
      <div class="meter__body">
        <div class="meter__track"><div class="meter__mask"></div><div class="meter__hold"></div></div>
        <div class="meter__scale">${MARKS.map(
          (db) => `<span style="bottom:${dbToFraction(db) * 100}%">${Math.abs(db)}</span>`,
        ).join("")}</div>
      </div>
      <div class="meter__value">--</div>`;
    this.name = name;
    this.element.querySelector(".meter__name").textContent = name;
    this.mask = this.element.querySelector(".meter__mask");
    this.hold = this.element.querySelector(".meter__hold");
    this.value = this.element.querySelector(".meter__value");
  }

  update(data) {
    const message = data ? MESSAGES[data.state] : "--";
    if (message) {
      this.element.dataset.state = "off";
      this.mask.style.transform = "scaleY(1)";
      this.hold.style.display = "none";
      this.value.textContent = message;
      this.element.setAttribute("aria-label", `${this.name} audio: ${message}`);
      return;
    }
    this.element.dataset.state = "ok";
    this.mask.style.transform = `scaleY(${1 - dbToFraction(data.peak_db)})`;
    this.hold.style.display = "block";
    this.hold.style.bottom = `${dbToFraction(data.hold_db) * 100}%`;
    const text = data.peak_db <= FLOOR_DB ? "-∞" : data.peak_db.toFixed(0);
    this.value.textContent = text;
    this.element.setAttribute("aria-label", `${this.name} audio peak ${text} dB`);
  }
}
