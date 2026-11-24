"""Lightweight multi-workspace registry for the local workbench.

A workspace is a real folder.  Its projects are normal ``.sfmproj`` files and
are never copied or deleted by this module; removing a workspace only removes
the registry entry.  This mirrors the useful part of the reference app without
introducing a second project storage format.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
import shutil
import uuid
from typing import Any, Iterable

from .storage import atomic_write_text, projects_dir, user_root


DEFAULT_NAME = "默认工作区"


@dataclass(frozen=True)
class Workspace:
    id: str
    name: str
    path: str
    default: bool = False
    available: bool = True


def workspaces_path() -> Path:
    return user_root() / "workspaces.json"


def session_order_path() -> Path:
    return user_root() / "session-order.json"


def recycle_sessions_dir() -> Path:
    return user_root() / "recycle" / "sessions"


def _default_path() -> str:
    try:
        return str(projects_dir().resolve())
    except Exception:
        return str((user_root() / "projects").resolve())


def load_workspaces() -> list[Workspace]:
    data: Any = {}
    path = workspaces_path()
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    raw = data.get("workspaces") if isinstance(data, dict) else None
    out: list[Workspace] = []
    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue
            p = str(item.get("path") or "").strip()
            name = str(item.get("name") or "").strip()
            if not p or not name:
                continue
            out.append(
                Workspace(
                    id=str(item.get("id") or uuid.uuid4().hex[:10]),
                    name=name,
                    path=p,
                    default=bool(item.get("default")),
                    available=Path(p).is_dir(),
                )
            )
    if not out:
        out = [
            Workspace(
                id="default",
                name=DEFAULT_NAME,
                path=_default_path(),
                default=True,
            )
        ]
    return out


def save_workspaces(workspaces: Iterable[Workspace]) -> None:
    items = [
        {"id": w.id, "name": w.name, "path": w.path, "default": bool(w.default)}
        for w in workspaces
    ]
    atomic_write_text(
        workspaces_path(),
        json.dumps({"schema": 1, "workspaces": items}, ensure_ascii=False, indent=2),
    )


def add_workspace(path: str | Path, name: str | None = None) -> Workspace:
    target = Path(path).expanduser().resolve()
    if not target.is_dir():
        raise ValueError("工作区必须是已存在的文件夹")
    spaces = load_workspaces()
    for w in spaces:
        if Path(w.path).resolve() == target:
            return w
    display = (name or target.name or "工作区").strip()
    ws = Workspace(id="ws-" + uuid.uuid4().hex[:8], name=display, path=str(target))
    spaces.append(ws)
    save_workspaces(spaces)
    return ws


def load_session_orders() -> dict[str, list[str]]:
    try:
        raw = json.loads(session_order_path().read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, list[str]] = {}
    for key, value in raw.items():
        if isinstance(key, str) and isinstance(value, list):
            out[key] = [str(x) for x in value if isinstance(x, str)]
    return out


def save_session_orders(orders: dict[str, list[str]]) -> None:
    atomic_write_text(
        session_order_path(),
        json.dumps(orders, ensure_ascii=False, indent=2),
    )


def set_session_order(workspace_path: str, paths: Iterable[str]) -> None:
    orders = load_session_orders()
    key = _canonical(workspace_path)
    orders[key] = [_canonical(p) for p in paths]
    save_session_orders(orders)


def move_session_to_recycle(path: str | Path) -> Path:
    """Move a .sfmproj into the app's recoverable recycle folder."""
    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(f"会话文件不存在：{source}")
    if source.suffix.lower() != ".sfmproj":
        raise ValueError(f"只能移除 .sfmproj 会话：{source}")
    folder = recycle_sessions_dir()
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / source.name
    n = 2
    while target.exists():
        target = folder / f"{source.stem} {n}{source.suffix}"
        n += 1
    shutil.move(str(source), str(target))
    return target


def _workspace_for(path: str, spaces: list[Workspace]) -> Workspace | None:
    try:
        p = Path(path).resolve()
    except Exception:
        return None
    best: Workspace | None = None
    best_len = -1
    for w in spaces:
        try:
            root = Path(w.path).resolve()
            p.relative_to(root)
        except Exception:
            continue
        n = len(str(root))
        if n > best_len:
            best, best_len = w, n
    return best


def _canonical(path: str | Path) -> str:
    try:
        return str(Path(path).expanduser().resolve())
    except Exception:
        return str(path)


def _project_title(path: str) -> str:
    """Read only the project title so a session row never falls back to a file stem."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        title = str(data.get("name") or "").strip()
        return title
    except Exception:
        return ""


def _nearest_parent(root: str, spaces: list[Workspace]) -> str:
    """Nearest registered ancestor folder, for the DSH Workspace Tree shape."""
    try:
        target = Path(root).resolve()
    except Exception:
        return ""
    best = ""
    best_len = -1
    for w in spaces:
        try:
            candidate = Path(w.path).resolve()
            if candidate == target:
                continue
            target.relative_to(candidate)
        except Exception:
            continue
        n = len(str(candidate))
        if n > best_len:
            best = str(candidate)
            best_len = n
    return best


def group_projects(
    recents: list[dict],
    spaces: list[Workspace] | None = None,
    current_name: str = "",
    current_path: str = "",
    include_empty: bool = True,
) -> list[dict]:
    """Group code files into a DSH-style workspace tree.

    A registered Workspace is a directory.  A ``.sfmproj`` is one session/code
    file in that directory.  Child workspaces are nested under their nearest
    registered ancestor; projects outside every workspace go to ``未分组``.
    The existing folder scan is intentionally retained as a compatibility
    discovery path (DSH itself only lists registered sessions).
    """
    spaces = spaces or load_workspaces()
    groups: dict[str, dict] = {}
    for w in spaces:
        root = _canonical(w.path)
        groups[root] = {
            "id": w.id,
            "name": w.name,
            "path": root,
            "parent_path": "",
            "projects": [],
            "default": bool(w.default),
            "available": bool(w.available),
        }
    for g in groups.values():
        g["parent_path"] = _nearest_parent(g["path"], spaces)

    ungrouped: dict = {
        "id": "ungrouped",
        "name": "未分组",
        "path": "",
        "parent_path": "",
        "projects": [],
        "default": False,
    }
    seen_paths: set[str] = set()
    current_key = _canonical(current_path) if current_path else ""

    def owner_group(file_path: str) -> dict:
        ws = _workspace_for(file_path, spaces)
        if ws is not None:
            key = _canonical(ws.path)
            if key in groups:
                return groups[key]
        return ungrouped

    def add_session(file_path: str, name: str, at: str = "") -> None:
        key = _canonical(file_path)
        if not key or key in seen_paths:
            # Mark an already discovered row as the active session.
            if key in seen_paths:
                for group in list(groups.values()) + [ungrouped]:
                    for item in group["projects"]:
                        if _canonical(str(item.get("path") or "")) == key:
                            item["current"] = key == current_key
            return
        seen_paths.add(key)
        target = owner_group(key)
        target["projects"].append(
            {
                "name": _project_title(key) or name or Path(key).stem,
                "path": key,
                "at": at,
                "current": key == current_key,
            }
        )

    for item in recents:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or "")
        name = str(item.get("name") or "")
        if not path or not name:
            continue
        add_session(path, name, str(item.get("at") or ""))

    # Discover .sfmproj files in registered workspace folders. A file nested in
    # both a parent and a child workspace belongs to the nearest (child) one.
    for w in spaces:
        if not w.available:
            continue
        root = Path(w.path)
        try:
            files = sorted(root.rglob("*.sfmproj"), key=lambda p: p.stat().st_mtime, reverse=True)[:200]
        except Exception:
            files = []
        for path in files:
            owner = _workspace_for(str(path), spaces)
            if owner is not None and _canonical(owner.path) != _canonical(w.path):
                continue
            try:
                at = datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds")
            except Exception:
                at = ""
            add_session(str(path), path.stem, at)

    if current_path:
        add_session(current_path, current_name or Path(current_path).stem, "")
    elif current_name:
        target = next((g for g in groups.values() if g.get("default")), None) or next(iter(groups.values()), None)
        if target is None:
            target = ungrouped
        target["projects"].insert(0, {"name": current_name, "path": "", "at": "", "current": True})

    # Keep the active project's display title current, but never move it in
    # the list. Sorting is by recency only; a click must not pin a session.
    if current_key and current_name:
        for group in list(groups.values()) + [ungrouped]:
            for item in group["projects"]:
                if _canonical(str(item.get("path") or "")) == current_key:
                    item["name"] = current_name
    result: list[dict] = []
    orders = load_session_orders()
    for group in list(groups.values()) + ([ungrouped] if ungrouped["projects"] else []):
        if not group["projects"] and not include_empty:
            continue
        # Selection must not mutate order: use recency only, never active-first.
        group["projects"].sort(key=lambda x: str(x.get("at") or ""), reverse=True)
        saved = orders.get(str(group.get("path") or ""))
        if saved:
            by_path = {_canonical(str(p.get("path") or "")): p for p in group["projects"]}
            ordered: list[dict] = []
            used: set[str] = set()
            for raw in saved:
                key = _canonical(raw)
                item = by_path.get(key)
                if item is not None and key not in used:
                    ordered.append(item)
                    used.add(key)
            for item in group["projects"]:
                key = _canonical(str(item.get("path") or ""))
                if key not in used:
                    ordered.append(item)
            group["projects"] = ordered
        result.append(group)
    result.sort(key=lambda g: (0 if g.get("default") else 1 if g.get("id") != "ungrouped" else 2, g["name"].lower()))
    return result

