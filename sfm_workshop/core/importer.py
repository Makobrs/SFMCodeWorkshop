"""Best-effort import of the SFML subset produced by this workshop.

The official ANTLR parser still owns syntax acceptance (L0).  This module is a
small semantic reader for the structured ``every … input … output … forget``
programs the app exports.  Unknown/complex clauses are preserved as warnings
instead of being silently invented.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Iterable

from .model import Batch, Label, Project, Send, Take, Task
from .validate import validate_code


@dataclass
class ImportResult:
    project: Project
    warnings: list[str] = field(default_factory=list)


_SIDE_FROM_SFML = {
    "top": "上面",
    "bottom": "下面",
    "front": "前面",
    "back": "后面",
    "left": "左面",
    "right": "右面",
    "north": "北面",
    "south": "南面",
    "east": "东面",
    "west": "西面",
}

_TOKEN_RE = re.compile(r'"((?:\\.|[^"])*)"|(\S+)')


def _tokens(line: str) -> list[tuple[str, bool]]:
    """Return (value, was_quoted) tokens; comments are stripped."""
    text = line.strip()
    if "--" in text:
        # best effort: don't strip a -- inside a quoted label
        quote = False
        cut = len(text)
        for i, ch in enumerate(text[:-1]):
            if ch == '"' and (i == 0 or text[i - 1] != "\\"):
                quote = not quote
            if not quote and text[i:i + 2] == "--":
                cut = i
                break
        text = text[:cut].rstrip()
    out = []
    for m in _TOKEN_RE.finditer(text):
        if m.group(1) is not None:
            raw = m.group(1).replace('\\"', '"').replace("\\\\", "\\")
            out.append((raw, True))
        elif m.group(2):
            out.append((m.group(2), False))
    return out


def _label(tokens: list[tuple[str, bool]], start: int) -> tuple[str, int]:
    if start >= len(tokens):
        return "", start
    return tokens[start][0], start + 1


def _side(tokens: list[tuple[str, bool]]) -> str:
    for i, (value, _quoted) in enumerate(tokens):
        low = value.lower()
        if low == "each" and i + 1 < len(tokens) and tokens[i + 1][0].lower() == "side":
            return "每个面"
        if low in _SIDE_FROM_SFML:
            return _SIDE_FROM_SFML[low]
    return "默认面"


def _limits(tokens: list[tuple[str, bool]]) -> tuple[int, int, str, str]:
    """Return quantity, retain, resource_id, unsupported clause text."""
    quantity = 0
    retain = 0
    resource_id = ""
    unsupported = ""
    i = 0
    while i < len(tokens):
        v = tokens[i][0]
        low = v.lower()
        if low == "retain":
            if i + 1 < len(tokens) and tokens[i + 1][0].isdigit():
                retain = int(tokens[i + 1][0])
                i += 2
                continue
        elif v.isdigit():
            if quantity == 0:
                quantity = int(v)
        elif low in ("with", "without", "except"):
            unsupported = " ".join(x[0] for x in tokens[i:])
            break
        elif ":" in v or v.startswith("#"):
            resource_id = v
        i += 1
    return quantity, retain, resource_id, unsupported


def _parse_input(tokens: list[tuple[str, bool]]) -> tuple[Take, list[str]]:
    warnings: list[str] = []
    qty, retain, rid, unsupported = _limits(tokens[1:])
    # label starts after FROM; support both input ... from label and
    # from label input ... (the latter is not emitted by this app).
    from_idx = next((i for i, (v, _q) in enumerate(tokens) if v.lower() == "from"), -1)
    if from_idx < 0:
        warnings.append("INPUT 没有 FROM，已跳过标签。")
        return Take(quantity=qty, retain=retain, resource_id=rid), warnings
    label, end = _label(tokens, from_idx + 1)
    side = _side(tokens[end:])
    if unsupported:
        warnings.append(f"INPUT 过滤条件暂未解析：{unsupported}")
    return (
        Take(
            source=label,
            side=side,
            resource_type="物品",
            resource_id=rid,
            quantity=qty,
            retain=retain,
        ),
        warnings,
    )


def _parse_output(tokens: list[tuple[str, bool]]) -> tuple[Send, list[str]]:
    warnings: list[str] = []
    retain = 0
    for i, (v, _q) in enumerate(tokens[:-1]):
        if v.lower() == "retain" and tokens[i + 1][0].isdigit():
            retain = int(tokens[i + 1][0])
            break
    to_idx = next((i for i, (v, _q) in enumerate(tokens) if v.lower() == "to"), -1)
    if to_idx < 0:
        warnings.append("OUTPUT 没有 TO，已跳过目标。")
        return Send(retain=retain), warnings
    target, end = _label(tokens, to_idx + 1)
    side = _side(tokens[end:])
    return Send(target=target, side=side, retain=retain), warnings


def import_sfml(text: str, profile_id: str = "1.21.1-neoforge", name_hint: str = "") -> ImportResult:
    errors = validate_code(text, profile_id).syntax_errors
    if errors:
        raise ValueError("SFML 语法错误，未导入：\n" + "\n".join(errors[:4]))
    project_name = name_hint.strip() or "导入工程"
    tasks: list[Task] = []
    warnings: list[str] = []
    current_task: Task | None = None
    current_batch: Batch | None = None
    pending_condition = ""
    if_depth = 0

    for raw_line in text.splitlines():
        tokens = _tokens(raw_line)
        if not tokens:
            continue
        values = [t[0] for t in tokens]
        low = values[0].lower()
        if low == "name" and len(tokens) >= 2:
            project_name = tokens[1][0]
            continue
        if low == "every" and len(tokens) >= 2:
            # every 20 ticks do / every redstone pulse do
            kind = "timer"
            interval = 20
            unit = "TICKS"
            joined = " ".join(v.lower() for v in values)
            if "redstone" in joined and "pulse" in joined:
                kind = "pulse"
            else:
                for i, v in enumerate(values):
                    if v.isdigit():
                        interval = max(1, int(v))
                        if i + 1 < len(values) and values[i + 1].lower() in ("seconds", "second"):
                            unit = "SECONDS"
                        break
            current_task = Task(
                name=f"导入任务 {len(tasks) + 1}",
                trigger_kind=kind,
                interval=interval,
                unit=unit,
                batches=[],
            )
            tasks.append(current_task)
            current_batch = None
            pending_condition = ""
            if_depth = 0
            continue
        if low == "if" and current_task is not None:
            then = next((i for i, v in enumerate(values) if v.lower() == "then"), -1)
            if then >= 0:
                pending_condition = " ".join(values[1:then])
                if_depth += 1
            continue
        if low == "input" and current_task is not None:
            take, warns = _parse_input(tokens)
            warnings.extend(warns)
            current_batch = Batch(take=take, sends=[], clear=False, condition=pending_condition)
            pending_condition = ""
            current_task.batches.append(current_batch)
            continue
        if low == "output" and current_task is not None:
            if current_batch is None:
                current_batch = Batch(take=Take(), sends=[], clear=False, condition=pending_condition)
                pending_condition = ""
                current_task.batches.append(current_batch)
                warnings.append("OUTPUT 出现在 INPUT 之前；已补一个空取批次。")
            send, warns = _parse_output(tokens)
            warnings.extend(warns)
            current_batch.sends.append(send)
            continue
        if low == "forget" and current_batch is not None:
            current_batch.clear = True
            continue
        if low == "end":
            if if_depth > 0:
                if_depth -= 1
            else:
                current_task = None
                current_batch = None
            continue

    if not tasks:
        raise ValueError("没有识别到 every ... do ... end 触发器。")
    # Drop triggers without any batch; normalize empty batch sends.
    tasks = [t for t in tasks if t.batches]
    if not tasks:
        raise ValueError("没有识别到 INPUT/OUTPUT 批次。")
    labels: list[Label] = []
    seen: set[str] = set()
    for task in tasks:
        for batch in task.batches:
            for name in [batch.take.source, *(s.target for s in batch.sends)]:
                if name and name not in seen:
                    seen.add(name)
                    labels.append(Label(name=name, kind="容器"))
    project = Project(name=project_name, profile_id=profile_id, labels=labels, tasks=tasks)
    project.active_task_id = tasks[0].id
    return ImportResult(project=project, warnings=warnings)
