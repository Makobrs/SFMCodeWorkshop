"""Regression tests for the three desktop-QA defects.

The tests are deliberately headless: opening a real Explorer window is
external side effect, so the fallback path is asserted at the shell call.
"""
from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox

from sfm_workshop.ui.main_window import MainWindow


def _app():
    return QApplication.instance() or QApplication([])


def _window(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    _app()
    w = MainWindow()
    w._autosave_candidate = None
    w._autosave_timer.stop()
    return w


def test_center_tabs_click_switch_stack(tmp_path, monkeypatch):
    w = _window(tmp_path, monkeypatch)
    try:
        w.tab_rules.click()
        assert w.center_tabs.checkedId() == 1
        assert w.center_stack.currentIndex() == 1
        w.tab_graph.click()
        assert w.center_tabs.checkedId() == 2
        assert w.center_stack.currentIndex() == 2
        w.tab_overview.click()
        assert w.center_tabs.checkedId() == 0
        assert w.center_stack.currentIndex() == 0
    finally:
        w.dirty = False
        w.close()


def test_open_logs_uses_startfile_fallback(tmp_path, monkeypatch):
    w = _window(tmp_path, monkeypatch)
    opened: list[str] = []
    monkeypatch.setattr(
        "sfm_workshop.ui.main_window.QDesktopServices.openUrl",
        lambda _url: False,
    )
    monkeypatch.setattr(
        "sfm_workshop.ui.main_window.os.startfile",
        lambda path: opened.append(path),
        raising=False,
    )
    try:
        w._open_logs()
        assert opened
        assert Path(opened[0]).is_dir()
        assert Path(opened[0]).name == "logs"
    finally:
        w.dirty = False
        w.close()


def test_open_recycle_creates_folder_and_uses_fallback(tmp_path, monkeypatch):
    w = _window(tmp_path, monkeypatch)
    opened: list[str] = []
    monkeypatch.setattr(
        "sfm_workshop.ui.main_window.QDesktopServices.openUrl",
        lambda _url: False,
    )
    monkeypatch.setattr(
        "sfm_workshop.ui.main_window.os.startfile",
        lambda path: opened.append(path),
        raising=False,
    )
    try:
        w._open_recycle_folder()
        assert opened
        assert Path(opened[0]).is_dir()
        assert Path(opened[0]).name == "sessions"
    finally:
        w.dirty = False
        w.close()


def test_open_folder_warns_only_when_both_strategies_fail(tmp_path, monkeypatch):
    w = _window(tmp_path, monkeypatch)
    warnings: list[str] = []
    monkeypatch.setattr(
        "sfm_workshop.ui.main_window.QDesktopServices.openUrl",
        lambda _url: False,
    )
    monkeypatch.setattr(
        "sfm_workshop.ui.main_window.os.startfile",
        lambda _path: (_ for _ in ()).throw(OSError("shell unavailable")),
        raising=False,
    )
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda _parent, _title, text: warnings.append(text),
    )
    try:
        w._open_logs()
        assert warnings and "logs" in warnings[0]
    finally:
        w.dirty = False
        w.close()
