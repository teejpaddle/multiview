"""Start the bridge: python -m mvbridge --config config/multiview.toml"""

from __future__ import annotations

import argparse
import logging
import multiprocessing
import os
import sys
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

from . import PROJECT_ROOT
from .config import ConfigError, MultiviewConfig, load_config

EXIT_BAD_CONFIG = 2


def _setup_logging(cfg: MultiviewConfig) -> None:
    log_dir = Path(cfg.server.log_dir)
    if not log_dir.is_absolute():
        log_dir = PROJECT_ROOT / log_dir
    log_dir.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter("%(asctime)s.%(msecs)03d %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S")
    file_handler = TimedRotatingFileHandler(
        log_dir / "multiview.log", when="midnight", backupCount=60, encoding="utf-8"
    )
    console = logging.StreamHandler()
    root = logging.getLogger()
    root.setLevel(cfg.server.log_level)
    for handler in (file_handler, console):
        handler.setFormatter(formatter)
        root.addHandler(handler)


def main() -> int:
    parser = argparse.ArgumentParser(prog="mvbridge", description="Show Multiview bridge")
    parser.add_argument("--config", default=str(PROJECT_ROOT / "config" / "multiview.toml"))
    parser.add_argument(
        "--print-window", action="store_true", help="print the monitor position and port, then exit"
    )
    args = parser.parse_args()

    try:
        cfg = load_config(args.config)
    except ConfigError as exc:
        print(exc, file=sys.stderr)
        return EXIT_BAD_CONFIG

    if args.print_window:
        print(cfg.ui.window_x, cfg.ui.window_y, cfg.server.port)
        return 0

    import uvicorn

    from .app import create_app

    _setup_logging(cfg)
    logging.getLogger("mvbridge").info(
        "BRIDGE start http://%s:%d pid=%d", cfg.server.host, cfg.server.port, os.getpid()
    )
    uvicorn.run(
        create_app(cfg),
        host=cfg.server.host,
        port=cfg.server.port,
        log_level="warning",
        access_log=False,
        log_config=None,
        ws_per_message_deflate=False,  # JPEG does not compress; this only wastes CPU.
    )
    return 0


if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(main())
