"""Application entry point."""
from __future__ import annotations

import sys

from PySide6.QtCore import Qt, QTimer, qInstallMessageHandler
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from .core import crashlog
from .ui.dialogs import CrashReportDialog
from .ui.main_window import MainWindow
from .ui.theme import ensure_fonts, ui_font


def run() -> int:
    if "--self-test" in sys.argv:
        from .self_test import run as self_test

        return self_test()
    # Install before QApplication/MainWindow: log the startup itself, and keep
    # faulthandler alive for native faults.
    previous_crash = crashlog.install()
    app = QApplication(sys.argv)
    qInstallMessageHandler(crashlog.qt_message_handler)
    app.setApplicationName("SFM代码生成工坊")
    app.setOrganizationName("SFMCodeWorkshop")
    app.setApplicationDisplayName("SFM代码生成工坊")
    app.setStyle("Fusion")
    app.aboutToQuit.connect(crashlog.mark_clean_exit)
    try:
        from .core.storage import resource_root

        icon = resource_root() / "icon.png"
        if icon.exists():
            app.setWindowIcon(QIcon(str(icon)))
    except Exception:
        pass
    ensure_fonts()
    app.setFont(ui_font(11))
    win = MainWindow()
    win.show()
    if previous_crash is not None:
        def show_crash_report() -> None:
            dlg = CrashReportDialog(previous_crash, win)
            dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
            dlg.exec()

        QTimer.singleShot(350, show_crash_report)
    return app.exec()
