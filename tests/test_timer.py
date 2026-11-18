import pytest

from mvbridge.timer import CountdownTimer, TimerError


class Clock:
    def __init__(self, now=1_000_000):
        self.now = now

    def __call__(self):
        return self.now


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def timer(clock):
    item = CountdownTimer(None, clock)
    item.apply("set_duration", 60_000)
    return item


def test_counts_down_from_the_wall_clock(timer, clock):
    timer.apply("start")
    clock.now += 15_000
    snapshot = timer.snapshot()
    assert snapshot["mode"] == "running"
    assert snapshot["remaining_ms"] == 45_000


def test_pause_and_resume_keep_remaining_time(timer, clock):
    timer.apply("start")
    clock.now += 10_000
    assert timer.apply("pause")["remaining_ms"] == 50_000
    clock.now += 99_000
    assert timer.snapshot()["remaining_ms"] == 50_000
    timer.apply("start")
    clock.now += 5_000
    assert timer.snapshot()["remaining_ms"] == 45_000


def test_runs_into_overrun(timer, clock):
    timer.apply("start")
    clock.now += 61_000
    snapshot = timer.snapshot()
    assert snapshot["mode"] == "overrun"
    assert snapshot["remaining_ms"] == -1_000


def test_reset_returns_to_the_duration(timer, clock):
    timer.apply("start")
    clock.now += 70_000
    snapshot = timer.apply("reset")
    assert snapshot["mode"] == "idle"
    assert snapshot["remaining_ms"] == 60_000


def test_running_countdown_cannot_be_replaced_by_accident(timer):
    timer.apply("start")
    with pytest.raises(TimerError):
        timer.apply("set_duration", 300_000)
    with pytest.raises(TimerError):
        timer.apply("set_target", 9_999_999_999)


def test_target_time_starts_counting(timer, clock):
    snapshot = timer.apply("set_target", clock.now + 120_000)
    assert snapshot["mode"] == "running"
    assert snapshot["remaining_ms"] == 120_000


def test_target_in_the_past_is_rejected(timer, clock):
    with pytest.raises(TimerError):
        timer.apply("set_target", clock.now - 1)


@pytest.mark.parametrize("value", [None, 0, -5])
def test_bad_duration_is_rejected(timer, value):
    with pytest.raises(TimerError):
        timer.apply("set_duration", value)


def test_running_timer_survives_a_restart(tmp_path, clock):
    path = tmp_path / "timer.json"
    first = CountdownTimer(path, clock)
    first.apply("set_duration", 60_000)
    first.apply("start")
    clock.now += 20_000
    second = CountdownTimer(path, clock)
    assert second.snapshot()["mode"] == "running"
    assert second.snapshot()["remaining_ms"] == 40_000


def test_paused_timer_survives_a_restart(tmp_path, clock):
    path = tmp_path / "timer.json"
    first = CountdownTimer(path, clock)
    first.apply("set_duration", 60_000)
    first.apply("start")
    clock.now += 20_000
    first.apply("pause")
    clock.now += 500_000
    assert CountdownTimer(path, clock).snapshot()["remaining_ms"] == 40_000


@pytest.mark.parametrize("content", ["not json", "{}", '{"mode":"running","duration_ms":1,"remaining_ms":1,"target_epoch_ms":null}'])
def test_damaged_state_file_is_ignored(tmp_path, clock, content):
    path = tmp_path / "timer.json"
    path.write_text(content, encoding="utf-8")
    assert CountdownTimer(path, clock).snapshot()["mode"] == "idle"
