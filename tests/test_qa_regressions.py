"""Regression coverage for the second QA pass.

These are headless tests of the actual save/rename/template/crash/inspector
paths.  External file-manager calls are mocked; file writes are real temp data.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from sfm_workshop.core import crashlog
from sfm_workshop.core.model import Project, SCHEMA_VERSION
from sfm_workshop.core.storage import save_project
from sfm_workshop.ui.dialogs import CatalogDialog
from sfm_workshop.ui.main_window import MainWindow


def _app():
    return QApplication.instance() or QApplication([])


def _window(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    _app()
    w = MainWindow()
    w._autosave_candidate = None
    w._autosave_timer.stop()
    w.show()
    _app().processEvents()
    return w


def test_newer_schema_cannot_be_downgraded(tmp_path):
    p = Project(schema_version=SCHEMA_VERSION + 1)
    target = tmp_path / "future.sfmproj"
    with pytest.raises(ValueError):
        save_project(p, target)
    assert not target.exists()


def test_rename_commits_title_and_regenerates_code(tmp_path, monkeypatch):
    w = _window(tmp_path, monkeypatch)
    target = tmp_path / "renamed.sfmproj"
    try:
        w.project_name_edit.setText("RENAMED-TITLE")
        with monkeypatch.context() as m:
            m.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(target), "SFM (*.sfmproj)"))
            w._save_project()
        saved = json.loads(target.read_text(encoding="utf-8"))
        assert saved["name"] == "RENAMED-TITLE"
        assert "RENAMED-TITLE" in w.code
    finally:
        w.dirty = False
        w.close()


def test_corrupt_last_project_surfaces_warning(tmp_path, monkeypatch):
    w = _window(tmp_path, monkeypatch)
    warnings: list[str] = []
    monkeypatch.setattr(QMessageBox, "warning", lambda _p, _t, text: warnings.append(text))
    try:
        w._project_load_error = str(tmp_path / "broken.sfmproj") + "\nexpect"
        w._show_project_load_warning()
        assert warnings and "上次工程未能打开" not in warnings[0]
        assert "broken.sfmproj" in warnings[0]
    finally:
        w.dirty = False
        w.close()


def test_user_template_path_wins_over_builtin_stem(tmp_path, monkeypatch):
    from sfm_workshop.core import templates
    from sfm_workshop.core.storage import save_project, user_templates_dir

    monkeypatch.setenv("APPDATA", str(tmp_path))
    custom = tmp_path / "furnace.sfmproj"
    save_project(Project(name="CUSTOM-FURNACE"), custom)
    copied = templates.copy_template_to_user(str(custom))
    loaded = templates.load_template(copied.stem)
    assert loaded.name == "CUSTOM-FURNACE"
    assert user_templates_dir().is_dir()


def test_live_marker_is_not_reported_as_crash(tmp_path, monkeypatch):
    import subprocess

    monkeypatch.setenv("APPDATA", str(tmp_path))
    owner = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(8)"])
    try:
        logs = crashlog.logs_dir()
        marker = crashlog.marker_path()
        marker.write_text(
            json.dumps(
                {
                    "pid": owner.pid,
                    "proc_start": crashlog._process_creation_time(owner.pid) or 0,
                    "started": "now",
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.setattr(crashlog, "_installed", False)
        monkeypatch.setattr(crashlog, "_current", None)
        monkeypatch.setattr(crashlog, "_crash_recorded", False)
        info = crashlog.install()
        assert info is None
        assert marker.exists()
        crashlog.mark_clean_exit()
        assert marker.exists()
    finally:
        owner.terminate()
        try:
            owner.wait(timeout=3)
        except Exception:
            owner.kill()


def test_save_settings_failure_does_not_mark_project_failed(tmp_path, monkeypatch):
    w = _window(tmp_path, monkeypatch)
    target = tmp_path / "kept.sfmproj"
    warnings: list[str] = []
    monkeypatch.setattr("sfm_workshop.ui.main_window.save_settings", lambda _s: (_ for _ in ()).throw(OSError("settings")))
    monkeypatch.setattr(QMessageBox, "critical", lambda _p, _t, text: warnings.append(text))
    try:
        w.project_path = target
        w.dirty = True
        w._save_project()
        assert target.exists()
        assert not warnings
    finally:
        w.dirty = False
        w.close()


def test_catalog_manual_copies_in_browse_mode(tmp_path, monkeypatch):
    w = _window(tmp_path, monkeypatch)
    dlg = CatalogDialog(w.project.profile_id, w, select_mode=False)
    try:
        with monkeypatch.context() as m:
            from PySide6.QtWidgets import QInputDialog

            m.setattr(QInputDialog, "getText", lambda *a, **k: ("minecraft:iron_ingot", True))
            dlg._manual()
        assert dlg.selected_id == "minecraft:iron_ingot"
        assert QApplication.clipboard().text() == "minecraft:iron_ingot"
    finally:
        dlg.deleteLater()
        w.dirty = False
        w.close()


def test_sidebar_hidden_keeps_inspector_available(tmp_path, monkeypatch):
    w = _window(tmp_path, monkeypatch)
    try:
        w.resize(1440, 900)
        w._show_center_tab(1)
        w._toggle_inspector()
        assert w.inspector.isVisible()
        w._toggle_sidebar()
        assert w.details_btn.isEnabled()
        assert w.inspector.isVisible()
        w._toggle_sidebar()
    finally:
        w.dirty = False
        w.close()


def test_save_as_has_window_shortcut(tmp_path, monkeypatch):
    w = _window(tmp_path, monkeypatch)
    try:
        assert w.act_save_as in w.actions()
        assert w.act_save_as.shortcut().toString()
    finally:
        w.dirty = False
        w.close()


def test_reveal_session_uses_folder_fallback(tmp_path, monkeypatch):
    w = _window(tmp_path, monkeypatch)
    session = tmp_path / "a.sfmproj"
    session.write_text("{}", encoding="utf-8")
    opened: list[str] = []
    monkeypatch.setattr("sfm_workshop.ui.main_window.QDesktopServices.openUrl", lambda _u: False)
    monkeypatch.setattr("sfm_workshop.ui.main_window.os.startfile", lambda p: opened.append(p), raising=False)
    try:
        w._reveal_session(str(session))
        assert opened and Path(opened[0]) == session.parent
    finally:
        w.dirty = False
        w.close()
