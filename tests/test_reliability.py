"""Regression tests for crash logging, session safety and AI result gating."""
from __future__ import annotations

import json
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from sfm_workshop.core.model import new_blank_project
from sfm_workshop.core.storage import load_project, save_project


def _app():
    return QApplication.instance() or QApplication([])


def test_crash_marker_and_log_paths(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    import sfm_workshop.core.storage as storage

    storage._USER_ROOT_CACHE = None
    storage._USER_ROOT_KEY = None
    from sfm_workshop.core import crashlog

    crashlog._installed = False
    crashlog._current = None
    crashlog._crash_recorded = False
    info = crashlog.install()
    assert info is None
    assert crashlog.marker_path().is_file()
    assert crashlog.runtime_log_path().is_file()
    assert crashlog.faulthandler_log_path().is_file()
    crashlog.log_event("reliability probe")
    crashlog.mark_clean_exit()
    assert not crashlog.marker_path().exists()


def test_stale_crash_marker_is_reported(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    import sfm_workshop.core.storage as storage

    storage._USER_ROOT_CACHE = None
    storage._USER_ROOT_KEY = None
    from sfm_workshop.core import crashlog

    crashlog._installed = True
    crashlog._current = None
    crashlog._crash_recorded = False
    crashlog.logs_dir().mkdir(parents=True, exist_ok=True)
    crashlog.marker_path().write_text(
        json.dumps({"pid": 999999, "started": "2026-01-01T00:00:00"}),
        encoding="utf-8",
    )
    previous, unclean = crashlog._read_previous()
    assert unclean and previous is not None
    # A malformed marker is still evidence of an unclean exit.
    crashlog.marker_path().write_text("{not json", encoding="utf-8")
    _, malformed = crashlog._read_previous()
    assert malformed is True
    crashlog.mark_clean_exit()


def test_save_as_appends_extension_instead_of_replacing(tmp_path):
    path = save_project(new_blank_project("A", "1.21.1-neoforge"), tmp_path / "factory.v2")
    assert path.name == "factory.v2.sfmproj"
    assert path.is_file()
    assert load_project(path).name == "A"


def test_project_with_utf8_bom_is_loadable(tmp_path):
    p = new_blank_project("BOM", "1.21.1-neoforge")
    path = tmp_path / "bom.sfmproj"
    save_project(p, path)
    path.write_text("\ufeff" + path.read_text(encoding="utf-8"), encoding="utf-8")
    assert load_project(path).name == "BOM"


def test_unavailable_workspace_is_not_forgotten(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    from sfm_workshop.core import workspaces
    from sfm_workshop.core.storage import user_root

    # Keep the module-level user root from a previous test out of the way.
    import sfm_workshop.core.storage as storage

    storage._USER_ROOT_CACHE = None
    storage._USER_ROOT_KEY = None
    available = tmp_path / "available"
    missing = tmp_path / "missing"
    available.mkdir()
    missing.mkdir()
    workspaces.save_workspaces(
        [
            workspaces.Workspace("a", "A", str(available)),
            workspaces.Workspace("b", "B", str(missing)),
        ]
    )
    missing.rmdir()
    loaded = workspaces.load_workspaces()
    assert {w.name for w in loaded} == {"A", "B"}
    assert next(w for w in loaded if w.name == "B").available is False
    workspaces.add_workspace(available)
    assert {w.name for w in workspaces.load_workspaces()} == {"A", "B"}


def test_new_task_cancel_does_not_mutate_project(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    import sfm_workshop.ui.main_window as mw

    _app()
    w = mw.MainWindow()
    w._autosave_candidate = None
    before = [t.id for t in w.project.tasks]
    undo_before = len(w._undo)

    def cancel(self):
        return 0

    monkeypatch.setattr(mw.TaskEditorDialog, "exec", cancel)
    w._new_task()
    assert [t.id for t in w.project.tasks] == before
    assert len(w._undo) == undo_before
    w._autosave_timer.stop()
    w.dirty = False
    w.close()


def test_ai_truncated_result_cannot_be_copied(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    from sfm_workshop.services.ai import AIResult, PromptManager
    from sfm_workshop.ui.dialogs import AIDialog
    from sfm_workshop.ui.main_window import MainWindow

    _app()
    w = MainWindow()
    w._autosave_candidate = None
    d = AIDialog(w.project, w.settings, PromptManager(), w)
    d._on_result(
        AIResult(
            code='sfm_version = "1"\n',
            raw="partial",
            status="truncated",
            error="finish_reason=length",
        )
    )
    assert d.copy_btn.isEnabled() is False
    assert d.save_btn.isEnabled() is False
    assert d.ai_status._state == "error"
    w._autosave_timer.stop()
    w.dirty = False
    w.close()


def test_session_context_menu_defers_action_until_exec_returns(tmp_path):
    from sfm_workshop.ui.widgets import SessionRow

    _app()
    row = SessionRow("Demo", str(tmp_path / "demo.sfmproj"), "刚刚", workspace_path=str(tmp_path))
    opened: list[str] = []
    row.openRequested.connect(opened.append)
    menu = row._build_menu()
    menu.actions()[0].trigger()
    assert row._menu_choice == "open"
    assert opened == []
    # The real contextMenuEvent emits only after menu.exec() has returned.
    row.openRequested.emit(row.path)
    assert opened == [row.path]
    menu.close()
    menu.deleteLater()
    row.deleteLater()
    _app().processEvents()


def test_deleting_current_session_does_not_resurrect_it(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from sfm_workshop.core.workspaces import add_workspace
    from sfm_workshop.ui.main_window import MainWindow

    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    _app()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    a = workspace / "A.sfmproj"
    b = workspace / "B.sfmproj"
    save_project(new_blank_project("A", "1.21.1-neoforge"), a)
    save_project(new_blank_project("B", "1.21.1-neoforge"), b)
    add_workspace(workspace)
    monkeypatch.setattr(
        QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Yes
    )
    w = MainWindow()
    w._autosave_candidate = None
    w._set_project(load_project(a), a)
    w._refresh_sidebar()
    w.dirty = False
    w._delete_session(str(a), str(workspace))
    assert not a.exists()
    assert w.project_path is not None and Path(w.project_path).resolve() == b.resolve()
    # Saving the replacement must not recreate the deleted path.
    w._save_project()
    assert not a.exists()
    assert b.exists()
    w._autosave_timer.stop()
    w.dirty = False
    w.close()

