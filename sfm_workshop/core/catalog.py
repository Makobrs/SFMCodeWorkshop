"""Local resource catalog imported from SFM's ``/sfm export_info false``.

The current game export is a JSON array of:
``{"id": "minecraft:iron_ingot", "tags": [...], "tooltip": "铁锭\\n..."}``.

We keep the embedded 51-item sample usable on first run, replace it with the
imported file, and never read the Minecraft installation directory.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import tempfile
from typing import Any

from .storage import atomic_write_text, resource_root, user_root

try:  # pypinyin is bundled in the release; fall back to ID/name search only.
    from pypinyin import Style, lazy_pinyin
except Exception:  # pragma: no cover - optional fallback
    Style = None
    lazy_pinyin = None


@dataclass(frozen=True)
class CatalogEntry:
    id: str
    name: str = ""
    tags: tuple[str, ...] = ()
    pinyin: str = ""
    initials: str = ""

    @property
    def display(self) -> str:
        if self.name and self.name != self.id:
            return f"{self.name}  —  {self.id}"
        return self.id


@dataclass(frozen=True)
class CatalogInfo:
    source: str
    count: int
    imported: bool


def _pinyin_pair(name: str) -> tuple[str, str]:
    text = (name or "").strip()
    if not text or lazy_pinyin is None:
        return "", ""
    try:
        full = "".join(lazy_pinyin(text)).lower()
        initials = "".join(lazy_pinyin(text, style=Style.FIRST_LETTER)).lower()
        return full, initials
    except Exception:
        return "", ""


def _name_from_raw(raw: dict[str, Any], rid: str) -> str:
    for key in ("name", "display_name", "displayName", "translation", "label", "title"):
        value = raw.get(key)
        if isinstance(value, str) and value.strip() and value.strip() != rid:
            return value.strip()
    tooltip = raw.get("tooltip")
    if isinstance(tooltip, str) and tooltip.strip():
        # SFM writes "中文名\n资源 ID\n模组名"; the first non-empty line is the
        # localized name.  Strip formatting/section signs just in case.
        for line in tooltip.replace("§", "").splitlines():
            line = line.strip()
            if line:
                return line
    return ""


def _tags_from_raw(raw: dict[str, Any]) -> tuple[str, ...]:
    tags = raw.get("tags") or []
    if isinstance(tags, str):
        tags = [tags]
    return tuple(str(x).strip() for x in tags if str(x).strip())


def _entry_from_any(value: Any, fallback_id: str = "") -> CatalogEntry | None:
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        return CatalogEntry(id=text, name=text)
    if not isinstance(value, dict):
        return None
    rid = ""
    for key in ("id", "resource", "resource_id", "registry_name", "key", "name"):
        v = value.get(key)
        if isinstance(v, str) and v.strip():
            rid = v.strip()
            break
    if not rid and fallback_id:
        rid = fallback_id
    if not rid:
        return None
    name = _name_from_raw(value, rid)
    tags = _tags_from_raw(value)
    py, initials = _pinyin_pair(name)
    return CatalogEntry(id=rid, name=name, tags=tags, pinyin=py, initials=initials)


def parse_items_payload(payload: Any) -> list[CatalogEntry]:
    """Parse an SFM export (or the embedded sample) into entries."""
    found: dict[str, CatalogEntry] = {}

    def add(entry: CatalogEntry | None) -> None:
        if entry is None or not entry.id:
            return
        old = found.get(entry.id)
        if old is None or (entry.name and not old.name):
            found[entry.id] = entry

    def walk(value: Any, fallback_id: str = "") -> None:
        if isinstance(value, list):
            for item in value:
                walk(item)
            return
        if isinstance(value, dict):
            # common wrappers
            for wrapper in ("items", "resources", "entries", "data", "values"):
                inner = value.get(wrapper)
                if isinstance(inner, (list, dict)):
                    walk(inner)
            entry = _entry_from_any(value, fallback_id)
            if entry:
                add(entry)
                # A single resource object (id/tooltip/tags) is not a mapping
                # of arbitrary ids; don't turn its field names into resources.
                return
            for key, val in value.items():
                if key in ("items", "resources", "entries", "data", "values", "version", "schema", "source"):
                    continue
                if isinstance(val, (dict, str)):
                    if isinstance(val, dict):
                        walk(val, str(key))
                    elif str(key).strip():
                        add(
                            CatalogEntry(
                                id=str(key).strip(),
                                name=str(val).strip(),
                                pinyin=_pinyin_pair(str(val).strip())[0],
                                initials=_pinyin_pair(str(val).strip())[1],
                            )
                        )
            return
        add(_entry_from_any(value, fallback_id))

    walk(payload)
    return sorted(found.values(), key=lambda e: e.id.lower())


def catalog_path(profile_id: str) -> Path:
    safe = "".join(c for c in profile_id if c.isalnum() or c in "-_") or "default"
    return user_root() / "resources" / f"items-{safe}.json"


def bundled_items_path() -> Path:
    return resource_root() / "items.json"


def _entries_from_saved(path: Path) -> tuple[list[CatalogEntry], str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    raw = data.get("entries") if isinstance(data, dict) else data
    source = str(data.get("source") or "导入 items.json") if isinstance(data, dict) else "导入 items.json"
    if not isinstance(raw, list):
        raise ValueError("资源库文件格式错误")
    out: list[CatalogEntry] = []
    for item in raw:
        if isinstance(item, dict) and item.get("id"):
            rid = str(item["id"]).strip()
            name = str(item.get("name") or "").strip()
            tags_raw = item.get("tags") or []
            tags = tuple(str(x) for x in tags_raw if str(x).strip()) if isinstance(tags_raw, list) else ()
            py = str(item.get("pinyin") or "").strip()
            initials = str(item.get("initials") or "").strip()
            if not py or not initials:
                py, initials = _pinyin_pair(name)
            out.append(CatalogEntry(id=rid, name=name, tags=tags, pinyin=py, initials=initials))
        elif isinstance(item, str):
            out.append(CatalogEntry(id=item, name=item))
    return out, source


def _bundled_entries() -> list[CatalogEntry]:
    path = bundled_items_path()
    if not path.exists():
        return []
    try:
        return parse_items_payload(json.loads(path.read_text(encoding="utf-8")))
    except Exception:
        return []


# cached by file identity + mtime; avoids reopening/re-parsing 17k items on
# every search keystroke while still replacing data after a new import.
_CACHE: dict[str, tuple[int, int, list[CatalogEntry], str]] = {}


def _load_with_cache(path: Path) -> tuple[list[CatalogEntry], str] | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    key = str(path.resolve())
    cached = _CACHE.get(key)
    if cached and cached[0] == stat.st_mtime_ns and cached[1] == stat.st_size:
        return cached[2], cached[3]
    try:
        entries, source = _entries_from_saved(path)
    except Exception:
        return None
    _CACHE[key] = (stat.st_mtime_ns, stat.st_size, entries, source)
    return entries, source


def load_catalog(profile_id: str) -> list[CatalogEntry]:
    imported = catalog_path(profile_id)
    if imported.exists():
        loaded = _load_with_cache(imported)
        if loaded:
            return loaded[0]
    return _bundled_entries()


def catalog_info(profile_id: str) -> CatalogInfo:
    imported = catalog_path(profile_id)
    if imported.exists():
        loaded = _load_with_cache(imported)
        if loaded:
            return CatalogInfo(source=loaded[1], count=len(loaded[0]), imported=True)
    entries = _bundled_entries()
    return CatalogInfo(source="内置示例", count=len(entries), imported=False)


def import_items(path: str | Path, profile_id: str) -> list[CatalogEntry]:
    src = Path(path)
    text = src.read_text(encoding="utf-8")
    payload = json.loads(text)
    entries = parse_items_payload(payload)
    if not entries:
        raise ValueError("没有解析到资源条目；请确认是 /sfm export_info false 生成的 items.json")
    dest = catalog_path(profile_id)
    dest.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "schema": 2,
        "profile": profile_id,
        "source": f"导入：{src.name}",
        "entries": [
            {
                "id": e.id,
                "name": e.name,
                "tags": list(e.tags),
                "pinyin": e.pinyin,
                "initials": e.initials,
            }
            for e in entries
        ],
    }
    # atomic write keeps the previous catalog intact if the disk is full.
    atomic_write_text(dest, json.dumps(data, ensure_ascii=False, indent=2))
    return entries


def _search_hay(entry: CatalogEntry) -> str:
    return f"{entry.id} {entry.name} {' '.join(entry.tags)}".lower()


def matches(entry: CatalogEntry, query: str) -> bool:
    q = (query or "").strip().lower()
    if not q:
        return True
    q_compact = "".join(q.split())
    hay = _search_hay(entry)
    pinyin = (entry.pinyin or "").replace(" ", "")
    initials = (entry.initials or "").replace(" ", "")
    return (
        q in hay
        or q_compact in hay
        or bool(q_compact and q_compact in pinyin)
        or bool(q_compact and q_compact in initials)
    )


def _rank(entry: CatalogEntry, query: str) -> tuple:
    q = (query or "").strip().lower()
    q_compact = "".join(q.split())
    name = entry.name.lower()
    rid = entry.id.lower()
    pinyin = (entry.pinyin or "").replace(" ", "")
    initials = (entry.initials or "").replace(" ", "")
    if name and name == q:
        score = 0
    elif name and q and q in name:
        score = 1
    elif q_compact and pinyin == q_compact:
        score = 2
    elif q_compact and initials == q_compact:
        score = 3
    elif rid == q:
        score = 4
    elif q and q in rid:
        score = 5
    else:
        score = 6
    # Prefer vanilla when the query is ambiguous (e.g. "td"), then the pinyin
    # lexical order ("tieding" before "tongding"/"tudou"), then stable id.
    return (score, pinyin or "zzzzzz", 0 if rid.startswith("minecraft:") else 1, rid)


def search_entries(entries: list[CatalogEntry], query: str, limit: int = 200) -> list[CatalogEntry]:
    rows = [e for e in entries if matches(e, query)]
    rows.sort(key=lambda e: _rank(e, query))
    return rows[:limit]


def search_catalog(profile_id: str, query: str, limit: int = 200) -> list[CatalogEntry]:
    return search_entries(load_catalog(profile_id), query, limit)


def get_entry(profile_id: str, rid: str) -> CatalogEntry | None:
    for e in load_catalog(profile_id):
        if e.id == rid:
            return e
    return None


__all__ = [
    "CatalogEntry",
    "CatalogInfo",
    "catalog_info",
    "catalog_path",
    "bundled_items_path",
    "import_items",
    "load_catalog",
    "matches",
    "parse_items_payload",
    "search_catalog",
    "search_entries",
]
