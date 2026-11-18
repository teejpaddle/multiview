"""Print each monitor's position. Copy the multiview monitor's x and y into the config."""

from __future__ import annotations

import sys


def enumerate_monitors() -> list[dict]:
    """Return every monitor as {index, x, y, w, h, primary}. Windows only."""
    import win32api
    import win32con

    monitors = []
    for index, (handle, _dc, rect) in enumerate(win32api.EnumDisplayMonitors()):
        info = win32api.GetMonitorInfo(handle)
        left, top, right, bottom = rect
        monitors.append(
            {
                "index": index,
                "x": left,
                "y": top,
                "w": right - left,
                "h": bottom - top,
                "primary": bool(info["Flags"] & win32con.MONITORINFOF_PRIMARY),
            }
        )
    return monitors


def main() -> int:
    if sys.platform != "win32":
        print("list_monitors.py runs on the Windows show PC.")
        return 1
    for monitor in enumerate_monitors():
        primary = "  (primary)" if monitor["primary"] else ""
        print(
            f"Monitor {monitor['index']}: x={monitor['x']} y={monitor['y']} "
            f"w={monitor['w']} h={monitor['h']}{primary}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
