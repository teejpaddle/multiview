// One WebSocket per feed. Decodes JPEG frames and keeps only the newest picture.

const HEADER_SIZE = 24;
const MAGIC = 0x3146564d; // "MVF1", little-endian

export function parseHeader(buffer) {
  if (buffer.byteLength < HEADER_SIZE) return null;
  const view = new DataView(buffer);
  if (view.getUint32(0, true) !== MAGIC) return null;
  const header = {
    seq: view.getUint32(4, true),
    captureMs: Number(view.getBigUint64(8, true)),
    width: view.getUint16(16, true),
    height: view.getUint16(18, true),
    jpegLength: view.getUint32(20, true),
  };
  return buffer.byteLength === HEADER_SIZE + header.jpegLength ? header : null;
}

export class FeedSocket {
  constructor(feedId, { onOpen, onFrame, onPicture }) {
    this.url = `ws://${location.host}/ws/feed/${encodeURIComponent(feedId)}`;
    this.onOpen = onOpen;
    this.onFrame = onFrame;
    this.onPicture = onPicture;
    this.retryMs = 1000;
    this.decoding = false;
    this.waiting = null;
    this.lastSeq = -1;
    this.connect();
  }

  connect() {
    const socket = new WebSocket(this.url);
    socket.binaryType = "arraybuffer";
    socket.onopen = () => {
      this.retryMs = 1000;
      this.lastSeq = -1;
      this.onOpen();
    };
    socket.onmessage = (event) => this.receive(event.data);
    socket.onclose = () => {
      setTimeout(() => this.connect(), this.retryMs);
      this.retryMs = 2000;
    };
    socket.onerror = () => socket.close();
  }

  receive(buffer) {
    const header = parseHeader(buffer);
    if (!header) return;
    this.onFrame(header);
    const blob = new Blob([new Uint8Array(buffer, HEADER_SIZE)], { type: "image/jpeg" });
    this.waiting = { header, blob };
    if (!this.decoding) this.decodeNext();
  }

  async decodeNext() {
    this.decoding = true;
    while (this.waiting) {
      const { header, blob } = this.waiting;
      this.waiting = null;
      try {
        const bitmap = await createImageBitmap(blob);
        this.onPicture(bitmap, header);
      } catch (error) {
        console.warn("Skipped a frame that could not be decoded", error);
      }
    }
    this.decoding = false;
  }
}
