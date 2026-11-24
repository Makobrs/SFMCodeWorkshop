"""Static, offline TPS-impact *estimate* derived from the project model.

The model is the single source of truth for the generated SFML, so this module
never reads game files, logs, network or TPS counters.  It applies the
heuristic recommended by the SFM reference material::

    blocks x sides x slots x trigger frequency

with extra weight for conditions, tag/resource patterns and multi-target
batches.  The raw result is an approximate visits-per-minute cost; ``score``
maps it linearly onto a 0–100 relative index (100 = the high-impact threshold),
not a TPS number, and the ``low/medium/high`` thresholds are product
heuristics documented below.  The note and warnings always state that the
estimate is not a measurement.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .model import Project, Task

#: Relative-cost thresholds (heuristic, not TPS values).  A timer task at
#: 20 ticks with one source and one target has a raw cost of 480; a 1-tick
#: energy task has 9600.  The public ``score`` maps raw cost onto 0–100 so a
#: progress bar/percentage has a stable meaning: 100 == high-impact threshold.
LEVEL_LOW_MAX = 300.0
LEVEL_HIGH_MIN = 2000.0
SCORE_MAX = 100.0
#: Raw cost per score point (20 raw units = 1 score point at the high threshold).
COST_PER_SCORE = LEVEL_HIGH_MIN / SCORE_MAX

#: Extra work multipliers per feature (heuristic).
CONDITION_WEIGHT = 0.20
PATTERN_WEIGHT = 0.15

NOTE = (
    "启发式静态估算，不是实测。只依据工程结构/生成代码的语句特征，"
    "不采集游戏 TPS、日志、存档或网络数据；实际表现取决于服务器配置、"
    "方块能力、库存与整合包。"
)


@dataclass
class TpsFactor:
    name: str
    value: float
    detail: str


@dataclass
class TpsEstimate:
    score: float = 0.0
    level: str = "未知"  # 低/中/高/未知
    factors: list[TpsFactor] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    note: str = NOTE


@dataclass
class _TaskMetrics:
    task: Task
    blocks: int
    side_visits: int
    slots: int
    frequency: float
    condition_count: int
    filter_count: int
    pattern_count: int
    send_count: int
    pulse: bool
    duration_note: str
    cost: float


def _batch_effective(batch) -> bool:  # type: ignore[no-untyped-def]
    if (batch.take.source or "").strip():
        return True
    return any((send.target or "").strip() for send in batch.sends)


def _task_energy_only(task: Task) -> bool:
    takes = [
        batch.take
        for batch in task.batches
        if (batch.take.source or "").strip()
    ]
    if not takes:
        return False
    return all((take.resource_type or "物品").strip() == "能量" for take in takes)


def _is_pattern(take) -> bool:  # type: ignore[no-untyped-def]
    raw = (take.resource_id or "").strip()
    return "*" in raw or (raw.startswith('"') and raw.endswith('"'))


def _uses_each_side(task: Task) -> bool:
    for batch in task.batches or []:
        if (batch.take.side or "").strip() == "每个面":
            return True
        if any((send.side or "").strip() == "每个面" for send in batch.sends):
            return True
    return False


def _quantity_is_unlimited(batch) -> bool:  # type: ignore[no-untyped-def]
    try:
        return int(batch.take.quantity or 0) <= 0
    except (TypeError, ValueError):
        return True


def _task_metrics(task: Task) -> _TaskMetrics | None:
    labels: set[str] = set()
    side_visits = 0
    send_count = 0
    filter_count = 0
    condition_count = 0
    pattern_count = 0
    duration_note = ""

    for batch in task.batches or []:
        if not _batch_effective(batch):
            continue
        take = batch.take
        source = (take.source or "").strip()
        if source:
            labels.add(source)
            side_visits += 6 if (take.side or "").strip() == "每个面" else 1
        if (take.with_filter or "").strip() or (take.without_filter or "").strip():
            filter_count += 1
        if (batch.condition or "").strip():
            condition_count += 1
        if _is_pattern(take):
            pattern_count += 1
        for send in batch.sends:
            target = (send.target or "").strip()
            if not target:
                continue
            labels.add(target)
            send_count += 1
            side_visits += 6 if (send.side or "").strip() == "每个面" else 1

    if not labels:
        return None

    blocks = len(labels)
    slots = 1 + send_count + (1 if filter_count else 0)

    pulse = (task.trigger_kind or "timer").strip().lower() == "pulse"
    if pulse:
        frequency = 1.0
        duration_note = "红石脉冲，频率未知；按每次脉冲一次执行计（系数 1）"
    else:
        unit = (task.unit or "TICKS").strip().upper()
        try:
            interval = int(task.interval)
        except (TypeError, ValueError):
            interval = 0
        ticks = interval * 20 if unit == "SECONDS" else interval
        ticks = max(1, ticks)
        frequency = 1200.0 / ticks  # executions per minute at nominal 20 TPS
        duration_note = (
            f"{ticks} tick ≈ {frequency:.1f} 次/分钟（名义 20 TPS）"
        )

    multiplier = (1.0 + CONDITION_WEIGHT * condition_count) * (
        1.0 + PATTERN_WEIGHT * pattern_count
    )
    cost = blocks * side_visits * slots * frequency * multiplier

    return _TaskMetrics(
        task=task,
        blocks=blocks,
        side_visits=side_visits,
        slots=slots,
        frequency=frequency,
        condition_count=condition_count,
        filter_count=filter_count,
        pattern_count=pattern_count,
        send_count=send_count,
        pulse=pulse,
        duration_note=duration_note,
        cost=cost,
    )


def _append_unique(items: list[str], text: str) -> None:
    if text not in items:
        items.append(text)


def _collect_task_notes(
    metrics: _TaskMetrics, warnings: list[str], suggestions: list[str]
) -> None:
    task_name = metrics.task.name or "未命名任务"

    if metrics.pulse:
        _append_unique(
            warnings,
            f"任务「{task_name}」使用红石脉冲：触发频率未知，估算按每次脉冲一次访问计。",
        )
        _append_unique(
            suggestions,
            f"任务「{task_name}」若需要稳定吞吐，可改为定时触发器；脉冲频率无法静态估算。",
        )
    else:
        unit = (metrics.task.unit or "TICKS").strip().upper()
        try:
            interval = int(metrics.task.interval)
        except (TypeError, ValueError):
            interval = 0
        ticks = interval * 20 if unit == "SECONDS" else interval
        if 0 < ticks < 20 and not _task_energy_only(metrics.task):
            _append_unique(
                warnings,
                f"任务「{task_name}」周期 {ticks} tick 属高频；非纯能量 I/O "
                "可能被服务器最小间隔拦截。",
            )
        if 0 < ticks < 40:
            _append_unique(
                suggestions,
                f"把任务「{task_name}」周期提高到 40–200 ticks（非紧急搬运）"
                "可近似线性降低访问频率。",
            )

    if _uses_each_side(metrics.task):
        _append_unique(
            warnings,
            f"任务「{task_name}」使用每个面：静态估算按 6 倍面访问计。",
        )
        _append_unique(
            suggestions,
            f"把任务「{task_name}」的每个面换成具体面（如顶面），"
            "面访问可从 6 次降到 1 次。",
        )

    if metrics.condition_count:
        _append_unique(
            warnings,
            f"任务「{task_name}」含 IF：每次执行会额外查询库存/红石状态。",
        )
        _append_unique(
            suggestions,
            f"任务「{task_name}」能用送出的先后顺序或保留值表达条件时，优先去掉 IF。",
        )

    if metrics.filter_count:
        _append_unique(
            warnings,
            f"任务「{task_name}」含 with/without 过滤：标签匹配会额外扫描。",
        )

    if metrics.pattern_count:
        _append_unique(
            warnings,
            f"任务「{task_name}」的资源模式含通配/正则：匹配面越大，单次扫描越重。",
        )
        _append_unique(
            suggestions,
            f"任务「{task_name}」尽量用明确的资源 ID 代替通配/正则。",
        )

    if metrics.send_count > 2:
        _append_unique(
            warnings,
            f"任务「{task_name}」有 {metrics.send_count} 个送：目标越多，"
            "每次执行的访问越多。",
        )
        _append_unique(
            suggestions,
            f"任务「{task_name}」减少同时送的目标，或拆成独立任务。",
        )

    has_sends = any(
        (send.target or "").strip()
        for batch in metrics.task.batches
        for send in batch.sends
    )
    unlimited = any(
        _batch_effective(batch)
        and (batch.take.source or "").strip()
        and _quantity_is_unlimited(batch)
        for batch in metrics.task.batches
    )
    if has_sends and unlimited:
        _append_unique(
            warnings,
            f"任务「{task_name}」未限制取货数量：单次可能搬运整批缓冲。",
        )
        _append_unique(
            suggestions,
            f"为任务「{task_name}」的取设置数量或保留值，缩小单次搬运量。",
        )


def estimate_tps(project: Project) -> TpsEstimate:
    """Estimate the relative cost of an enabled project (static only).

    Deterministic: tasks are visited in model order and suggestions/warnings
    keep a stable order.  A project with no enabled/effective task, or one
    made only of pulse triggers, reports ``未知`` because no usable frequency
    is known.
    """
    metrics: list[_TaskMetrics] = []
    for task in project.tasks:
        if not task.enabled:
            continue
        item = _task_metrics(task)
        if item is not None:
            metrics.append(item)

    if not metrics:
        return TpsEstimate(
            score=0.0,
            level="未知",
            factors=[
                TpsFactor(
                    name="任务",
                    value=0.0,
                    detail="没有启用的有效任务，无法估算。",
                )
            ],
            warnings=["没有可估算的启用任务。"],
            suggestions=[],
            note=NOTE,
        )

    total_cost = sum(item.cost for item in metrics)
    total_blocks = sum(item.blocks for item in metrics)
    total_sides = sum(item.side_visits for item in metrics)
    total_slots = sum(item.slots for item in metrics)
    total_frequency = sum(item.frequency for item in metrics)
    total_conditions = sum(item.condition_count for item in metrics)
    total_filters = sum(item.filter_count for item in metrics)
    total_patterns = sum(item.pattern_count for item in metrics)
    score = round(min(SCORE_MAX, total_cost / COST_PER_SCORE), 2)

    condition_multiplier = (1.0 + CONDITION_WEIGHT * total_conditions) * (
        1.0 + PATTERN_WEIGHT * total_patterns
    )

    warnings: list[str] = []
    suggestions: list[str] = []
    for item in metrics:
        _collect_task_notes(item, warnings, suggestions)

    all_pulse = all(item.pulse for item in metrics)
    if all_pulse:
        level = "未知"
    elif total_cost < LEVEL_LOW_MAX:
        level = "低"
    elif total_cost < LEVEL_HIGH_MIN:
        level = "中"
    else:
        level = "高"

    factors = [
        TpsFactor(
            name="触发频率",
            value=round(total_frequency, 2),
            detail="；".join(
                f"{item.task.name or '未命名任务'}：{item.duration_note}"
                for item in metrics
            ),
        ),
        TpsFactor(
            name="方块/标签访问",
            value=float(total_blocks),
            detail="；".join(
                f"{item.task.name or '未命名任务'} 引用 {item.blocks} 个标签"
                for item in metrics
            ),
        ),
        TpsFactor(
            name="面访问",
            value=float(total_sides),
            detail="具体面按 1 计，每个面按 6 计（启发式）。",
        ),
        TpsFactor(
            name="槽位/语句",
            value=float(total_slots),
            detail="1 + 送的数量 + 是否含 with/without（启发式）。",
        ),
        TpsFactor(
            name="条件/过滤放大",
            value=round(condition_multiplier, 2),
            detail=(
                f"{total_conditions} 个 IF、{total_filters} 个 with/without、"
                f"{total_patterns} 个通配/正则资源；"
                f"每 IF ×{1 + CONDITION_WEIGHT:.2f}、每模式 ×{1 + PATTERN_WEIGHT:.2f}。"
            ),
        ),
        TpsFactor(
            name="相对成本指数",
            value=score,
            detail=(
                "0–100 相对指数（100 = 高影响阈值；原始成本 "
                f"{total_cost:.1f}，每分钟访问量近似），不是 TPS。"
                f"等级阈值（启发式）：低 < {LEVEL_LOW_MAX:g}，"
                f"中 < {LEVEL_HIGH_MIN:g}，高 ≥ {LEVEL_HIGH_MIN:g}（原始成本）。"
            ),
        ),
    ]

    return TpsEstimate(
        score=score,
        level=level,
        factors=factors,
        warnings=warnings,
        suggestions=suggestions,
        note=NOTE,
    )


__all__ = [
    "CONDITION_WEIGHT",
    "COST_PER_SCORE",
    "LEVEL_HIGH_MIN",
    "LEVEL_LOW_MAX",
    "NOTE",
    "PATTERN_WEIGHT",
    "SCORE_MAX",
    "TpsEstimate",
    "TpsFactor",
    "estimate_tps",
]
