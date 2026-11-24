"""Filesystem storage, paths and small app settings for SFM Code Workshop."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import json
import os
from pathlib import Path
import shutil
import tempfile
import uuid
from typing import Any

from .model import Project, SCHEMA_VERSION, project_to_json, project_from_json


APP_NAME = "SFM代码生成工坊"
APP_DIR_NAME = "SFMCodeWorkshop"
PROJECT_EXT = ".sfmproj"
_USER_ROOT_CACHE: Path | None = None
_USER_ROOT_KEY: tuple[str, str, str] | None = None


def app_root() -> Path:
    """Directory containing the executable (or source package)."""
    import sys

    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def resource_root() -> Path:
    """Bundled resources; PyInstaller one-dir puts them under _MEIPASS."""
    import sys

    if getattr(sys, "frozen", False):
        base = getattr(sys, "_MEIPASS", None)
        if base:
            return Path(base) / "resources"
        return Path(sys.executable).resolve().parent / "resources"
    return app_root() / "resources"


def user_root() -> Path:
    """Writable app data root, resolved once per process.

    Re-probing on every accessor could switch roots after one transient
    PermissionError (antivirus, roaming profile), splitting settings/autosave
    across directories. Keep the first successful root for the session.
    """
    global _USER_ROOT_CACHE, _USER_ROOT_KEY
    key = (
        os.environ.get("APPDATA", ""),
        os.environ.get("HOME", ""),
        os.environ.get("USERPROFILE", ""),
    )
    if _USER_ROOT_CACHE is not None and _USER_ROOT_KEY == key:
        return _USER_ROOT_CACHE
    candidates: list[Path] = []
    base = os.environ.get("APPDATA")
    if base:
        candidates.append(Path(base) / APP_DIR_NAME)
    candidates.append(Path.home() / "Documents" / APP_DIR_NAME)
    candidates.append(Path.home() / APP_DIR_NAME)
    candidates.append(app_root() / "data")
    candidates.append(Path(tempfile.gettempdir()) / APP_DIR_NAME)
    last_error: Exception | None = None
    for root in candidates:
        try:
            root.mkdir(parents=True, exist_ok=True)
            probe = root / ".write-probe"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
            _USER_ROOT_CACHE = root
            _USER_ROOT_KEY = key
            return root
        except Exception as exc:  # permission/read-only/AV
            last_error = exc
            continue
    raise RuntimeError(f"无法创建可写的应用数据目录: {last_error}")


def projects_dir() -> Path:
    d = user_root() / "projects"
    d.mkdir(parents=True, exist_ok=True)
    return d


def user_templates_dir() -> Path:
    d = user_root() / "templates"
    d.mkdir(parents=True, exist_ok=True)
    return d


def presets_templates_dir() -> Path:
    # Bundled resources should be read-only in an install; create only when
    # the directory is writable (source tree/tests), tolerate read-only.
    d = resource_root() / "templates" / "presets"
    try:
        d.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return d


def settings_path() -> Path:
    return user_root() / "settings.json"


def recent_path() -> Path:
    return user_root() / "recent.json"


def autosave_path() -> Path:
    return user_root() / "autosave.sfmproj"


def ensure_dirs() -> None:
    # Only user-writable dirs. Bundled resources must not be modified.
    for d in (projects_dir(), user_templates_dir()):
        d.mkdir(parents=True, exist_ok=True)


def load_autosave() -> Project | None:
    path = autosave_path()
    if not path.exists():
        return None
    try:
        return load_project(path)
    except Exception:
        return None


def atomic_write_text(path: str | Path, text: str, encoding: str = "utf-8") -> None:
    """Atomically replace ``path`` without tempfile's Windows retry loop.

    ``tempfile.mkstemp`` treats ``PermissionError`` on Windows as a possible
    name collision and, when ``os.access(dir, W_OK)`` is (misleadingly) true,
    retries up to TMP_MAX names. In a protected folder such as a Desktop
    workspace this turns a transparent permission failure into a long GUI
    freeze. Create exactly one unpredictable sibling with O_EXCL instead; a
    permission error is surfaced immediately.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    fd = -1
    tmp: Path | None = None
    last_collision: FileExistsError | None = None
    for _ in range(4):
        candidate = path.with_name(
            f".{path.name}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp"
        )
        try:
            fd = os.open(candidate, flags, 0o600)
            tmp = candidate
            break
        except FileExistsError as exc:
            last_collision = exc
            continue
        # PermissionError/OSError must not be retried here.
    if tmp is None:
        raise last_collision or PermissionError(f"无法创建临时文件：{path.parent}")
    try:
        with os.fdopen(fd, "w", encoding=encoding, newline="\n") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def save_project(project: Project, path: str | Path | None = None) -> Path:
    ensure_dirs()
    if int(getattr(project, "schema_version", SCHEMA_VERSION)) > SCHEMA_VERSION:
        raise ValueError(
            "工程由更新版本创建，当前版本保存会丢失未知字段；"
            "请升级应用后再保存。"
        )
    if path is None:
        safe = "".join(c for c in project.name if c not in '\\/:*?"<>|').strip() or "未命名工程"
        path = projects_dir() / f"{safe}{PROJECT_EXT}"
    path = Path(path)
    if path.suffix.lower() != PROJECT_EXT:
        # Append instead of replacing: "factory.v2" must not silently write
        # "factory.sfmproj" over an existing, different project.
        path = path.with_name(path.name + PROJECT_EXT)
    project.updated_at = datetime.now().astimezone().replace(microsecond=0).isoformat()
    atomic_write_text(path, project_to_json(project))
    add_recent(path)
    return path


def load_project(path: str | Path) -> Project:
    path = Path(path)
    return project_from_json(path.read_text(encoding="utf-8-sig"))


def autosave(project: Project) -> None:
    ensure_dirs()
    if int(getattr(project, "schema_version", SCHEMA_VERSION)) > SCHEMA_VERSION:
        raise ValueError(
            "工程由更新版本创建，当前版本不会写入自动保存以避免丢失未知字段。"
        )
    atomic_write_text(autosave_path(), project_to_json(project))


def export_sfml(code: str, path: str | Path) -> Path:
    path = Path(path)
    if path.suffix.lower() != ".sfm":
        path = path.with_name(path.name + ".sfm")
    # UTF-8 without BOM, LF, no timestamp.
    atomic_write_text(path, code, encoding="utf-8")
    return path


# ---- recent projects ----------------------------------------------------

def load_recent() -> list[dict[str, Any]]:
    try:
        data = json.loads(recent_path().read_text(encoding="utf-8-sig"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def add_recent(path: str | Path) -> None:
    path = str(Path(path).resolve())
    items = [x for x in load_recent() if isinstance(x, dict) and x.get("path") != path]
    items.insert(0, {"path": path, "name": Path(path).stem, "at": datetime.now().isoformat(timespec="seconds")})
    items = [x for x in items if isinstance(x, dict) and isinstance(x.get("path"), str) and Path(x["path"]).exists()][:12]
    try:
        atomic_write_text(recent_path(), json.dumps(items, ensure_ascii=False, indent=2))
    except Exception:
        pass


def remove_recent(path: str | Path) -> None:
    target = str(Path(path).resolve())
    items = [
        x for x in load_recent()
        if isinstance(x, dict) and str(x.get("path") or "") != target
    ]
    try:
        atomic_write_text(recent_path(), json.dumps(items, ensure_ascii=False, indent=2))
    except Exception:
        pass


@dataclass
class AppSettings:
    theme: str = "light"  # light|dark
    profile_id: str = "1.21.1-neoforge"
    reduced_motion: bool = False
    ui_scale: int = 100
    language: str = "zh_CN"
    ai_enabled: bool = False
    ai_base_url: str = "https://api.deepseek.com"
    ai_model: str = "deepseek-chat"
    ai_protocol: str = "DeepSeek 官方 API"
    ai_prompt_version: int = 1
    prompt_override: str = ""
    last_project: str = ""

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "AppSettings":
        allowed = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        return cls(**allowed)


def load_settings() -> AppSettings:
    try:
        return AppSettings.from_dict(json.loads(settings_path().read_text(encoding="utf-8-sig")))
    except Exception:
        return AppSettings()


def save_settings(settings: AppSettings) -> None:
    ensure_dirs()
    atomic_write_text(settings_path(), json.dumps(settings.to_dict(), ensure_ascii=False, indent=2))


def copy_template_to_user(src: str | Path, name: str | None = None) -> Path:
    src = Path(src)
    ensure_dirs()
    target = user_templates_dir() / (name or src.name)
    if target.exists():
        stem, suffix = target.stem, target.suffix
        i = 2
        while target.exists():
            target = user_templates_dir() / f"{stem} {i}{suffix}"
            i += 1
    shutil.copy2(src, target)
    return target
