# Show Multiview — Technical Plan and Claude Code Handoff

**Goal:** One local web page on the show PC's operator monitor that shows three labeled, live previews: **Center Screen**, **Side Screens**, and **PTZ Camera**. It also shows a clock/countdown panel and audio meters. Each tile makes it obvious at a glance whether its feed is live, late, lost, or restored. The multiview must never disturb projector playback.

**Audience:** Part 1 is for the operator (Tej). Parts 2–4 are for the coding agent. Part 5 lists every assumption that must be proven on site.

Items marked **⚠ ON-SITE #n** are assumptions that are not yet verified. They are collected in Part 5.

---

## 0. Decisions already made (do not re-litigate)

| Topic | Decision | Why |
|---|---|---|
| Resolume capture | Add two extra screens in Resolume Advanced Output with the output device set to **Spout**: "MV Center" and "MV Side". Each copies its show screen's slices at a reduced resolution. The bridge receives them locally. | The operator asked for the least setup. Spout is built into Resolume, needs no extra install and no hardware, and does not touch the projector outputs. Resolume's docs say Spout/NDI outputs can be treated as separate screens in Advanced Output, and the screen width and height set the shared texture's resolution. |
| Camera capture | Pull the PTZOptics **RTSP sub-stream over TCP** from its static IP. No capture card. | The camera is already on wired Ethernet with a static IP. PTZOptics documents the RTSP form `rtsp://<ip>:554/1`. The IP stream runs alongside the camera's SDI output. |
| Bridge | **Python 3.12** local server: FastAPI + uvicorn. It runs one **worker process per feed** under a supervisor. | Python has mature libraries for Spout (SpoutGL), RTSP decode (PyAV, which bundles FFmpeg) and WASAPI audio. Separate worker processes keep a crash in one feed from affecting the others. |
| Browser transport | **JPEG frames over WebSocket** (one socket per feed) plus one JSON status WebSocket. The browser draws to `<canvas>`. | Everything runs on one machine for one viewer. Loopback bandwidth is free, latency is about 1–2 frames, and per-frame timing makes health detection exact. No WebRTC/codec negotiation is needed. |
| Front end | Plain HTML, CSS and ES-module JavaScript served by the bridge. **No npm, no build step.** | Least setup, nothing to compile on the show PC. |
| Browser | **Microsoft Edge** (already on Windows) in `--app` full-screen mode with its own profile. | No install. A separate profile keeps it apart from personal browsing. |
| Network exposure | Bind to **127.0.0.1 only**. | There is one viewer on the same machine. This avoids firewall prompts and LAN exposure. |
| Preview quality | Center at 1152×536, Side at 960×540, PTZ at 960×540 (scaled from a 1280×720 sub-stream). All at **30 fps**, JPEG quality 75. | This matches the actual on-screen tile size in a 2×2 grid on a 1080p monitor, so higher resolution would add load without adding visible detail. 30 fps is enough to judge motion and smoothness. |
| Audio | **No audio playback, ever.** The page shows meters only. "Show Audio" comes from WASAPI loopback of Resolume's audio device. "Cam Audio" comes from the RTSP audio track, if present. | The operator asked for meters, not sound. Metering is computed on the server, so the browser never receives audio. |
| Projector protection | Projectors always win. Previews degrade automatically under load, there is a one-click **Pause Previews** kill switch, the bridge runs at BelowNormal priority, and Resolume runs at High priority. | The operator's priority. |

**Known limitation to tell the operator:** the Spout copy is taken *inside* Resolume. It proves what Resolume is sending to each screen, but it does **not** prove that the physical chain is working: GPU output, the 4K link, the SDI converter, the SDI distribution and the projectors themselves. Confirm those by eye. Part 2, step H describes the hardware upgrade path if physical confirmation is ever needed.

---

## PART 1 — Operator setup (hardware and software, no coding)

### A. Collect machine facts (10 min, once)
1. **GPU:** Task Manager → Performance. List every GPU shown and its name.
2. **Which GPU drives which display:** Settings → System → Display → Advanced display. For each of the 4 displays, note "Connected to: <GPU name>".
3. **CPU and RAM:** Task Manager → Performance → CPU / Memory.
4. **Resolume edition:** Help → About (or the title bar) shows **Arena** or **Avenue** and the version number.
5. Write all of this into `config/site-notes.md` in the project.

**⚠ ON-SITE #1:** Resolume's docs describe routing a specific Advanced Output screen to Spout or NDI as an **Arena** capability. Avenue may only offer Spout of the whole composition. If you have Avenue, go to Part 2, step H, fallback 1.

**⚠ ON-SITE #2:** Spout shares GPU textures. Resolume and the bridge must render on the **same GPU**. If step A2 shows displays spread over two GPUs (for example, onboard graphics plus a graphics card), go to Settings → System → Display → Graphics. Set both `Arena.exe`/`Avenue.exe` and `python.exe` to the GPU that drives the projectors.

### B. Windows prep (once)
1. Power plan: **High performance**. Set sleep and display-off to **Never**.
2. Turn off the screen saver. Turn on **Do Not Disturb**, so notifications cannot appear on a projector.
3. Windows Update: set active hours to cover show times, or pause updates during show weeks.
4. Install **Python 3.12 (64-bit)** with "Add to PATH" checked: `winget install Python.Python.3.12`.
5. Install **FFmpeg CLI**. It is used only to generate test clips, not during the show: `winget install Gyan.FFmpeg`.
6. Optional for debugging: **VLC** (`winget install VideoLAN.VLC`) to open the camera's RTSP URL by hand.
7. No NDI runtime, no OBS, no MediaMTX and no capture drivers are needed for the primary path.

Assumption (default): you have admin rights and internet access during install. The show itself needs no internet.

### C. PTZOptics camera (once, about 10 min)
1. From the show PC, `ping <camera-ip>`. You should get replies with less than 1 ms latency. If not, put the PC's NIC on the camera's subnet.
2. Open `http://<camera-ip>` → **Video** settings. **Leave stream 1 (main) untouched.** Set **stream 2 (secondary)** to:
   - Codec **H.264** (not H.265)
   - **1280×720**, **30 fps**
   - **I-frame interval 30**, or the lowest available. This makes reconnects fast.
   - Bitrate about 2–4 Mbps
   - Audio: enable it on the stream if the camera has an audio input you want to meter.
3. Verify in VLC: Media → Open Network Stream → `rtsp://<camera-ip>:554/2`.
   - **⚠ ON-SITE #3:** The sub-stream path. Use `/2` per PTZOptics convention; if it fails try `/1`; if neither works, check the camera's web UI or manual for the exact path.
4. Write down the working URL. It goes into the config.

### D. Resolume (once, then saved in the Advanced Output preset)
1. Open **Output → Advanced**. Your existing **Center** and **Side** screens stay **exactly as they are**.
2. Add a new screen. Name it **`MV Center`**.
   - Set its output device to **Spout**.
   - Set Width/Height to **1152 × 536** (about half of the 2308×1075 center slice).
   - Recreate the Center screen's slice(s) so the **input selection** covers the same composition area as the Center slice. Copy and paste the slice if Resolume allows it.
   - Fit the slice output to fill the screen.
   - Turn on **Black BG** on the slice. Resolume sends alpha, and this prevents transparent areas.
3. Add another screen, **`MV Side`**: Spout, **960 × 540**. Mirror the Side screen's slice input area the same way, with Black BG on.
4. Save as a new Advanced Output preset: **"Show + Multiview"**. Keep the original preset as **"Show only"**. That is your instant fallback.
5. Run the project tool `python tools/list_sources.py`. It prints the Spout sender names exactly as the bridge will see them. Paste those names into the config.
   - **⚠ ON-SITE #4:** Confirm the sender names, and confirm that each MV preview shows the **whole** slice, not a cropped corner.
6. Note your composition's normal frame rate (Resolume's FPS readout) with **"Show only"** active. This is the baseline for test T6.
   - **⚠ ON-SITE #5:** Find where your Resolume version shows composition FPS.

### E. Install the multiview software (after Claude Code builds it)
1. Copy the `multiview/` folder to `C:\Show\multiview\`.
2. In PowerShell, run `scripts\Install.ps1`. It creates a `.venv`, installs pinned requirements and creates a desktop shortcut **"Start Multiview"**.
3. Copy `config\multiview.example.toml` to `config\multiview.toml` and fill in:
   - the camera URL
   - the two Spout sender names
   - the Windows audio output device Resolume uses (Resolume Preferences → Audio)
   - the multiview monitor (run `python tools\list_monitors.py` to get its position)
4. Run `scripts\Preflight.ps1`. Every line must say PASS.

### F. Show-day startup sequence
1. Power on projectors, SDI converter and distribution, and the camera. Wait about 60 s for the camera to boot.
2. Boot the PC and launch Resolume. Load the composition. Confirm that the Advanced Output preset is **"Show + Multiview"**. Confirm that the projectors show the correct content.
3. Double-click **Start Multiview**. The script:
   - raises Resolume's priority to High
   - starts the bridge minimized at BelowNormal priority
   - waits for `http://127.0.0.1:8090/healthz` (up to 20 s)
   - opens Edge full-screen on the multiview monitor
4. Check: all three tiles are green **LIVE** with frame counters moving, and the clock shows the correct time.

Start order does not matter. If Resolume or the camera comes up after the bridge, tiles stay **CONNECTING/NO SIGNAL** and go live on their own.

**Shutdown:** double-click **Stop Multiview**, or close the Edge window and the bridge console.

**Emergency:** click **Pause Previews** (or press `P`) to stop all capture immediately. If you suspect Resolume is still affected, switch Advanced Output to **"Show only"**.

### G. During the show
The bridge never reads from or writes to the projector outputs. Closing or crashing the multiview has no effect on what the projectors show.

### H. Fallbacks and upgrade paths (only if an ON-SITE check fails)
1. **Avenue, or no per-screen Spout:** set the feed type to `display`. This captures the projector displays with Windows desktop capture. Cost: it copies full-resolution 4K frames to the CPU, so it is capped at **15 fps**, and test T6 must be re-run. If T6 fails, use option 3.
2. **Spout fails across GPUs:** set the feed type to `ndi`. Use Resolume NDI screens at the same reduced sizes. Install the NDI 6 Runtime (or NDI Tools).
3. **You need physical-chain confirmation:** add two UVC-class capture devices on spare loop or distribution outputs, then set the feed type to `uvc`.
   - Side: from a spare SDI distribution output.
   - Center: from a 4K HDMI splitter.
   - Example device: a Magewell USB Capture SDI/HDMI.
4. **Camera RTSP latency is over 500 ms (T5):** the camera's SDI output → SDI distribution amplifier → UVC SDI capture → feed type `uvc`.

---

## PART 2 — Coding handoff (for Claude Code)

### 2.1 Project structure

```
multiview/
  README.md
  requirements.txt                 # pinned versions
  config/
    multiview.example.toml
    multiview.toml                 # gitignored, site-specific
    site-notes.md
  mvbridge/                        # Python package; run: python -m mvbridge
    __main__.py                    # parse --config, start uvicorn on 127.0.0.1
    app.py                         # FastAPI app, HTTP + WS routes, static files
    config.py                      # pydantic models, load TOML (tomllib), validation
    supervisor.py                  # spawn/monitor/restart worker processes, aggregate status
    framebus.py                    # per-feed latest-frame slot + fan-out to WS clients (drop-old)
    health.py                      # server-side source-state machine + static/black analysis
    protocol.py                    # binary frame header pack/unpack, status JSON schema
    timer.py                       # clock/countdown state, persisted to state/timer.json
    perf.py                        # CPU/GPU sampling (win32pdh), degrade controller
    priority.py                    # set own processes BelowNormal (psutil)
    audio/
      meter.py                     # peak/RMS dBFS computation, peak-hold
      wasapi_loopback.py           # show-audio meter via PyAudioWPatch loopback
    workers/
      base.py                      # Worker ABC: run loop, reconnect policy, emit(frame|state|meter)
      synthetic.py                 # moving test pattern + optional dropouts (dev/CI, no hardware)
      spout.py                     # SpoutGL receiver in hidden GLFW GL context
      rtsp.py                      # PyAV RTSP (TCP) decode, scale, camera audio meter
      ndi.py                       # fallback (cyndilib)                 [milestone 9]
      display.py                   # fallback desktop capture (dxcam/WGC) [milestone 9]
      uvc.py                       # fallback DirectShow via PyAV dshow   [milestone 9]
  web/
    index.html
    css/multiview.css
    js/main.js                     # boot, layout from /api/config
    js/tile.js                     # canvas render + client health state machine + overlays
    js/feedSocket.js               # per-feed WS, reconnect, decode via createImageBitmap
    js/statusSocket.js             # JSON status/meter/timer WS
    js/clock.js                    # clock + countdown panel and controls
    js/meter.js                    # vertical meter widget
  scripts/
    Install.ps1  Start-Multiview.ps1  Stop-Multiview.ps1  Preflight.ps1  Create-Shortcut.ps1
  tools/
    list_sources.py                # list Spout senders (and NDI if installed), test camera URL
    list_monitors.py               # print monitors with x,y,w,h for Edge window placement
    make_test_clips.ps1            # FFmpeg: CENTER/SIDE routing+latency test clips
    routing_check.py               # automated colour/motion routing assertion (T1)
    perf_logger.py                 # CSV of CPU, GPU-3D, bridge RSS, per-feed fps/age (T6)
  tests/
    test_health.py  test_framebus.py  test_config.py  test_protocol.py  test_timer.py
  state/                           # runtime (timer.json), gitignored
  logs/                            # rotating logs, gitignored
```

`requirements.txt` (pin exact versions at build time): `fastapi`, `uvicorn[standard]`, `pydantic`, `av` (PyAV), `SpoutGL`, `glfw`, `numpy`, `simplejpeg` (bundles libjpeg-turbo, so no DLL to install), `PyAudioWPatch`, `pywin32`, `psutil`, `pytest`.

Verify the exact SpoutGL receiver API (method names, buffer format, how a frame is flagged as new) against the package's bundled examples before coding `spout.py`. Do not guess method names.

### 2.2 Configuration (`multiview.toml`)

```toml
[server]
host = "127.0.0.1"            # never 0.0.0.0
port = 8090
log_dir = "logs"
log_level = "INFO"

[ui]
title = "SHOW MULTIVIEW"
clock_24h = false
countdown_warn_s = 60         # amber in final N seconds
countdown_overrun = "count_up_red"
layout = "grid2x2"            # [Center][Side] / [PTZ][Clock]

[health]                       # defaults, can be overridden per feed
late_ms = 1000                 # amber
lost_ms = 3000                 # red NO SIGNAL
reconnect_interval_ms = 2000
reconnect_max_interval_ms = 10000
restored_flash_ms = 3000
static_after_s = 10            # frames arriving but picture unchanged
static_mad_threshold = 0.6     # mean abs diff on 64x36 luma, 0-255 scale
black_luma_threshold = 10
black_after_s = 3

[perf]
auto_degrade = true
gpu_3d_high_pct = 85
cpu_high_pct = 75
sustain_s = 5
recover_s = 30
levels = [ {fps=30,q=75,scale=1.0}, {fps=15,q=70,scale=1.0},
           {fps=10,q=65,scale=0.75}, {fps=5,q=60,scale=0.5} ]

[audio.show]
enabled = true
source = "wasapi_loopback"
device_match = "Speakers"      # substring of Resolume's output device name
attach_to_feed = "center"

[[feed]]
id = "center"
label = "CENTER SCREEN"
type = "spout"                 # spout | rtsp | ndi | display | uvc | synthetic
spout.sender = "MV Center"     # exact name from tools/list_sources.py
preview = { width = 1152, height = 536, fps = 30, jpeg_quality = 75 }

[[feed]]
id = "side"
label = "SIDE SCREENS"
type = "spout"
spout.sender = "MV Side"
preview = { width = 960, height = 540, fps = 30, jpeg_quality = 75 }

[[feed]]
id = "ptz"
label = "PTZ CAMERA"
type = "rtsp"
rtsp.url = "rtsp://192.168.100.88:554/2"
rtsp.transport = "tcp"
rtsp.open_timeout_ms = 3000
rtsp.read_timeout_ms = 2000
rtsp.audio_meter = true        # meter the camera audio track if present
preview = { width = 960, height = 540, fps = 30, jpeg_quality = 75 }

# Fallback parameter blocks (used only when type changes):
# ndi.source = "PC-NAME (MV Center)"
# display.monitor_index = 3   display.max_fps = 15
# uvc.device = "USB Capture SDI"
```

Validation: unknown keys are an error. Feed ids must be unique. Exactly three feeds in v1. Bad config means a clear console message and exit code 2, with no stack trace.

### 2.3 Major components

**Supervisor (`supervisor.py`)**
- Spawns one `multiprocessing.Process` per feed, plus one for show audio.
- Each worker gets a `Pipe` (control: pause/resume, degrade level) and an output `Queue(maxsize=3)`.
- The worker puts only the newest item: if the queue is full, it discards the oldest.
- A reader thread per worker moves items into the `framebus`/status store.
- If a worker exits or stops heartbeating for 5 s, it is killed and restarted with backoff (2 s doubling to 10 s). Its state becomes `ERROR` with the reason.
- Sets all bridge processes to `BELOW_NORMAL_PRIORITY_CLASS`.

**Worker contract (`workers/base.py`)**
- Emits `Frame(seq, capture_ts_ns, w, h, jpeg_bytes)`. `capture_ts_ns` is `time.time_ns()` at the moment the source frame is obtained.
- Emits `State(source_state, detail)`, where `source_state ∈ {connecting, connected, stalled, disconnected, error, paused}`.
- Emits `Meter(peak_db, rms_db)` at 20 Hz when applicable.
- Emits a heartbeat at 1 Hz.
- Throttles to the configured preview fps and **never reads from the source faster than that**. This keeps GPU readback minimal.
- Health analysis runs in the worker on a 64×36 luma thumbnail of each emitted frame: a strided numpy downsample.
  - It computes the mean absolute difference from the previous thumbnail and the mean luma.
  - It emits `static=true/false` and `black=true/false` per the `[health]` thresholds.

**Spout worker**
- Creates a hidden GLFW window/GL context. Opens a receiver bound to `spout.sender`.
- Every 1/fps s: if the sender is missing, state `disconnected` (retry every `reconnect_interval_ms`). If present, receive into an RGBA buffer, drop alpha (composite on black), and JPEG-encode with simplejpeg. Resize only if the sender size differs from the preview size; area interpolation via numpy/PyAV.
- If SpoutGL exposes a frame-new or frame-count signal, no new frame for `late_ms` means state `stalled`.
- **⚠ ON-SITE #6:** If Resolume's sender does not provide frame counting, a hung-but-open sender looks "live and still", not lost. Log which mode is active at startup. The UI then shows **LIVE · STILL** rather than red. Document this in the README.

**RTSP worker**
- PyAV `av.open(url, options={"rtsp_transport":"tcp","fflags":"nobuffer","flags":"low_delay","max_delay":"0","stimeout":<open_timeout_us>})`.
- Decode only the video stream (plus audio for the meter if enabled). Use `frame.reformat(width,height,'rgb24')`, then simplejpeg.
- If no packet arrives for `read_timeout_ms`, state `stalled`. On an exception or EOF: close the container, state `disconnected`, reopen every `reconnect_interval_ms`. Never block longer than the timeouts.
- If the stream has no audio track, emit meter state `no_track`.
- Drop decoded frames older than the newest one (latest-only), so a backlog can never build up.

**Show-audio worker:** PyAudioWPatch WASAPI loopback on the device matched by `device_match`. Compute 50 ms blocks into peak/RMS dBFS. If the device is not found, meter state `no_device`. Never output audio.

**Framebus + WebSockets (`app.py`, `framebus.py`)**
- `GET /` serves `web/index.html`. `GET /api/config` returns labels, layout, thresholds and feed ids (no URLs or credentials).
- `WS /ws/feed/{id}`: binary messages. Header (little-endian, 24 bytes): `b"MVF1"` | `uint32 seq` | `uint64 capture_ts_ms` | `uint16 w` | `uint16 h` | `uint32 jpeg_len`, followed by the JPEG bytes.
  - Per-client send policy: if the previous send has not completed, replace the pending frame with the newest one (latest-only). The server never queues more than 1 frame per client.
- `WS /ws/status`: JSON at 10 Hz:
  `{"t":ms, "feeds":{id:{"source_state","fps","last_capture_ms","w","h","static","black","reconnects","detail"}}, "meters":{"show":{...},"cam":{...}}, "perf":{"cpu","gpu3d","level","paused"}, "timer":{...}}`
  - Meters also push at 20 Hz as `{"type":"meters",...}`.
- `GET /api/snapshot/{id}.jpg`: the latest frame (used by tests).
- `POST /api/previews {"paused":bool}` and `POST /api/timer {"action":"start|pause|reset|set_duration|set_target","value":...}`.
- `GET /healthz`: 200 plus a short JSON summary.

**Perf/degrade (`perf.py`)**
- Every 1 s, read total CPU % (psutil) and GPU 3D engine utilization via `win32pdh` counter `\GPU Engine(*engtype_3D)\Utilization Percentage` (sum per adapter, take the max adapter).
- If above threshold for `sustain_s`: step to the next degrade level and push it to all workers.
- If below for `recover_s`: step back one level.
- Show the level in the UI header ("PREVIEW REDUCED – L2").
- Pause Previews tells every worker to stop receiving immediately: it releases the Spout receiver and closes RTSP. Tiles show **PAUSED**.

**Timer (`timer.py`)**
- State: `mode (idle|running|paused|overrun)`, `target_epoch_ms` or `remaining_ms`, `duration_ms`.
- Computed from the wall clock, so there is no drift accumulation. Persisted on every change; restored on restart.

**Front end**
- Layout: a CSS grid, 2×2 filling the viewport.
  - Header bar, 40 px: title, server status, degrade level, Pause button.
  - Top row: Center | Side. Bottom row: PTZ | Clock panel.
  - Each tile letterboxes its canvas inside the cell, keeping the aspect ratio. Show Audio is a vertical meter on the right edge of the **Center** tile. Cam Audio is on the PTZ tile.
- `feedSocket.js`: on message, parse the header and `createImageBitmap(new Blob([jpeg],{type:"image/jpeg"}))`. Keep only the newest bitmap and call `.close()` on any replaced bitmap. Draw in `requestAnimationFrame`. On socket close, reconnect after 1 s, then every 2 s.
- Clock panel: a large time of day, and below it a countdown (`MM:SS`, `H:MM:SS` when ≥1 h).
  - Controls: duration presets (5/10/15 min), a custom field, a target-time field, and Start/Pause/Reset.
  - Shortcuts: `Space` start/pause, `R` reset, `P` pause previews.
  - Amber in the final `countdown_warn_s`. At zero it turns red and counts up as `+MM:SS OVER`.
- The page never creates audio elements or an AudioContext.

### 2.4 Tile behavior (the operator contract)

The client computes the tile state every animation frame from `age = now − time of last received frame` (client clock), combined with the server's `source_state`. The server and browser share one machine clock, so the age is exact.

| State | Trigger | Border (6 px, outside the picture) | Status chip (top-right, always text) | Picture |
|---|---|---|---|---|
| **CONNECTING** | No frame yet since page load or socket open | Grey | `CONNECTING…` | Dark placeholder with label |
| **LIVE** | age < `late_ms` | Green | `LIVE · 30 fps · 48 ms` (fps measured, pipeline age) | Normal |
| **LIVE · STILL** | LIVE and `static` for ≥ `static_after_s` | Green | `LIVE · STILL 0:42` | Normal; small pause glyph |
| **LIVE · BLACK** | LIVE and `black` for ≥ `black_after_s` | Green | `LIVE · BLACK` | Normal |
| **LATE** | `late_ms` ≤ age < `lost_ms`, or server says `stalled` | Amber | `LATE 1.8 s` | Last frame, normal |
| **NO SIGNAL** | age ≥ `lost_ms`, or server says `disconnected`/`error` | Red, blinking 1 Hz | `NO SIGNAL · lost 0:12 · retrying` (+ `detail`) | Last frame, grayscale at 35% opacity, centered red banner `NO SIGNAL` |
| **RESTORED** | First frame after NO SIGNAL | Green, with a pulse | `RESTORED` for `restored_flash_ms`, then LIVE | Normal |
| **PAUSED** | Operator paused previews | Blue, dashed | `PAUSED` | Last frame at 35% opacity |
| **SERVER OFFLINE** (all tiles) | Status WS closed for > 2 s | Red header bar across the page | `MULTIVIEW SERVER OFFLINE – reconnecting` | All tiles show NO SIGNAL styling |

Additional at-a-glance cues:
- **Frame ticker:** an 8-segment ring at the tile's bottom-left that advances one segment per received frame. When feeds stop, it stops, even if the image looks plausible.
- The **label** (top-left, large, white on black) is always visible in every state.
- Status is never carried by colour alone: every state has a text chip, which matters because test content is red and blue.
- The clock panel's seconds digit is the page-alive heartbeat. If it stops, the page itself has frozen.

### 2.5 Scripts

- **`Start-Multiview.ps1`**
  1. Set the Resolume process priority to High, if running.
  2. Start `.venv\Scripts\python.exe -m mvbridge --config config\multiview.toml` minimized.
  3. Poll `/healthz` for up to 20 s.
  4. Launch Edge:
     ```
     msedge.exe --app=http://127.0.0.1:8090 --user-data-dir="%LOCALAPPDATA%\ShowMultiview\edge" --window-position=<x>,<y> --start-fullscreen --disable-backgrounding-occluded-windows --disable-renderer-backgrounding --disable-background-timer-throttling --no-first-run
     ```
     The x and y values come from config. The three `--disable-*` flags stop Edge from throttling the page when it is covered.
- **`Stop-Multiview.ps1`:** close that Edge profile's window and stop the bridge process tree.
- **`Preflight.ps1`:** runs `tools/list_sources.py --check`. Each line prints PASS or FAIL:
  - Python version
  - config valid
  - port free
  - each Spout sender found
  - camera RTSP opens and decodes 1 frame within 3 s
  - audio device found
  - multiview monitor exists

### 2.6 Implementation milestones

Each milestone has a done-when criterion. Build and verify in this order. Use the `synthetic` source so milestones 1–2 need no hardware.

1. **Skeleton.** Config loading/validation, supervisor, synthetic worker (moving bars, frame counter, alternate red/blue backgrounds), framebus, both WebSockets, 2×2 UI with labels and canvases.
   - Done when 3 synthetic tiles render at 30 fps in Edge, pipeline age is under 60 ms, and `pytest` passes for config, protocol and framebus.
2. **Health.** Server and client state machines, all states in §2.4, server-offline handling, frame ticker. The synthetic worker gets `dropout_after_s`, `stall_after_s` and `freeze_picture_after_s` test knobs.
   - Done when the scripted synthetic dropouts produce the exact §2.4 transitions within ±200 ms of thresholds. Unit tests use a fake clock.
3. **RTSP worker.** Low-latency options, reconnect loop, timeouts, latest-only decode.
   - Done when the camera tile is LIVE, and unplugging and replugging the network gives NO SIGNAL then RESTORED with no bridge restart.
4. **Spout worker.** Hidden GL context, sender discovery in `tools/list_sources.py`, alpha removal, frame-new detection with mode logging.
   - Done when the MV Center/MV Side senders render correctly and disabling an MV screen in Resolume drives the tile to NO SIGNAL.
5. **Clock and countdown.** Panel, controls, shortcuts, persistence.
   - Done when T8 passes.
6. **Audio meters.** WASAPI loopback and RTSP audio meter, peak-hold at 1.5 s, scale −60 to 0 dBFS (green < −18, amber −18 to −6, red > −6), plus `no_device` and `no_track` states.
   - Done when the meters move with test tones and the page produces no sound.
7. **Perf and protection.** Perf sampling, degrade controller, Pause Previews, process priorities, header indicators.
   - Done when forcing thresholds low in config visibly steps levels, and Pause drops the bridge's CPU to under 2%.
8. **Ops tooling.** Install, Start, Stop, Preflight, Create-Shortcut, `list_monitors.py`, `make_test_clips.ps1`, `routing_check.py`, `perf_logger.py`, and README with an operator quick card.
   - Done when a clean machine goes from zip to running using only the README.
9. **Fallbacks (optional, build only if an ON-SITE check fails).** `ndi`, `display` (max 15 fps), `uvc` workers behind the same worker contract.

Logging: one rotating log per day in `logs/`. Log every state transition, with feed, from, to, reason and timestamp. Tests T2 to T4 are scored from these logs.

### 2.7 Test assets (`tools/make_test_clips.ps1`)

FFmpeg generates two 60 fps, 2-minute H.264 clips (or DXV if your Resolume workflow prefers it):
- **`TEST_CENTER.mov`:** 2308×1075, solid **red** background, large "CENTER", a white bar sweeping **left→right** once per second, a burned-in frame counter and a millisecond clock (`drawtext` with `%{pts\:hms}` and `n`).
- **`TEST_SIDE.mov`:** 1920×1080, solid **blue** background, large "SIDE", a white bar sweeping **top→bottom**, plus its own counter and clock.
- **`TEST_JUDDER.mov`:** 60 fps, a single vertical white bar moving 32 px/frame on black, used to spot dropped or repeated projector frames.

---

## PART 3 — Acceptance tests (pass/fail)

Run these in order on the show PC with the real projectors connected. Record results in `logs/acceptance-<date>.md`.

**T0 Preflight**
- Run `Preflight.ps1`.
- **Pass:** every line PASS.

**T1 Routing (different moving content per output)**
1. Play `TEST_CENTER` on the layer or clip routed to the Center screen and `TEST_SIDE` on the Side screen.
2. Run `python tools/routing_check.py`. It takes 10 snapshots per feed, 200 ms apart.

**Pass when all of these hold:**
- The center tile's mean R > 2× mean B, and the side tile's mean B > 2× mean R.
- Consecutive snapshots of each feed differ (MAD > 2), proving motion.
- Visually: the CENTER tile shows red/"CENTER" with a horizontal sweep, and SIDE shows blue/"SIDE" with a vertical sweep.
- Both side projectors and the center projector match their tiles by eye.

Then swap the clips in Resolume. **Pass:** both tiles swap within 1 s and `routing_check.py --expect swapped` passes.

**T2 Camera disconnect and reconnect**

Cable pull:
1. With all tiles LIVE, unplug the camera's Ethernet at the PC side.
2. **Pass when all of these hold:**
   - The PTZ tile shows LATE within 1.5 s and NO SIGNAL within 3.5 s, with dimmed last frame, lost timer and "retrying".
   - Center and Side stay LIVE, with fps within 10% of before.
3. Replug the cable. **Pass:** RESTORED within 10 s of replug, then LIVE, with no page reload or bridge restart.
4. Repeat the pull and replug 5 times. **Pass:** 5/5, and bridge memory growth stays under 50 MB across the cycles (perf logger).

Power cycle:
1. Power-cycle the camera.
2. **Pass:** NO SIGNAL throughout the boot, then RESTORED within 10 s of the camera's RTSP becoming available (check with VLC in parallel).

**T3 Resolume feed loss, freeze and still picture**
1. Disable or remove the `MV Center` screen's Spout output.
   - **Pass:** the Center tile shows NO SIGNAL within 3.5 s. Re-enable it: RESTORED within 5 s.
   - **Pass:** the center projector is unaffected throughout.
2. Pause the clip on the center layer.
   - **Pass:** the tile stays green and shows LIVE · STILL after about 10 s. It must **not** show red.
3. Play a black clip.
   - **Pass:** LIVE · BLACK within 4 s.
4. Record which Spout frame-detection mode was logged at startup (⚠ ON-SITE #6).

**T4 Bridge and browser resilience**
1. Kill the bridge process.
   - **Pass:** the page shows SERVER OFFLINE within 2.5 s.
   - Run Start-Multiview again: **Pass:** all tiles LIVE within 15 s without reloading the page.
2. Press F5 in Edge.
   - **Pass:** all tiles LIVE within 5 s.

**T5 Latency (target under 500 ms, from your answers)**
- **Method:** a phone photo containing both the reference and the multiview tile. Take 10 photos per feed and record the median and the maximum.
  - Center and Side: photograph the projected test clip's ms clock and the tile's ms clock together. Do the same against Resolume's own output preview on the operator monitor, for a projector-independent figure.
  - PTZ: point the camera at a phone running a ms stopwatch placed next to the multiview monitor. Photograph both the stopwatch and the PTZ tile.
- **Pass:**
  - Center and Side: median **≤ 150 ms** and maximum ≤ 250 ms, measured against Resolume's output preview.
  - PTZ: median **≤ 500 ms** and maximum ≤ 650 ms.
  - The on-tile pipeline age stays under 100 ms for all tiles.
- If PTZ fails: first set the camera's I-frame interval and bitrate lower and retry. If it still fails, go to Part 1 H4. **⚠ ON-SITE #7.**

**T6 Full-load rehearsal (effect on projector playback)**
1. **Baseline:** Advanced Output on "Show only" with the multiview stopped. Run the heaviest show content plus `TEST_JUDDER` on center for 10 min. Log with `perf_logger.py` and record Resolume FPS.
2. **Under load:** "Show + Multiview" active, all three tiles live, countdown running, for **60 min** or the show length, whichever is longer.

**Pass when all of these hold:**
- Resolume composition FPS average is within **1 fps** of baseline, and it never drops more than 3 fps below baseline for more than 1 s.
- GPU-3D utilization averages **≤ 80%**, and total CPU averages **≤ 60%**.
- No degrade step occurs, or if one does, it is logged and the operator agrees the preview stayed usable.
- Each tile averages **≥ 28 fps**, with zero unexpected LATE or NO SIGNAL events.
- Bridge memory growth stays **< 100 MB/h**.
- **Judder check:** film the center projector showing `TEST_JUDDER` for 10 s with phone slow-motion (240 fps), once at baseline and once under load. Count repeated or skipped bar positions. Under load may have **no more than baseline + 1** irregularities per 10 s. Repeat for one side projector using the side output.
- Clicking **Pause Previews** mid-rehearsal: all tiles show PAUSED within 1 s, and resuming gives all LIVE within 3 s.

**T7 Audio meters**
- Play a −12 dBFS tone through Resolume. **Pass:** Show Audio peak reads −12 ±2 dB.
- If the camera has audio: speak into it. **Pass:** the cam meter moves. If there is no track, it shows `NO AUDIO TRACK`.
- **Pass:** the page is silent throughout, confirmed with system volume up.

**T8 Clock and countdown**
- Clock matches the Windows clock to ±1 s.
- A 30-minute countdown ends within ±1 s of a reference stopwatch.
- Amber appears in the last 60 s. At zero it shows red `+00:01 OVER` and counts up.
- An F5 reload or a bridge restart mid-countdown keeps the countdown within ±1 s.

---

## PART 4 — Assumptions taken as defaults (not answered in Q&A)

| # | Assumption | Change if wrong |
|---|---|---|
| D1 | A deliberately still or black picture is a **quiet** indicator (LIVE · STILL / LIVE · BLACK), never an alarm. Only missing frames go amber or red. | Thresholds in `[health]` |
| D2 | Amber after 1 s without frames, red after 3 s, reconnect every 2 s with backoff to 10 s | `[health]` |
| E1 | Admin rights; Python and FFmpeg installable; internet only during setup | — |
| E2 | Python backend and vanilla JS. Claude Code builds on this same Windows PC (or builds elsewhere, then runs Preflight here). | — |
| E3 | Manual start from a desktop shortcut that opens a full-screen Edge app window on the multiview monitor. No auto-start at login. | Add a Task Scheduler entry later |
| E4 | Previews auto-degrade under load; projectors always win | `[perf].auto_degrade` |
| C4 | "No audio, but need audio meters": meters shown, no sound. Show Audio comes from Resolume's output device, Cam Audio from the RTSP track. | Disable either `[audio.*]` block |
| C1 | The multiview monitor is about 1920×1080; the layout scales to other sizes | CSS grid is responsive |

---

## PART 5 — ON-SITE verification list

1. **Edition:** is Resolume **Arena** (per-screen Spout output available)? If Avenue, use the `display` fallback or hardware.
2. **GPU topology:** are all outputs and Resolume on one GPU, with `python.exe` assigned to the same GPU (Spout requirement)? If not, use the NDI fallback.
3. **PTZ sub-stream path** (`/2`) and its H.264 settings, confirmed in VLC.
4. **Spout sender names**, and whether the MV screens show the full slice area (not cropped or offset) at reduced resolution.
5. **Where Resolume shows composition FPS**, and the baseline value.
6. **Spout frame-new detection mode:** does a stalled Resolume show as LATE/NO SIGNAL, or only as LIVE · STILL?
7. **PTZ RTSP latency ≤ 500 ms** (T5). If not, use the SDI capture path.
8. **The two extra Resolume Spout screens** add no measurable FPS loss or judder on the 4K60 center and HD side outputs (T6). This is the main risk, since the GPU is unknown.
9. **Edge full-screen window** lands on the correct monitor and stays unthrottled when the operator works on the other monitor.
