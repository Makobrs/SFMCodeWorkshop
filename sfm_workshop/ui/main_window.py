"""Main window and application wiring."""
from __future__ import annotations

from datetime import datetime
from collections import deque
import copy
import os
from pathlib import Path
import sys
from typing import Any

from PySide6.QtCore import QDateTime, QPoint, QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QFont, QFontMetrics, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QFrame,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)

from ..core import crashlog
from ..core.model import (
    PROFILES,
    Project,
    SCHEMA_VERSION,
    Task,
    new_blank_project,
    new_default_project,
    new_id,
    project_from_json,
    project_to_json,
    unique_name,
)
from .command_palette import Command, CommandPaletteDialog
from .inspector import TaskInspector
from .overview import OverviewPage
from ..core.storage import (
    AppSettings,
    autosave,
    autosave_path,
    ensure_dirs,
    export_sfml,
    load_autosave,
    load_project,
    load_recent,
    load_settings,
    projects_dir,
    save_project,
    save_settings,
)
from . import theme as theme_mod
from .dialogs import (
    AIDialog,
    AboutDialog,
    CatalogDialog,
    LabelDialog,
    LabelLibraryDialog,
    SettingsDialog,
    TaskEditorDialog,
    TemplateDialog,
)
from .graph import GraphPanel
from .icons import icon as svg_icon, theme_icon
from .theme import Theme, apply_theme, ui_font
from .widgets import (
    CodeView,
    CommandBar,
    CutButton,
    DSHSidebar,
    EfficiencyPanel,
    InlineStatus,
    IssueList,
    IssueView,
    RuleCard,
    SectionHeader,
    Toast,
)


class FileMenuItem(QFrame):
    """One file-menu row with an explicit icon -> label -> shortcut rhythm.

    A plain QMenu lets the platform style reserve a wide icon cell; that made
    the icons sit near the border instead of next to their labels. This row is
    local to the file menu and leaves all other menus untouched.
    """

    def __init__(self, action: QAction, menu: QMenu, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.action = action
        self.menu = menu
        self.setObjectName("FileMenuItem")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(30)
        self.setMinimumWidth(238)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setToolTip(action.toolTip() or action.text())
        t = theme_mod.current()
        self.setStyleSheet(
            f"QWidget#FileMenuItem {{ background: transparent; }}"
            f"QWidget#FileMenuItem:hover {{ background: {t.chip}; }}"
            f"QLabel#FileMenuText {{ color: {t.ink}; background: transparent; }}"
            f"QLabel#FileMenuShortcut {{ color: {t.ink2}; background: transparent; }}"
        )
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 0, 18, 0)
        lay.setSpacing(8)
        icon = QLabel()
        icon.setFixedSize(15, 15)
        icon.setPixmap(action.icon().pixmap(15, 15))
        lay.addWidget(icon, 0, Qt.AlignmentFlag.AlignVCenter)
        text = QLabel(action.text().replace("&", ""))
        text.setObjectName("FileMenuText")
        text.setFont(ui_font(10))
        lay.addWidget(text, 1, Qt.AlignmentFlag.AlignVCenter)
        shortcut = action.shortcut().toString(QKeySequence.SequenceFormat.NativeText)
        if shortcut:
            sc = QLabel(shortcut)
            sc.setObjectName("FileMenuShortcut")
            sc.setFont(ui_font(9))
            sc.setMinimumWidth(52)
            sc.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            lay.addWidget(sc, 0, Qt.AlignmentFlag.AlignVCenter)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self.action.isEnabled():
            self.menu.close()
            self.action.trigger()
        super().mouseReleaseEvent(event)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("SFM代码生成工坊")
        self.setMinimumSize(1180, 760)
        self.resize(1440, 900)
        self.settings = load_settings()
        from . import motion

        motion.set_reduced(bool(getattr(self.settings, "reduced_motion", False)))
        self._storage_error = ""
        self._sidebar_open = True
        try:
            ensure_dirs()
        except Exception as exc:
            self._storage_error = str(exc)
        self._autosave_candidate: Project | None = None
        self.project: Project = self._initial_project()
        self.project_path: Path | None = None
        self.dirty = False
        self.filter_label: str | None = None
        self.code = ""
        self.validation: Any = None
        self.estimate: Any = None
        self._last_autosave: str = ""
        self._autosave_error: str = ""
        self._toast: Toast | None = None
        self._undo: list[str] = []
        self._redo: list[str] = []
        self._restoring = False
        self._sidebar_cache_key: tuple | None = None
        self._sidebar_cache: list[dict] = []
        self.activity: deque[tuple[str, str, str]] = deque(maxlen=8)
        self._focus_mode = False

        self._build_ui()
        self._apply_responsive_layout()
        self._autosave_timer = QTimer(self)
        self._autosave_timer.setSingleShot(True)
        self._autosave_timer.timeout.connect(self._autosave_now)
        self._apply_theme(rebuild=False)
        self._refresh_all()
        self._toast = Toast(self.centralWidget())
        self._toast.hide()
        self._update_history_actions()
        self._record_activity("载入工作台", f"{self.project.name} · {len(self.project.tasks)} 条规则", "OPEN")
        if self._storage_error:
            QTimer.singleShot(150, self._show_storage_warning)
        if getattr(self, "_project_load_error", ""):
            crashlog.log_event(f"last project load failed: {self._project_load_error}")
            QTimer.singleShot(350, self._show_project_load_warning)
        QTimer.singleShot(200, self._maybe_recover_autosave)

    # ------------------------------------------------------------------
    # setup
    # ------------------------------------------------------------------
    def _initial_project(self) -> Project:
        last_path: Path | None = None
        p: Project | None = None
        self._project_load_error = ""
        try:
            last = getattr(self.settings, "last_project", "")
            if last and Path(last).exists():
                last_path = Path(last)
                try:
                    p = load_project(last_path)
                except Exception as exc:
                    self._project_load_error = f"{last_path}\n{exc}"
                    p = None
        except Exception:
            p = None
        if p is None:
            try:
                from ..core.templates import load_template

                p = load_template("furnace", self.settings.profile_id)
                self._add_starter_tasks(p)
            except Exception:
                p = new_default_project()
                self._add_starter_tasks(p)
        # A newer autosave is offered as a recovery draft, never silently applied.
        try:
            auto = load_autosave()
            auto_path = autosave_path()
            if auto is not None and auto_path.exists():
                if last_path is None or auto_path.stat().st_mtime > last_path.stat().st_mtime + 2:
                    self._autosave_candidate = auto
        except Exception:
            pass
        return p

    def _maybe_recover_autosave(self) -> None:
        if self._autosave_candidate is None:
            return
        ret = QMessageBox.question(
            self,
            "发现自动保存草稿",
            "检测到比上次保存更新的自动保存草稿。\n恢复草稿？（不会覆盖原工程文件）",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if ret == QMessageBox.StandardButton.Yes:
            self.project = self._autosave_candidate
            self.project_path = None
            self.dirty = True
            self._refresh_all()
            self._toast_msg("已恢复自动保存草稿；保存前请另存")
        self._autosave_candidate = None

    def _show_storage_warning(self) -> None:
        QMessageBox.warning(
            self,
            "数据目录不可写",
            "应用数据目录不可写，工程可能无法保存。\n"
            "请把程序放到可写目录，或检查 Documents/AppData 权限。\n\n"
            f"{self._storage_error}",
        )

    def _show_project_load_warning(self) -> None:
        QMessageBox.warning(
            self,
            "上次工程未能打开",
            "上次打开的工程读取失败，已暂时载入内置模板。\n"
            "原文件没有被覆盖；请用「文件 > 打开工程」重试，或检查文件是否损坏。\n\n"
            f"{self._project_load_error}",
        )

    def _add_starter_tasks(self, p: Project) -> None:
        """First-run demo: three readable cards, all using existing labels."""
        if len(p.tasks) >= 3:
            return
        from ..core.model import Batch, Send, Take, Task

        labels = p.label_names()
        if not labels:
            return

        def pick(*needles: str) -> str:
            for needle in needles:
                for name in labels:
                    if needle in name:
                        return name
            return labels[0]

        source = pick("原料")
        fuel = pick("煤", "燃料")
        machine = pick("熔炉", "机器")
        output = pick("成品", "收集")
        if not any(t.name == "燃料补给" for t in p.tasks) and fuel != source:
            t = Task(name="燃料补给")
            t.batches[0] = Batch(
                take=Take(source=fuel, side="默认面", quantity=1),
                sends=[Send(target=machine, side="底面", retain=1)],
                clear=True,
            )
            p.tasks.append(t)
        if not any(t.name == "成品输出" for t in p.tasks) and machine != output:
            t = Task(name="成品输出")
            t.batches[0] = Batch(
                take=Take(source=machine, side="底面"),
                sends=[Send(target=output, side="默认面")],
                clear=True,
            )
            p.tasks.append(t)
        p.active_task_id = p.tasks[0].id if p.tasks else None

    def _build_ui(self) -> None:
        central = QWidget()
        central.setObjectName("Root")
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.command = CommandBar()
        self.command.themeToggled.connect(self._toggle_theme)
        self.command.profileChanged.connect(self._change_profile)
        self.command.checkRequested.connect(self._check)
        self.command.copyRequested.connect(self._copy)
        self.command.aiRequested.connect(self._open_ai)
        self.command.settingsRequested.connect(self._open_settings)
        self.command.fileRequested.connect(self._file_menu)
        self.command.paletteRequested.connect(self._open_command_palette)
        self.command.sidebarToggleRequested.connect(self._toggle_sidebar)
        root.addWidget(self.command)

        body = QWidget()
        body_lay = QHBoxLayout(body)
        body_lay.setContentsMargins(0, 0, 0, 0)
        body_lay.setSpacing(0)
        root.addWidget(body, 1)

        self.sidebar = DSHSidebar()
        self.sidebar.setFixedWidth(248)
        self.sidebar.templateRequested.connect(self._open_templates)
        self.sidebar.newSessionRequested.connect(self._new_session_default)
        self.sidebar.openProjectRequested.connect(self._open_project)
        self.sidebar.recentRequested.connect(self._open_recent)
        self.sidebar.workspaceAddRequested.connect(self._add_workspace)
        self.sidebar.sessionCreateRequested.connect(self._create_session_in_workspace)
        self.sidebar.sessionDeleteRequested.connect(self._delete_session)
        self.sidebar.sessionOpenRequested.connect(self._open_recent)
        self.sidebar.sessionRenameRequested.connect(self._rename_session)
        self.sidebar.sessionRevealRequested.connect(self._reveal_session)
        self.sidebar.sessionOrderChanged.connect(self._save_session_order)
        self.sidebar.recycleRequested.connect(self._open_recycle_folder)
        body_lay.addWidget(self.sidebar)
        body_lay.addWidget(self._vline())

        center = QWidget()
        center.setMinimumWidth(560)
        center.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        center_lay = QVBoxLayout(center)
        center_lay.setContentsMargins(0, 0, 0, 0)
        center_lay.setSpacing(0)
        body_lay.addWidget(center, 1)

        self.center_head = QWidget()
        ch = QHBoxLayout(self.center_head)
        ch.setContentsMargins(16, 8, 16, 3)
        ch.setSpacing(8)
        self.center_header = SectionHeader("// RULES", "规则")
        self.center_header.set_meta("")
        self.center_header.title.setText("工作台")
        self.center_header.eyebrow.setText("// WORKBENCH")
        ch.addWidget(self.center_header, 1)
        self.filter_btn = CutButton("× 清除筛选", "ghost", True)
        self.filter_btn.clicked.connect(self._clear_filter)
        self.filter_btn.hide()
        ch.addWidget(self.filter_btn)
        self.details_btn = CutButton("详情", "ghost", True)
        self.details_btn.setIcon(theme_icon("panel-right", muted=False, size=13))
        self.details_btn.setToolTip("显示/隐藏任务详情（规则页）")
        self.details_btn.clicked.connect(self._toggle_inspector)
        ch.addWidget(self.details_btn)
        self.resource_btn = CutButton("资源库", "ghost", True)
        self.resource_btn.clicked.connect(lambda: self._open_catalog())
        ch.addWidget(self.resource_btn)
        self.labels_btn = CutButton("标签库", "ghost", True)
        self.labels_btn.clicked.connect(self._open_label_library)
        ch.addWidget(self.labels_btn)
        self.add_rule = CutButton("新建规则", "ghost", True)
        self.add_rule.setProperty("iconTextCentered", True)
        self.add_rule.setIcon(theme_icon("plus", muted=False, size=14))
        self.add_rule.clicked.connect(self._new_task)
        ch.addWidget(self.add_rule)
        center_lay.addWidget(self.center_head)

        # The project context has moved out of the left rail and into the
        # rules area, matching the requested workspace division.
        self.project_bar = QFrame()
        self.project_bar.setObjectName("ProjectBar")
        pb = QHBoxLayout(self.project_bar)
        pb.setContentsMargins(16, 3, 16, 3)
        pb.setSpacing(7)
        pe = QLabel("// PROJECT 工程")
        pe.setObjectName("Eyebrow")
        pb.addWidget(pe)
        self.project_name_edit = QLineEdit()
        self.project_name_edit.setObjectName("ProjectName")
        self.project_name_edit.setToolTip("点击重命名工程")
        self.project_name_edit.setMaxLength(60)
        self.project_name_edit.editingFinished.connect(self._rename_project)
        self.project_name_edit.textChanged.connect(self._resize_project_name_edit)
        self.project_name_edit.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        pb.addWidget(self.project_name_edit, 0)
        self.project_edit_hint = QLabel()
        self.project_edit_hint.setObjectName("ProjectEditHint")
        self.project_edit_hint.setFixedSize(18, 18)
        self.project_edit_hint.setCursor(Qt.CursorShape.PointingHandCursor)
        self.project_edit_hint.setToolTip("点击标题或铅笔图标重命名会话")
        self.project_edit_hint.setPixmap(theme_icon("pen", muted=True, size=12).pixmap(12, 12))
        self.project_edit_hint.mousePressEvent = lambda e: (  # type: ignore[method-assign]
            self.project_name_edit.setFocus(),
            self.project_name_edit.selectAll(),
        )
        pb.addWidget(self.project_edit_hint, 0, Qt.AlignmentFlag.AlignVCenter)
        self.project_meta_label = QLabel("")
        self.project_meta_label.setObjectName("Muted")
        self.project_meta_label.setFont(ui_font(9))
        pb.addWidget(self.project_meta_label, 0)
        pb.addStretch(1)
        self.save_project_btn = CutButton("保存", "ghost", True)
        self.save_project_btn.clicked.connect(self._save_project)
        pb.addWidget(self.save_project_btn)
        center_lay.addWidget(self.project_bar)
        self.inline_status = InlineStatus()
        self.inline_status.actionRequested.connect(self._locate_first_issue)
        center_lay.addWidget(self.inline_status)

        tab_row = QWidget()
        tr = QHBoxLayout(tab_row)
        tr.setContentsMargins(16, 0, 16, 0)
        tr.setSpacing(2)
        self.center_tabs = QButtonGroup(self)
        self.center_tabs.setExclusive(True)
        self.tab_overview = QPushButton("总览")
        self.tab_overview.setObjectName("Tab")
        self.tab_overview.setCheckable(True)
        self.tab_overview.setIcon(theme_icon("layout-dashboard", muted=False, size=14))
        self.tab_rules = QPushButton("规则")
        self.tab_rules.setObjectName("Tab")
        self.tab_rules.setCheckable(True)
        self.tab_rules.setIcon(theme_icon("list", muted=False, size=14))
        self.tab_graph = QPushButton("执行图")
        self.tab_graph.setObjectName("Tab")
        self.tab_graph.setCheckable(True)
        self.tab_graph.setIcon(theme_icon("workflow", muted=False, size=14))
        self.center_tabs.addButton(self.tab_overview, 0)
        self.center_tabs.addButton(self.tab_rules, 1)
        self.center_tabs.addButton(self.tab_graph, 2)
        self.center_tabs.idClicked.connect(self._show_center_tab)
        tr.addWidget(self.tab_overview)
        tr.addWidget(self.tab_rules)
        tr.addWidget(self.tab_graph)
        tr.addStretch(1)
        self.center_tab_meta = QLabel("")
        self.center_tab_meta.setObjectName("Muted")
        self.center_tab_meta.setFont(ui_font(9))
        tr.addWidget(self.center_tab_meta)
        center_lay.addWidget(tab_row)

        self.center_stack = QStackedWidget()
        self.overview = OverviewPage()
        self.overview.newRuleRequested.connect(self._new_task)
        self.overview.templateRequested.connect(self._open_templates)
        self.overview.checkRequested.connect(self._check)
        self.overview.copyRequested.connect(self._copy)
        self.overview.graphRequested.connect(self._show_graph)
        self.overview.resourceRequested.connect(self._open_catalog)
        self.overview.labelsRequested.connect(self._open_label_library)
        self.overview.commandRequested.connect(self._open_command_palette)
        self.overview.issueRequested.connect(self._locate_first_issue)
        self.overview.saveRequested.connect(self._save_project)
        self.overview.rulesRequested.connect(lambda: self._show_center_tab(1))
        self.overview.codeRequested.connect(self._focus_code)
        self.center_stack.addWidget(self.overview)
        self.rules_scroll = QScrollArea()
        self.rules_scroll.setWidgetResizable(True)
        self.rules_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.rules_body = QWidget()
        self.rules_lay = QVBoxLayout(self.rules_body)
        self.rules_lay.setContentsMargins(16, 8, 16, 10)
        self.rules_lay.setSpacing(2)
        self.rules_scroll.setWidget(self.rules_body)
        self.rules_page = QWidget()
        self.rules_page.setObjectName("RulesPage")
        rpl = QHBoxLayout(self.rules_page)
        rpl.setContentsMargins(0, 0, 0, 0)
        rpl.setSpacing(0)
        rpl.addWidget(self.rules_scroll, 1)
        self.inspector = TaskInspector()
        self.inspector.editRequested.connect(self._edit_task)
        self.inspector.graphRequested.connect(self._show_task_graph)
        self.inspector.duplicateRequested.connect(self._duplicate_task)
        self.inspector.toggleRequested.connect(self._toggle_task)
        self.inspector.deleteRequested.connect(self._delete_task)
        self.inspector.hide()
        self._inspector_open = False
        rpl.addWidget(self.inspector)
        self.center_stack.addWidget(self.rules_page)
        self.graph_panel = GraphPanel()
        self.graph_panel.editRequested.connect(self._edit_task)
        self.graph_panel.addSendRequested.connect(self._add_send)
        self.graph_panel.addConditionRequested.connect(self._edit_condition)
        self.graph_panel.willChange.connect(self._push_undo)
        self.graph_panel.changed.connect(self._graph_changed)
        self.center_stack.addWidget(self.graph_panel)
        self.center_stack.setCurrentIndex(0)
        self.tab_overview.setChecked(True)
        self.center_stack.currentChanged.connect(self._center_tab_changed)
        center_lay.addWidget(self.center_stack, 1)

        body_lay.addWidget(self._vline())
        right = QWidget()
        right.setFixedWidth(400)
        self.right_panel = right
        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(0, 0, 0, 0)
        right_lay.setSpacing(0)
        body_lay.addWidget(right)

        # code panel
        code_panel = QFrame()
        code_panel.setObjectName("Panel")
        cp = QVBoxLayout(code_panel)
        cp.setContentsMargins(0, 0, 0, 0)
        cp.setSpacing(0)
        code_head = QWidget()
        chl = QHBoxLayout(code_head)
        chl.setContentsMargins(12, 7, 12, 4)
        chl.setSpacing(6)
        code_title = SectionHeader("// CODE", "代码")
        chl.addWidget(code_title, 1)
        self.code_meta = QLabel("")
        self.code_meta.setObjectName("Muted")
        self.code_meta.setFont(ui_font(9))
        chl.addWidget(self.code_meta)
        self.export_btn = CutButton("导出", "ghost", True)
        self.export_btn.clicked.connect(self._export)
        chl.addWidget(self.export_btn)
        cp.addWidget(code_head)
        self.code_view = CodeView()
        cp.addWidget(self.code_view, 1)
        code_foot = QWidget()
        cfl = QHBoxLayout(code_foot)
        cfl.setContentsMargins(12, 4, 12, 6)
        cfl.setSpacing(6)
        self.code_footer = QLabel("")
        self.code_footer.setObjectName("Muted")
        self.code_footer.setFont(ui_font(9))
        cfl.addWidget(self.code_footer, 1)
        self.copy_small = CutButton("复制", "ghost", True)
        self.copy_small.clicked.connect(self._copy)
        cfl.addWidget(self.copy_small)
        cp.addWidget(code_foot)
        right_lay.addWidget(code_panel, 3)
        right_lay.addWidget(self._hline())

        # check panel
        check_panel = QFrame()
        check_panel.setObjectName("Panel")
        cp2 = QVBoxLayout(check_panel)
        cp2.setContentsMargins(0, 0, 0, 0)
        cp2.setSpacing(0)
        check_head = QWidget()
        chl2 = QHBoxLayout(check_head)
        chl2.setContentsMargins(12, 7, 12, 2)
        chl2.setSpacing(6)
        self.check_header = SectionHeader("// CHECK", "校验")
        self.check_header.set_meta("")
        chl2.addWidget(self.check_header, 1)
        cp2.addWidget(check_head)
        check_tabs = QWidget()
        ctl = QHBoxLayout(check_tabs)
        ctl.setContentsMargins(12, 0, 12, 0)
        ctl.setSpacing(2)
        self.check_group = QButtonGroup(self)
        self.check_group.setExclusive(True)
        self.tab_issues = QPushButton("问题 0")
        self.tab_issues.setObjectName("Tab")
        self.tab_issues.setCheckable(True)
        self.tab_issues.setChecked(True)
        self.tab_eff = QPushButton("效率")
        self.tab_eff.setObjectName("Tab")
        self.tab_eff.setCheckable(True)
        self.check_group.addButton(self.tab_issues, 0)
        self.check_group.addButton(self.tab_eff, 1)
        ctl.addWidget(self.tab_issues)
        ctl.addWidget(self.tab_eff)
        ctl.addStretch(1)
        cp2.addWidget(check_tabs)
        self.check_stack = QStackedWidget()
        issues_scroll = QScrollArea()
        issues_scroll.setWidgetResizable(True)
        issues_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.issue_list = IssueList()
        self.issue_list.issueActivated.connect(self._jump_to_issue_line)
        issues_scroll.setWidget(self.issue_list)
        self.check_stack.addWidget(issues_scroll)
        self.eff_panel = EfficiencyPanel()
        eff_scroll = QScrollArea()
        eff_scroll.setWidgetResizable(True)
        eff_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        eff_scroll.setWidget(self.eff_panel)
        self.check_stack.addWidget(eff_scroll)
        cp2.addWidget(self.check_stack, 1)
        self.check_group.idClicked.connect(self.check_stack.setCurrentIndex)
        right_lay.addWidget(check_panel, 2)

        # status
        status = QFrame()
        status.setFixedHeight(28)
        sl = QHBoxLayout(status)
        sl.setContentsMargins(12, 0, 12, 0)
        sl.setSpacing(8)
        self.status_left = QLabel("")
        self.status_left.setObjectName("Status")
        self.status_right = QLabel("离线 / 无遥测")
        self.status_right.setObjectName("Status")
        sl.addWidget(self.status_left, 1)
        sl.addWidget(self.status_right)
        root.addWidget(status)

        self._build_file_actions()
        QShortcut(QKeySequence("Ctrl+K"), self, activated=self._open_command_palette)
        QShortcut(QKeySequence("F5"), self, activated=self._check)
        QShortcut(QKeySequence("Ctrl+E"), self, activated=self._export)
        QShortcut(QKeySequence("Ctrl+,"), self, activated=self._open_settings)
        QShortcut(QKeySequence("Ctrl+Shift+F"), self, activated=self._toggle_focus_mode)
        QShortcut(QKeySequence("Ctrl+B"), self, activated=self._toggle_sidebar)

    def _build_file_actions(self) -> None:
        self.act_overview = QAction("总览", self)
        self.act_overview.triggered.connect(lambda: self._show_center_tab(0))
        self._set_action_icon(self.act_overview, "layout-dashboard")
        self.act_command = QAction("命令面板…", self)
        self.act_command.setShortcut(QKeySequence("Ctrl+K"))
        self.act_command.triggered.connect(self._open_command_palette)
        self._set_action_icon(self.act_command, "keyboard")
        self.act_focus = QAction("专注模式", self)
        self.act_focus.setShortcut(QKeySequence("Ctrl+Shift+F"))
        self.act_focus.triggered.connect(self._toggle_focus_mode)
        self._set_action_icon(self.act_focus, "focus")
        self.act_undo = QAction("撤销", self)
        self.act_undo.setShortcut(QKeySequence.StandardKey.Undo)
        self.act_undo.triggered.connect(self._undo_action)
        self.act_redo = QAction("重做", self)
        self.act_redo.setShortcuts(
            [QKeySequence.StandardKey.Redo, QKeySequence("Ctrl+Shift+Z")]
        )
        self.act_redo.triggered.connect(self._redo_action)
        self.act_new = QAction("新建会话", self)
        self.act_new.setShortcut(QKeySequence.StandardKey.New)
        self.act_new.triggered.connect(self._new_session_default)
        self.act_open = QAction("打开工程…", self)
        self.act_open.setShortcut(QKeySequence.StandardKey.Open)
        self.act_open.triggered.connect(self._open_project)
        self._set_action_icon(self.act_open, "folder-open")
        self.act_import_sfm = QAction("导入 .sfm…", self)
        self.act_import_sfm.triggered.connect(self._import_sfm)
        self._set_action_icon(self.act_import_sfm, "download")
        self.act_save = QAction("保存", self)
        self.act_save.setShortcut(QKeySequence.StandardKey.Save)
        self.act_save.triggered.connect(self._save_project)
        self._set_action_icon(self.act_save, "save")
        self.act_save_as = QAction("另存为…", self)
        self.act_save_as.setShortcut(QKeySequence.StandardKey.SaveAs)
        self.act_save_as.triggered.connect(self._save_as)
        self._set_action_icon(self.act_save_as, "save")
        self.act_export_project = QAction("导出工程…", self)
        self.act_export_project.triggered.connect(self._export_project)
        self._set_action_icon(self.act_export_project, "save")
        self.act_export = QAction("导出 .sfm…", self)
        self.act_export.triggered.connect(self._export)
        self._set_action_icon(self.act_export, "arrow-up-from-line")
        self.act_catalog = QAction("资源库 / items.json…", self)
        self.act_catalog.triggered.connect(self._open_catalog)
        self._set_action_icon(self.act_catalog, "package")
        self.act_logs = QAction("打开日志目录", self)
        self.act_logs.triggered.connect(self._open_logs)
        self._set_action_icon(self.act_logs, "folder-open")
        self.act_about = QAction("关于", self)
        self.act_about.triggered.connect(lambda: AboutDialog(self).exec())
        self._set_action_icon(self.act_about, "info")
        self.act_exit = QAction("退出", self)
        self.act_exit.triggered.connect(self.close)
        self.addAction(self.act_undo)
        self.addAction(self.act_redo)
        self.addAction(self.act_save)
        self.addAction(self.act_save_as)
        self.addAction(self.act_new)
        self.addAction(self.act_open)

    def _set_action_icon(self, action: QAction, name: str) -> None:
        action.setProperty("dshIcon", name)
        action.setIcon(theme_icon(name, muted=False, size=15))

    def _refresh_action_icons(self) -> None:
        for action in self.findChildren(QAction):
            name = action.property("dshIcon")
            if name:
                action.setIcon(theme_icon(str(name), muted=False, size=15))

    def _refresh_button_icons(self) -> None:
        t = theme_mod.current()
        from .icons import icon as svg_icon

        pairs = (
            (getattr(self, "resource_btn", None), "package", False),
            (getattr(self, "labels_btn", None), "tag", False),
            (getattr(self, "add_rule", None), "plus", False),
            (getattr(self, "save_project_btn", None), "save", False),
            (getattr(self, "export_btn", None), "arrow-up-from-line", False),
        )
        for btn, name, primary in pairs:
            if btn is None:
                continue
            btn.setIcon(svg_icon(name, t.on_signal if primary else t.ink, 14))
            btn.updateGeometry()
        command = getattr(self, "command", None)
        if command is not None:
            for btn, name, color in (
                (command.file_btn, "file-code", t.command_ink),
                (command.sidebar_btn, "panel-left-open", t.command_ink),
                (command.theme_btn, "sun" if t.dark else "moon", t.command_ink),
                (command.check_btn, "list-checks", t.signal if command.check_btn.variant == "attention" else t.command_ink),
                (command.ai_btn, "sparkles", t.command_ink),
                (command.copy_btn, "copy", t.on_signal),
                (command.settings_btn, "gear", t.command_ink),
            ):
                btn.setIcon(svg_icon(name, color, 14))
                btn.updateGeometry()
        if hasattr(self, "tab_rules"):
            self.tab_rules.setIcon(svg_icon("list", t.ink2, 12))
            self.tab_rules.setIconSize(QSize(12, 12))
            self.tab_graph.setIcon(svg_icon("workflow", t.ink2, 12))
            self.tab_graph.setIconSize(QSize(12, 12))
        if hasattr(self, "copy_small"):
            self.copy_small.setIcon(svg_icon("copy", t.ink, 14))
            self.copy_small.updateGeometry()
        hint = getattr(self, "project_edit_hint", None)
        if hint is not None:
            hint.setPixmap(svg_icon("pen", t.ink2, 12).pixmap(12, 12))

    # ------------------------------------------------------------------
    # helper drawing
    # ------------------------------------------------------------------
    def _vline(self) -> QFrame:
        f = QFrame()
        f.setFixedWidth(1)
        f.setObjectName("HLine")
        f.setStyleSheet(f"background: {theme_mod.current().rule};")
        return f

    def _hline(self) -> QFrame:
        f = QFrame()
        f.setFixedHeight(1)
        f.setObjectName("HLine")
        f.setStyleSheet(f"background: {theme_mod.current().rule};")
        return f

    # ------------------------------------------------------------------
    # theme / settings
    # ------------------------------------------------------------------
    def _apply_theme(self, rebuild: bool = True) -> None:
        t = theme_mod.THEMES.get(self.settings.theme, theme_mod.LIGHT)
        from . import motion

        motion.set_reduced(bool(getattr(self.settings, "reduced_motion", False)))
        app = QApplication.instance()
        if app is not None:
            apply_theme(app, t)
        self._refresh_action_icons()
        self._refresh_button_icons()
        if hasattr(self, "sidebar"):
            self.sidebar.apply_theme_icons()
        if hasattr(self, "code_view"):
            self.code_view.refresh_theme()
        if hasattr(self, "overview"):
            self.overview.refresh_theme()
        if hasattr(self, "inspector"):
            self.inspector.refresh_theme()
        self.command.set_theme_label(t.dark)
        self.command.set_profiles(
            [(pid, p.label) for pid, p in PROFILES.items()],
            self.project.profile_id if hasattr(self, "project") else self.settings.profile_id,
        )
        if rebuild:
            self._refresh_all()
        else:
            self._refresh_all()

    def _toggle_theme(self) -> None:
        self.settings.theme = "light" if self.settings.theme == "dark" else "dark"
        try:
            save_settings(self.settings)
        except Exception:
            pass
        self._apply_theme()
        self._record_activity("切换主题", "深色" if self.settings.theme == "dark" else "浅色", "VIEW")

    def _change_profile(self, profile_id: str) -> None:
        if profile_id not in PROFILES:
            return
        self._push_undo()
        self.project.profile_id = profile_id
        self.settings.profile_id = profile_id
        try:
            save_settings(self.settings)
        except Exception:
            pass
        self._mark_dirty()
        self._refresh_all()

    def _open_settings(self) -> None:
        dlg = SettingsDialog(self.settings, self)
        if dlg.exec():
            try:
                save_settings(self.settings)
            except Exception as exc:
                QMessageBox.warning(self, "设置未保存", f"设置无法写入：{exc}")
            self._apply_theme()
            self._toast_msg("设置已保存")
        dlg.deleteLater()

    # ------------------------------------------------------------------
    # project operations
    # ------------------------------------------------------------------
    def _set_project(self, project: Project, path: Path | None = None) -> None:
        if hasattr(self, "_autosave_timer"):
            self._autosave_timer.stop()
        self.project = project
        self.project_path = path
        crashlog.log_event(f"project open path={path} name={project.name!r}")
        self.settings.profile_id = project.profile_id
        self.settings.last_project = str(path) if path else ""
        try:
            save_settings(self.settings)
        except Exception:
            pass
        self.filter_label = None
        self.filter_btn.hide()
        self.dirty = False
        self._reset_history()
        self._refresh_all()
        self._record_activity("打开工程", self.project.name, "OPEN")

    def _save_project(self) -> None:
        self._commit_project_name()
        if getattr(self.project, "schema_version", SCHEMA_VERSION) > SCHEMA_VERSION:
            QMessageBox.warning(
                self,
                "工程版本较新",
                "这个工程由更新版本创建，当前版本保存会丢失未知字段。\n"
                "请升级应用后再保存，或先另存备份。",
            )
            return
        if not self.project_path:
            self._save_as()
            return
        try:
            save_project(self.project, self.project_path)
        except Exception as exc:
            crashlog.log_event(f"project save failed path={self.project_path}: {exc}")
            QMessageBox.critical(self, "保存失败", str(exc))
            return
        self._autosave_timer.stop()
        self.dirty = False
        crashlog.log_event(f"project saved path={self.project_path}")
        self.settings.last_project = str(self.project_path)
        try:
            save_settings(self.settings)
        except Exception as exc:
            crashlog.log_event(f"settings save failed after project save: {exc}")
            self._toast_msg("工程已保存，但最近工程/设置未保存")
        self._refresh_chrome()
        self._refresh_sidebar()
        self._toast_msg("工程已保存")
        self._record_activity("保存工程", Path(self.project_path).name, "SAVE")

    def _save_as(self) -> None:
        self._commit_project_name()
        if getattr(self.project, "schema_version", SCHEMA_VERSION) > SCHEMA_VERSION:
            QMessageBox.warning(
                self,
                "工程版本较新",
                "这个工程由更新版本创建，当前版本另存会丢失未知字段，已取消。",
            )
            return
        default = self.project.name or "未命名工程"
        path, _ = QFileDialog.getSaveFileName(self, "另存工程", f"{default}.sfmproj", "SFM 工程 (*.sfmproj)")
        if not path:
            return
        try:
            out = save_project(self.project, path)
        except Exception as exc:
            QMessageBox.critical(self, "保存失败", str(exc))
            return
        self._autosave_timer.stop()
        self.project_path = out
        self.dirty = False
        self.settings.last_project = str(out)
        try:
            save_settings(self.settings)
        except Exception as exc:
            crashlog.log_event(f"settings save failed after save-as: {exc}")
            self._toast_msg("工程已保存，但最近工程/设置未保存")
        self._refresh_chrome()
        self._refresh_sidebar()
        self._toast_msg(f"已保存：{out.name}")

    def _open_project(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "打开工程", "", "SFM 工程 (*.sfmproj);;所有文件 (*)")
        if path:
            self._open_recent(path)

    def _export_project(self) -> None:
        if getattr(self.project, "schema_version", SCHEMA_VERSION) > SCHEMA_VERSION:
            QMessageBox.warning(
                self,
                "工程版本较新",
                "这个工程由更新版本创建，当前版本导出会丢失未知字段，已取消。",
            )
            return
        default = self.project.name or "未命名工程"
        path, _ = QFileDialog.getSaveFileName(
            self, "导出工程（.sfmproj）", f"{default}.sfmproj", "SFM 工程 (*.sfmproj)"
        )
        if not path:
            return
        try:
            out = save_project(self.project, path)
            self._toast_msg(f"工程已导出：{out.name}")
            self._refresh_sidebar()
        except Exception as exc:
            QMessageBox.critical(self, "导出工程失败", str(exc))

    def _import_sfm(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "导入 .sfm", "", "SFML (*.sfm);;所有文件 (*)"
        )
        if not path:
            return
        try:
            text = Path(path).read_text(encoding="utf-8")
            from ..core.importer import import_sfml

            result = import_sfml(text, self.settings.profile_id, Path(path).stem)
            if not self._persist_current_session():
                return
            self._set_project(result.project, None)
            self.dirty = True
            self._mark_dirty()
            self._refresh_all()
            self._toast_msg(f"已导入 {len(result.project.tasks)} 个触发器")
            if result.warnings:
                QMessageBox.information(
                    self,
                    "导入完成（有提示）",
                    "以下内容未完全映射，生成为默认值或已跳过：\n"
                    + "\n".join(f"· {w}" for w in result.warnings[:10]),
                )
        except Exception as exc:
            QMessageBox.critical(self, "导入 .sfm 失败", str(exc))

    def _open_recent(self, path: str) -> None:
        if not path:
            return
        if self.project_path and Path(path) == self.project_path:
            return
        if self.dirty:
            ret = QMessageBox.question(
                self,
                "打开其他工程？",
                "当前工程有未保存修改。",
                QMessageBox.StandardButton.Save
                | QMessageBox.StandardButton.Discard
                | QMessageBox.StandardButton.Cancel,
            )
            if ret == QMessageBox.StandardButton.Cancel:
                return
            if ret == QMessageBox.StandardButton.Save:
                self._save_project()
                if self.dirty:
                    return
        try:
            p = load_project(path)
            self._set_project(p, Path(path))
            self._toast_msg(f"已打开：{Path(path).name}")
        except Exception as exc:
            QMessageBox.critical(self, "打开失败", str(exc))

    def _refresh_sidebar(self) -> None:
        try:
            from ..core.workspaces import group_projects, load_workspaces

            recent = load_recent()
            spaces = load_workspaces()
            key = (
                tuple((w.id, w.name, w.path, w.default, w.available) for w in spaces),
                tuple((str(r.get("path") or ""), str(r.get("name") or ""), str(r.get("at") or "")) for r in recent),
                str(self.project_path) if self.project_path else "",
                self.project.name,
            )
            if self._sidebar_cache_key == key:
                groups = self._sidebar_cache
            else:
                groups = group_projects(
                    recent,
                    spaces,
                    current_name=self.project.name,
                    current_path=str(self.project_path) if self.project_path else "",
                )
                self._sidebar_cache_key = key
                self._sidebar_cache = groups
        except Exception:
            groups = []
        if not hasattr(self, "sidebar"):
            return
        self.sidebar.set_profile(self.project.profile.label)
        self.sidebar.set_workspaces(
            groups,
            self.project.name,
            str(self.project_path) if self.project_path else "",
        )

    def _add_workspace(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "添加工作区文件夹", str(Path.home()))
        if not path:
            return
        try:
            from ..core.workspaces import add_workspace

            ws = add_workspace(path)
            self._refresh_sidebar()
            self._toast_msg(f"已添加工作区：{ws.name}")
        except Exception as exc:
            QMessageBox.warning(self, "添加工作区失败", str(exc))

    def _persist_current_session(self) -> bool:
        """Keep the current session independent before opening a new one.

        Clicking + must never put a Save/Don't Save/Cancel dialog inside the
        button's click signal: an unsaved current project with no path used to
        enter a modal Save-As loop and the sidebar appeared frozen. Persisting
        silently (to the existing file, or the default workspace for an
        unsaved session) keeps both sessions recoverable and makes switching
        non-blocking.
        """
        if not self.dirty:
            return True
        if not self.project_path:
            root = projects_dir()
            try:
                root.mkdir(parents=True, exist_ok=True)
            except Exception as exc:
                QMessageBox.warning(self, "当前会话未保存", f"无法创建用户工程目录：{exc}")
                return False
            target = root / f"会话-{datetime.now().strftime('%Y%m%d-%H%M%S')}.sfmproj"
            n = 2
            while target.exists():
                target = root / f"会话-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{n}.sfmproj"
                n += 1
        else:
            target = self.project_path
        try:
            save_project(self.project, target)
        except Exception as exc:
            QMessageBox.warning(
                self,
                "当前会话保存失败",
                f"为避免丢失当前会话，未继续操作。\n\n{target}\n{exc}",
            )
            return False
        if not self.project_path:
            self.project_path = target
            self.settings.last_project = str(target)
            try:
                save_settings(self.settings)
            except Exception:
                pass
        self.dirty = False
        if hasattr(self, "_autosave_timer"):
            self._autosave_timer.stop()
        return True

    def _create_session_in_workspace(self, workspace_path: str) -> None:
        if getattr(self, "_creating_session", False):
            return
        self._creating_session = True
        try:
            root = Path(workspace_path)
            if not workspace_path or not root.is_dir():
                QMessageBox.warning(self, "新建会话失败", "工作区目录不存在或不可访问。")
                self._refresh_sidebar()
                return
            if not self._persist_current_session():
                return
            stamp = datetime.now().strftime("%H%M%S")
            target = root / f"会话-{stamp}.sfmproj"
            n = 2
            while target.exists():
                target = root / f"会话-{stamp}-{n}.sfmproj"
                n += 1
            project = new_blank_project(
                f"新会话 {datetime.now().strftime('%H:%M:%S')}", self.settings.profile_id
            )
            try:
                save_project(project, target)
            except PermissionError as exc:
                QMessageBox.warning(
                    self,
                    "新建会话失败",
                    f"目录没有写权限，未创建会话。\n\n{root}\n{exc}",
                )
                return
            except Exception as exc:
                QMessageBox.warning(
                    self,
                    "新建会话失败",
                    f"无法在该工作区创建会话。\n\n{root}\n{exc}",
                )
                return
            if hasattr(self, "sidebar"):
                self.sidebar.expand_workspace(str(root.resolve()))
            self._set_project(project, target)
            self._toast_msg(f"已新建会话：{target.stem}")
        finally:
            self._creating_session = False

    def _open_recycle_folder(self) -> None:
        try:
            from ..core.workspaces import recycle_sessions_dir

            self._open_folder(recycle_sessions_dir(), "无法打开回收站")
        except Exception as exc:
            QMessageBox.warning(self, "无法打开回收站", str(exc))

    def _open_folder(self, folder: Path, title: str) -> None:
        """Open a local folder with Explorer, with a Windows fallback.

        QDesktopServices can return False even when Explorer is available
        (for example under a restricted shell or a non-default file-manager
        association).  os.startfile uses the Windows shell directly and is a
        useful second attempt; if both fail, surface the real warning.
        """
        folder.mkdir(parents=True, exist_ok=True)
        opened = False
        try:
            opened = bool(QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder))))
        except Exception:
            opened = False
        if not opened and sys.platform == "win32":
            try:
                os.startfile(str(folder))  # type: ignore[attr-defined]
                opened = True
            except Exception:
                opened = False
        if not opened:
            crashlog.log_event(f"open-folder failed: {folder}")
            QMessageBox.warning(
                self,
                title,
                f"请在文件资源管理器中手动打开：\n{folder}",
            )

    def _new_session_default(self) -> None:
        from ..core.workspaces import load_workspaces

        spaces = load_workspaces()
        target = next(
            (w for w in spaces if w.default and w.available),
            next((w for w in spaces if w.available), None),
        )
        path = target.path if target is not None else str(projects_dir())
        self._create_session_in_workspace(path)

    def _save_session_order(self, workspace_path: str, paths: list) -> None:
        try:
            from ..core.workspaces import set_session_order

            set_session_order(workspace_path, paths)
        except Exception as exc:
            QMessageBox.warning(self, "顺序保存失败", f"会话顺序无法保存：\n{exc}")

    def _rename_session(self, path: str) -> None:
        source = Path(path)
        if not source.is_file():
            QMessageBox.warning(self, "重命名会话失败", f"会话文件不存在：\n{source}")
            return
        try:
            if self.project_path and Path(self.project_path).resolve() == source.resolve():
                self.project_name_edit.setFocus()
                self.project_name_edit.selectAll()
                self._toast_msg("直接修改标题后按 Enter 即可重命名")
                return
            project = load_project(source)
            name, ok = QInputDialog.getText(
                self, "重命名会话", "新的会话标题：", text=project.name or "未命名会话"
            )
            if not ok or not name.strip():
                return
            project.name = name.strip()[:60]
            save_project(project, source)
            self._refresh_sidebar()
            self._toast_msg(f"已重命名：{project.name}")
        except Exception as exc:
            QMessageBox.warning(self, "重命名会话失败", f"{source}\n{exc}")

    def _reveal_session(self, path: str) -> None:
        source = Path(path)
        if not source.exists():
            QMessageBox.warning(self, "找不到会话", f"会话文件不存在：\n{source}")
            return
        self._open_folder(source.parent, "无法打开文件夹")

    def _delete_session(self, path: str, workspace_path: str) -> None:
        from ..core.workspaces import (
            load_session_orders,
            move_session_to_recycle,
            recycle_sessions_dir,
            set_session_order,
        )
        from ..core.storage import remove_recent

        source = Path(path)
        crashlog.log_event(f"session delete requested path={source}")
        if not source.is_file():
            QMessageBox.warning(self, "删除会话失败", f"会话文件不存在：\n{source}")
            self._refresh_sidebar()
            return
        answer = QMessageBox.question(
            self,
            "删除会话",
            "将把这个会话移到应用回收站，不直接永久删除。\n\n"
            f"{source}\n\n"
            f"恢复位置：{recycle_sessions_dir()}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        was_current = bool(self.project_path and Path(self.project_path).resolve() == source.resolve())
        if was_current and self.dirty:
            try:
                save_project(self.project, source)
                self.dirty = False
            except Exception as exc:
                QMessageBox.warning(
                    self,
                    "删除已取消",
                    f"当前会话保存失败，未移动到回收站。\n\n{source}\n{exc}",
                )
                return
        try:
            recycled = move_session_to_recycle(source)
        except Exception as exc:
            QMessageBox.warning(self, "删除会话失败", f"{source}\n{exc}")
            return
        remove_recent(source)
        try:
            orders = load_session_orders()
            key = str(Path(workspace_path).resolve()) if workspace_path else ""
            if key in orders:
                set_session_order(key, [p for p in orders[key] if Path(p).resolve() != source.resolve()])
        except Exception:
            pass
        self._refresh_sidebar()
        if was_current:
            # The editor must never keep a path to a file that has just moved
            # to the recycle bin; otherwise the next Ctrl+S resurrects it.
            self.project_path = None
            opened = False
            candidates = sorted(
                (p for p in source.parent.glob("*.sfmproj") if p.is_file() and p.resolve() != source.resolve()),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            for candidate in candidates:
                try:
                    loaded = load_project(candidate)
                except Exception:
                    continue
                self._set_project(loaded, candidate)
                opened = True
                break
            if not opened:
                self._create_session_in_workspace(str(source.parent))
        self._toast_msg(f"已移到回收站：{recycled.name}")

    def _rename_project(self) -> None:
        if not hasattr(self, "project_name_edit"):
            return
        if not self._commit_project_name():
            self.project_name_edit.setText(self.project.name)

    def _commit_project_name(self) -> bool:
        """Apply the title edit before save/close, even without Enter."""
        if not hasattr(self, "project_name_edit"):
            return False
        text = self.project_name_edit.text().strip()
        if not text:
            self.project_name_edit.setText(self.project.name)
            return False
        if text == self.project.name:
            return False
        self._push_undo()
        self.project.name = text
        self.dirty = True
        self._refresh_all()
        return True

    def _resize_project_name_edit(self) -> None:
        if not hasattr(self, "project_name_edit"):
            return
        text = self.project_name_edit.text() or "新会话"
        width = QFontMetrics(self.project_name_edit.font()).horizontalAdvance(text) + 12
        self.project_name_edit.setFixedWidth(min(max(72, width), 320))

    def _open_label_library(self) -> None:
        dlg = LabelLibraryDialog(self.project, self)
        if not dlg.exec():
            dlg.deleteLater()
            return
        new_labels = dlg.labels()
        old = {x.id: x.name for x in self.project.labels}
        renames = {old[k]: v for k, v in dlg.renames.items() if old.get(k) and old[k] != v}
        self._push_undo()
        self.project.labels = new_labels
        if renames:
            for task in self.project.tasks:
                for b in task.batches:
                    if b.take.source in renames:
                        b.take.source = renames[b.take.source]
                    for send in b.sends:
                        if send.target in renames:
                            send.target = renames[send.target]
        self._mark_dirty()
        self._refresh_all()
        self._toast_msg("标签库已更新")
        dlg.deleteLater()

    def _open_templates(self) -> None:
        dlg = TemplateDialog(self, self.project)
        dlg.chosen.connect(lambda key: dlg.accept() if self._load_template_key(key) else None)
        dlg.exec()
        dlg.deleteLater()

    def _load_template_key(self, key: str) -> bool:
        try:
            from ..core.templates import load_template

            if not self._persist_current_session():
                return False
            p = load_template(key, self.settings.profile_id)
            self._set_project(p, None)
            return True
        except Exception as exc:
            QMessageBox.critical(self, "模板加载失败", str(exc))
            return False

    def _mark_dirty(self) -> None:
        self.dirty = True
        self._refresh_chrome()
        if hasattr(self, "_autosave_timer"):
            self._autosave_timer.start(900)

    # ---- undo / redo -----------------------------------------------------
    def _snapshot(self) -> str:
        return project_to_json(self.project)

    def _push_undo(self) -> None:
        if self._restoring:
            return
        try:
            self._undo.append(self._snapshot())
            self._undo = self._undo[-100:]
            self._redo.clear()
            self._update_history_actions()
        except Exception:
            pass

    def _reset_history(self) -> None:
        self._undo.clear()
        self._redo.clear()
        self._update_history_actions()

    def _update_history_actions(self) -> None:
        if hasattr(self, "act_undo"):
            self.act_undo.setEnabled(bool(self._undo))
        if hasattr(self, "act_redo"):
            self.act_redo.setEnabled(bool(self._redo))

    def _undo_action(self) -> None:
        if not self._undo:
            return
        try:
            self._redo.append(self._snapshot())
            text = self._undo.pop()
            self._restoring = True
            self.project = project_from_json(text)
            self._restoring = False
            self.dirty = True
            if hasattr(self, "_autosave_timer"):
                self._autosave_timer.start(900)
            self._refresh_all()
            self._update_history_actions()
            self._toast_msg("已撤销")
        except Exception as exc:
            self._restoring = False
            self._toast_msg(f"撤销失败：{exc}")

    def _redo_action(self) -> None:
        if not self._redo:
            return
        try:
            self._undo.append(self._snapshot())
            text = self._redo.pop()
            self._restoring = True
            self.project = project_from_json(text)
            self._restoring = False
            self.dirty = True
            if hasattr(self, "_autosave_timer"):
                self._autosave_timer.start(900)
            self._refresh_all()
            self._update_history_actions()
            self._toast_msg("已重做")
        except Exception as exc:
            self._restoring = False
            self._toast_msg(f"重做失败：{exc}")

    def _autosave_now(self) -> None:
        if not self.dirty:
            return
        try:
            autosave(self.project)
            self._last_autosave = datetime.now().strftime("%H:%M")
            self._autosave_error = ""
            self._refresh_status()
        except Exception as exc:
            self._autosave_error = str(exc)
            self._refresh_status()
            self._toast_msg("自动保存失败；当前修改仍在内存中")

    # ------------------------------------------------------------------
    # tasks
    # ------------------------------------------------------------------
    def _new_task(self) -> None:
        task = Task(name=unique_name("新任务", {t.name for t in self.project.tasks}))
        names = self.project.label_names()
        if names:
            task.batches[0].take.source = names[0]
            if len(names) > 1:
                task.batches[0].sends[0].target = names[1]
        dlg = TaskEditorDialog(self.project, task, self)
        if not dlg.exec():
            dlg.deleteLater()
            return
        dlg.deleteLater()
        self._push_undo()
        self.project.tasks.append(task)
        self.project.active_task_id = task.id
        self._mark_dirty()
        self._refresh_all()
        self._record_activity("新建规则", task.name, "BUILD")

    def _edit_task(self, task_id: str) -> None:
        task = self.project.task_by_id(task_id)
        if not task:
            return
        before = self._snapshot()
        dlg = TaskEditorDialog(self.project, task, self)
        if dlg.exec():
            # Undo captures the pre-dialog state; a cancelled editor must not
            # leave a no-op entry in the history.
            self._undo.append(before)
            self._undo = self._undo[-100:]
            self._redo.clear()
            self._update_history_actions()
            self._mark_dirty()
            self._refresh_all()
            self._toast_msg("任务已更新")
        dlg.deleteLater()

    def _edit_condition(self) -> None:
        task = self.project.active_task()
        if task is not None:
            self._edit_task(task.id)


    def _delete_task(self, task_id: str) -> None:
        task = self.project.task_by_id(task_id)
        if not task:
            return
        ret = QMessageBox.question(
            self,
            "删除任务",
            f"删除「{task.name}」？\n此操作会修改工程，可用 Ctrl+Z 撤销。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if ret != QMessageBox.StandardButton.Yes:
            return
        self._push_undo()
        self.project.remove_task(task_id)
        self._mark_dirty()
        self._refresh_all()
        self._toast_msg("已删除任务")
        self._record_activity("删除规则", task.name, "DELETE")

    def _add_send(self) -> None:
        task = self.project.active_task()
        if not task or not task.batches:
            return
        from ..core.model import Send

        idx = self.graph_panel.current_batch_index() if hasattr(self, "graph_panel") else 0
        b = task.batches[max(0, min(idx, len(task.batches) - 1))]
        target = self.project.label_names()[0] if self.project.label_names() else ""
        self._push_undo()
        b.sends.append(Send(target=target, side="默认面"))
        self._mark_dirty()
        self._refresh_all()
        self._record_activity("添加送目标", task.name, "BUILD")

    def _graph_changed(self) -> None:
        self._mark_dirty()
        self._refresh_all()

    # ------------------------------------------------------------------
    # labels
    # ------------------------------------------------------------------
    def _add_label(self) -> None:
        dlg = LabelDialog(parent=self)
        if not dlg.exec():
            dlg.deleteLater()
            return
        name, kind, note, cap = dlg.value()
        dlg.deleteLater()
        if any(l.name == name for l in self.project.labels):
            QMessageBox.warning(self, "重复标签", "标签名已存在。")
            return
        from ..core.model import Label

        self._push_undo()
        self.project.labels.append(Label(name=name, kind=kind, note=note, capacity=cap))
        self._mark_dirty()
        self._refresh_all()

    def _edit_label(self, label_id: str) -> None:
        # Sidebar emits the label name for filters; resolve by id or name.
        label = next((l for l in self.project.labels if l.id == label_id or l.name == label_id), None)
        if not label:
            return
        dlg = LabelDialog(label, self)
        if not dlg.exec():
            dlg.deleteLater()
            return
        name, kind, note, cap = dlg.value()
        dlg.deleteLater()
        if any(l.id != label.id and l.name == name for l in self.project.labels):
            QMessageBox.warning(self, "重复标签", "标签名已存在。")
            return
        # Update references if the name changed.
        self._push_undo()
        old = label.name
        label.name, label.kind, label.note, label.capacity = name, kind, note, cap
        if old != name:
            for t in self.project.tasks:
                for b in t.batches:
                    if b.take.source == old:
                        b.take.source = name
                    for s in b.sends:
                        if s.target == old:
                            s.target = name
        self._mark_dirty()
        self._refresh_all()

    def _show_label_check(self) -> None:
        try:
            from ..core.validate import validate_project
            from ..core.codegen import generate_project

            code = generate_project(self.project)
            labels = sorted({l.name for l in self.project.labels if l.name})
            used = sorted({l for l in labels if f'"{l}"' in code})
            msg = "代码里引用的标签：\n" + ("\n".join(f"· {x}" for x in used) if used else "（无）")
            msg += "\n\n复制后请在游戏内逐个用标签枪核对；本工具不自动绑定方块。"
        except Exception:
            msg = "代码尚未就绪；请先修复问题。"
        QMessageBox.information(self, "标签核对", msg)

    def _filter_by_label(self, label: str) -> None:
        self.filter_label = None if self.filter_label == label else label
        self.filter_btn.setVisible(bool(self.filter_label))
        if self.filter_label:
            self.filter_btn.setText(f"× 清除筛选：{self.filter_label}")
        self._render_rules()

    def _clear_filter(self) -> None:
        self.filter_label = None
        self.filter_btn.hide()
        self._render_rules()

    # ------------------------------------------------------------------
    # code / validation
    # ------------------------------------------------------------------
    def _refresh_all(self) -> None:
        self.code = self._generate_code()
        self.validation = self._validate()
        self.estimate = self._estimate()
        self._refresh_chrome()
        self._refresh_sidebar()
        self._render_rules()
        self._render_graph()
        self._render_code()
        locked = self.validation is None or bool(getattr(self.validation, "blocks", 0))
        self.code_view.setTextInteractionFlags(
            Qt.TextInteractionFlag.NoTextInteraction
            if locked
            else (Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.TextSelectableByKeyboard)
        )
        self._render_issues()
        self._render_estimate()
        self._refresh_overview()
        self._refresh_inspector()
        self._refresh_status()
        self._toast_position()

    def _generate_code(self) -> str:
        try:
            from ..core.codegen import generate_project

            return generate_project(self.project)
        except Exception as exc:
            return f"-- 生成器未就绪：{exc}\n"

    def _validate(self):
        try:
            from ..core.validate import validate_project

            return validate_project(self.project)
        except Exception as exc:
            return None

    def _estimate(self):
        try:
            from ..core.tps import estimate_tps

            return estimate_tps(self.project)
        except Exception:
            return None

    def _refresh_chrome(self) -> None:
        self.command.set_project(self.project.name, self.dirty, self.project_path is not None)
        self.command.set_profiles(
            [(pid, p.label) for pid, p in PROFILES.items()],
            self.project.profile_id,
        )
        blocks = getattr(self.validation, "blocks", 0) or 0
        possible = getattr(self.validation, "warnings", 0) or 0
        total = blocks + possible if self.validation is not None else 0
        self.command.set_check(total, bool(blocks))
        self.center_header.set_meta(
            f"{len(self.project.tasks):02d} 条 │ {sum(len(t.batches) for t in self.project.tasks):02d} 批次"
        )
        self.center_tab_meta.setText(
            f"{sum(len(t.batches) for t in self.project.tasks):02d} 批次"
        )
        if hasattr(self, "project_name_edit"):
            if not self.project_name_edit.hasFocus():
                self.project_name_edit.setText(self.project.name)
            self._resize_project_name_edit()
            self.project_meta_label.setText(
                f"{len(self.project.labels)} 设备 │ {len(self.project.tasks)} 规则"
            )
        self.check_header.set_meta(
            "0 阻断 / 0 提示" if self.validation is None else f"{blocks} 阻断 / {possible} 提示"
        )
        self.tab_issues.setText(
            f"问题 {self._issue_group_count}/{total}"
            if getattr(self, "_issue_group_count", total) != total
            else f"问题 {total}"
        )
        chars = len(self.code)
        lines = len(self.code.splitlines())
        self.code_meta.setText(f"{lines} 行 / {chars} 字符")
        self.code_footer.setText(f"{chars} 字符 / 上限 32,367 · UTF-8 · LF")
        self._update_action_availability(blocks)

    def _update_action_availability(self, blocks: int) -> None:
        blocked = bool(blocks) or self.validation is None
        reason = "有阻断问题，先修复再复制" if blocked else ""
        t = theme_mod.current()
        for btn in (self.command.copy_btn, self.copy_small):
            btn.setEnabled(not blocked)
            btn.setToolTip(reason)
        self.command.copy_btn.setIcon(
            svg_icon("copy", t.command_muted if blocked else t.on_signal, 14)
        )
        self.copy_small.setIcon(svg_icon("copy", t.ink2 if blocked else t.ink, 14))
        self.export_btn.setEnabled(bool(self.code.strip()) and not blocked)
        self.export_btn.setToolTip(reason)

    def _render_rules(self) -> None:
        while self.rules_lay.count():
            item = self.rules_lay.takeAt(0)
            if item.widget():
                w = item.widget()
                w.hide()
                w.setParent(None)
                w.deleteLater()
        tasks = self.project.tasks
        if self.filter_label:
            tasks = [
                t for t in tasks
                if any(
                    self.filter_label in (b.take.source, *(s.target for s in b.sends), b.condition)
                    for b in t.batches
                )
            ]
        if not tasks:
            empty = QWidget()
            el = QVBoxLayout(empty)
            el.setContentsMargins(8, 32, 8, 32)
            el.setSpacing(7)
            empty_icon = QLabel()
            empty_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
            icon_name = "list-filter" if self.filter_label else "list-todo"
            empty_icon.setPixmap(theme_icon(icon_name, muted=True, size=28).pixmap(28, 28))
            el.addWidget(empty_icon)
            title = QLabel("筛选下没有任务" if self.filter_label else "还没有任务")
            title.setObjectName("EmptyTitle")
            title.setAlignment(Qt.AlignmentFlag.AlignCenter)
            body = QLabel(
                "清除筛选，或换一个标签。" if self.filter_label
                else "从一个能跑的起点开始；规则、代码和校验会保持同帧。"
            )
            body.setObjectName("EmptyBody")
            body.setAlignment(Qt.AlignmentFlag.AlignCenter)
            body.setWordWrap(True)
            el.addWidget(title)
            el.addWidget(body)
            actions = QHBoxLayout()
            actions.setSpacing(6)
            actions.addStretch(1)
            if self.filter_label:
                clear = CutButton("清除筛选", "ghost", True)
                clear.setIcon(theme_icon("x", muted=False, size=13))
                clear.clicked.connect(self._clear_filter)
                actions.addWidget(clear)
            else:
                from_tpl = CutButton("从模板开始", "primary", True)
                from_tpl.setIcon(theme_icon("layout-template", muted=False, size=14))
                from_tpl.clicked.connect(self._open_templates)
                actions.addWidget(from_tpl)
            actions.addStretch(1)
            el.addLayout(actions)
            self.rules_lay.addStretch(1)
            self.rules_lay.addWidget(empty)
        else:
            active = self.project.active_task_id
            for i, task in enumerate(tasks):
                status = "未校验"
                if self.validation is not None:
                    task_issues = [x for x in getattr(self.validation, "issues", []) if getattr(x, "task_id", None) == task.id]
                    global_block = bool(getattr(self.validation, "syntax_errors", [])) or any(
                        getattr(x, "level", "") == "block" and getattr(x, "task_id", None) is None
                        for x in getattr(self.validation, "issues", [])
                    )
                    if global_block or any(getattr(x, "level", "") == "block" for x in task_issues):
                        status = "需修复"
                    elif task.enabled:
                        status = "已校验"
                    else:
                        status = "停用"
                elif not task.enabled:
                    status = "停用"
                card = RuleCard()
                card.update_task(task, self.project.tasks.index(task), task.id == active, status)
                card.clicked.connect(self._select_task)
                card.editRequested.connect(self._edit_task)
                card.deleteRequested.connect(self._delete_task)
                self.rules_lay.addWidget(card)
        self.rules_lay.addStretch(1)

    def _select_task(self, task_id: str) -> None:
        if not self.project.task_by_id(task_id):
            return
        self.project.active_task_id = task_id
        self._refresh_all()

    def _render_graph(self) -> None:
        task = self.project.active_task()
        idx = self.graph_panel.current_batch_index() if hasattr(self, "graph_panel") else 0
        self.graph_panel.set_task(task, idx)

    def _render_code(self) -> None:
        self.code_view.set_code(self.code)

    def _focus_code(self) -> None:
        self.code_view.setFocus()
        self.code_view.ensureCursorVisible()

    def _render_issues(self) -> None:
        issues = []
        if not self.project.tasks:
            issues.append(
                IssueView(
                    "info",
                    "还没有规则可校验",
                    "新建规则后会生成代码，并运行本地 L0 / L1 检查。",
                    "—",
                )
            )
        elif self.validation is None:
            issues.append(
                IssueView(
                    "info",
                    "校验器尚未就绪",
                    "核心 validate 模块未加载；复制前请先修复。",
                    "—",
                )
            )
        else:
            for issue in list(getattr(self.validation, "issues", [])):
                line = getattr(issue, "line", None)
                issues.append(
                    IssueView(
                        getattr(issue, "level", "info"),
                        getattr(issue, "message", ""),
                        getattr(issue, "code", ""),
                        f"L.{line}" if line else "—",
                        int(line or 0),
                    )
                )
            for err in list(getattr(self.validation, "syntax_errors", [])):
                issues.append(IssueView("block", "SFML 语法错误", err, "L0", 0))
        # The validator emits one message per batch, so three batches with the
        # same missing side become three identical rows.  Keep the exact line
        # references but show one row per distinct message; the code gutter
        # still marks every line.
        grouped: dict[tuple[str, str, str], IssueView] = {}
        for issue in issues:
            key = (issue.level, issue.title, issue.detail)
            if key not in grouped:
                grouped[key] = issue
            else:
                prev = grouped[key]
                if issue.ref and issue.ref != "—" and issue.ref not in prev.ref:
                    prev.ref = f"{prev.ref} / {issue.ref}" if prev.ref != "—" else issue.ref
        visible_issues = list(grouped.values())
        severity = {"block": 0, "possible": 1, "reminder": 2, "info": 3}
        visible_issues.sort(key=lambda x: severity.get(x.level, 4))
        self._issue_group_count = len(visible_issues)
        self.issue_list.set_issues(visible_issues, len(visible_issues))
        self.code_view.set_issue_lines({
            issue.line: issue.level for issue in issues if issue.line
        })
        blocks = [x for x in issues if x.level == "block"]
        if blocks:
            first = next((x for x in blocks if x.line), None)
            detail = self._issue_brief(blocks[0].title)
            if len(blocks) > 1:
                detail = f"{detail} 另有 {len(blocks) - 1} 条阻断；右侧逐条定位。"
            self.inline_status.set_message(
                "block",
                f"{len(blocks)} 条阻断阻止复制",
                detail,
                action_text="定位第一个",
                action=first is not None,
            )
        elif self.validation is None:
            self.inline_status.set_message(
                "info",
                "校验器尚未就绪",
                "复制前的本地校验不可用；请先修复校验模块。",
                action=False,
            )
        else:
            self.inline_status.hide()

    @staticmethod
    def _issue_brief(text: str) -> str:
        clean = " ".join(str(text or "").split())
        return clean if len(clean) <= 72 else clean[:69] + "…"

    def _locate_first_issue(self) -> None:
        if self.validation is None:
            return
        issues = list(getattr(self.validation, "issues", []))
        for issue in issues:
            line = int(getattr(issue, "line", 0) or 0)
            if line and getattr(issue, "level", "") == "block":
                self._jump_to_issue_line(line)
                return
        for issue in issues:
            line = int(getattr(issue, "line", 0) or 0)
            if line:
                self._jump_to_issue_line(line)
                return
        self.check_stack.setCurrentIndex(0)
        self.tab_issues.setChecked(True)

    def _jump_to_issue_line(self, line: int) -> None:
        self.code_view.jump_to_line(int(line))

    def _render_estimate(self) -> None:
        self.eff_panel.set_estimate(self.estimate)

    def _refresh_status(self) -> None:
        t = self.project.profile
        labels = len(self.project.labels)
        tasks = len(self.project.tasks)
        chars = len(self.code)
        save = self._last_autosave or "--:--"
        if self._autosave_error:
            save_text = "自动保存失败"
        elif self._storage_error:
            save_text = "数据目录不可写"
        else:
            save_text = f"自动保存 {save}"
        self.status_left.setText(
            f"SFM {t.sfm}  │  {labels} 设备  │  {tasks} 规则  │  {chars} 字符  │  {save_text}"
        )

    # ------------------------------------------------------------------
    # actions
    # ------------------------------------------------------------------
    def _check(self) -> None:
        crashlog.log_event("validate requested")
        self.validation = self._validate()
        self.estimate = self._estimate()
        self._refresh_chrome()
        self._render_issues()
        self._render_estimate()
        self.check_stack.setCurrentIndex(0)
        self.tab_issues.setChecked(True)
        blocks = getattr(self.validation, "blocks", 0) or 0
        warnings = getattr(self.validation, "warnings", 0) or 0
        if self.validation is None:
            self._toast_msg("校验器未就绪")
        elif blocks:
            self._toast_msg(f"校验完成：{blocks} 阻断 / {warnings} 提示")
        else:
            self._toast_msg(f"校验完成：0 阻断 / {warnings} 提示")
        self._record_activity("本地校验", f"{blocks} 阻断 / {warnings} 提示", "VERIFY")

    def _copy(self) -> None:
        crashlog.log_event("copy requested")
        if not self.code.strip():
            self._toast_msg("没有可复制的代码")
            return
        blocks = getattr(self.validation, "blocks", 0) if self.validation is not None else 0
        if self.validation is None:
            self._toast_msg("校验器未就绪，先修复再复制")
            return
        if blocks:
            self.check_stack.setCurrentIndex(0)
            self.tab_issues.setChecked(True)
            self._toast_msg("有阻断问题，先修复再复制")
            return
        app = QApplication.instance()
        if app:
            app.clipboard().setText(self.code)
        self._toast_msg("已复制代码")
        t = theme_mod.current()
        self.command.copy_btn.setText("已复制")
        self.command.copy_btn.setIcon(svg_icon("check", t.on_signal, 14))
        self.copy_small.setIcon(svg_icon("check", t.ink, 14))
        if not hasattr(self, "_copy_reset_timer"):
            self._copy_reset_timer = QTimer(self)
            self._copy_reset_timer.setSingleShot(True)
            self._copy_reset_timer.timeout.connect(self._reset_copy_state)
        self._copy_reset_timer.start(1200)
        self._record_activity("复制代码", f"{len(self.code):,} 字符", "EXPORT")

    def _reset_copy_state(self) -> None:
        t = theme_mod.current()
        self.command.copy_btn.setText("复制代码")
        self.command.copy_btn.setIcon(svg_icon("copy", t.on_signal, 14))
        self.copy_small.setIcon(svg_icon("copy", t.ink, 14))

    def _export(self) -> None:
        if not self.code.strip():
            self._toast_msg("没有可导出的代码")
            return
        blocks = getattr(self.validation, "blocks", 0) if self.validation is not None else 1
        if blocks:
            self.check_stack.setCurrentIndex(0)
            self.tab_issues.setChecked(True)
            self._toast_msg("有阻断问题，先修复再导出")
            return
        path, _ = QFileDialog.getSaveFileName(self, "导出 SFML", f"{self.project.name}.sfm", "SFML (*.sfm)")
        if not path:
            return
        try:
            export_sfml(self.code, path)
            self._toast_msg(f"已导出：{Path(path).name}")
        except Exception as exc:
            QMessageBox.critical(self, "导出失败", str(exc))

    def _file_menu(self) -> None:
        menu = QMenu(self)
        menu.setStyleSheet(
            f"QMenu::separator {{ height: 1px; background: {theme_mod.current().rule}; margin: 5px 8px; }}"
        )

        def add(action: QAction) -> None:
            row = FileMenuItem(action, menu)
            widget_action = QWidgetAction(menu)
            widget_action.setDefaultWidget(row)
            menu.addAction(widget_action)

        add(self.act_overview)
        add(self.act_command)
        add(self.act_focus)
        menu.addSeparator()
        add(self.act_open)
        add(self.act_new)
        add(self.act_import_sfm)
        menu.addSeparator()
        add(self.act_save)
        add(self.act_save_as)
        add(self.act_export_project)
        add(self.act_export)
        menu.addSeparator()
        add(self.act_catalog)
        add(self.act_logs)
        menu.addSeparator()
        add(self.act_undo)
        add(self.act_redo)
        menu.addSeparator()
        add(self.act_about)
        add(self.act_exit)
        pos = self.command.file_btn.mapToGlobal(QPoint(0, self.command.file_btn.height()))
        menu.exec(pos)
        menu.deleteLater()

    def _open_ai(self) -> None:
        try:
            from ..services.ai import PromptManager

            pm = PromptManager(override=getattr(self.settings, "prompt_override", ""))
            dlg = AIDialog(self.project, self.settings, pm, self)
            dlg.exec()
            dlg.deleteLater()
            try:
                save_settings(self.settings)
            except Exception:
                pass
        except Exception as exc:
            QMessageBox.critical(self, "AI 生成不可用", str(exc))

    def _open_catalog(self) -> None:
        dlg = CatalogDialog(self.project.profile_id, self, select_mode=False)
        dlg.exec()
        dlg.deleteLater()

    def _open_logs(self) -> None:
        try:
            from ..core.crashlog import logs_dir

            self._open_folder(logs_dir(), "无法打开日志目录")
        except Exception as exc:
            QMessageBox.warning(self, "无法打开日志目录", str(exc))

    def _center_tab_changed(self, idx: int) -> None:
        if idx < 0:
            idx = self.center_tabs.checkedId()
        if not hasattr(self, "center_stack"):
            return
        self.center_stack.setCurrentIndex(idx)
        if hasattr(self, "details_btn"):
            self.details_btn.setVisible(idx == 1)
            available = getattr(self, "_inspector_available", self.width() >= 1280)
            self.details_btn.setEnabled(idx == 1 and available)
            self.details_btn.setToolTip(
                "当前宽度不足以显示详情；放大窗口或收起侧栏后可打开。"
                if not available else "显示/隐藏任务详情（规则页）"
            )
        if hasattr(self, "inspector"):
            available = getattr(self, "_inspector_available", self.width() >= 1280)
            self.inspector.setVisible(idx == 1 and available and self._inspector_open)
        if idx == 0:
            self.center_header.eyebrow.setText("// OVERVIEW")
            self.center_header.title.setText("总览")
            self._refresh_overview()
            if hasattr(self, "overview"):
                self.overview.play_entrance()
        elif idx == 1:
            self.center_header.eyebrow.setText("// RULES")
            self.center_header.title.setText("规则工作台")
            self._refresh_inspector()
        elif idx == 2:
            self.center_header.eyebrow.setText("// EXECUTION")
            self.center_header.title.setText("执行图")
            self._render_graph()

    def _show_center_tab(self, idx: int) -> None:
        btn = {0: self.tab_overview, 1: self.tab_rules, 2: self.tab_graph}.get(idx)
        if btn is not None:
            btn.setChecked(True)
        if self.center_stack.currentIndex() != idx:
            self.center_stack.setCurrentIndex(idx)
        else:
            self._center_tab_changed(idx)

    def _show_graph(self) -> None:
        self._show_center_tab(2)

    def _show_task_graph(self, task_id: str) -> None:
        if self.project.task_by_id(task_id):
            self.project.active_task_id = task_id
            self._refresh_all()
            self._show_center_tab(2)

    def _toggle_inspector(self) -> None:
        if not getattr(self, "_inspector_available", False):
            self._toast_msg("当前宽度不足：请放大窗口或收起侧栏后打开详情")
            return
        if self.center_stack.currentIndex() != 1:
            self._show_center_tab(1)
        self._inspector_open = not self._inspector_open
        self.inspector.setVisible(self._inspector_open)
        self.details_btn.setProperty("active", self._inspector_open)
        self.details_btn.variant = "attention" if self._inspector_open else "ghost"
        self.details_btn.update()
        self.details_btn.style().unpolish(self.details_btn)
        self.details_btn.style().polish(self.details_btn)
        if self._inspector_open:
            self._refresh_inspector()


    def _refresh_overview(self) -> None:
        if not hasattr(self, "overview"):
            return
        profile = self.project.profile.label if self.project.profile else ""
        self.overview.set_state(
            self.project,
            self.validation,
            self.estimate,
            self.code,
            list(self.activity),
            str(self.project_path) if self.project_path else "",
            profile,
            self.dirty,
        )

    def _refresh_inspector(self) -> None:
        if not hasattr(self, "inspector"):
            return
        task = self.project.active_task()
        idx = self.project.tasks.index(task) if task in self.project.tasks else 0
        batch = self.graph_panel.current_batch_index() if hasattr(self, "graph_panel") else 0
        self.inspector.set_task(task, idx, batch)

    def _record_activity(self, title: str, detail: str = "", kind: str = "INFO") -> None:
        self.activity.appendleft((title, detail, kind))
        try:
            crashlog.log_event(f"activity[{kind}] {title} :: {detail}")
        except Exception:
            pass
        self._refresh_overview()

    def _open_command_palette(self) -> None:
        commands = [
            Command("总览", "查看工程健康、TPS 与最近活动", "layout-dashboard", "", lambda: self._show_center_tab(0), "NAVIGATE"),
            Command("规则工作台", "查看和筛选全部规则", "list", "", lambda: self._show_center_tab(1), "NAVIGATE"),
            Command("执行图", "查看当前任务的执行链路", "workflow", "", lambda: self._show_graph(), "NAVIGATE"),
            Command("新建规则", "打开任务编辑器创建规则", "plus", "", self._new_task, "BUILD"),
            Command("新建会话", "在默认工作区创建独立工程", "file-plus", "Ctrl N", self._new_session_default, "BUILD"),
            Command("模板库", "从已验证的 SFM 模板开始", "layout-template", "", self._open_templates, "BUILD"),
            Command("资源库", "搜索 items / 方块 ID", "package", "", self._open_catalog, "REFERENCE"),
            Command("标签库", "管理取送标签", "tag", "", self._open_label_library, "REFERENCE"),
            Command("本地校验", "重新运行 L0 / L1 校验", "list-checks", "F5", self._check, "VERIFY"),
            Command("复制代码", "复制当前生成的 SFML", "copy", "", self._copy, "VERIFY"),
            Command("导出 .sfm", "导出可直接导入的文件", "arrow-up-from-line", "Ctrl E", self._export, "VERIFY"),
            Command("AI 生成", "可选联网，默认关闭", "sparkles", "", self._open_ai, "OPTIONAL"),
            Command("设置", "主题、动效与 AI 配置", "gear", "Ctrl ,", self._open_settings, "SYSTEM"),
            Command("打开日志目录", "运行日志与崩溃报告", "folder-open", "", self._open_logs, "SYSTEM"),
            Command("切换主题", "浅色 / 深色", "sun", "", self._toggle_theme, "SYSTEM"),
            Command("专注模式", "隐藏侧栏与代码面板", "focus", "Ctrl Shift F", self._toggle_focus_mode, "SYSTEM"),
            Command("详情面板", "显示 / 隐藏当前规则详情", "panel-right", "", self._toggle_inspector, "SYSTEM"),
            Command("切换侧栏", "给规则或代码更多横向空间", "panel-left-open", "Ctrl B", self._toggle_sidebar, "SYSTEM"),
        ]
        dlg = CommandPaletteDialog(commands, self)
        dlg.exec()
        dlg.deleteLater()

    def _toggle_focus_mode(self) -> None:
        self._focus_mode = not self._focus_mode
        self.sidebar.setVisible(not self._focus_mode)
        self.right_panel.setVisible(not self._focus_mode)
        self.center_head.setVisible(not self._focus_mode)
        self.project_bar.setVisible(not self._focus_mode)
        self.inline_status.setVisible(not self._focus_mode)
        self._toast_msg("专注模式：开" if self._focus_mode else "专注模式：关")

    def _duplicate_task(self, task_id: str) -> None:
        task = self.project.task_by_id(task_id)
        if not task:
            return
        self._push_undo()
        clone = copy.deepcopy(task)
        clone.id = new_id("task")
        clone.name = unique_name(task.name + " 副本", {t.name for t in self.project.tasks})
        idx = self.project.tasks.index(task)
        self.project.tasks.insert(idx + 1, clone)
        self.project.active_task_id = clone.id
        self._mark_dirty()
        self._refresh_all()
        self._record_activity("复制规则", clone.name, "BUILD")
        self._toast_msg("已复制规则")

    def _toggle_task(self, task_id: str) -> None:
        task = self.project.task_by_id(task_id)
        if not task:
            return
        self._push_undo()
        task.enabled = not task.enabled
        self._mark_dirty()
        self._refresh_all()
        self._record_activity("规则启停", f"{task.name} · {'启用' if task.enabled else '停用'}", "BUILD")

    def _toast_msg(self, text: str) -> None:
        if not self._toast:
            self._toast = Toast(self.centralWidget())
        self._toast.show_message(text)
        self._toast_position()

    def _toast_position(self) -> None:
        if self._toast and self._toast.isVisible():
            parent = self.centralWidget()
            if parent:
                self._toast.move(
                    max(10, (parent.width() - self._toast.width()) // 2),
                    max(10, parent.height() - self._toast.height() - 48),
                )

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._toast_position()
        self._apply_responsive_layout()

    def _apply_responsive_layout(self) -> None:
        w = self.width()
        if not hasattr(self, "right_panel"):
            return
        sidebar_visible = self._sidebar_open
        if not sidebar_visible:
            sidebar_w = 0
        elif w < 1280:
            sidebar_w = 220
        elif w < 1440:
            sidebar_w = 232
        else:
            sidebar_w = 248
        right_w = 320 if w < 1280 else (360 if w < 1440 else 400)
        if self.sidebar.width() != sidebar_w and sidebar_visible:
            self.sidebar.setFixedWidth(sidebar_w)
        if self.right_panel.width() != right_w:
            self.right_panel.setFixedWidth(right_w)
        center_w = max(0, w - sidebar_w - right_w - 2)
        self._inspector_available = center_w >= 700
        self.details_btn.setEnabled(bool(self._inspector_available))
        self.details_btn.setToolTip(
            "详情面板需要至少 700px 的内容区宽度" if not self._inspector_available
            else "显示/隐藏任务详情（规则页）"
        )
        if not self._inspector_available and self.inspector.isVisible():
            # Keep _inspector_open: restoring width should restore the panel.
            self.inspector.hide()
        elif self._inspector_available and self._inspector_open and self.center_stack.currentIndex() == 1:
            self.inspector.show()
        if hasattr(self, "overview"):
            self.overview.set_compact(center_w < 760)
        if hasattr(self, "command"):
            self.command.sidebar_btn.setVisible(not sidebar_visible)

    def _toggle_sidebar(self) -> None:
        self._sidebar_open = not self._sidebar_open
        self.sidebar.setVisible(self._sidebar_open)
        self._apply_responsive_layout()
        self._toast_msg("侧栏已收起" if not self._sidebar_open else "侧栏已展开")


    def closeEvent(self, event) -> None:  # noqa: N802
        try:
            self._commit_project_name()
            if hasattr(self, "_autosave_timer"):
                self._autosave_timer.stop()
            if self.dirty:
                ret = QMessageBox.question(
                    self,
                    "保存工程？",
                    "工程有未保存的修改。要保存再退出吗？",
                    QMessageBox.StandardButton.Save
                    | QMessageBox.StandardButton.Discard
                    | QMessageBox.StandardButton.Cancel,
                )
                if ret == QMessageBox.StandardButton.Cancel:
                    event.ignore()
                    return
                if ret == QMessageBox.StandardButton.Save:
                    self._save_project()
                    if self.dirty:
                        event.ignore()
                        return
                elif ret == QMessageBox.StandardButton.Discard:
                    # "Discard" must not be resurrected as a recovery draft.
                    try:
                        autosave_path().unlink(missing_ok=True)
                    except Exception:
                        pass
                    self.dirty = False
            save_settings(self.settings)
        except Exception:
            pass
        super().closeEvent(event)
