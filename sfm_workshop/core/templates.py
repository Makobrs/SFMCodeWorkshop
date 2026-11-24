"""Built-in templates and user-template storage.

Templates are ordinary ``Project.to_dict()`` JSON documents (``.sfmproj``):

* eight read-only presets ship under ``resources/templates/presets`` and are
  rebuilt from the definitions in this module when a file is missing (or is
  unreadable), so a fresh checkout or a repaired install always has them;
* the blank template and user templates live under the user data directory
  and stay writable;
* loading always returns a project with a fresh project id so opening the
  same template twice never produces two projects sharing one identity.

The preset files are intentionally deterministic (fixed ids/timestamps) so a
rebuild produces byte-identical JSON.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import storage
from .model import (
    DEFAULT_PROFILE,
    PROFILES,
    Batch,
    Label,
    Project,
    Send,
    Take,
    Task,
    new_blank_project,
    new_id,
    now_iso,
    project_from_json,
    project_to_json,
)

BLANK_KEY = "blank"
BLANK_FILENAME = "blank.sfmproj"

#: Stable timestamp for generated preset files (deterministic rebuilds).
_FIXED_TS = "2026-01-01T00:00:00+00:00"

_PRESET_FILES: dict[str, str] = {
    "furnace": "01-furnace.sfmproj",
    "fuel": "02-fuel.sfmproj",
    "tree-farm": "03-tree-farm.sfmproj",
    "bee-sorting": "04-bee-sorting.sfmproj",
    "ore-sorting": "05-ore-sorting.sfmproj",
    "fluid": "06-fluid.sfmproj",
    "energy": "07-energy.sfmproj",
    "redstone": "08-redstone.sfmproj",
}

_SPECS: tuple[tuple[str, str, str], ...] = (
    (
        "furnace",
        "熔炉自动线",
        "从原料箱向熔炉顶部投料，最多 8 个、保留 2 个；燃料和产物建议各建一条任务。",
    ),
    (
        "fuel",
        "燃料补给",
        "用保留值把熔炉底部的燃料补到 1 个，避免一次塞满燃料槽。",
    ),
    (
        "tree-farm",
        "树场收集",
        "每 20 tick 从树场输出收集至多 64 个原木到箱子，适合小型树场。",
    ),
    (
        "bee-sorting",
        "蜂箱分类",
        "按蜂产品标签收取蜜脾；标签需在整合包内确认后使用。",
    ),
    (
        "ore-sorting",
        "矿物分拣",
        "按矿石标签把混合箱里的矿石分拣到矿石箱，不匹配的物品留在源箱。",
    ),
    (
        "fluid",
        "流体转运",
        "从水箱顶面按 1000 mB 抽取水送到机器顶面；流体和能量都应使用具体面。",
    ),
    (
        "energy",
        "能量传输",
        "纯能量 I/O 可用 1 tick 周期，从能源仓顶面输送到用电器顶面。",
    ),
    (
        "redstone",
        "红石脉冲",
        "红石脉冲触发一次搬运 1 个物品；实际频率由按钮或杠杆控制。",
    ),
)

_NAME_BY_KEY = {key: name for key, name, _description in _SPECS}
_STEM_TO_KEY = {
    Path(filename).stem: key for key, filename in _PRESET_FILES.items()
}


@dataclass(frozen=True)
class TemplateInfo:
    key: str
    name: str
    description: str
    path: Path | None
    builtin: bool


# ---------------------------------------------------------------------------
# Model builders
# ---------------------------------------------------------------------------


def _take(**kwargs: object) -> Take:
    return Take(**kwargs)  # type: ignore[arg-type]


def _send(**kwargs: object) -> Send:
    return Send(**kwargs)  # type: ignore[arg-type]


def _template(
    key: str,
    labels: tuple[tuple[str, str, str], ...],
    task_name: str,
    take: Take,
    sends: list[Send],
    *,
    trigger_kind: str = "timer",
    interval: int = 20,
    unit: str = "TICKS",
    clear: bool = True,
) -> Project:
    project = Project(
        id=f"proj-template-{key}",
        name=_NAME_BY_KEY[key],
        profile_id=DEFAULT_PROFILE,
        template_key=key,
        created_at=_FIXED_TS,
        updated_at=_FIXED_TS,
    )
    project.labels = [
        Label(id=f"lbl-{key}-{index}", name=name, kind=kind, note=note)
        for index, (name, kind, note) in enumerate(labels, start=1)
    ]
    task = Task(
        id=f"task-{key}-1",
        name=task_name,
        trigger_kind=trigger_kind,
        interval=interval,
        unit=unit,
        batches=[Batch(take=take, sends=sends, clear=clear)],
        enabled=True,
    )
    project.tasks = [task]
    project.active_task_id = task.id
    return project


def _furnace() -> Project:
    return _template(
        "furnace",
        (
            ("原料箱", "容器", "待烧炼的矿石或原料"),
            ("煤炭箱", "容器", "燃料备用"),
            ("熔炉", "机器", "顶部投料、底部加燃料"),
            ("成品箱", "容器", "收集产物"),
        ),
        "矿石投料",
        _take(source="原料箱", quantity=8, retain=2),
        [_send(target="熔炉", side="顶面")],
    )


def _fuel() -> Project:
    return _template(
        "fuel",
        (
            ("燃料箱", "容器", "煤炭等燃料"),
            ("熔炉", "机器", "底部为燃料输入面"),
        ),
        "燃料补给",
        _take(source="燃料箱", quantity=1),
        [_send(target="熔炉", side="底面", retain=1)],
    )


def _tree_farm() -> Project:
    return _template(
        "tree-farm",
        (
            ("树场输出", "其他", "树场产物的集中点"),
            ("原木箱", "容器", "接收原木"),
            ("骨粉箱", "容器", "可选：树场催熟材料"),
        ),
        "收集原木",
        _take(source="树场输出", quantity=64),
        [_send(target="原木箱")],
    )


def _bee_sorting() -> Project:
    return _template(
        "bee-sorting",
        (
            ("蜂箱输出", "其他", "蜂箱或离心机产物"),
            ("蜜脾箱", "容器", "接收蜜脾"),
            ("蜂蜜瓶箱", "容器", "接收蜂蜜瓶"),
        ),
        "收集蜜脾",
        _take(source="蜂箱输出", quantity=16, with_filter="#c:combs"),
        [_send(target="蜜脾箱")],
    )


def _ore_sorting() -> Project:
    return _template(
        "ore-sorting",
        (
            ("混合箱", "容器", "未分类的混合产物"),
            ("矿石箱", "容器", "接收矿石"),
            ("废石箱", "容器", "接收非矿石"),
        ),
        "分拣矿石",
        _take(source="混合箱", quantity=32, with_filter="#c:ores"),
        [_send(target="矿石箱")],
    )


def _fluid() -> Project:
    return _template(
        "fluid",
        (
            ("水箱", "容器", "流体源，需使用具体面访问"),
            ("流体机器", "机器", "接收流体，需使用具体面访问"),
        ),
        "抽取水源",
        _take(
            source="水箱",
            side="顶面",
            resource_type="流体",
            resource_id="minecraft:water",
            quantity=1000,
        ),
        [_send(target="流体机器", side="顶面")],
    )


def _energy() -> Project:
    return _template(
        "energy",
        (
            ("能源仓", "能量", "FE 来源"),
            ("用电器", "机器", "FE 接收方"),
        ),
        "能量输送",
        _take(source="能源仓", side="顶面", resource_type="能量"),
        [_send(target="用电器", side="顶面")],
        interval=1,
    )


def _redstone() -> Project:
    return _template(
        "redstone",
        (
            ("入口箱", "容器", "脉冲触发时取货"),
            ("出口箱", "容器", "脉冲触发时送货"),
        ),
        "脉冲搬运",
        _take(source="入口箱", quantity=1),
        [_send(target="出口箱")],
        trigger_kind="pulse",
    )


def _blank_template() -> Project:
    project = Project(
        id="proj-template-blank",
        name="未命名工程",
        profile_id=DEFAULT_PROFILE,
        template_key=BLANK_KEY,
        created_at=_FIXED_TS,
        updated_at=_FIXED_TS,
    )
    project.labels = [
        Label(id="lbl-blank-1", name="原料箱", kind="容器"),
        Label(id="lbl-blank-2", name="熔炉", kind="机器"),
        Label(id="lbl-blank-3", name="成品箱", kind="容器"),
    ]
    return project


_BUILDERS: dict[str, Callable[[], Project]] = {
    "furnace": _furnace,
    "fuel": _fuel,
    "tree-farm": _tree_farm,
    "bee-sorting": _bee_sorting,
    "ore-sorting": _ore_sorting,
    "fluid": _fluid,
    "energy": _energy,
    "redstone": _redstone,
    BLANK_KEY: _blank_template,
}


# ---------------------------------------------------------------------------
# Filesystem helpers
# ---------------------------------------------------------------------------


def _payload(project: Project) -> str:
    return project_to_json(project) + "\n"


def _presets_dir() -> Path | None:
    try:
        return storage.presets_templates_dir()
    except OSError:
        return None


def _write_builtin(key: str, *, force: bool = False) -> Path | None:
    """Create a preset file from the code definition if needed."""
    directory = _presets_dir()
    if directory is None:
        return None
    path = directory / _PRESET_FILES[key]
    if path.exists() and not force:
        return path
    try:
        storage.atomic_write_text(path, _payload(_BUILDERS[key]()))
    except OSError:
        return path if path.exists() else None
    return path


def _ensure_blank_template(*, force: bool = False) -> Path:
    path = storage.user_templates_dir() / BLANK_FILENAME
    if path.exists() and not force:
        return path
    storage.atomic_write_text(path, _payload(_blank_template()))
    return path


def ensure_builtin_templates() -> list[Path]:
    """Materialise missing preset/blank files and return the paths that exist.

    Existing files are never overwritten, so user-visible read-only presets
    stay exactly as bundled/repaired.  Failures to write into a read-only
    program directory are tolerated: templates can still be loaded from the
    definitions in this module.
    """
    paths: list[Path] = []
    for key in _BUILDERS:
        if key == BLANK_KEY:
            continue
        path = _write_builtin(key)
        if path is not None:
            paths.append(path)
    try:
        paths.append(_ensure_blank_template())
    except OSError:
        pass
    return paths


def _read_project(path: Path) -> Project:
    return project_from_json(path.read_text(encoding="utf-8-sig"))


def _load_builtin_project(key: str) -> Project:
    if key == BLANK_KEY:
        try:
            return _read_project(_ensure_blank_template())
        except OSError:
            # Transient sharing/AV lock: never overwrite the user's blank
            # template just because a read failed.
            return _blank_template()
        except (ValueError, TypeError):
            try:
                return _read_project(_ensure_blank_template(force=True))
            except (OSError, ValueError, TypeError):
                return _blank_template()
    path = _write_builtin(key)
    if path is not None:
        try:
            return _read_project(path)
        except (OSError, ValueError):
            rebuilt = _write_builtin(key, force=True)
            if rebuilt is not None:
                try:
                    return _read_project(rebuilt)
                except (OSError, ValueError):
                    pass
    return _BUILDERS[key]()


def _resolve_builtin_key(value: str) -> str | None:
    text = (value or "").strip()
    if not text:
        return None
    if text in _BUILDERS:
        return text
    if text in _PRESET_FILES:
        return text
    stem = Path(text).stem
    if stem in _STEM_TO_KEY:
        return _STEM_TO_KEY[stem]
    if stem in _BUILDERS:
        return stem
    return None


def _find_user_template(value: str) -> Path | None:
    text = (value or "").strip()
    if not text:
        return None
    try:
        directory = storage.user_templates_dir()
    except OSError:
        return None
    for candidate in (directory / text, directory / f"{text}.sfmproj"):
        if candidate.is_file():
            return candidate
    stem = Path(text).stem.lower()
    try:
        candidates = sorted(directory.glob("*.sfmproj"))
    except OSError:
        return None
    for path in candidates:
        if path.stem.lower() == stem:
            return path
    return None


def _is_under(path: Path, directory: Path) -> bool:
    try:
        return path.resolve().is_relative_to(directory.resolve())
    except (OSError, ValueError):
        return False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def list_templates() -> list[TemplateInfo]:
    """Return the 8 read-only presets, then user templates (including blank).

    The blank template is written to the default user template directory, so
    it is presented as a user template (``builtin=False``) and can be edited
    like any other user file, while the 8 presets stay read-only.
    """
    infos: list[TemplateInfo] = []
    for key, name, description in _SPECS:
        path = _write_builtin(key)
        infos.append(
            TemplateInfo(key=key, name=name, description=description, path=path, builtin=True)
        )

    blank_path: Path | None
    try:
        blank_path = _ensure_blank_template()
    except OSError:
        blank_path = None
    infos.append(
        TemplateInfo(
            key=BLANK_KEY,
            name="空白模板",
            description="空白工程：只有基础标签，没有任务；从零开始搭规则（保存在用户模板目录，可编辑）。",
            path=blank_path,
            builtin=False,
        )
    )

    try:
        user_paths = sorted(storage.user_templates_dir().glob("*.sfmproj"))
    except OSError:
        user_paths = []
    for path in user_paths:
        if path.name == BLANK_FILENAME:
            continue
        try:
            name = _read_project(path).name or path.stem
        except (OSError, ValueError):
            name = path.stem
        infos.append(
            TemplateInfo(
                key=path.stem,
                name=name,
                description="用户保存的模板（可编辑）。",
                path=path,
                builtin=False,
            )
        )
    return infos


def load_template(key_or_path: str, profile_id: str | None = None) -> Project:
    """Load a template by built-in key, preset filename, user file or path.

    A fresh project id and timestamps are assigned so the loaded project is a
    new document; label/task ids and ``ui`` layout are kept intact.  When a
    valid ``profile_id`` is supplied it overrides the template's profile;
    otherwise the profile stored in the template is kept.
    """
    raw = str(key_or_path or "").strip()
    if not raw:
        raise FileNotFoundError("模板标识为空")

    project: Project | None = None
    resolved_key = raw

    path = Path(raw)
    if path.is_file():
        try:
            project = _read_project(path)
        except (OSError, ValueError) as exc:
            raise ValueError(f"模板文件无法读取：{path}") from exc
        # A built-in preset file keeps its semantic key (01-furnace ->
        # furnace). A user file keeps its own stem, even when the stem is
        # similar to a preset; source paths must win for imports.
        preset_key = _resolve_builtin_key(path.stem)
        presets = _presets_dir()
        resolved_key = (
            preset_key
            if preset_key is not None and presets is not None and _is_under(path, presets)
            else path.stem
        )

    if project is None:
        builtin_key = _resolve_builtin_key(raw)
        if builtin_key is not None:
            project = _load_builtin_project(builtin_key)
            resolved_key = builtin_key

    if project is None:
        user_path = _find_user_template(raw)
        if user_path is not None:
            try:
                project = _read_project(user_path)
            except (OSError, ValueError) as exc:
                raise ValueError(f"模板文件无法读取：{user_path}") from exc
            resolved_key = user_path.stem

    if project is None:
        raise FileNotFoundError(f"找不到模板：{raw}")

    project.id = new_id("proj")
    project.template_key = resolved_key
    project.created_at = now_iso()
    project.updated_at = now_iso()
    if profile_id in PROFILES:
        project.profile_id = profile_id
    project.ensure_active()
    return project


def save_template(project: Project, path: Path) -> Path:
    """Write *project* as a template JSON file; presets are read-only."""
    target = Path(path)
    if target.suffix.lower() != ".sfmproj":
        target = target.with_name(target.name + ".sfmproj")
    presets = _presets_dir()
    if presets is not None and _is_under(target, presets):
        raise ValueError("presets 模板是只读的；请使用 copy_template_to_user 或保存到用户目录。")
    storage.atomic_write_text(target, _payload(project))
    return target


def copy_template_to_user(key: str) -> Path:
    """Copy a built-in/user template into the user template directory."""
    raw = str(key or "").strip()
    # An explicit source path wins over a built-in stem lookup. Otherwise
    # importing a user file named furnace.sfmproj would copy the wrong file.
    response = Path(raw)
    if response.is_file():
        target_name = response.name
        if _resolve_builtin_key(response.stem) is not None:
            # Never let a user file share a built-in key. The prefix also
            # makes the copied template unambiguous in the picker.
            target_name = f"user-{response.name}"
        return storage.copy_template_to_user(response, name=target_name)

    builtin_key = _resolve_builtin_key(raw)
    if builtin_key == BLANK_KEY:
        # The blank template already lives in the user directory.
        return _ensure_blank_template()

    if builtin_key is not None:
        source = _write_builtin(builtin_key)
        if source is not None and source.is_file():
            return storage.copy_template_to_user(source)
        return _write_user_copy(_BUILDERS[builtin_key](), _PRESET_FILES[builtin_key])

    user_path = _find_user_template(raw)
    if user_path is not None:
        return storage.copy_template_to_user(user_path)

    raise FileNotFoundError(f"找不到模板：{raw}")


def _write_user_copy(project: Project, filename: str) -> Path:
    directory = storage.user_templates_dir()
    target = directory / filename
    if target.exists():
        stem, suffix = target.stem, target.suffix
        index = 2
        while target.exists():
            target = directory / f"{stem} {index}{suffix}"
            index += 1
    storage.atomic_write_text(target, _payload(project))
    return target


def blank_project(profile_id: str = DEFAULT_PROFILE) -> Project:
    """Create a writable blank project (three starter labels, no tasks)."""
    if profile_id not in PROFILES:
        profile_id = DEFAULT_PROFILE
    return new_blank_project("未命名工程", profile_id)


__all__ = [
    "BLANK_FILENAME",
    "BLANK_KEY",
    "TemplateInfo",
    "blank_project",
    "copy_template_to_user",
    "ensure_builtin_templates",
    "list_templates",
    "load_template",
    "save_template",
]
