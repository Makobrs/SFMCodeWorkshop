"""Offline self-test used by the packaged executable (`--self-test`)."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

from .core.codegen import generate_project
from .core.model import Project, new_blank_project, project_from_json, project_to_json
from .core.storage import ensure_dirs, load_project, save_project
from .core.templates import list_templates, load_template
from .core.tps import estimate_tps
from .core.validate import validate_project


def _emit(text: str) -> None:
    """print() is unavailable in a windowed PyInstaller build."""
    try:
        print(text)
    except Exception:
        pass


def _write_report(text: str) -> None:
    try:
        from .core.storage import user_root

        targets = [user_root() / "self-test.json", Path(tempfile.gettempdir()) / "SFMCodeWorkshop-self-test.json"]
    except Exception:
        targets = [Path(tempfile.gettempdir()) / "SFMCodeWorkshop-self-test.json"]
    for target in targets:
        try:
            target.write_text(text, encoding="utf-8")
            break
        except Exception:
            continue


def run() -> int:
    report: dict = {
        "ok": False,
        "templates": [],
        "blank_builtin": None,
        "syntax_errors": [],
        "issues": [],
    }
    try:
        try:
            ensure_dirs()
        except Exception as exc:
            # Self-test must still report a readable failure even when APPDATA
            # is locked down; never let this raise before the report exists.
            report["storage_error"] = f"{type(exc).__name__}: {exc}"
        items = list_templates()
        report["templates"] = [x.key for x in items]
        blank = next((x for x in items if x.key == "blank"), None)
        report["blank_builtin"] = bool(blank.builtin) if blank else None
        if len([x for x in items if x.builtin]) != 8:
            raise AssertionError("expected exactly 8 built-in presets")
        if blank is None or blank.builtin:
            raise AssertionError("blank template must be a user template")
        p = load_template("furnace", "1.21.1-neoforge")
        code = generate_project(p)
        result = validate_project(p)
        report["syntax_errors"] = list(result.syntax_errors)
        report["issues"] = [
            {"level": i.level, "code": i.code, "message": i.message}
            for i in result.issues[:10]
        ]
        if result.syntax_errors:
            raise AssertionError("generated code failed L0 parser")
        from .core.importer import import_sfml

        imported = import_sfml(code, "1.21.1-neoforge", "self-test")
        if len(imported.project.tasks) != len(p.tasks):
            raise AssertionError("SFML import roundtrip failed")
        report["import"] = {"tasks": len(imported.project.tasks)}
        est = estimate_tps(p)
        report["tps"] = {"score": est.score, "level": est.level}
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "roundtrip.sfmproj"
            save_project(p, path)
            p2 = load_project(path)
            if p2.name != p.name or len(p2.tasks) != len(p.tasks):
                raise AssertionError("project roundtrip failed")
        # Exercise the bundled catalog + pypinyin in the packaged build.
        try:
            from .core.catalog import bundled_items_path, parse_items_payload, search_entries

            import json as _json

            sample = parse_items_payload(_json.loads(bundled_items_path().read_text(encoding="utf-8")))
            names = [e.id for e in sample]
            if "minecraft:iron_ingot" not in names:
                raise AssertionError("bundled catalog missing iron_ingot")
            for query in ("铁锭", "tieding", "td", "minecraft:iron_ingot"):
                if not any(e.id == "minecraft:iron_ingot" for e in search_entries(sample, query)):
                    raise AssertionError(f"catalog search failed: {query}")
            report["catalog"] = {"count": len(sample), "pinyin": True}
        except Exception as exc:
            report["catalog_error"] = f"{type(exc).__name__}: {exc}"
            raise
        report["ok"] = True
        text = json.dumps(report, ensure_ascii=False, indent=2)
        _write_report(text)
        _emit(text)
        return 0
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
        text = json.dumps(report, ensure_ascii=False, indent=2)
        _write_report(text)
        _emit(text)
        return 1


if __name__ == "__main__":
    raise SystemExit(run())
