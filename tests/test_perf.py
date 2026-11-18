import pytest

from mvbridge.config import PerfConfig
from mvbridge.perf import DegradeController, aggregate_gpu


def run(controller, start, end, cpu, gpu=None):
    level = controller.level
    for second in range(start, end):
        level = controller.update(float(second), cpu, gpu)
    return level


def test_steps_down_only_after_sustained_load():
    controller = DegradeController(PerfConfig(sustain_s=5))
    assert run(controller, 0, 5, 90) == 0
    assert run(controller, 5, 6, 90) == 1


def test_brief_spike_is_ignored():
    controller = DegradeController(PerfConfig(sustain_s=5))
    run(controller, 0, 4, 90)
    run(controller, 4, 5, 10)
    assert run(controller, 5, 9, 90) == 0


def test_stops_at_the_lowest_level():
    controller = DegradeController(PerfConfig(sustain_s=1))
    assert run(controller, 0, 60, 99) == 3


def test_recovers_one_level_at_a_time():
    controller = DegradeController(PerfConfig(sustain_s=1, recover_s=30))
    run(controller, 0, 10, 99)
    assert controller.level == 3
    assert run(controller, 10, 40, 10) == 3
    assert run(controller, 40, 41, 10) == 2
    assert run(controller, 41, 71, 10) == 1


def test_gpu_load_also_degrades():
    controller = DegradeController(PerfConfig(sustain_s=1))
    assert run(controller, 0, 3, 10, 95) >= 1


def test_auto_degrade_can_be_disabled():
    controller = DegradeController(PerfConfig(auto_degrade=False, sustain_s=1))
    assert run(controller, 0, 20, 99, 99) == 0


def test_missing_gpu_counter_uses_cpu_only():
    controller = DegradeController(PerfConfig(sustain_s=1))
    assert run(controller, 0, 5, 10, None) == 0


def test_gpu_is_summed_per_adapter_and_busiest_wins():
    values = {
        "pid_1_luid_0x00000000_0x0000A000_phys_0_eng_0_engtype_3D": 30.0,
        "pid_2_luid_0x00000000_0x0000A000_phys_0_eng_0_engtype_3D": 25.0,
        "pid_3_luid_0x00000000_0x0000B000_phys_0_eng_0_engtype_3D": 40.0,
    }
    assert aggregate_gpu(values) == pytest.approx(55.0)


def test_gpu_total_is_capped_and_handles_no_data():
    assert aggregate_gpu({"pid_1_luid_0x0_0x1_eng_0": 70, "pid_2_luid_0x0_0x1_eng_1": 70}) == 100
    assert aggregate_gpu({}) is None
