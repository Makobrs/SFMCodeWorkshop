from __future__ import annotations

from sfm_workshop.core import validate
from sfm_workshop.core.model import Label, Project, Send, Take, Task
from sfm_workshop.grammar import parse_sfml


def codes(result: validate.ValidationResult) -> list[str]:
    return [issue.code for issue in result.issues]


def test_valid_code_is_not_blocked():
    code = (
        'name "有效程序"\n'
        "every 20 ticks do\n"
        '    input 8 retain 2 from "原料箱" top side\n'
        '    output to "熔炉" top side\n'
        "    forget\n"
        "end\n"
    )
    result = validate.validate_code(code)
    assert result.syntax_errors == []
    assert result.issues == []
    assert not result.blocked
    assert result.blocks == 0
    assert result.warnings == 0


def test_syntax_error_blocks_and_is_reported_separately():
    code = "every 20 ticks do\n    input from\nend\n"
    result = validate.validate_code(code)
    assert result.syntax_errors
    assert result.blocked
    # Syntax errors live in ``syntax_errors`` (the UI renders that list) and
    # are counted by ``blocks``, but they are not duplicated in ``issues``.
    assert not [issue for issue in result.issues if issue.code == "syntax"]
    assert result.blocks >= 1
    assert any(":0 " in error or ":" in error for error in result.syntax_errors)


def test_program_too_long_blocks():
    code = "--" + "a" * validate.PROGRAM_CHAR_LIMIT
    result = validate.validate_code(code)
    assert "program.too_long" in codes(result)
    assert result.blocked


def test_empty_label_blocks():
    code = 'every 20 ticks do\n    input from ""\n    output to "b"\n    forget\nend\n'
    result = validate.validate_code(code)
    assert "label.empty" in codes(result)
    assert result.blocked


def test_long_label_blocks():
    label = "长" * (validate.LABEL_MAX_LEN + 1)
    code = f'every 20 ticks do\n    input from "{label}"\n    forget\nend\n'
    result = validate.validate_code(code)
    assert "label.too_long" in codes(result)
    assert result.blocked


def test_fast_timer_non_energy_is_possible_not_block():
    code = 'every 1 ticks do\n    input from "a"\n    output to "b"\n    forget\nend\n'
    result = validate.validate_code(code)
    assert "timer.fast" in codes(result)
    assert not result.blocked
    assert result.blocks == 0


def test_fast_timer_energy_only_is_clean():
    code = 'every 1 ticks do\n    input fe:: from "a"\n    output to "b"\n    forget\nend\n'
    result = validate.validate_code(code)
    assert "timer.fast" not in codes(result)


def test_zero_timer_blocks_grammar_ok_but_lint_blocks():
    code = 'every 0 ticks do\n    input from "a"\n    forget\nend\n'
    assert parse_sfml(code) == []  # grammar accepts 0; runtime does not
    result = validate.validate_code(code)
    assert "timer.zero" in codes(result)
    assert result.blocked


def test_each_side_is_a_reminder():
    code = 'every 20 ticks do\n    input 5 from "a" each side\n    output to "b" each side\nend\n'
    result = validate.validate_code(code)
    assert "side.each" in codes(result)
    assert not result.blocked


def test_no_quantity_is_a_possible_issue():
    code = 'every 20 ticks do\n    input from "a"\n    output to "b"\n    forget\nend\n'
    result = validate.validate_code(code)
    issue = next(i for i in result.issues if i.code == "input.no_quantity")
    assert issue.level == "possible"
    assert not result.blocked


def test_missing_forget_is_a_possible_issue():
    code = 'every 20 ticks do\n    input 5 from "a"\n    output to "b"\nend\n'
    result = validate.validate_code(code)
    assert "batch.no_clear" in codes(result)
    assert not result.blocked


def test_output_without_input_is_a_possible_issue():
    code = 'every 20 ticks do\n    output to "b"\n    forget\nend\n'
    result = validate.validate_code(code)
    assert "flow.output_without_input" in codes(result)


def test_overlong_resource_id_blocks():
    code = (
        'every 20 ticks do\n'
        '    input a:b:c:d:e from "x"\n'
        '    forget\n'
        "end\n"
    )
    result = validate.validate_code(code)
    assert "resource.segments" in codes(result)
    assert result.blocked


def test_too_many_if_is_a_reminder():
    body = "".join(
        "    if redstone then\n"
        '        output to "b"\n'
        "    end\n"
        for _ in range(validate.MAX_IF_PER_TRIGGER + 2)
    )
    code = "every 20 ticks do\n" + body + "end\n"
    result = validate.validate_code(code)
    assert "if.too_many" in codes(result)
    assert not result.blocked


def test_tag_filter_is_info_only():
    code = 'every 20 ticks do\n    input with #c:ores from "a"\n    forget\nend\n'
    result = validate.validate_code(code)
    assert "tag.unverified" in codes(result)
    assert not result.blocked


def _valid_project() -> Project:
    project = Project(name="有效工程")
    project.labels = [Label(name="原料箱"), Label(name="熔炉", kind="机器")]
    task = Task(name="投料")
    task.batches[0].take = Take(source="原料箱", quantity=8, retain=2)
    task.batches[0].sends = [Send(target="熔炉", side="顶面")]
    project.tasks = [task]
    project.active_task_id = task.id
    return project


def test_validate_project_clean_project_is_not_blocked():
    result = validate.validate_project(_valid_project())
    assert not result.blocked
    assert result.syntax_errors == []
    assert result.blocks == 0


def test_validate_project_unknown_label_blocks_and_maps_task():
    project = _valid_project()
    project.tasks[0].batches[0].take.source = "不存在的标签"
    result = validate.validate_project(project)
    unknown = [i for i in result.issues if i.code == "label.unknown"]
    assert unknown and unknown[0].level == "block"
    assert unknown[0].task_id == project.tasks[0].id
    assert result.blocked


def test_validate_project_missing_source_and_target_block():
    project = _valid_project()
    project.tasks[0].batches[0].take.source = ""
    project.tasks[0].batches[0].sends = [Send(target="")]
    result = validate.validate_project(project)
    result_codes = codes(result)
    assert "label.missing_source" in result_codes
    assert "label.missing_target" in result_codes
    assert result.blocked


def test_validate_project_negative_limits_block():
    project = _valid_project()
    project.tasks[0].batches[0].take.quantity = -1
    project.tasks[0].batches[0].take.retain = -2
    project.tasks[0].batches[0].sends[0].retain = -3
    result = validate.validate_project(project)
    assert "limit.negative" in codes(result)
    assert result.blocked


def test_validate_project_unknown_side_and_type_block():
    project = _valid_project()
    project.tasks[0].batches[0].take.side = "上边"
    project.tasks[0].batches[0].take.resource_type = "魔法"
    result = validate.validate_project(project)
    result_codes = codes(result)
    assert "side.unknown" in result_codes
    assert "resource_type.unknown" in result_codes
    assert result.blocked


def test_validate_project_label_problems_block():
    project = _valid_project()
    project.labels.append(Label(name="原料箱"))  # duplicate
    project.labels.append(Label(name=""))
    result = validate.validate_project(project)
    result_codes = codes(result)
    assert "label.duplicate" in result_codes
    assert "label.empty_name" in result_codes
    assert result.blocked


def test_validate_project_unrepresentable_label_blocks():
    project = _valid_project()
    project.labels[0].name = "尾\\"
    project.tasks[0].batches[0].take.source = "尾\\"
    result = validate.validate_project(project)
    assert "label.unrepresentable" in codes(result)
    assert result.blocked


def test_disabled_task_is_ignored_except_info():
    project = _valid_project()
    project.tasks[0].enabled = False
    project.tasks[0].batches[0].take.source = ""
    result = validate.validate_project(project)
    assert "task.disabled" in codes(result)
    assert "label.missing_source" not in codes(result)
    assert not result.blocked


def test_task_without_batches_is_info_only():
    project = Project(name="空任务工程")
    project.tasks = [Task(name="空", batches=[])]
    project.active_task_id = project.tasks[0].id
    result = validate.validate_project(project)
    assert "task.empty" in codes(result)
    assert not result.blocked


def test_empty_batch_blocks_missing_source_and_target():
    project = Project(name="空批次工程")
    project.tasks = [Task(name="空批次")]
    project.active_task_id = project.tasks[0].id
    result = validate.validate_project(project)
    result_codes = codes(result)
    assert "label.missing_source" in result_codes
    assert "label.missing_target" in result_codes
    assert result.blocked


def test_task_id_mapping_uses_generated_line_ranges():
    first = Task(name="一")
    first.batches[0].take = Take(source="来源")
    first.batches[0].sends = [Send(target="目标")]
    second = Task(name="二")
    second.batches[0].take = Take(source="来源", quantity=-1)
    second.batches[0].sends = [Send(target="目标")]
    project = Project(name="多任务")
    project.labels = [Label(name="来源"), Label(name="目标")]
    project.tasks = [first, second]
    project.active_task_id = first.id
    result = validate.validate_project(project)
    negative = [i for i in result.issues if i.code == "limit.negative"]
    assert negative and negative[0].task_id == second.id


def test_invalid_filter_blocks():
    project = _valid_project()
    project.tasks[0].batches[0].take.with_filter = "a b"
    result = validate.validate_project(project)
    assert "filter.invalid" in codes(result)
    assert result.blocked
    assert result.syntax_errors == []  # invalid filter is omitted from code


def test_invalid_condition_blocks():
    project = _valid_project()
    project.tasks[0].batches[0].condition = "redstone >"
    result = validate.validate_project(project)
    assert "condition.invalid" in codes(result)
    assert result.blocked
    assert result.syntax_errors == []


def test_invalid_resource_id_blocks():
    project = _valid_project()
    project.tasks[0].batches[0].take.resource_id = 'bad"id'
    result = validate.validate_project(project)
    assert "resource.invalid" in codes(result)
    assert result.blocked
    assert result.syntax_errors == []


def test_quoted_regex_resource_is_info_only():
    project = _valid_project()
    project.tasks[0].batches[0].take.resource_id = '".*_ingot"'
    result = validate.validate_project(project)
    assert "resource.regex" in codes(result)
    assert "resource.invalid" not in codes(result)
    assert not result.blocked


def test_result_properties_count_levels():
    result = validate.ValidationResult(
        issues=[
            validate.ValidationIssue("block", "x", "一"),
            validate.ValidationIssue("possible", "y", "二"),
            validate.ValidationIssue("reminder", "z", "三"),
            validate.ValidationIssue("info", "w", "四"),
        ]
    )
    assert result.blocked
    assert result.blocks == 1
    assert result.warnings == 3


def test_syntax_errors_alone_mark_blocked():
    result = validate.ValidationResult(syntax_errors=["1:0 boom"])
    assert result.blocked
    assert result.blocks == 1
    assert result.warnings == 0


def test_seconds_below_minimum_is_fine():
    code = 'every 1 seconds do\n    input from "a"\n    forget\nend\n'
    result = validate.validate_code(code)
    assert "timer.fast" not in codes(result)


def test_long_but_valid_code_is_not_blocked():
    blocks = []
    for _ in range(100):
        blocks.append(
            "every 20 ticks do\n"
            '    input 1 from "a"\n'
            '    output to "b"\n'
            "    forget\n"
            "end\n"
        )
    code = "\n".join(blocks)
    result = validate.validate_code(code)
    assert len(code) < validate.PROGRAM_CHAR_LIMIT
    assert not result.blocked
