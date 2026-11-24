"""Core data model for SFM Code Workshop.

The model is deliberately small and serialisable.  UI, code generation,
validation, templates and the TPS estimator all share these objects.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
import uuid
from typing import Any


SCHEMA_VERSION = 1

SIDES: list[str] = [
    "默认面",
    "每个面",
    "上面",
    "下面",
    "前面",
    "后面",
    "左面",
    "右面",
    "东面",
    "西面",
    "南面",
    "北面",
    # legacy/canonical Minecraft wording kept for existing projects/templates
    "顶面",
    "底面",
]

# SFM 4.34 accepts six world faces and four directions relative to the target
# block's facing property.  These are NOT player-view relative.
SIDE_TO_SFML = {
    "默认面": "",
    "每个面": "each side",
    "上面": "top side",
    "下面": "bottom side",
    "前面": "front side",
    "后面": "back side",
    "左面": "left side",
    "右面": "right side",
    "北面": "north side",
    "南面": "south side",
    "东面": "east side",
    "西面": "west side",
    "顶面": "top side",
    "底面": "bottom side",
}

SIDE_GROUPS: list[tuple[str, list[str], str]] = [
    ("上下", ["上面", "下面"], "世界垂直面；所有方块都适用。"),
    ("东西南北", ["东面", "西面", "南面", "北面"], "固定世界方向；与玩家朝向无关。"),
    (
        "前后左右",
        ["前面", "后面", "左面", "右面"],
        "相对目标方块自身的 facing；不是玩家视角。方块没有 facing 时等价于 null side。",
    ),
]

RESOURCE_TYPES: list[str] = ["物品", "流体", "能量", "化学品"]
LABEL_KINDS: list[str] = ["容器", "机器", "能量", "其他"]
TRIGGER_UNITS: list[str] = ["TICKS", "SECONDS"]


@dataclass
class Profile:
    id: str
    mc: str
    loader: str
    sfm: str
    label: str


PROFILES: dict[str, Profile] = {
    "1.21.1-neoforge": Profile(
        id="1.21.1-neoforge",
        mc="1.21.1",
        loader="NeoForge 21.1.x",
        sfm="4.34.0",
        label="MC 1.21.1 / NeoForge / SFM 4.34.0",
    ),
    "1.20.1-forge": Profile(
        id="1.20.1-forge",
        mc="1.20.1",
        loader="Forge 47.x",
        sfm="4.34.0",
        label="MC 1.20.1 / Forge / SFM 4.34.0",
    ),
}
DEFAULT_PROFILE = "1.21.1-neoforge"


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


@dataclass
class Label:
    id: str = field(default_factory=lambda: new_id("lbl"))
    name: str = ""
    kind: str = "容器"
    note: str = ""
    capacity: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Label":
        return cls(
            id=str(d.get("id") or new_id("lbl")),
            name=str(d.get("name") or ""),
            kind=str(d.get("kind") or "容器"),
            note=str(d.get("note") or ""),
            capacity=int(d.get("capacity") or 0),
        )


@dataclass
class Take:
    source: str = ""
    side: str = "默认面"
    resource_type: str = "物品"
    resource_id: str = ""
    quantity: int = 0          # 0 = all
    retain: int = 0            # 0 = do not emit RETAIN
    with_filter: str = ""
    without_filter: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> "Take":
        d = d or {}
        return cls(
            source=str(d.get("source") or ""),
            side=str(d.get("side") or "默认面"),
            resource_type=str(d.get("resource_type") or "物品"),
            resource_id=str(d.get("resource_id") or ""),
            quantity=int(d.get("quantity") or 0),
            retain=int(d.get("retain") or 0),
            with_filter=str(d.get("with_filter") or ""),
            without_filter=str(d.get("without_filter") or ""),
        )


@dataclass
class Send:
    target: str = ""
    side: str = "默认面"
    retain: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> "Send":
        d = d or {}
        return cls(
            target=str(d.get("target") or ""),
            side=str(d.get("side") or "默认面"),
            retain=int(d.get("retain") or 0),
        )


@dataclass
class Batch:
    take: Take = field(default_factory=Take)
    sends: list[Send] = field(default_factory=lambda: [Send()])
    clear: bool = True
    condition: str = ""       # optional IF expression (statement-level)

    def to_dict(self) -> dict[str, Any]:
        return {
            "take": self.take.to_dict(),
            "sends": [s.to_dict() for s in self.sends],
            "clear": bool(self.clear),
            "condition": self.condition,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> "Batch":
        d = d or {}
        sends_raw = d.get("sends")
        sends = [Send.from_dict(x) for x in sends_raw] if isinstance(sends_raw, list) else []
        if not sends:
            sends = [Send()]
        return cls(
            take=Take.from_dict(d.get("take")),
            sends=sends,
            clear=bool(d.get("clear", True)),
            condition=str(d.get("condition") or ""),
        )


@dataclass
class Task:
    id: str = field(default_factory=lambda: new_id("task"))
    name: str = "新任务"
    trigger_kind: str = "timer"       # timer | pulse
    interval: int = 20
    unit: str = "TICKS"
    batches: list[Batch] = field(default_factory=lambda: [Batch()])
    enabled: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "trigger_kind": self.trigger_kind,
            "interval": self.interval,
            "unit": self.unit,
            "batches": [b.to_dict() for b in self.batches],
            "enabled": bool(self.enabled),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Task":
        batches_raw = d.get("batches")
        batches = [Batch.from_dict(x) for x in batches_raw] if isinstance(batches_raw, list) else []
        if not batches:
            batches = [Batch()]
        return cls(
            id=str(d.get("id") or new_id("task")),
            name=str(d.get("name") or "新任务"),
            trigger_kind=str(d.get("trigger_kind") or "timer"),
            interval=int(d.get("interval") or 20),
            unit=str(d.get("unit") or "TICKS").upper(),
            batches=batches,
            enabled=bool(d.get("enabled", True)),
        )


@dataclass
class Project:
    id: str = field(default_factory=lambda: new_id("proj"))
    name: str = "未命名工程"
    profile_id: str = DEFAULT_PROFILE
    labels: list[Label] = field(default_factory=list)
    tasks: list[Task] = field(default_factory=list)
    active_task_id: str | None = None
    template_key: str = ""
    schema_version: int = SCHEMA_VERSION
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)
    ui: dict[str, Any] = field(default_factory=dict)

    # ---- profile helpers -------------------------------------------------
    @property
    def profile(self) -> Profile:
        return PROFILES.get(self.profile_id, PROFILES[DEFAULT_PROFILE])

    # ---- task helpers ----------------------------------------------------
    def task_by_id(self, task_id: str | None) -> Task | None:
        if not task_id:
            return None
        return next((t for t in self.tasks if t.id == task_id), None)

    def active_task(self) -> Task | None:
        t = self.task_by_id(self.active_task_id)
        if t is not None:
            return t
        return self.tasks[0] if self.tasks else None

    def ensure_active(self) -> Task | None:
        t = self.active_task()
        self.active_task_id = t.id if t else None
        return t

    def label_names(self) -> list[str]:
        return [l.name for l in self.labels if l.name.strip()]

    def add_label(self, name: str = "新标签", kind: str = "容器") -> Label:
        name = unique_name(name, {l.name for l in self.labels})
        label = Label(name=name, kind=kind)
        self.labels.append(label)
        return label

    def add_task(self) -> Task:
        names = {t.name for t in self.tasks}
        name = unique_name("新任务", names)
        task = Task(name=name)
        # sensible defaults from existing labels
        names_list = [l.name for l in self.labels]
        if names_list:
            task.batches[0].take.source = names_list[0]
            if len(names_list) > 1:
                task.batches[0].sends[0].target = names_list[1]
        self.tasks.append(task)
        self.active_task_id = task.id
        return task

    def remove_task(self, task_id: str) -> None:
        self.tasks = [t for t in self.tasks if t.id != task_id]
        if self.active_task_id == task_id:
            self.active_task_id = self.tasks[0].id if self.tasks else None

    # ---- serialisation ---------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": int(getattr(self, "schema_version", SCHEMA_VERSION)),
            "id": self.id,
            "name": self.name,
            "profile_id": self.profile_id,
            "labels": [l.to_dict() for l in self.labels],
            "tasks": [t.to_dict() for t in self.tasks],
            "active_task_id": self.active_task_id,
            "template_key": self.template_key,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "ui": self.ui,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Project":
        labels_raw = d.get("labels")
        labels = [Label.from_dict(x) for x in labels_raw] if isinstance(labels_raw, list) else []
        tasks_raw = d.get("tasks")
        tasks = [Task.from_dict(x) for x in tasks_raw] if isinstance(tasks_raw, list) else []
        p = cls(
            id=str(d.get("id") or new_id("proj")),
            name=str(d.get("name") or "未命名工程"),
            profile_id=str(d.get("profile_id") or DEFAULT_PROFILE),
            labels=labels,
            tasks=tasks,
            active_task_id=d.get("active_task_id"),
            template_key=str(d.get("template_key") or ""),
            schema_version=int(d.get("schema_version") or SCHEMA_VERSION),
            created_at=str(d.get("created_at") or now_iso()),
            updated_at=str(d.get("updated_at") or now_iso()),
            ui=d.get("ui") if isinstance(d.get("ui"), dict) else {},
        )
        if p.profile_id not in PROFILES:
            p.profile_id = DEFAULT_PROFILE
        p.ensure_active()
        return p


def unique_name(base: str, used: set[str]) -> str:
    base = (base or "新标签").strip() or "新标签"
    if base not in used:
        return base
    i = 2
    while f"{base} {i}" in used:
        i += 1
    return f"{base} {i}"


def new_blank_project(name: str = "未命名工程", profile_id: str = DEFAULT_PROFILE) -> Project:
    p = Project(name=name, profile_id=profile_id if profile_id in PROFILES else DEFAULT_PROFILE)
    for label_name, kind in (("原料箱", "容器"), ("熔炉", "机器"), ("成品箱", "容器")):
        p.labels.append(Label(name=label_name, kind=kind))
    return p


def new_default_project() -> Project:
    """Friendly first-run project: labels + one task, but no template code."""
    p = new_blank_project("熔炉自动线")
    task = Task(name="主线补给")
    task.batches[0].take.source = "原料箱"
    task.batches[0].take.side = "默认面"
    task.batches[0].sends[0].target = "熔炉"
    task.batches[0].sends[0].side = "顶面"
    p.tasks.append(task)
    p.active_task_id = task.id
    return p


def load_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def project_to_json(project: Project) -> str:
    return json.dumps(project.to_dict(), ensure_ascii=False, indent=2)


def project_from_json(text: str) -> Project:
    return Project.from_dict(json.loads(text))
