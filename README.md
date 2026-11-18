# Show Multiview

One local page on the show PC's operator monitor with live previews of the **Center Screen**, **Side Screens** and **PTZ Camera**, plus a clock, a countdown and audio meters. Each tile shows at a glance whether its feed is live, late, lost or restored.

The multiview only reads copies of the video. Closing or crashing it has no effect on the projectors.

## Operator quick card

| To do this | Do this |
|---|---|
| Start | Double-click **Start Multiview** |
| Stop | Double-click **Stop Multiview** |
| Stop all preview capture now | Click **Pause Previews** or press `P` |
| Start or pause the countdown | `Space` |
| Reset the countdown | `R` |
| Protect a running show if Resolume seems affected | Pause Previews, then switch Advanced Output to **Show only** |

| Tile shows | Meaning | What to do |
|---|---|---|
| Green `LIVE` | Frames are arriving | Nothing |
| Green `LIVE · STILL` | Frames are arriving, but the picture is not changing | Check it is meant to be still |
| Green `LIVE · BLACK` | Frames are arriving, but the picture is black | Check it is meant to be black |
| Amber `LATE` | No new frame for over 1 second | Watch it |
| Red `NO SIGNAL` | No new frame for over 3 seconds. It keeps retrying by itself | Check the source |
| Green `RESTORED` | The feed has just come back | Nothing |
| Blue `PAUSED` | Previews were paused by the operator | Press `P` to resume |
| Red bar across the top | The multiview server has stopped | Double-click **Start Multiview** |

If the clock's seconds stop moving, the page itself has frozen. Press `F5`.

> **Limit:** the Center and Side previews are copied inside Resolume. They prove what Resolume is sending, not that the GPU outputs, SDI chain or projectors are working. Confirm those by eye.

## Setup on the show PC

Do the operator setup in Part 1 of the [technical plan](docs/multiview-plan.md) first (Windows settings, camera sub-stream and the two Resolume Spout screens). Then:

1. Copy this folder to `C:\Show\multiview\`.
2. In PowerShell, install it:
   ```powershell
   cd C:\Show\multiview
   powershell -ExecutionPolicy Bypass -File scripts\Install.ps1
   ```
3. Find the values for the config:
   ```powershell
   .venv\Scripts\python.exe tools\list_sources.py
   .venv\Scripts\python.exe tools\list_monitors.py
   ```
4. Edit `config\multiview.toml` and fill in every value marked `SITE`.
5. Run the checks. Every line must say PASS.
   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts\Preflight.ps1
   ```

### GPU preference (on-site check 2)

Spout needs Resolume and the bridge on the same GPU. `.venv\Scripts\python.exe` is only a launcher for the installed Python, so in **Settings > System > Display > Graphics**, assign the GPU that drives the projectors to the installed `python.exe` as well, typically `%LOCALAPPDATA%\Programs\Python\Python312\python.exe`.

## On-site checks

These can only be proven on the show PC. Record the results in `config\site-notes.md`.

| # | Check | If it fails |
|---|---|---|
| 1 | Resolume edition offers per-screen Spout output | The `display` fallback or capture hardware is needed |
| 2 | Resolume and the bridge are on the same GPU | The `ndi` fallback is needed |
| 3 | The camera sub-stream path works in VLC | Try `/1`, or check the camera manual |
| 4 | Sender names are correct and each preview shows the whole slice | Fix the slice input area in Resolume |
| 5 | Baseline composition FPS is recorded | Needed for test T6 |
| 6 | Spout frame-detect mode. Search today's log for `frame-detect mode` | With `none`, a hung sender shows `LIVE · STILL` rather than red |
| 7 | PTZ latency is 500 ms or less (T5) | Lower the camera's I-frame interval, then consider SDI capture |
| 8 | The Spout screens cause no FPS loss or judder (T6) | Lower preview sizes, or use **Show only** |
| 9 | Edge opens on the right monitor and keeps running when covered | Correct `window_x` and `window_y` |

If the Spout picture appears upside down, add `spout.flip_vertical = true` to that feed.

The `ndi`, `display` and `uvc` fallback sources (plan milestone 9) are built only if one of these checks fails. Selecting one before then gives a clear config error.

## Acceptance test tools

| Test | Tool |
|---|---|
| T0 Preflight | `scripts\Preflight.ps1` |
| T1 Routing | `tools\make_test_clips.ps1` to create clips, then `python tools\routing_check.py` and `python tools\routing_check.py --expect swapped` |
| T2 to T4 Loss and recovery | Scored from `logs\multiview.log`. Search for `TILE` and `SOURCE` |
| T6 Full-load rehearsal | `python tools\perf_logger.py --duration 3600` |

The center test clip is 2308×1076 because H.264 needs an even height.

## Development

Everything except Spout and WASAPI runs on any platform with test patterns:

```bash
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m mvbridge --config config/multiview.dev.toml
```

Open <http://127.0.0.1:8090>. `config/multiview.faults.toml` walks the tiles through each health state on a repeating cycle, and `tools/fake_rtsp_camera.py` provides a test camera.

```bash
.venv/bin/python -m pytest tests
```

`mvbridge/health.py` and `web/js/tileState.js` implement the same tile rules. Change them together: `tests/vectors/tile_states.json` checks both.
