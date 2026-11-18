import copy
import subprocess
import sys
from pathlib import Path

import pytest

from mvbridge.config import ConfigError, load_config, parse_config

ROOT = Path(__file__).resolve().parents[1]

VALID = {
    "feed": [
        {"id": "center", "label": "CENTER", "type": "spout", "spout": {"sender": "MV Center"}},
        {"id": "side", "label": "SIDE", "type": "spout", "spout": {"sender": "MV Side"}},
        {"id": "ptz", "label": "PTZ", "type": "rtsp", "rtsp": {"url": "rtsp://10.0.0.5:554/2"}},
    ]
}


def variant(**changes):
    data = copy.deepcopy(VALID)
    data.update(changes)
    return data


@pytest.mark.parametrize("name", ["multiview.example.toml", "multiview.dev.toml", "multiview.faults.toml"])
def test_shipped_configs_are_valid(name):
    assert len(load_config(ROOT / "config" / name).feed) == 3


def test_example_matches_plan_values():
    cfg = load_config(ROOT / "config" / "multiview.example.toml")
    assert cfg.server.host == "127.0.0.1"
    assert [level.fps for level in cfg.perf.levels] == [30, 15, 10, 5]
    assert (cfg.feed[0].preview.width, cfg.feed[0].preview.height) == (1152, 536)
    assert cfg.feed[2].rtsp.transport == "tcp"


def test_unknown_key_is_an_error():
    with pytest.raises(ConfigError, match="surprise"):
        parse_config(variant(surprise=True))


def test_unknown_nested_key_is_an_error():
    with pytest.raises(ConfigError, match="latee_ms"):
        parse_config(variant(health={"latee_ms": 5}))


def test_duplicate_feed_ids_rejected():
    data = copy.deepcopy(VALID)
    data["feed"][1]["id"] = "center"
    with pytest.raises(ConfigError, match="unique"):
        parse_config(data)


@pytest.mark.parametrize("count", [2, 4])
def test_exactly_three_feeds(count):
    data = copy.deepcopy(VALID)
    data["feed"] = (data["feed"] * 2)[:count]
    for index, feed in enumerate(data["feed"]):
        feed["id"] = f"feed{index}"
    data["audio"] = {"show": {"attach_to_feed": "feed0"}}
    with pytest.raises(ConfigError, match="exactly 3"):
        parse_config(data)


def test_refuses_to_bind_beyond_loopback():
    with pytest.raises(ConfigError, match="server.host"):
        parse_config(variant(server={"host": "0.0.0.0"}))


def test_late_must_be_before_lost():
    with pytest.raises(ConfigError, match="late_ms"):
        parse_config(variant(health={"late_ms": 5000, "lost_ms": 3000}))


def test_audio_must_attach_to_a_real_feed():
    with pytest.raises(ConfigError, match="attach_to_feed"):
        parse_config(variant(audio={"show": {"attach_to_feed": "nope"}}))


def test_unbuilt_fallback_explains_itself():
    data = copy.deepcopy(VALID)
    data["feed"][0] = {"id": "center", "label": "C", "type": "ndi"}
    with pytest.raises(ConfigError, match="milestone 9"):
        parse_config(data)


def test_feed_type_needs_its_block():
    data = copy.deepcopy(VALID)
    del data["feed"][0]["spout"]
    with pytest.raises(ConfigError, match="spout.sender"):
        parse_config(data)


def test_per_feed_health_override():
    data = copy.deepcopy(VALID)
    data["feed"][2]["health"] = {"late_ms": 1500}
    cfg = parse_config(data)
    assert cfg.health_for(cfg.feed[2]).late_ms == 1500
    assert cfg.health_for(cfg.feed[0]).late_ms == 1000


def test_invalid_override_combination_rejected():
    data = copy.deepcopy(VALID)
    data["feed"][2]["health"] = {"late_ms": 9000}
    with pytest.raises(ConfigError, match="late_ms"):
        parse_config(data)


def test_bad_config_exits_2_without_a_traceback(tmp_path):
    path = tmp_path / "bad.toml"
    path.write_text("[server]\nhost = '0.0.0.0'\n", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-m", "mvbridge", "--config", str(path)],
        capture_output=True, text=True, cwd=ROOT, timeout=30,
    )
    assert result.returncode == 2
    assert "Invalid configuration" in result.stderr
    assert "Traceback" not in result.stderr


def test_missing_file_message():
    with pytest.raises(ConfigError, match="not found"):
        load_config("does-not-exist.toml")
