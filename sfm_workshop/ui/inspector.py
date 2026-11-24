"""Contextual task inspector used beside the rule list."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..core.model import Task
from . import theme as theme_mod
from .icons import icon as svg_icon
from .theme import mono_font, ui_font
from .widgets import CutButton


class TaskInspector(QFrame):
    editRequested = Signal(str)
    graphRequested = Signal(str)
    duplicateRequested = Signal(str)
    toggleRequested = Signal(str)
    deleteRequested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Inspector")
        self.setMinimumWidth(232)
        self.setMaximumWidth(264)
        self._task: Task | None = None
        self._batch_index = 0
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(8)
        head = QHBoxLayout()
        e = QLabel("// INSPECT")
        e.setObjectName("Eyebrow")
        e.setFont(mono_font(8))
        head.addWidget(e)
        head.addStretch(1)
        self.index = QLabel("01")
        self.index.setObjectName("MiniBadge")
        self.index.setFont(mono_font(8))
        head.addWidget(self.index)
        lay.addLayout(head)
        self.title = QLabel("未选择规则")
        self.title.setObjectName("InspectorTitle")
        self.title.setFont(ui_font(15, QFont.Weight.Bold))
        self.title.setWordWrap(True)
        lay.addWidget(self.title)
        self.status = QLabel("LOCAL / READY")
        self.status.setObjectName("MiniBadge")
        self.status.setFont(mono_font(10))
        self.status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status.setFixedHeight(18)
        self.status.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        lay.addWidget(self.status, 0, Qt.AlignmentFlag.AlignLeft)
        self.summary = QLabel("")
        self.summary.setObjectName("Muted")
        self.summary.setWordWrap(True)
        self.summary.setFont(ui_font(9))
        lay.addWidget(self.summary)
        self.stats = QVBoxLayout()
        self.stats.setSpacing(2)
        lay.addLayout(self.stats)
        actions = QGridLayout()
        actions.setHorizontalSpacing(4)
        actions.setVerticalSpacing(4)
        self.edit_btn = CutButton("编辑", "ghost", True)
        self.edit_btn.setIcon(svg_icon("pen", theme_mod.current().ink, 13))
        self.edit_btn.clicked.connect(self._edit)
        actions.addWidget(self.edit_btn, 0, 0)
        self.graph_btn = CutButton("图谱", "ghost", True)
        self.graph_btn.setIcon(svg_icon("workflow", theme_mod.current().ink, 13))
        self.graph_btn.clicked.connect(self._graph)
        actions.addWidget(self.graph_btn, 0, 1)
        self.dup_btn = CutButton("复制", "ghost", True)
        self.dup_btn.setIcon(svg_icon("copy", theme_mod.current().ink, 13))
        self.dup_btn.clicked.connect(self._duplicate)
        actions.addWidget(self.dup_btn, 1, 0)
        self.toggle_btn = CutButton("停用", "quiet", True)
        self.toggle_btn.clicked.connect(self._toggle)
        actions.addWidget(self.toggle_btn, 1, 1)
        self.delete_btn = CutButton("删除", "danger", True)
        self.delete_btn.setIcon(svg_icon("trash", theme_mod.current().danger, 13))
        self.delete_btn.clicked.connect(self._delete)
        actions.addWidget(self.delete_btn, 2, 0, 1, 2)
        lay.addLayout(actions)
        lay.addStretch(1)
        self._set_buttons(False)

    def _set_buttons(self, on: bool) -> None:
        for b in (self.edit_btn, self.graph_btn, self.dup_btn, self.toggle_btn, self.delete_btn):
            b.setEnabled(on)

    def refresh_theme(self) -> None:
        t = theme_mod.current()
        self.edit_btn.setIcon(svg_icon("pen", t.ink, 13))
        self.graph_btn.setIcon(svg_icon("workflow", t.ink, 13))
        self.dup_btn.setIcon(svg_icon("copy", t.ink, 13))
        self.delete_btn.setIcon(svg_icon("trash", t.danger, 13))

    def set_task(self, task: Task | None, index: int = 0, batch_index: int = 0) -> None:
        self._task = task
        self._batch_index = max(0, batch_index)
        while self.stats.count():
            item = self.stats.takeAt(0)
            if item.widget():
                w = item.widget()
                w.hide()
                w.setParent(None)
                w.deleteLater()
        if task is None:
            self.index.setText("—")
            self.title.setText("未选择规则")
            self.summary.setText("从左侧选择一条规则，或者新建规则。")
            self.status.setText("无规则")
            self.status.setProperty("tone", "idle")
            self.toggle_btn.setText("停用")
            self._set_buttons(False)
            self._polish_status()
            return
        self._set_buttons(True)
        self.index.setText(f"{index + 1:02d}")
        self.title.setText(task.name)
        trigger = "红石脉冲" if task.trigger_kind == "pulse" else f"每 {task.interval} {'秒' if task.unit == 'SECONDS' else 'tick'}"
        batches = len(task.batches)
        batch_no = min(self._batch_index, max(0, batches - 1))
        take = task.batches[batch_no].take if task.batches else None
        sends = sum(len(b.sends) for b in task.batches)
        self.summary.setText(f"{trigger} · {batches} 批次 · {sends} 送")
        self.status.setText("已启用" if task.enabled else "已停用")
        self.status.setProperty("tone", "ok" if task.enabled else "warn")
        self.toggle_btn.setText("停用" if task.enabled else "启用")
        self._polish_status()
        for k, v in (
            ("TRIGGER", trigger),
            ("TAKE", f"{take.source if take else '—'} / {take.side if take else '—'}"),
            ("QTY", str(take.quantity if take else 0)),
            ("CLEAR", "on" if task.batches and task.batches[batch_no].clear else "off"),
        ):
            row = QFrame()
            row.setObjectName("InspectRow")
            rl = QHBoxLayout(row)
            rl.setContentsMargins(0, 4, 0, 4)
            rl.setSpacing(8)
            key = QLabel(k)
            key.setObjectName("MonoMuted")
            key.setFont(mono_font(10))
            key.setFixedWidth(52)
            val = QLabel(v)
            val.setObjectName("InspectValue")
            val.setFont(ui_font(10))
            val.setWordWrap(True)
            val.setMinimumWidth(0)
            rl.addWidget(key)
            rl.addWidget(val, 1)
            self.stats.addWidget(row)

    def _polish_status(self) -> None:
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)

    def _edit(self) -> None:
        if self._task:
            self.editRequested.emit(self._task.id)

    def _graph(self) -> None:
        if self._task:
            self.graphRequested.emit(self._task.id)

    def _duplicate(self) -> None:
        if self._task:
            self.duplicateRequested.emit(self._task.id)

    def _toggle(self) -> None:
        if self._task:
            self.toggleRequested.emit(self._task.id)

    def _delete(self) -> None:
        if self._task:
            self.deleteRequested.emit(self._task.id)
