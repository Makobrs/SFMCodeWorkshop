from __future__ import annotations

import pytest

from sfm_workshop.core import storage, templates, tps
from sfm_workshop.core.model import Project, Send, Take, Task

LEVELS = {"低", "中", "高", "未知"}


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    monkeypatch.setattr(storage, "resource_root", lambda: tmp_path / "resources")
    return tmp_path


def make_task(
    *,
    source: str = "来源",
    target: str = "目标",
    interval: int = 20,
    unit: str = "TICKS",
    trigger_kind: str = "timer",
    take_side: str = "默认面",
    send_side: str = "默认面",
    quantity: int = 1,
    with_filter: str = "",
    condition: str = "",
    sends: int = 1,
) -> Task:
    task = Task(
        name="任务",
        interval=interval,
        unit=unit,
        trigger_kind=trigger_kind,
    )
    task.batches[0].take = Take(
        source=source,
        side=take_side,
        quantity=quantity,
        with_filter=with_filter,
    )
    task.batches[0].sends = [
        Send(target=f"{target}{index}" if index else target, side=send_side)
        for index in range(sends)
    ]
    task.batches[0].condition = condition
    return task


def make_project(*tasks: Task) -> Project:
    project = Project(name="估算工程")
    for task in tasks:
        project.tasks.append(task)
    project.active_task_id = project.tasks[0].id if project.tasks else None
    return project


def test_estimate_is_deterministic_and_well_formed():
    project = make_project(make_task())
    first = tps.estimate_tps(project)
    second = tps.estimate_tps(project)
    assert first == second
    assert first.score >= 0
    assert first.level in LEVELS
    assert first.factors
    assert all(isinstance(factor.value, float) for factor in first.factors)
    assert "估算" in first.note
    assert "不是实测" in first.note


def test_all_templates_estimate_within_contract():
    for info in templates.list_templates():
        project = templates.load_template(info.key)
        estimate = tps.estimate_tps(project)
        assert estimate.level in LEVELS
        assert estimate.score >= 0
        assert estimate.factors
        assert estimate.note


def test_score_is_a_0_to_100_relative_index():
    for info in templates.list_templates():
        estimate = tps.estimate_tps(templates.load_template(info.key))
        assert 0 <= estimate.score <= tps.SCORE_MAX
    energy_estimate = tps.estimate_tps(templates.load_template("energy"))
    furnace_score = tps.estimate_tps(templates.load_template("furnace")).score
    assert energy_estimate.score == tps.SCORE_MAX
    assert energy_estimate.level == "高"
    assert 0 < furnace_score < tps.SCORE_MAX


def test_pulse_frequency_is_unknown():
    pulse = make_project(make_task(trigger_kind="pulse"))
    estimate = tps.estimate_tps(pulse)
    assert estimate.level == "未知"
    assert any("脉冲" in warning and "频率" in warning for warning in estimate.warnings)
    assert estimate.score > 0


def test_no_tasks_is_unknown_zero():
    estimate = tps.estimate_tps(Project(name="空工程"))
    assert estimate.score == 0
    assert estimate.level == "未知"
    assert estimate.warnings
    assert estimate.factors


def test_disabled_task_is_ignored():
    task = make_task()
    task.enabled = False
    estimate = tps.estimate_tps(make_project(task))
    assert estimate.score == 0
    assert estimate.level == "未知"


def test_each_side_increases_score():
    default = tps.estimate_tps(make_project(make_task()))
    each_side = tps.estimate_tps(
        make_project(make_task(take_side="每个面", send_side="每个面"))
    )
    assert each_side.score > default.score
    assert any("每个面" in warning for warning in each_side.warnings)
    assert any("每个面" in item for item in each_side.suggestions)


def test_faster_interval_increases_score():
    slow = tps.estimate_tps(make_project(make_task(interval=200)))
    fast = tps.estimate_tps(make_project(make_task(interval=20)))
    assert fast.score > slow.score
    assert fast.score == pytest.approx(slow.score * 10)


def test_seconds_unit_matches_ticks():
    seconds = tps.estimate_tps(make_project(make_task(interval=1, unit="SECONDS")))
    ticks = tps.estimate_tps(make_project(make_task(interval=20, unit="TICKS")))
    assert seconds.score == pytest.approx(ticks.score)


def test_condition_and_filter_increase_score():
    plain = tps.estimate_tps(make_project(make_task(quantity=1)))
    conditional = tps.estimate_tps(
        make_project(make_task(quantity=1, condition="redstone"))
    )
    filtered = tps.estimate_tps(make_project(make_task(quantity=1, with_filter="#c:ores")))
    assert conditional.score > plain.score
    assert filtered.score > plain.score
    assert any("IF" in warning for warning in conditional.warnings)
    assert any("过滤" in warning for warning in filtered.warnings)


def test_multiple_sends_increase_score_and_suggest_split():
    one = tps.estimate_tps(make_project(make_task(sends=1)))
    three = tps.estimate_tps(make_project(make_task(sends=3)))
    assert three.score > one.score
    assert any("3 个送" in warning for warning in three.warnings)
    assert any("减少同时送的目标" in item for item in three.suggestions)


def test_unlimited_quantity_adds_warning_and_suggestion():
    limited = tps.estimate_tps(make_project(make_task(quantity=8)))
    unlimited = tps.estimate_tps(make_project(make_task(quantity=0)))
    assert any("未限制取货数量" in warning for warning in unlimited.warnings)
    assert any("设置数量" in item for item in unlimited.suggestions)
    # Quantity does not change the contract's blocks x sides x slots formula.
    assert unlimited.score == limited.score


def test_fast_non_energy_timer_warns_only_when_relevant():
    normal = make_project(make_task(interval=20))
    fast = make_project(make_task(interval=1))
    energy_fast = make_project(
        Task(name="能量", interval=1)
    )
    energy_fast.tasks[0].batches[0].take = Take(
        source="能源", side="顶面", resource_type="能量"
    )
    energy_fast.tasks[0].batches[0].sends = [Send(target="机器", side="顶面")]

    assert not any("周期 20 tick 属高频" in w for w in tps.estimate_tps(normal).warnings)
    assert any("周期 1 tick 属高频" in w for w in tps.estimate_tps(fast).warnings)
    assert not any("属高频" in w for w in tps.estimate_tps(energy_fast).warnings)


def test_multiple_tasks_accumulate_score():
    one = tps.estimate_tps(make_project(make_task()))
    two = tps.estimate_tps(make_project(make_task(), make_task()))
    assert two.score == pytest.approx(one.score * 2)


def test_level_thresholds_are_relative_and_documented():
    estimate = tps.estimate_tps(make_project(make_task(interval=20)))
    assert estimate.level == "中"
    factor = next(f for f in estimate.factors if f.name == "相对成本指数")
    assert "不是 TPS" in factor.detail
    assert 0 < estimate.score < tps.SCORE_MAX


def test_malformed_quantity_does_not_crash():
    task = make_task()
    task.batches[0].take.quantity = "not-a-number"  # type: ignore[assignment]
    estimate = tps.estimate_tps(make_project(task))
    assert estimate.score >= 0
    assert estimate.level in LEVELS


def test_estimate_does_not_read_game_data():
    import inspect

    source = inspect.getsource(tps)
    for forbidden in ("socket", "requests", "urllib", "subprocess", "psutil"):
        assert forbidden not in source
