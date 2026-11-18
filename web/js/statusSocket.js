// JSON status, meter and timer updates. Also tells the page when the server has gone quiet.

const OFFLINE_AFTER_MS = 2000;

export class StatusSocket {
  constructor({ onStatus, onMeters }) {
    this.url = `ws://${location.host}/ws/status`;
    this.onStatus = onStatus;
    this.onMeters = onMeters;
    this.lastMessageAt = performance.now();
    this.connect();
  }

  get offline() {
    return performance.now() - this.lastMessageAt > OFFLINE_AFTER_MS;
  }

  connect() {
    const socket = new WebSocket(this.url);
    socket.onmessage = (event) => {
      this.lastMessageAt = performance.now();
      const message = JSON.parse(event.data);
      if (message.type === "meters") this.onMeters(message.meters);
      else this.onStatus(message);
    };
    socket.onclose = () => setTimeout(() => this.connect(), 1000);
    socket.onerror = () => socket.close();
  }
}
