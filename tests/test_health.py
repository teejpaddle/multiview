import json
import logging
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

from mvbridge.config import HealthConfig
from mvbridge.health import (
    LATE,
    LIVE,
    NO_SIGNAL,
    FpsMeter,
    PictureAnalyzer,
    StatusStore,
    TileMachine,
)
from mvbridge.protocol import FrameMsg

TESTS = Path(__file__).parent
VECTORS = json.loads((TESTS / "vectors" / "tile_states.json").read_text(encoding="utf-8"))


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def scenario_ids():
    return [scenario["name"] for scenario in VECTORS["scenarios"]]


@pytest.mark.parametrize("scenario", VECTORS["scenarios"], ids=scenario_ids())
def test_tile_machine_vectors(scenario):
    machine = TileMachine(HealthConfig(**VECTORS["thresholds"]), scenario["steps"][0]["t"])
    for step in scenario["steps"]:
        if step.get("frame"):
            machine.on_frame(step["t"])
        actual = machine.update(
            step["t"],
            step.get("source", "connecting"),
            step.get("static", False),
            step.get("black", False),
            step.get("paused", False),
            step.get("offline", False),
        )
        assert actual == step["expect"], f"at t={step['t']}"


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is not installed")
def test_browser_state_machine_matches_the_same_vectors():
    result = subprocess.run(
        ["node", str(TESTS / "run_tile_vectors.mjs")], capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, result.stderr


def moving(index: int) -> np.ndarray:
    image = np.full((540, 960, 3), 80, dtype=np.uint8)
    left = (index * 60) % 840
    image[:, left : left + 120] = 255
    return image


def test_moving_picture_is_not_static():
    clock = FakeClock()
    analyzer = PictureAnalyzer(HealthConfig(), clock)
    for index in range(400):
        clock.now = index / 30
        flags = analyzer.update(moving(index))
    assert not flags.static
    assert not flags.black


def test_frozen_picture_turns_static_after_threshold():
    clock = FakeClock()
    analyzer = PictureAnalyzer(HealthConfig(static_after_s=10), clock)
    picture = moving(0)
    analyzer.update(picture)
    clock.now = 9.9
    assert not analyzer.update(picture).static
    clock.now = 10.0
    flags = analyzer.update(picture)
    assert flags.static
    assert flags.static_s == pytest.approx(10.0)


def test_picture_change_clears_static():
    clock = FakeClock()
    analyzer = PictureAnalyzer(HealthConfig(static_after_s=1), clock)
    analyzer.update(moving(0))
    clock.now = 2
    assert analyzer.update(moving(0)).static
    clock.now = 2.1
    assert not analyzer.update(moving(5)).static


def test_slow_fade_still_counts_as_motion():
    clock = FakeClock()
    analyzer = PictureAnalyzer(HealthConfig(static_after_s=5, static_mad_threshold=0.6), clock)
    for index in range(600):
        clock.now = index / 30
        level = 40 + index // 6  # About 0.17 luma per frame, below the threshold each time.
        flags = analyzer.update(np.full((540, 960, 3), level, dtype=np.uint8))
    assert not flags.static


def test_black_after_threshold():
    clock = FakeClock()
    analyzer = PictureAnalyzer(HealthConfig(black_after_s=3), clock)
    black = np.zeros((540, 960, 3), dtype=np.uint8)
    analyzer.update(black)
    clock.now = 2.9
    assert not analyzer.update(black).black
    clock.now = 3.0
    assert analyzer.update(black).black
    clock.now = 3.1
    assert not analyzer.update(moving(1)).black


def test_fps_meter_window():
    meter = FpsMeter()
    for index in range(60):
        meter.tick(index / 30)
    assert meter.value(59 / 30) == pytest.approx(30, abs=1)
    assert meter.value(10) == 0


def test_status_store_logs_tile_transitions(caplog):
    clock = FakeClock()
    clock.now = 1_000_000
    store = StatusStore({"ptz": HealthConfig()}, wall_ms=lambda: int(clock.now))
    frame = FrameMsg(1, 1_000_000_000_000, 960, 540, b"x")
    store.on_state("ptz", "connected")
    with caplog.at_level(logging.INFO, logger="mvbridge.health"):
        store.on_frame("ptz", frame)
        store.tick()
        clock.now += 1200
        store.tick()
        clock.now += 2000
        store.tick()
    messages = [record.getMessage() for record in caplog.records]
    assert any(f"to={LIVE} " in message for message in messages)
    assert any(f"from={LIVE} to={LATE}" in message for message in messages)
    assert any(f"from={LATE} to={NO_SIGNAL}" in message for message in messages)


def test_reconnects_are_counted_but_not_the_first_connection():
    store = StatusStore({"ptz": HealthConfig()})
    store.on_state("ptz", "connected")
    store.on_state("ptz", "disconnected", "cable")
    store.on_state("ptz", "connected")
    assert store.feeds_snapshot()["ptz"]["reconnects"] == 1
