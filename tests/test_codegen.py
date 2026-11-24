from __future__ import annotations

import pytest

from sfm_workshop.core import codegen
from sfm_workshop.core.model import Project, Send, SIDES, Take, Task
from sfm_workshop.grammar import parse_sfml


def assert_parses(code: str) -> None:
    errors = parse_sfml(code)
    assert errors == [], (errors, code)


def make_task(
    take: Take | None = None,
    sends: list[Send] | None = None,
    *,
    name: str = "任务",
    **kwargs: object,
) -> Task:
    task = Task(name=name, **kwargs)  # type: ignore[arg-type]
    task.batches[0].take = take or Take(source="来源")
    task.batches[0].sends = sends if sends is not None else [Send(target="目标")]
    return task


def make_project(*tasks: Task, name: str = "测试工程", profile: str = "1.21.1-neoforge") -> Project:
    project = Project(name=name, profile_id=profile)
    project.tasks = list(tasks)
    project.active_task_id = project.tasks[0].id if project.tasks else None
    return project


def test_generate_task_contract_signature():
    task = make_task()
    code = codegen.generate_task(task)
    assert isinstance(code, str)
    assert code.startswith("every 20 ticks do")
    assert code.endswith("end\n")
    assert_parses(code)


def test_basic_project_is_deterministic_lf_and_parses():
    task = make_task(
        Take(source="原料箱", quantity=8, retain=2),
        [Send(target="熔炉", side="顶面")],
    )
    project = make_project(task, name="熔炉自动线")

    first = codegen.generate_project(project)
    second = codegen.generate_project(project)

    assert first == second
    assert "\r" not in first
    assert first.endswith("\n")
    assert first.startswith('name "熔炉自动线"\n')
    assert '    input 8 retain 2 from "原料箱"\n' in first
    assert '    output to "熔炉" top side\n' in first
    assert "    forget\n" in first
    assert_parses(first)


def test_blank_project_returns_name_only():
    code = codegen.generate_project(Project(name="空白工程"))
    assert code == 'name "空白工程"\n'
    assert_parses(code)


def test_no_name_and_no_tasks_returns_empty_string():
    assert codegen.generate_project(Project(name="   ")) == ""


def test_embedded_quotes_are_escaped():
    task = make_task(Take(source='入"口'), [Send(target='出"口')])
    code = codegen.generate_project(make_project(task, name='我的"工坊"'))
    assert 'name "我的\\"工坊\\""' in code
    assert 'from "入\\"口"' in code
    assert_parses(code)


def test_side_suffix_mapping():
    assert codegen.side_suffix("默认面") == ""
    assert codegen.side_suffix("") == ""
    assert codegen.side_suffix("未知面") == ""
    assert codegen.side_suffix("每个面") == "each side"
    assert codegen.side_suffix("顶面") == "top side"
    assert codegen.side_suffix("底面") == "bottom side"
    assert codegen.side_suffix("北面") == "north side"
    assert codegen.side_suffix("南面") == "south side"
    assert codegen.side_suffix("东面") == "east side"
    assert codegen.side_suffix("西面") == "west side"
    # Every model side except the default maps to a concrete SFML qualifier.
    for side in SIDES:
        if side != "默认面":
            assert codegen.side_suffix(side)


def test_each_side_on_take_and_send():
    task = make_task(
        Take(source="水箱", side="每个面", resource_type="流体"),
        [Send(target="机器", side="每个面")],
    )
    code = codegen.generate_project(make_project(task, name="x"))
    assert 'from "水箱" each side' in code
    assert 'to "机器" each side' in code
    assert_parses(code)


def test_quantity_retain_resource_item():
    task = make_task(
        Take(source="a", quantity=8, retain=2, resource_id="minecraft:iron_ingot"),
        [Send(target="b", retain=1)],
    )
    code = codegen.generate_project(make_project(task, name="x"))
    assert 'input 8 retain 2 minecraft:iron_ingot from "a"' in code
    assert 'output retain 1 to "b"' in code
    assert_parses(code)


def test_with_filter_only():
    task = make_task(Take(source="a", with_filter="#c:ores"))
    code = codegen.generate_project(make_project(task, name="x"))
    assert 'input with #c:ores from "a"' in code
    assert_parses(code)


def test_without_filter_only():
    task = make_task(Take(source="a", without_filter="#minecraft:planks"))
    code = codegen.generate_project(make_project(task, name="x"))
    assert 'input without #minecraft:planks from "a"' in code
    assert_parses(code)


def test_bare_filter_is_tagged():
    task = make_task(Take(source="a", with_filter="forge:gems"))
    code = codegen.generate_project(make_project(task, name="x"))
    assert "input with tag forge:gems from" in code
    assert_parses(code)


def test_both_filters_become_one_compound_clause():
    task = make_task(
        Take(source="a", with_filter="#c:ores", without_filter="#minecraft:planks")
    )
    code = codegen.generate_project(make_project(task, name="x"))
    assert 'input with (#c:ores) and (not (#minecraft:planks)) from "a"' in code
    assert_parses(code)


@pytest.mark.parametrize(
    ("resource_type", "resource_id", "expected"),
    [
        ("物品", "", ""),
        ("物品", "minecraft:diamond", "minecraft:diamond"),
        ("物品", "item:minecraft:redstone", "item:minecraft:redstone"),
        ("流体", "", "fluid::"),
        ("流体", "minecraft:water", "fluid:minecraft:water"),
        ("流体", "fluid:minecraft:water", "fluid:minecraft:water"),
        ("能量", "", "fe::"),
        ("能量", "forge_energy:forge:energy", "forge_energy:forge:energy"),
    ],
)
def test_resource_token(resource_type: str, resource_id: str, expected: str):
    take = Take(source="a", resource_type=resource_type, resource_id=resource_id)
    assert codegen.resource_token(take) == expected


def test_chemical_prefix_depends_on_profile():
    take = Take(source="a", resource_type="化学品", resource_id="mekanism:nuclear_waste")
    assert codegen.resource_token(take, "1.21.1-neoforge") == "chemical:mekanism:nuclear_waste"
    assert codegen.resource_token(take, "1.20.1-forge") == "gas:mekanism:nuclear_waste"

    empty = Take(source="a", resource_type="化学品")
    assert codegen.resource_token(empty, "1.20.1-forge") == "gas::"
    assert codegen.resource_token(empty, "1.21.1-neoforge") == "chemical::"


def test_condition_wraps_batch_statement():
    task = make_task(Take(source="原料"), [Send(target="熔炉")])
    task.batches[0].condition = '"仓库" has > 100'
    code = codegen.generate_project(make_project(task, name="x"))
    assert '    if "仓库" has > 100 then\n' in code
    assert code.count("end\n") == 2  # IF end + trigger end
    assert_parses(code)


def test_condition_accepts_pasted_if_statement():
    task = make_task(Take(source="a"))
    task.batches[0].condition = 'if redstone > 0 then'
    code = codegen.generate_project(make_project(task, name="x"))
    assert "if redstone > 0 then" in code
    assert "if if" not in code
    assert_parses(code)


def test_pulse_trigger():
    task = make_task(trigger_kind="pulse")
    code = codegen.generate_project(make_project(task, name="红石脉冲"))
    assert "every redstone pulse do" in code
    assert_parses(code)


def test_seconds_unit():
    task = make_task(unit="SECONDS", interval=5)
    code = codegen.generate_project(make_project(task, name="x"))
    assert "every 5 seconds do" in code
    assert_parses(code)


def test_disabled_and_empty_tasks_are_skipped():
    empty = Task(name="空任务")  # no source / no target
    disabled = make_task(Take(source="a"), name="禁用任务")
    disabled.enabled = False
    enabled = make_task(Take(source="来源"), name="保留任务")
    project = make_project(empty, disabled, enabled, name="x")
    code = codegen.generate_project(project)
    assert "空任务" not in code
    assert "禁用任务" not in code
    assert code.count("every ") == 1
    assert_parses(code)


def test_multiple_tasks_are_separated_by_blank_line():
    first = make_task(Take(source="a"), name="一")
    second = make_task(Take(source="b"), name="二")
    code = codegen.generate_project(make_project(first, second, name="x"))
    assert code.count("every 20 ticks do") == 2
    assert "\n\n" in code
    assert "end\n\nevery" in code
    assert_parses(code)


def test_invalid_values_are_clamped_for_l0_safety():
    task = make_task(
        Take(source="a", quantity=-5, retain=-2, side="不存在面"),
        [Send(target="b", retain=-1, side="也不存在")],
        interval=0,
    )
    code = codegen.generate_project(make_project(task, name="x"))
    assert "every 1 ticks do" in code
    assert "-5" not in code and "retain -" not in code
    assert_parses(code)


def test_trailing_backslash_label_still_parses():
    task = make_task(Take(source="尾巴\\"), [Send(target="出口\\")])
    code = codegen.generate_project(make_project(task, name="x"))
    # Lossy but parseable; validate.project reports the label as unrepresentable.
    assert 'from "尾巴"' in code
    assert_parses(code)


def test_no_nbt_or_435_syntax():
    task = make_task(
        Take(source="a", resource_type="流体", resource_id="minecraft:water"),
        [Send(target="b")],
    )
    code = codegen.generate_project(make_project(task, name="x"))
    for token in ("{", "}", "LET ", "CREATE INPUT", "BROADCAST", "RENDER IMAGE"):
        assert token not in code
    assert_parses(code)


def test_clear_only_batch_is_skipped():
    task = Task(name="只有清空")
    assert task.batches[0].clear is True
    assert codegen.generate_task(task) == ""


def test_invalid_filter_is_omitted_but_code_parses():
    task = make_task(Take(source="a", with_filter="a b"))
    code = codegen.generate_project(make_project(task, name="x"))
    assert "with" not in code
    assert_parses(code)


def test_invalid_condition_is_omitted_but_code_parses():
    task = make_task(Take(source="a"))
    task.batches[0].condition = "redstone >"
    code = codegen.generate_project(make_project(task, name="x"))
    assert "if " not in code
    assert code.count("end") == 1
    assert_parses(code)


def test_invalid_resource_id_keeps_type_intent_and_parses():
    fluid = make_task(
        Take(source="a", resource_type="流体", resource_id='bad"id')
    )
    fluid_code = codegen.generate_project(make_project(fluid, name="x"))
    assert "fluid::" in fluid_code
    assert_parses(fluid_code)

    item = make_task(Take(source="a", resource_id="a:b:c:d:e"))
    item_code = codegen.generate_project(make_project(item, name="x"))
    assert "a:b:c:d:e" not in item_code
    assert_parses(item_code)


def test_quoted_regex_resource_is_kept():
    task = make_task(Take(source="a", quantity=5, resource_id='".*_ingot"'))
    code = codegen.generate_project(make_project(task, name="x"))
    assert 'input 5 ".*_ingot" from "a"' in code
    assert_parses(code)


def test_generate_task_accepts_profile_for_chemical_prefix():
    task = make_task(Take(source="a", resource_type="化学品", resource_id="mekanism:oxygen"))
    code = codegen.generate_task(task, "1.20.1-forge")
    assert "gas:mekanism:oxygen" in code
    assert_parses(code)


def test_generated_statements_do_not_have_trailing_spaces():
    task = make_task(
        Take(source="a", quantity=1),
        [Send(target="b", side="顶面")],
        name="x",
    )
    code = codegen.generate_project(make_project(task, name="x"))
    for line in code.splitlines():
        assert line == line.rstrip()
