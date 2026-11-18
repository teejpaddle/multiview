"""Load and validate multiview.toml. A bad file produces one readable ConfigError."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

FALLBACK_TYPES = {"ndi", "display", "uvc"}


class ConfigError(Exception):
    """The configuration cannot be used. The message is safe to show the operator."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ServerConfig(_Strict):
    host: Literal["127.0.0.1"] = "127.0.0.1"
    port: int = Field(default=8090, ge=1024, le=65535)
    log_dir: str = "logs"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"


class UiConfig(_Strict):
    title: str = "SHOW MULTIVIEW"
    clock_24h: bool = False
    countdown_warn_s: int = Field(default=60, ge=0)
    countdown_overrun: Literal["count_up_red"] = "count_up_red"
    layout: Literal["grid2x2"] = "grid2x2"
    # Top-left corner of the multiview monitor, from tools/list_monitors.py.
    window_x: int = 0
    window_y: int = 0


class HealthConfig(_Strict):
    late_ms: int = Field(default=1000, gt=0)
    lost_ms: int = Field(default=3000, gt=0)
    reconnect_interval_ms: int = Field(default=2000, gt=0)
    reconnect_max_interval_ms: int = Field(default=6000, gt=0)
    restored_flash_ms: int = Field(default=3000, ge=0)
    static_after_s: float = Field(default=10, gt=0)
    static_mad_threshold: float = Field(default=0.6, ge=0)
    black_luma_threshold: float = Field(default=10, ge=0, le=255)
    black_after_s: float = Field(default=3, gt=0)

    @model_validator(mode="after")
    def _ordered(self) -> "HealthConfig":
        if self.late_ms >= self.lost_ms:
            raise ValueError("late_ms must be smaller than lost_ms")
        if self.reconnect_interval_ms > self.reconnect_max_interval_ms:
            raise ValueError("reconnect_interval_ms cannot exceed reconnect_max_interval_ms")
        return self


class HealthOverride(_Strict):
    late_ms: Optional[int] = Field(default=None, gt=0)
    lost_ms: Optional[int] = Field(default=None, gt=0)
    reconnect_interval_ms: Optional[int] = Field(default=None, gt=0)
    reconnect_max_interval_ms: Optional[int] = Field(default=None, gt=0)
    restored_flash_ms: Optional[int] = Field(default=None, ge=0)
    static_after_s: Optional[float] = Field(default=None, gt=0)
    static_mad_threshold: Optional[float] = Field(default=None, ge=0)
    black_luma_threshold: Optional[float] = Field(default=None, ge=0, le=255)
    black_after_s: Optional[float] = Field(default=None, gt=0)


class PerfLevel(_Strict):
    fps: int = Field(gt=0, le=60)
    q: int = Field(ge=10, le=100)
    scale: float = Field(gt=0, le=1)


def _default_levels() -> list[PerfLevel]:
    return [
        PerfLevel(fps=30, q=75, scale=1.0),
        PerfLevel(fps=15, q=70, scale=1.0),
        PerfLevel(fps=10, q=65, scale=0.75),
        PerfLevel(fps=5, q=60, scale=0.5),
    ]


class PerfConfig(_Strict):
    auto_degrade: bool = True
    gpu_3d_high_pct: float = Field(default=85, gt=0, le=100)
    cpu_high_pct: float = Field(default=75, gt=0, le=100)
    sustain_s: float = Field(default=5, gt=0)
    recover_s: float = Field(default=30, gt=0)
    levels: list[PerfLevel] = Field(default_factory=_default_levels, min_length=1)


class AudioShowConfig(_Strict):
    enabled: bool = True
    source: Literal["wasapi_loopback", "synthetic"] = "wasapi_loopback"
    device_match: str = "Speakers"
    attach_to_feed: str = "center"


class AudioConfig(_Strict):
    show: AudioShowConfig = AudioShowConfig()


class PreviewConfig(_Strict):
    width: int = Field(default=960, ge=64, le=3840)
    height: int = Field(default=540, ge=36, le=2160)
    fps: int = Field(default=30, gt=0, le=60)
    jpeg_quality: int = Field(default=75, ge=10, le=100)


class SpoutConfig(_Strict):
    sender: str = Field(min_length=1)
    # Set true only if the on-site check shows the picture upside down.
    flip_vertical: bool = False


class RtspConfig(_Strict):
    url: str = Field(min_length=1)
    transport: Literal["tcp"] = "tcp"
    open_timeout_ms: int = Field(default=3000, gt=0)
    read_timeout_ms: int = Field(default=2000, gt=0)
    audio_meter: bool = True

    @field_validator("url")
    @classmethod
    def _rtsp_scheme(cls, value: str) -> str:
        if not value.lower().startswith(("rtsp://", "rtsps://")):
            raise ValueError("must start with rtsp://")
        return value


class SyntheticConfig(_Strict):
    """Test pattern with scripted faults, used for development and rehearsal without hardware."""

    background: tuple[int, int, int] = (40, 44, 52)
    motion: Literal["horizontal", "vertical"] = "horizontal"
    audio_meter: Optional[Literal["cam", "no_track"]] = None
    dropout_after_s: Optional[float] = Field(default=None, ge=0)
    dropout_for_s: float = Field(default=8, gt=0)
    stall_after_s: Optional[float] = Field(default=None, ge=0)
    stall_for_s: float = Field(default=2, gt=0)
    freeze_picture_after_s: Optional[float] = Field(default=None, ge=0)
    freeze_picture_for_s: float = Field(default=15, gt=0)
    black_picture_after_s: Optional[float] = Field(default=None, ge=0)
    black_picture_for_s: float = Field(default=8, gt=0)
    crash_after_s: Optional[float] = Field(default=None, ge=0)
    repeat_every_s: Optional[float] = Field(default=None, gt=0)


class NdiConfig(_Strict):
    source: str = ""


class DisplayConfig(_Strict):
    monitor_index: int = 0
    max_fps: int = 15


class UvcConfig(_Strict):
    device: str = ""


class FeedConfig(_Strict):
    id: str = Field(pattern=r"^[a-z0-9_-]{1,32}$")
    label: str = Field(min_length=1)
    type: Literal["spout", "rtsp", "ndi", "display", "uvc", "synthetic"]
    preview: PreviewConfig = PreviewConfig()
    health: Optional[HealthOverride] = None
    spout: Optional[SpoutConfig] = None
    rtsp: Optional[RtspConfig] = None
    synthetic: Optional[SyntheticConfig] = None
    ndi: Optional[NdiConfig] = None
    display: Optional[DisplayConfig] = None
    uvc: Optional[UvcConfig] = None

    @model_validator(mode="after")
    def _type_block(self) -> "FeedConfig":
        if self.type in FALLBACK_TYPES:
            raise ValueError(
                f"feed type '{self.type}' is an on-site fallback that has not been built yet "
                "(plan milestone 9)"
            )
        if self.type == "spout" and self.spout is None:
            raise ValueError("type 'spout' needs spout.sender")
        if self.type == "rtsp" and self.rtsp is None:
            raise ValueError("type 'rtsp' needs rtsp.url")
        return self


class MultiviewConfig(_Strict):
    server: ServerConfig = ServerConfig()
    ui: UiConfig = UiConfig()
    health: HealthConfig = HealthConfig()
    perf: PerfConfig = PerfConfig()
    audio: AudioConfig = AudioConfig()
    feed: list[FeedConfig]

    @model_validator(mode="after")
    def _feeds(self) -> "MultiviewConfig":
        if len(self.feed) != 3:
            raise ValueError(f"exactly 3 [[feed]] blocks are required, found {len(self.feed)}")
        ids = [feed.id for feed in self.feed]
        if len(set(ids)) != len(ids):
            raise ValueError(f"feed ids must be unique, found {ids}")
        show = self.audio.show
        if show.enabled and show.attach_to_feed not in ids:
            raise ValueError(f"audio.show.attach_to_feed '{show.attach_to_feed}' is not a feed id")
        return self

    def health_for(self, feed: FeedConfig) -> HealthConfig:
        """Global [health] values with any per-feed overrides applied."""
        if feed.health is None:
            return self.health
        overrides = feed.health.model_dump(exclude_none=True)
        try:
            return HealthConfig(**{**self.health.model_dump(), **overrides})
        except ValidationError as exc:
            raise ConfigError(f"feed '{feed.id}' health override: {_describe(exc)}") from exc


def _describe(exc: ValidationError) -> str:
    lines = []
    for error in exc.errors():
        where = ".".join(str(part) for part in error["loc"]) or "config"
        message = error["msg"].removeprefix("Value error, ")
        lines.append(f"  {where}: {message}")
    return "\n".join(lines)


def parse_config(data: dict) -> MultiviewConfig:
    try:
        config = MultiviewConfig.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(f"Invalid configuration:\n{_describe(exc)}") from exc
    for feed in config.feed:
        config.health_for(feed)
    return config


def load_config(path: str | Path) -> MultiviewConfig:
    path = Path(path)
    try:
        with path.open("rb") as handle:
            data = tomllib.load(handle)
    except FileNotFoundError as exc:
        raise ConfigError(f"Config file not found: {path}") from exc
    except OSError as exc:
        raise ConfigError(f"Cannot read config file {path}: {exc.strerror}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"Config file {path} is not valid TOML: {exc}") from exc
    return parse_config(data)
