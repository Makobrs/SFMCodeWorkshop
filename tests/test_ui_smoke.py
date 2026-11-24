import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox

from sfm_workshop.services.ai import AIResult, PromptManager
from sfm_workshop.ui.dialogs import AIDialog, CatalogDialog, LabelLibraryDialog
from sfm_workshop.ui.main_window import MainWindow


def _app():
    return QApplication.instance() or QApplication([])


def test_main_window_undo_and_redo(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    _app()
    w = MainWindow()
    w._autosave_candidate = None
    before = len(w.project.active_task().batches[0].sends)
    w._add_send()
    assert len(w.project.active_task().batches[0].sends) == before + 1
    w._undo_action()
    assert len(w.project.active_task().batches[0].sends) == before
    w._redo_action()
    assert len(w.project.active_task().batches[0].sends) == before + 1
    w._autosave_timer.stop()
    w.dirty = False
    w.close()


def test_ai_candidate_requires_local_l0(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    _app()
    w = MainWindow()
    w._autosave_candidate = None
    d = AIDialog(w.project, w.settings, PromptManager(), w)
    d._on_result(AIResult(code="hello world", raw="hello world", status="invalid_sfml", error="syntax"))
    assert d.copy_btn.isEnabled() is False
    assert d.save_btn.isEnabled() is False
    assert "L0/L1" in d.review.text()
    w._autosave_timer.stop()
    w.dirty = False
    w.close()


def test_face_names_and_filters_are_localized():
    from sfm_workshop.core.model import SIDES

    assert {"上面", "下面", "左面", "右面", "东面", "西面", "南面", "北面"} <= set(SIDES)


def test_catalog_supports_chinese_pinyin_initials_and_copy(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    _app()
    w = MainWindow()
    w._autosave_candidate = None
    d = CatalogDialog(w.project.profile_id, w, select_mode=False)
    d.search.setText("td")
    d._refresh()
    assert d.list.count() > 0
    ids = {d.list.item(i).data(256) for i in range(d.list.count())}
    assert "minecraft:iron_ingot" in ids
    d._copy_command()
    assert "/sfm export_info false" == d.copy_btn.text()
    assert QApplication.clipboard().text() == "/sfm export_info false"
    w._autosave_timer.stop()
    w.dirty = False
    w.close()


def test_label_picker_returns_clicked_label(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    _app()
    w = MainWindow()
    w._autosave_candidate = None
    d = LabelLibraryDialog(w.project, w, select_mode=True)
    d.list.setCurrentRow(0)
    d._accept()
    assert d.selected_name
    w._autosave_timer.stop()
    w.dirty = False
    w.close()


def test_task_editor_supports_multiple_batches(tmp_path, monkeypatch):
    from sfm_workshop.ui.dialogs import TaskEditorDialog

    monkeypatch.setenv("APPDATA", str(tmp_path))
    _app()
    w = MainWindow()
    w._autosave_candidate = None
    task = w.project.active_task()
    assert len(task.batches) == 1
    d = TaskEditorDialog(w.project, task, w)
    d._add_batch()
    d.source.setCurrentText("煤炭箱")
    d._send_rows[0].target.setCurrentText("熔炉")
    d._accept()
    assert len(task.batches) == 2
    assert task.batches[1].take.source == "煤炭箱"
    w._autosave_timer.stop()
    w.dirty = False
    w.close()


def test_new_session_is_a_file_inside_workspace(tmp_path, monkeypatch):
    from sfm_workshop.core.workspaces import add_workspace
    from sfm_workshop.ui.widgets import SessionRow, WorkspaceRow

    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    _app()
    w = MainWindow()
    w._autosave_candidate = None
    workspace = tmp_path / "Workspace"
    workspace.mkdir()
    add_workspace(workspace)
    w._refresh_sidebar()
    w._create_session_in_workspace(str(workspace))
    assert w.project_path is not None
    assert w.project_path.parent == workspace.resolve()
    assert len(list(workspace.glob("*.sfmproj"))) == 1
    app = _app()
    app.processEvents()
    assert w.sidebar.findChildren(WorkspaceRow)
    assert w.sidebar.findChildren(SessionRow)
    w._autosave_timer.stop()
    w.dirty = False
    w.close()


def test_plus_click_with_dirty_current_does_not_block(tmp_path, monkeypatch):
    from sfm_workshop.core.workspaces import add_workspace
    from sfm_workshop.ui.widgets import WorkspaceRow

    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    _app()
    workspace = tmp_path / "Workspace"
    workspace.mkdir()
    add_workspace(workspace)
    w = MainWindow()
    w._autosave_candidate = None
    w._refresh_sidebar()
    w.dirty = True
    rows = [
        row for row in w.sidebar.findChildren(WorkspaceRow)
        if row.path and Path(row.path).resolve() == workspace.resolve()
    ]
    assert rows
    rows[0].plus.click()
    app = _app()
    app.processEvents()
    app.processEvents()
    assert w.project_path is not None
    assert w.project_path.parent == workspace.resolve()
    assert len(list(workspace.glob("*.sfmproj"))) == 1
    # The previous dirty session was persisted as its own default-workspace file.
    assert w.settings.last_project == str(w.project_path)
    w._autosave_timer.stop()
    w.dirty = False
    w.close()


def test_new_rule_button_has_no_duplicate_plus_text(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    _app()
    w = MainWindow()
    w._autosave_candidate = None
    assert w.add_rule.text() == "新建规则"
    assert bool(w.add_rule.property("iconTextCentered"))
    w._autosave_timer.stop()
    w.dirty = False
    w.close()


def test_clicking_session_switches_without_reordering(tmp_path, monkeypatch):
    from sfm_workshop.core.model import new_blank_project
    from sfm_workshop.core.storage import save_project
    from sfm_workshop.core.workspaces import add_workspace
    from sfm_workshop.ui.widgets import SessionRow

    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    _app()
    workspace = tmp_path / "Workspace"
    workspace.mkdir()
    add_workspace(workspace)
    newer = new_blank_project("Newer", "1.21.1-neoforge")
    older = new_blank_project("Older", "1.21.1-neoforge")
    newer_path = workspace / "newer.sfmproj"
    older_path = workspace / "older.sfmproj"
    save_project(older, older_path)
    save_project(newer, newer_path)
    w = MainWindow()
    w._autosave_candidate = None
    w._set_project(newer, newer_path)
    w._refresh_sidebar()
    app = _app()
    app.processEvents()
    before = [(r.name.text(), r.path) for r in w.sidebar.findChildren(SessionRow)]
    assert len(before) >= 2
    target = next(row for row in w.sidebar.findChildren(SessionRow) if Path(row.path).resolve() == older_path.resolve())
    target.clicked.emit(target.path)
    app.processEvents()
    assert w.project_path is not None
    assert w.project_path.resolve() == older_path.resolve()
    after = [(r.name.text(), r.path) for r in w.sidebar.findChildren(SessionRow)]
    assert after == before
    w._autosave_timer.stop()
    w.dirty = False
    w.close()


def test_top_new_session_creates_in_default_workspace(tmp_path, monkeypatch):
    from sfm_workshop.core.storage import projects_dir
    from PySide6.QtWidgets import QPushButton

    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    _app()
    w = MainWindow()
    w._autosave_candidate = None
    button = next(
        b for b in w.sidebar.findChildren(QPushButton) if "新建会话" in b.text()
    )
    button.click()
    app = _app()
    app.processEvents()
    app.processEvents()
    assert w.project_path is not None
    assert w.project_path.parent.resolve() == projects_dir().resolve()
    assert w.project_path.is_file()
    w._autosave_timer.stop()
    w.dirty = False
    w.close()


def test_session_order_drag_persists(tmp_path, monkeypatch):
    from sfm_workshop.core.model import new_blank_project
    from sfm_workshop.core.storage import save_project
    from sfm_workshop.core.workspaces import add_workspace, group_projects
    from sfm_workshop.ui.widgets import SessionRow

    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    _app()
    workspace = tmp_path / "Workspace"
    workspace.mkdir()
    add_workspace(workspace)
    a = workspace / "a.sfmproj"
    b = workspace / "b.sfmproj"
    save_project(new_blank_project("A", "1.21.1-neoforge"), a)
    save_project(new_blank_project("B", "1.21.1-neoforge"), b)
    w = MainWindow()
    w._autosave_candidate = None
    w._set_project(new_blank_project("A", "1.21.1-neoforge"), a)
    w._refresh_sidebar()
    app = _app()
    app.processEvents()
    rows = w.sidebar.findChildren(SessionRow)
    assert len(rows) >= 2
    # Drop A before B; this is the reverse of the initial newest-first order.
    rows[0].dropRequested.emit(str(a), str(b), False)
    # In the real widget this is emitted after QDrag.exec() returns. The
    # refresh must happen outside the drag/drop event loop.
    rows[0].dragFinished.emit()
    app.processEvents()
    groups = group_projects(
        __import__("sfm_workshop.core.storage", fromlist=["load_recent"]).load_recent()
    )
    target = next(g for g in groups if g["path"] == str(workspace.resolve()))
    names = [p["name"] for p in target["projects"]]
    assert names == ["A", "B"]
    w._autosave_timer.stop()
    w.dirty = False
    w.close()


def test_delete_session_moves_to_app_recycle(tmp_path, monkeypatch):
    from sfm_workshop.core.model import new_blank_project
    from sfm_workshop.core.storage import save_project
    from sfm_workshop.core.workspaces import add_workspace, recycle_sessions_dir

    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    _app()
    workspace = tmp_path / "Workspace"
    workspace.mkdir()
    add_workspace(workspace)
    path = workspace / "delete-me.sfmproj"
    save_project(new_blank_project("Delete Me", "1.21.1-neoforge"), path)
    w = MainWindow()
    w._autosave_candidate = None
    w._refresh_sidebar()
    monkeypatch.setattr(
        QMessageBox, "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )
    w._delete_session(str(path), str(workspace))
    assert not path.exists()
    recycled = list(recycle_sessions_dir().glob("*.sfmproj"))
    assert recycled and recycled[0].name == "delete-me.sfmproj"
    w._autosave_timer.stop()
    w.dirty = False
    w.close()


def test_template_dialog_has_import_export_and_name_edit_hint(tmp_path, monkeypatch):
    from sfm_workshop.ui.dialogs import TemplateDialog

    monkeypatch.setenv("APPDATA", str(tmp_path))
    _app()
    w = MainWindow()
    w._autosave_candidate = None
    d = TemplateDialog(w, w.project)
    labels = [b.text() for b in d.findChildren(__import__("PySide6.QtWidgets", fromlist=["QPushButton"]).QPushButton)]
    assert "导入模板" in labels
    assert "导出模板" in labels
    assert "载入模板" in labels
    assert not w.project_edit_hint.pixmap().isNull()
    d.close()
    w._autosave_timer.stop()
    w.dirty = False
    w.close()


def test_recycle_entry_opens_recycle_folder(tmp_path, monkeypatch):
    from PySide6.QtGui import QDesktopServices
    from sfm_workshop.core.workspaces import recycle_sessions_dir

    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    _app()
    w = MainWindow()
    w._autosave_candidate = None
    opened = []
    monkeypatch.setattr(
        QDesktopServices, "openUrl",
        lambda url: opened.append(url.toLocalFile()) or True,
    )
    assert not w.sidebar.recycle_btn.isHidden()
    w.sidebar.recycle_btn.click()
    assert opened
    assert Path(opened[0]).resolve() == recycle_sessions_dir().resolve()
    w._autosave_timer.stop()
    w.dirty = False
    w.close()


def test_toast_second_message_stays_visible(tmp_path, monkeypatch):
    from PySide6.QtTest import QTest
    from sfm_workshop.ui.widgets import Toast

    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    _app()
    w = MainWindow()
    w._autosave_candidate = None
    w.show()
    t = Toast(w)
    t.show_message("first", 80)
    QTest.qWait(250)
    t.show_message("second", 1000)
    QTest.qWait(450)
    assert t.isVisible()
    assert t.reveal == 1.0
    t.hide()
    w._autosave_timer.stop()
    w.dirty = False
    w.close()


def test_template_browse_does_not_create_session_files(tmp_path, monkeypatch):
    from sfm_workshop.core.storage import projects_dir

    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    _app()
    w = MainWindow()
    w._autosave_candidate = None
    before = set(projects_dir().glob("*.sfmproj"))
    for _ in range(3):
        assert w._load_template_key("furnace")
    after = set(projects_dir().glob("*.sfmproj"))
    assert after == before
    w._autosave_timer.stop()
    w.dirty = False
    w.close()


def test_edge_sweep_does_not_park_a_border_at_end(tmp_path, monkeypatch):
    from PySide6.QtGui import QColor
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QWidget
    from sfm_workshop.ui.widgets import CutButton

    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    _app()
    host = QWidget()
    host.setStyleSheet("background: #F3F1EA;")
    button = CutButton("终点", "primary", True, host)
    button.resize(130, 30)
    button.show()
    host.show()
    QTest.qWait(20)
    button._set_edge(0.0)
    QTest.qWait(20)
    base = button.grab().toImage()
    button._set_edge(1.0)
    QTest.qWait(20)
    end = button.grab().toImage()
    # At the end of the sweep the highlight is fully faded; it must not
    # leave an extra black/white strip on the right edge.
    edge_px = QColor(base.pixelColor(base.width() - 2, base.height() // 2))
    end_px = QColor(end.pixelColor(end.width() - 2, end.height() // 2))
    assert end_px == edge_px
    # Exit must clear immediately rather than parking the bar.
    button._animate_hover(True)
    QTest.qWait(350)
    button._animate_hover(False)
    button._set_edge(0.0)
    QTest.qWait(20)
    # Sample both vertical edges after exit; the paint must be identical to
    # the no-sweep state (text/hover styling is not involved here).
    after = button.grab().toImage()
    for x in (0, after.width() - 1):
        for y in (5, after.height() // 2, after.height() - 6):
            assert after.pixelColor(x, y) == base.pixelColor(x, y)
    host.close()


def test_ai_status_bar_phases_and_task_editor_sections(tmp_path, monkeypatch):
    from sfm_workshop.core.templates import load_template
    from sfm_workshop.services.ai import PromptManager
    from sfm_workshop.ui.dialogs import AIDialog, AIStatusBar, TaskEditorDialog

    monkeypatch.setenv("APPDATA", str(tmp_path))
    _app()
    w = MainWindow()
    w._autosave_candidate = None
    bar = AIStatusBar()
    bar.set_state("running", "正在请求")
    assert bar._active == 0
    bar.set_state("review", "本地校验")
    assert bar._completed == 2 and bar._active == 2
    bar.set_state("done", "完成")
    assert bar._completed == 3 and bar._active == -1
    bar._timer.stop()
    project = load_template("furnace", "1.21.1-neoforge")
    ai = AIDialog(w.project, w.settings, PromptManager(), w)
    assert ai.ai_status is not None
    ai.close()
    editor = TaskEditorDialog(w.project, project.tasks[0], w)
    sections = editor.findChildren(__import__("PySide6.QtWidgets", fromlist=["QLabel"]).QLabel)
    assert any(label.text().startswith("触发器") for label in sections)
    editor.close()
    w._autosave_timer.stop()
    w.dirty = False
    w.close()


def test_session_context_menu_has_open_rename_reveal_and_delete(tmp_path):
    from sfm_workshop.ui.widgets import SessionRow

    _app()
    row = SessionRow("Demo", str(tmp_path / "demo.sfmproj"), "刚刚", workspace_path=str(tmp_path))
    menu = row._build_menu()
    assert [a.text() for a in menu.actions() if not a.isSeparator()] == [
        "打开", "重命名", "在文件夹中显示", "删除"
    ]
    menu.deleteLater()
