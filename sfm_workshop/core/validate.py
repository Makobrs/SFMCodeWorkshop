"""Conservative SFML lint: L0 grammar plus a small, offline L1 semantic pass.

The result is deliberately *not* a promise about runtime behaviour: label
bindings, block capabilities, server configuration and other mods can still
reject a program that parses and lints cleanly.  L1 only reports what can be
seen in the code and in the project model, using three severities:

* ``block``    -- the program is malformed or certain runtime limits are
  violated; copying should be disabled;
* ``possible`` -- likely a problem (e.g. a timer below the server minimum for
  non-energy work), but a server or pack may accept it;
* ``reminder`` / ``info`` -- useful context, never blocking.

Labels are always written quoted by :mod:`core.codegen`; the code-level lint
therefore only inspects quoted labels after ``from``/``to``.  Project-level
checks compare model label references with the declared labels.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from sfm_workshop.grammar import parse_sfml

from . import codegen
from .model import (
    DEFAULT_PROFILE,
    PROFILES,
    RESOURCE_TYPES,
    SIDES,
    TRIGGER_UNITS,
    Project,
    Task,
)

#: Hard limits from the PRD / SFM 4.34.0 (heuristic source constants).
PROGRAM_CHAR_LIMIT = codegen.PROGRAM_CHAR_LIMIT
LABEL_MAX_LEN = 256
TIMER_MIN_TICKS = 20
MAX_IF_PER_TRIGGER = 10
RESOURCE_MAX_SEGMENTS = 4

#: Codes whose project-level (model-aware) version supersedes the code scan.
_MODEL_OWNED_CODES = {"timer.fast", "label.too_long", "resource.segments"}

_COMMENT_RE = re.compile(r"--.*$")
_QUOTED_RE = re.compile(r'"(?:\\"|[^"])*"')
_LABEL_QUOTED_RE = re.compile(r'"((?:\\"|[^"])*)"')
_TIMER_HEADER_RE = re.compile(
    r"^every\s+(?:(\d+)\s*)?(?:global\s+|g\s+)?(seconds|second|ticks|tick)\b.*?\bdo$",
    re.IGNORECASE,
)
_PULSE_HEADER_RE = re.compile(r"^every\s+redstone\s+pulse\s+do$", re.IGNORECASE)
_ENERGY_TOKEN_RE = re.compile(
    r"\b(?:fe|forge_energy|energy|rf|power|mekanism_energy)::?", re.IGNORECASE
)
_NON_ENERGY_TYPE_RE = re.compile(
    r"\b(?:item|fluid|chemical|gas|infusion|slurry|pigment|redstone):", re.IGNORECASE
)
_OVERLONG_RESOURCE_RE = re.compile(
    r"(?<![A-Za-z0-9_*])([A-Za-z_*][A-Za-z0-9_*]*(?::[A-Za-z0-9_*.\-]*){4,})"
)
_INPUT_LIMIT_RE = re.compile(r"^input\s+(?:\d+\b|retain\b)", re.IGNORECASE)
_FROM_FIRST_RE = re.compile(r"^from\b", re.IGNORECASE)
_EACH_SIDE_RE = re.compile(r"\beach\s+side\b", re.IGNORECASE)
_SIDE_WORD_RE = re.compile(r"\bside\b", re.IGNORECASE)
_WITH_WORD_RE = re.compile(r"\b(?:with|without)\b", re.IGNORECASE)


@dataclass
class ValidationIssue:
    level: str  # block | possible | reminder | info
    code: str
    message: str
    line: int | None = None
    task_id: str | None = None


@dataclass
class ValidationResult:
    issues: list[ValidationIssue] = field(default_factory=list)
    syntax_errors: list[str] = field(default_factory=list)

    @property
    def blocked(self) -> bool:
        return bool(self.syntax_errors) or any(
            issue.level == "block" for issue in self.issues
        )

    @property
    def blocks(self) -> int:
        """Blocking diagnostics, including L0 syntax errors."""
        return len(self.syntax_errors) + sum(
            1 for issue in self.issues if issue.level == "block"
        )

    @property
    def warnings(self) -> int:
        """All non-blocking issues (possible + reminder + info)."""
        return sum(1 for issue in self.issues if issue.level != "block")


def _issue(
    level: str,
    code: str,
    message: str,
    line: int | None = None,
    task_id: str | None = None,
) -> ValidationIssue:
    return ValidationIssue(
        level=level, code=code, message=message, line=line, task_id=task_id
    )


def _strip_comment(text: str) -> str:
    return _COMMENT_RE.sub("", text)


def _strip_quoted(text: str) -> str:
    return _QUOTED_RE.sub(" ", text)


def _labels_in_line(text: str) -> list[str]:
    """Return quoted labels appearing after ``from``/``to`` on one line."""
    match = re.search(r"\b(?:from|to)\b", text, re.IGNORECASE)
    if not match:
        return []
    suffix = text[match.end() :]
    return [raw.replace('\\"', '"') for raw in _LABEL_QUOTED_RE.findall(suffix)]


def _trigger_segments(code: str) -> list[dict[str, object]]:
    """Split code into trigger segments (header + body lines) for linting.

    This is intentionally lexical: it does not build an AST, so ``end`` lines
    are not paired.  A segment ends when the next ``every`` header starts.
    """
    segments: list[dict[str, object]] = []
    current: dict[str, object] | None = None
    for number, raw in enumerate(code.splitlines(), start=1):
        text = _strip_comment(raw).strip()
        if not text:
            continue
        timer = _TIMER_HEADER_RE.match(text)
        pulse = _PULSE_HEADER_RE.match(text)
        if timer or pulse:
            if current is not None:
                segments.append(current)
            if pulse:
                current = {
                    "start": number,
                    "pulse": True,
                    "period_ticks": None,
                    "lines": [],
                }
            else:
                assert timer is not None
                period = int(timer.group(1)) if timer.group(1) else 1
                unit = (timer.group(2) or "ticks").lower()
                current = {
                    "start": number,
                    "pulse": False,
                    "period_ticks": period * (20 if unit.startswith("second") else 1),
                    "lines": [],
                }
            continue
        if current is not None:
            lines = current["lines"]
            assert isinstance(lines, list)
            lines.append((number, text))
    if current is not None:
        segments.append(current)
    return segments


def _segment_energy_only(lines: list[tuple[int, str]]) -> bool:
    """Heuristic: every input carries an energy type and outputs do not type.

    SFM outputs without an explicit resource transfer the buffered inputs, so
    an output with no typed token inherits the (energy) buffer.  This is a
    conservative approximation, used only for the timer-minimum reminder.
    """
    inputs = [text for _n, text in lines if text.lower().startswith("input")]
    if not inputs:
        return False
    for text in inputs:
        if not _ENERGY_TOKEN_RE.search(_strip_quoted(text)):
            return False
    for _n, text in lines:
        if not text.lower().startswith("output"):
            continue
        bare = _strip_quoted(text)
        if _ENERGY_TOKEN_RE.search(bare):
            continue
        if _NON_ENERGY_TYPE_RE.search(bare):
            return False
    return True


def _lint_segment(result: ValidationResult, segment: dict[str, object]) -> None:
    start = int(segment["start"])
    lines = segment["lines"]
    assert isinstance(lines, list)
    io_lines: list[tuple[int, str]] = [
        (number, text)
        for number, text in lines
        if text.lower().startswith(("input", "output"))
    ]
    io_seq: list[str] = []
    if_count = 0
    each_side_count = 0
    unspecified_side = 0
    no_quantity_line: int | None = None
    for number, text in lines:
        lowered = text.lower()
        if lowered.startswith("input"):
            io_seq.append("input")
            if (
                no_quantity_line is None
                and not _INPUT_LIMIT_RE.match(text)
                and not _FROM_FIRST_RE.match(text)
            ):
                no_quantity_line = number
        elif lowered.startswith("output"):
            io_seq.append("output")
        elif lowered.startswith("forget"):
            io_seq.append("forget")
        if re.match(r"^if\b", text, re.IGNORECASE):
            if_count += 1

    for number, text in io_lines:
        if _EACH_SIDE_RE.search(text):
            each_side_count += 1
        if not _SIDE_WORD_RE.search(_strip_quoted(text)):
            unspecified_side += 1

    if segment["pulse"]:
        result.issues.append(
            _issue(
                "reminder",
                "trigger.pulse",
                "红石脉冲触发由玩家/世界事件决定频率，静态校验无法推算；"
                "请在实际使用节奏下观察。",
                start,
            )
        )
    else:
        raw_period = segment["period_ticks"]
        period_ticks = 1 if raw_period is None else int(raw_period)
        if period_ticks < 1:
            result.issues.append(
                _issue(
                    "block",
                    "timer.zero",
                    "定时周期必须为正数；every 0 ticks 无法运行。",
                    start,
                )
            )
        elif period_ticks < TIMER_MIN_TICKS and not _segment_energy_only(lines):
            result.issues.append(
                _issue(
                    "possible",
                    "timer.fast",
                    f"周期 {period_ticks} tick 低于默认最小间隔 {TIMER_MIN_TICKS} tick；"
                    "仅纯能量 I/O 可 1 tick，其余会被服务器配置拦截。",
                    start,
                )
            )

    if if_count > MAX_IF_PER_TRIGGER:
        result.issues.append(
            _issue(
                "reminder",
                "if.too_many",
                f"单个触发器有 {if_count} 个 IF，超过默认 {MAX_IF_PER_TRIGGER} 个后"
                "编译器会跳过分支模拟检查（仍可运行）。",
                start,
            )
        )

    if each_side_count:
        result.issues.append(
            _issue(
                "reminder",
                "side.each",
                f"{each_side_count} 条 I/O 使用每个面：会尝试 6 个方向，"
                "能用具体面时优先具体面。",
                start,
            )
        )

    if unspecified_side:
        result.issues.append(
            _issue(
                "info",
                "side.unspecified",
                f"{unspecified_side} 条 I/O 未指定面，使用默认面（空方向能力）；"
                "部分机器/储罐需要具体面才能访问。",
                start,
            )
        )

    if no_quantity_line is not None:
        result.issues.append(
            _issue(
                "possible",
                "input.no_quantity",
                "取货未限制数量：单次可能搬运当前缓冲中的全部资源，确认这是预期。",
                no_quantity_line,
            )
        )

    if "output" in io_seq and "input" not in io_seq:
        result.issues.append(
            _issue(
                "possible",
                "flow.output_without_input",
                "触发器内只有送、没有取；没有登记输入时送不出资源（请确认这是预期的空操作）。",
                start,
            )
        )

    if io_seq and io_seq[-1] != "forget" and "input" in io_seq:
        result.issues.append(
            _issue(
                "possible",
                "batch.no_clear",
                "触发器末尾没有 FORGET：输入缓存可能残留到下一次执行，建议显式清空。",
                start,
            )
        )

    for number, text in io_lines:
        for label in _labels_in_line(text):
            if not label.strip():
                result.issues.append(
                    _issue("block", "label.empty", "标签名为空，无法绑定。", number)
                )
            elif len(label) > LABEL_MAX_LEN:
                result.issues.append(
                    _issue(
                        "block",
                        "label.too_long",
                        f"标签名长度 {len(label)} 超过 SFML 4.22+ 上限 {LABEL_MAX_LEN}。",
                        number,
                    )
                )


def validate_code(code: str, profile_id: str = DEFAULT_PROFILE) -> ValidationResult:
    """Validate generated or pasted SFML text.

    L0 runs the bundled official 4.34 ANTLR parser.  L1 scans the text for
    limits that do not need a running game.  ``profile_id`` is accepted for
    API symmetry; both supported profiles ship SFM 4.34 with the same
    documented timer defaults.
    """
    _ = PROFILES.get(profile_id)  # reserved for future per-profile limits
    text = code or ""
    result = ValidationResult()

    syntax_errors = parse_sfml(text)
    result.syntax_errors.extend(syntax_errors)

    if len(text) > PROGRAM_CHAR_LIMIT:
        result.issues.append(
            _issue(
                "block",
                "program.too_long",
                f"程序长度 {len(text)} 字符，超过 4.34.0 上限 {PROGRAM_CHAR_LIMIT} 字符。",
            )
        )

    for number, raw in enumerate(text.splitlines(), start=1):
        bare = _strip_quoted(_strip_comment(raw))
        for match in _OVERLONG_RESOURCE_RE.finditer(bare):
            token = match.group(1)
            result.issues.append(
                _issue(
                    "block",
                    "resource.segments",
                    f"资源 ID「{token}」超过 {RESOURCE_MAX_SEGMENTS} 段；"
                    "完整形式最多 sfm:类型:命名空间:名称。",
                    number,
                )
            )

    has_tag_filter = False
    for segment in _trigger_segments(text):
        _lint_segment(result, segment)
        lines = segment["lines"]
        assert isinstance(lines, list)
        for _number, line in lines:
            if _WITH_WORD_RE.search(_strip_quoted(_strip_comment(line))):
                has_tag_filter = True
                break

    if has_tag_filter:
        result.issues.append(
            _issue(
                "info",
                "tag.unverified",
                "with/without 的标签是否存在、是否有对应资源，离线无法核验；"
                "复制前请按整合包确认。",
            )
        )

    return result


def _positive_task_energy_only(task: Task) -> bool:
    takes = [
        batch.take
        for batch in task.batches
        if (batch.take.source or "").strip()
    ]
    if not takes:
        return False
    return all(
        (take.resource_type or "物品").strip() == "能量" for take in takes
    )


def _task_ranges(project: Project) -> list[tuple[str, int, int]]:
    """Return (task_id, first_line, last_line) for generated task blocks."""
    blocks = codegen.task_blocks(project)
    offset = 2 if (project.name or "").strip() else 1
    ranges: list[tuple[str, int, int]] = []
    for task, block in blocks:
        line_count = block.count("\n")
        ranges.append((task.id, offset, offset + line_count - 1))
        offset += line_count + 1  # blank line between trigger blocks
    return ranges


def _attach_task_ids(result: ValidationResult, project: Project) -> None:
    ranges = _task_ranges(project)
    if not ranges:
        return
    for issue in result.issues:
        if issue.task_id is not None or issue.line is None:
            continue
        for task_id, first, last in ranges:
            if first <= issue.line <= last:
                issue.task_id = task_id
                break


def _dedupe(issues: list[ValidationIssue]) -> list[ValidationIssue]:
    seen: set[tuple[object, ...]] = set()
    unique: list[ValidationIssue] = []
    for issue in issues:
        key = (
            issue.level,
            issue.code,
            issue.message,
            issue.line,
            issue.task_id,
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(issue)
    return unique


def _validate_labels(project: Project, issues: list[ValidationIssue]) -> set[str]:
    known: set[str] = set()
    for label in project.labels:
        name = str(label.name)
        if not name.strip():
            issues.append(
                _issue("block", "label.empty_name", "存在空标签名；请先命名。")
            )
            continue
        if name in known:
            issues.append(
                _issue(
                    "possible",
                    "label.duplicate",
                    f"标签名「{name}」重复；游戏内同名标签会指向同一组方块。",
                )
            )
        known.add(name)
        if len(name) > LABEL_MAX_LEN:
            issues.append(
                _issue(
                    "block",
                    "label.too_long",
                    f"标签名「{name[:20]}…」长度 {len(name)} 超过上限 {LABEL_MAX_LEN}。",
                )
            )
        if name.endswith("\\") or any(ch in name for ch in "\r\n\t"):
            issues.append(
                _issue(
                    "block",
                    "label.unrepresentable",
                    f"标签名「{name}」以反斜杠结尾或含换行/制表符，"
                    "无法在 SFML 字符串中无损表示。",
                )
            )
        elif "\\" in name or '"' in name:
            issues.append(
                _issue(
                    "info",
                    "label.special_chars",
                    f"标签名「{name}」含反斜杠/引号，生成时会转义，"
                    "请在游戏内核对绑定结果。",
                )
            )
    return known


def _validate_task(
    task: Task,
    known_labels: set[str],
    profile_id: str,
    issues: list[ValidationIssue],
) -> None:
    trigger_kind = (task.trigger_kind or "timer").strip().lower()
    if trigger_kind not in ("timer", "pulse"):
        issues.append(
            _issue(
                "block",
                "trigger.unknown",
                f"任务「{task.name}」的触发类型「{task.trigger_kind}」未知；"
                "仅支持 timer / pulse。",
                task_id=task.id,
            )
        )

    if trigger_kind == "timer":
        unit = (task.unit or "TICKS").strip().upper()
        if unit not in TRIGGER_UNITS:
            issues.append(
                _issue(
                    "block",
                    "trigger.unit",
                    f"任务「{task.name}」的时间单位「{task.unit}」未知；"
                    "仅支持 TICKS / SECONDS。",
                    task_id=task.id,
                )
            )
        try:
            interval = int(task.interval)
        except (TypeError, ValueError):
            interval = 0
        if interval < 1:
            issues.append(
                _issue(
                    "block",
                    "interval.invalid",
                    f"任务「{task.name}」的周期必须为正整数。",
                    task_id=task.id,
                )
            )
        elif not _positive_task_energy_only(task) and interval < TIMER_MIN_TICKS:
            ticks = interval * 20 if unit == "SECONDS" else interval
            if ticks < TIMER_MIN_TICKS:
                issues.append(
                    _issue(
                        "possible",
                        "timer.fast",
                        f"任务「{task.name}」周期 {ticks} tick 低于默认最小间隔 "
                        f"{TIMER_MIN_TICKS} tick；仅纯能量 I/O 可 1 tick。",
                        task_id=task.id,
                    )
                )

    batches = list(task.batches or [])
    if not batches:
        issues.append(
            _issue(
                "info",
                "task.empty",
                f"任务「{task.name}」没有批次，不会生成代码。",
                task_id=task.id,
            )
        )
        return

    for batch in batches:
        take = batch.take
        source = (take.source or "").strip()
        if not source:
            issues.append(
                _issue(
                    "block",
                    "label.missing_source",
                    f"任务「{task.name}」的取缺少来源标签。",
                    task_id=task.id,
                )
            )
        elif source not in known_labels:
            issues.append(
                _issue(
                    "block",
                    "label.unknown",
                    f"任务「{task.name}」引用了未声明的来源标签「{source}」。",
                    task_id=task.id,
                )
            )
        if take.side and take.side not in SIDES:
            issues.append(
                _issue(
                    "block",
                    "side.unknown",
                    f"任务「{task.name}」的来源面「{take.side}」未知。",
                    task_id=task.id,
                )
            )
        resource_type = (take.resource_type or "物品").strip()
        if resource_type not in RESOURCE_TYPES:
            issues.append(
                _issue(
                    "block",
                    "resource_type.unknown",
                    f"任务「{task.name}」的资源类型「{take.resource_type}」未知；"
                    "可选：物品/流体/能量/化学品。",
                    task_id=task.id,
                )
            )
        for key, value in (
            ("数量", take.quantity),
            ("保留", take.retain),
        ):
            try:
                number = int(value)
            except (TypeError, ValueError):
                number = 0
            if number < 0:
                issues.append(
                    _issue(
                        "block",
                        "limit.negative",
                        f"任务「{task.name}」的取{key}为负数；SFML 只接受非负整数。",
                        task_id=task.id,
                    )
                )
        token = codegen.resource_token(take, profile_id)
        raw_id = (take.resource_id or "").strip()
        if token and not codegen.is_valid_resource_token(token):
            if token.count(":") + 1 > RESOURCE_MAX_SEGMENTS:
                issues.append(
                    _issue(
                        "block",
                        "resource.segments",
                        f"任务「{task.name}」的资源 ID「{token}」超过 "
                        f"{RESOURCE_MAX_SEGMENTS} 段。",
                        task_id=task.id,
                    )
                )
            else:
                issues.append(
                    _issue(
                        "block",
                        "resource.invalid",
                        f"任务「{task.name}」的资源 ID「{raw_id}」不是合法的 SFML "
                        "资源名（只允许字母/数字/_/*/./- 与最多 4 段，或整体加引号的正则）。",
                        task_id=task.id,
                    )
                )
        elif raw_id and codegen.is_quoted_resource_id(raw_id):
            issues.append(
                _issue(
                    "info",
                    "resource.regex",
                    f"任务「{task.name}」的资源 ID 按正则解释，"
                    "匹配范围需在游戏内确认。",
                    task_id=task.id,
                )
            )

        for filter_name, filter_value in (
            ("with", take.with_filter),
            ("without", take.without_filter),
        ):
            if (filter_value or "").strip() and not codegen.filter_is_valid(
                filter_value, filter_name
            ):
                issues.append(
                    _issue(
                        "block",
                        "filter.invalid",
                        f"任务「{task.name}」的 {filter_name} 过滤表达式无法解析；"
                        "请检查 #标签、括号与 and/or。",
                        task_id=task.id,
                    )
                )

        condition = (batch.condition or "").strip()
        if condition and not codegen.condition_is_valid(condition):
            issues.append(
                _issue(
                    "block",
                    "condition.invalid",
                    f"任务「{task.name}」的 IF 条件无法解析；"
                    "请检查比较符（> / >= / eq 等）与 and/or。",
                    task_id=task.id,
                )
            )

        sends = [send for send in (batch.sends or []) if (send.target or "").strip()]
        if not sends:
            issues.append(
                _issue(
                    "block",
                    "label.missing_target",
                    f"任务「{task.name}」的送缺少目标标签。",
                    task_id=task.id,
                )
            )
        for send in sends:
            target = (send.target or "").strip()
            if target not in known_labels:
                issues.append(
                    _issue(
                        "block",
                        "label.unknown",
                        f"任务「{task.name}」引用了未声明的目标标签「{target}」。",
                        task_id=task.id,
                    )
                )
            if send.side and send.side not in SIDES:
                issues.append(
                    _issue(
                        "block",
                        "side.unknown",
                        f"任务「{task.name}」的目标面「{send.side}」未知。",
                        task_id=task.id,
                    )
                )
            try:
                retain = int(send.retain)
            except (TypeError, ValueError):
                retain = 0
            if retain < 0:
                issues.append(
                    _issue(
                        "block",
                        "limit.negative",
                        f"任务「{task.name}」的送保留值为负数。",
                        task_id=task.id,
                    )
                )


def validate_project(project: Project) -> ValidationResult:
    """Validate a whole project (generated code + model-level checks)."""
    code = codegen.generate_project(project)
    profile_id = project.profile_id if project.profile_id in PROFILES else DEFAULT_PROFILE
    result = validate_code(code, profile_id)
    _attach_task_ids(result, project)
    result.issues = [
        issue for issue in result.issues if issue.code not in _MODEL_OWNED_CODES
    ]

    model_issues: list[ValidationIssue] = []
    known_labels = _validate_labels(project, model_issues)
    for task in project.tasks:
        if not task.enabled:
            model_issues.append(
                _issue(
                    "info",
                    "task.disabled",
                    f"任务「{task.name}」已禁用，不参与代码生成。",
                    task_id=task.id,
                )
            )
            continue
        _validate_task(task, known_labels, profile_id, model_issues)

    result.issues = _dedupe([*result.issues, *model_issues])
    return result


__all__ = [
    "LABEL_MAX_LEN",
    "MAX_IF_PER_TRIGGER",
    "PROGRAM_CHAR_LIMIT",
    "RESOURCE_MAX_SEGMENTS",
    "TIMER_MIN_TICKS",
    "ValidationIssue",
    "ValidationResult",
    "validate_code",
    "validate_project",
]
