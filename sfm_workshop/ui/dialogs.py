"""Dialogs: task editor, labels, templates, AI generation, settings, about."""
from __future__ import annotations

from pathlib import Path
import os
import queue
import sys
import threading
import time
from typing import Any

from PySide6.QtCore import QTimer, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QFont, QPainter
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..core.model import (
    LABEL_KINDS,
    RESOURCE_TYPES,
    SIDES,
    TRIGGER_UNITS,
    Batch,
    Label,
    Project,
    Send,
    Task,
)
from . import theme as theme_mod
from .face_picker import FacePickerDialog
from .icons import apply_search_icon, theme_icon
from .theme import mono_font, ui_font
from .widgets import CutButton, ScrubSpinBox, Toast


def _hint(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("Muted")
    lbl.setFont(ui_font(9))
    lbl.setWordWrap(True)
    return lbl


def _line(text: str = "") -> QLineEdit:
    w = QLineEdit(text)
    return w


def _label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setFont(ui_font(10, QFont.Weight.DemiBold))
    return lbl


class SendRow(QWidget):
    removeRequested = Signal(object)

    def __init__(self, labels: list[str], target: str = "", side: str = "默认面", retain: int = 0, parent=None) -> None:
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(5)
        self.target = QComboBox()
        self.target.setEditable(True)
        self.target.setPlaceholderText("目标标签 / 方块")
        self.target.addItems(labels)
        if target:
            self.target.setCurrentText(target)
        self.side = QComboBox()
        self.side.addItems(SIDES)
        self.side.setToolTip(
            "上/下=世界垂直面；东/西/南/北=固定世界方向；"
            "前/后/左/右=相对目标方块 facing（不是玩家视角）。"
        )
        if side in SIDES:
            self.side.setCurrentText(side)
        self.retain = ScrubSpinBox()
        self.retain.setRange(0, 999999)
        self.retain.setValue(max(0, int(retain)))
        self.retain.setPrefix("保留 ")
        self.retain.setToolTip("0 = 不写 RETAIN；拖动数字可快速调整")
        self.retain.setFixedWidth(78)
        face = CutButton("面", "ghost", True)
        face.setFixedWidth(30)
        face.setIcon(theme_icon("compass", muted=False, size=12))
        face.setToolTip("选择方块面")
        face.clicked.connect(self._pick_face)
        rm = CutButton("", "danger", True)
        rm.setFixedWidth(28)
        rm.setIcon(theme_icon("x", muted=False, size=13))
        rm.setToolTip("移除这条送目标")
        rm.clicked.connect(lambda: self.removeRequested.emit(self))
        lay.addWidget(self.target, 1)
        lay.addWidget(self.side, 0)
        lay.addWidget(face, 0)
        lay.addWidget(self.retain, 0)
        lay.addWidget(rm, 0)

    def _pick_face(self) -> None:
        dlg = FacePickerDialog(self.side.currentText(), self)
        if dlg.exec():
            self.side.setCurrentText(dlg.selected_side)

    def values(self) -> tuple[str, str, int]:
        return self.target.currentText().strip(), self.side.currentText(), self.retain.value()


class TaskEditorDialog(QDialog):
    def __init__(self, project: Project, task: Task, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("编辑任务 / Task")
        self.resize(760, 700)
        self.project = project
        self.task = task
        self._batches: list[Batch] = [
            Batch.from_dict(b.to_dict()) for b in task.batches
        ] or [Batch()]
        self._batch_index = 0
        self._send_rows: list[SendRow] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 12)
        root.setSpacing(8)
        head = QLabel("// TASK / 任务")
        head.setObjectName("Eyebrow")
        root.addWidget(head)
        title = QLabel("把“何时、从哪取、送到哪”写成一句话")
        title.setFont(ui_font(17, QFont.Weight.Bold))
        root.addWidget(title)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget()
        form = QVBoxLayout(content)
        form.setContentsMargins(0, 4, 8, 4)
        form.setSpacing(8)
        scroll.setWidget(content)
        root.addWidget(scroll, 1)

        # trigger
        form.addWidget(self._section("触发器 / TRIGGER"))
        g = QFormLayout()
        g.setHorizontalSpacing(12)
        g.setVerticalSpacing(6)
        self.name = _line(task.name)
        self.kind = QComboBox()
        self.kind.addItems(["每 N tick", "红石脉冲"])
        self.kind.setCurrentIndex(1 if task.trigger_kind == "pulse" else 0)
        self.interval = ScrubSpinBox()
        self.interval.setRange(1, 999999)
        self.interval.setValue(max(1, task.interval))
        self.interval.setToolTip("单击输入；左右拖动可快速调整（Shift 加速）")
        self.unit = QComboBox()
        self.unit.addItems(TRIGGER_UNITS)
        self.unit.setCurrentText(task.unit)
        g.addRow(_label("任务名"), self.name)
        g.addRow(_label("触发器"), self.kind)
        trig_row = QWidget()
        tr = QHBoxLayout(trig_row)
        tr.setContentsMargins(0, 0, 0, 0)
        tr.setSpacing(5)
        tr.addWidget(self.interval)
        tr.addWidget(self.unit)
        tr.addWidget(_hint("普通 ≥20 tick；纯能量 1 tick"))
        g.addRow(_label("间隔"), trig_row)
        form.addLayout(g)
        self.kind.currentIndexChanged.connect(self._sync_trigger)

        # batch selector; each batch is one TAKE -> SEND -> FORGET group
        form.addWidget(self._section("批次 / BATCHES"))
        batch_bar = QWidget()
        bb = QHBoxLayout(batch_bar)
        bb.setContentsMargins(0, 0, 0, 0)
        bb.setSpacing(5)
        bb.addWidget(_label("当前批次"))
        self.batch_combo = QComboBox()
        self.batch_combo.setMinimumWidth(150)
        self.batch_combo.currentIndexChanged.connect(self._switch_batch)
        bb.addWidget(self.batch_combo)
        self.batch_add = CutButton("批次", "ghost", True)
        self.batch_add.setIcon(theme_icon("plus", muted=False, size=12))
        self.batch_add.clicked.connect(self._add_batch)
        bb.addWidget(self.batch_add)
        self.batch_del = CutButton("删除批次", "danger", True)
        self.batch_del.setIcon(theme_icon("trash", muted=False, size=12))
        self.batch_del.clicked.connect(self._remove_batch)
        bb.addWidget(self.batch_del)
        bb.addStretch(1)
        form.addWidget(batch_bar)
        form.addWidget(_hint("一个触发器可以包含多个批次；每个批次 = 取 → 送 → 清空/条件。"))

        b0 = self._batch()
        # take
        form.addWidget(self._section("取 / TAKE"))
        g2 = QFormLayout()
        g2.setHorizontalSpacing(12)
        g2.setVerticalSpacing(6)
        self.source = QComboBox()
        self.source.setEditable(True)
        self.source.addItems(project.label_names())
        self.source.setCurrentText(b0.take.source)
        self.side = QComboBox()
        self.side.addItems(SIDES)
        self.side.setToolTip(
            "上/下=世界垂直面；东/西/南/北=固定世界方向；"
            "前/后/左/右=相对目标方块 facing（不是玩家视角）。"
        )
        self.side.setCurrentText(b0.take.side)
        self.rtype = QComboBox()
        self.rtype.addItems(RESOURCE_TYPES)
        self.rtype.setCurrentText(b0.take.resource_type)
        self.resource_type = self.rtype
        self.rid = _line(b0.take.resource_id)
        self.rid.setPlaceholderText("可留空；例 minecraft:iron_ingot")
        rid_row = QWidget()
        rl = QHBoxLayout(rid_row)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(5)
        rl.addWidget(self.rid, 1)
        catalog_btn = CutButton("资源库", "ghost", True)
        catalog_btn.setIcon(theme_icon("package", muted=False, size=13))
        catalog_btn.clicked.connect(self._open_catalog)
        rl.addWidget(catalog_btn)
        self.qty = ScrubSpinBox()
        self.qty.setRange(0, 999999)
        self.qty.setValue(b0.take.quantity)
        self.qty.setSpecialValueText("全部")
        self.qty.setToolTip("单击输入；左右拖动可快速调整（Shift 加速）")
        self.retain = ScrubSpinBox()
        self.retain.setRange(0, 999999)
        self.retain.setValue(b0.take.retain)
        self.retain.setSpecialValueText("不写")
        self.retain.setToolTip("单击输入；左右拖动可快速调整（Shift 加速）")
        self.with_filter = _line(b0.take.with_filter)
        self.with_filter.setPlaceholderText("只取匹配的标签/ID，例 #forge:ingots 或 minecraft:iron_ingot")
        self.without_filter = _line(b0.take.without_filter)
        self.without_filter.setPlaceholderText("取时排除匹配项，例 minecraft:gold_ingot")
        source_box = QWidget()
        sb = QHBoxLayout(source_box)
        sb.setContentsMargins(0, 0, 0, 0)
        sb.setSpacing(5)
        sb.addWidget(self.source, 1)
        source_lib = CutButton("标签库", "ghost", True)
        source_lib.setIcon(theme_icon("tag", muted=False, size=13))
        source_lib.clicked.connect(self._open_source_library)
        sb.addWidget(source_lib)
        g2.addRow(_label("来源标签"), source_box)
        face_row = QWidget()
        fr = QHBoxLayout(face_row)
        fr.setContentsMargins(0, 0, 0, 0)
        fr.setSpacing(5)
        fr.addWidget(self.side, 1)
        face_btn = CutButton("选择面", "ghost", True)
        face_btn.setIcon(theme_icon("compass", muted=False, size=13))
        face_btn.clicked.connect(self._open_face_picker)
        fr.addWidget(face_btn)
        g2.addRow(_label("取面"), face_row)
        g2.addRow(_label("资源类型"), self.rtype)
        g2.addRow(_label("资源 ID"), rid_row)
        qrow = QWidget()
        ql = QHBoxLayout(qrow)
        ql.setContentsMargins(0, 0, 0, 0)
        ql.setSpacing(8)
        qty_box = QWidget()
        qv = QVBoxLayout(qty_box)
        qv.setContentsMargins(0, 0, 0, 0)
        qv.setSpacing(2)
        qv.addWidget(_hint("取多少"))
        qv.addWidget(self.qty)
        retain_box = QWidget()
        rv = QVBoxLayout(retain_box)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.setSpacing(2)
        rv.addWidget(_hint("送出后保留"))
        rv.addWidget(self.retain)
        ql.addWidget(qty_box, 1)
        ql.addWidget(retain_box, 1)
        ql.addWidget(_hint("0 = 全部 / 不写 RETAIN"))
        g2.addRow(_label("数量"), qrow)
        g2.addRow(_label("包含过滤"), self.with_filter)
        g2.addRow(_label("排除过滤"), self.without_filter)
        form.addLayout(g2)

        # sends
        form.addWidget(self._section("送 / SEND"))
        form.addWidget(_hint("每行：目标标签 / 方块 · 面 · 保留数量"))
        self.send_box = QVBoxLayout()
        self.send_box.setSpacing(4)
        form.addLayout(self.send_box)
        add_send = CutButton("＋ 添加送", "ghost", True)
        add_send.setIcon(theme_icon("plus", muted=False, size=13))
        add_send.clicked.connect(lambda: self._add_send_row())
        form.addWidget(add_send)
        for s in b0.sends:
            self._add_send_row(s.target, s.side, s.retain)

        # clear/condition
        form.addWidget(self._section("清空 / 条件"))
        g3 = QFormLayout()
        g3.setHorizontalSpacing(12)
        g3.setVerticalSpacing(6)
        self.clear = QCheckBox("送出后自动 FORGET")
        self.clear.setChecked(b0.clear)
        self.condition = _line(b0.condition)
        self.condition.setPlaceholderText("可留空；例 redstone ge 1（IF ... THEN ... END）")
        g3.addRow(_label("清空"), self.clear)
        g3.addRow(_label("条件"), self.condition)
        form.addLayout(g3)
        form.addStretch(1)

        foot = QHBoxLayout()
        foot.addWidget(_hint("保存后仍要经过本地语法/语义检查；红色只用于删除。"))
        foot.addStretch(1)
        cancel = CutButton("取消", "ghost", True)
        cancel.clicked.connect(self.reject)
        ok = CutButton("保存任务", "primary", True)
        ok.clicked.connect(self._accept)
        foot.addWidget(cancel)
        foot.addWidget(ok)
        root.addLayout(foot)
        self._sync_trigger()
        self._refresh_batch_combo()

    def _section(self, text: str) -> QWidget:
        icon_name = {
            "触发器": "timer",
            "批次": "layers",
            "取": "package-open",
            "送": "send",
            "清空": "eraser",
        }.get(text.split(" ")[0], "list")
        box = QWidget()
        lay = QHBoxLayout(box)
        lay.setContentsMargins(0, 8, 0, 0)
        lay.setSpacing(5)
        icon = QLabel()
        icon.setFixedSize(13, 13)
        icon.setPixmap(theme_icon(icon_name, muted=True, size=12).pixmap(12, 12))
        lay.addWidget(icon, 0, Qt.AlignmentFlag.AlignVCenter)
        label = QLabel(text)
        label.setObjectName("Eyebrow")
        label.setFont(ui_font(9, QFont.Weight.Bold))
        lay.addWidget(label, 0, Qt.AlignmentFlag.AlignVCenter)
        lay.addStretch(1)
        return box

    def _batch(self) -> Batch:
        if not self._batches:
            self._batches.append(Batch())
        self._batch_index = max(0, min(self._batch_index, len(self._batches) - 1))
        return self._batches[self._batch_index]

    def _refresh_batch_combo(self) -> None:
        if not hasattr(self, "batch_combo"):
            return
        self.batch_combo.blockSignals(True)
        self.batch_combo.clear()
        for i in range(len(self._batches)):
            self.batch_combo.addItem(f"批次 {i + 1} / {len(self._batches)}")
        self.batch_combo.setCurrentIndex(self._batch_index)
        self.batch_combo.blockSignals(False)
        if hasattr(self, "batch_del"):
            self.batch_del.setEnabled(len(self._batches) > 1)

    def _switch_batch(self, index: int) -> None:
        if index < 0 or index == self._batch_index:
            return
        self._sync_current_batch()
        self._batch_index = max(0, min(index, len(self._batches) - 1))
        self._load_batch()

    def _load_batch(self) -> None:
        b = self._batch()
        if self.source.findText(b.take.source) < 0 and b.take.source:
            self.source.addItem(b.take.source)
        self.source.setCurrentText(b.take.source)
        self.side.setCurrentText(b.take.side)
        self.rtype.setCurrentText(b.take.resource_type)
        self.rid.setText(b.take.resource_id)
        self.qty.setValue(int(b.take.quantity))
        self.retain.setValue(int(b.take.retain))
        self.with_filter.setText(b.take.with_filter)
        self.without_filter.setText(b.take.without_filter)
        self.clear.setChecked(b.clear)
        self.condition.setText(b.condition)
        while self._send_rows:
            row = self._send_rows.pop()
            row.setParent(None)
            row.deleteLater()
        for s in b.sends:
            self._add_send_row(s.target, s.side, s.retain)
        self._refresh_batch_combo()

    def _sync_current_batch(self) -> None:
        b = self._batch()
        b.take.source = self.source.currentText().strip()
        b.take.side = self.side.currentText()
        b.take.resource_type = self.rtype.currentText()
        b.take.resource_id = self.rid.text().strip()
        b.take.quantity = int(self.qty.value())
        b.take.retain = int(self.retain.value())
        b.take.with_filter = self.with_filter.text().strip()
        b.take.without_filter = self.without_filter.text().strip()
        b.sends = [
            Send(target=target, side=side, retain=int(retain))
            for target, side, retain in (r.values() for r in self._send_rows)
            if target
        ]
        b.clear = self.clear.isChecked()
        b.condition = self.condition.text().strip()

    def _add_batch(self) -> None:
        self._sync_current_batch()
        self._batches.append(Batch())
        self._batch_index = len(self._batches) - 1
        self._load_batch()
        self._refresh_batch_combo()

    def _remove_batch(self) -> None:
        if len(self._batches) <= 1:
            QMessageBox.information(self, "至少一个批次", "一个任务至少保留一个批次。")
            return
        self._sync_current_batch()
        self._batches.pop(self._batch_index)
        self._batch_index = min(self._batch_index, len(self._batches) - 1)
        self._load_batch()
        self._refresh_batch_combo()

    def _sync_trigger(self) -> None:
        pulse = self.kind.currentIndex() == 1
        self.interval.setEnabled(not pulse)
        self.unit.setEnabled(not pulse)

    def _open_face_picker(self) -> None:
        dlg = FacePickerDialog(self.side.currentText(), self)
        if dlg.exec():
            self.side.setCurrentText(dlg.selected_side)

    def _open_source_library(self) -> None:
        dlg = LabelLibraryDialog(self.project, self, select_mode=True)
        if dlg.exec() and dlg.selected_name:
            name = dlg.selected_name
            if self.source.findText(name) < 0:
                self.source.addItem(name)
            self.source.setCurrentText(name)

    def _open_catalog(self) -> None:
        dlg = CatalogDialog(self.project.profile_id, self)
        if dlg.exec() and dlg.selected_id:
            self.rid.setText(dlg.selected_id)

    def _add_send_row(self, target: str = "", side: str = "默认面", retain: int = 0) -> None:
        labels = self.project.label_names()
        row = SendRow(labels, target, side, retain)
        row.removeRequested.connect(self._remove_send)
        self._send_rows.append(row)
        self.send_box.addWidget(row)

    def _remove_send(self, row: SendRow) -> None:
        if row in self._send_rows:
            self._send_rows.remove(row)
            row.setParent(None)
            row.deleteLater()

    def _accept(self) -> None:
        if not self.name.text().strip():
            QMessageBox.warning(self, "缺少名称", "任务名不能为空。")
            return
        self._sync_current_batch()
        for i, batch in enumerate(self._batches, 1):
            if not batch.take.source.strip():
                QMessageBox.warning(self, "缺少来源", f"批次 {i} 还没有选择来源标签。")
                return
            if not any(s.target.strip() for s in batch.sends):
                QMessageBox.warning(self, "缺少目标", f"批次 {i} 至少需要一个送目标。")
                return
        self.task.name = self.name.text().strip()
        self.task.trigger_kind = "pulse" if self.kind.currentIndex() == 1 else "timer"
        self.task.interval = int(self.interval.value())
        self.task.unit = self.unit.currentText()
        self.task.batches = self._batches
        self.accept()


class LabelDialog(QDialog):
    def __init__(self, label: Label | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.label_obj = label
        self.setWindowTitle("标签 / Label")
        self.resize(440, 300)
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 12)
        root.setSpacing(8)
        e = QLabel("// LABEL / 设备标签")
        e.setObjectName("Eyebrow")
        root.addWidget(e)
        title = QLabel("标签是代码里引用的名字")
        title.setFont(ui_font(16, QFont.Weight.Bold))
        root.addWidget(title)
        form = QFormLayout()
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(7)
        self.name = _line(label.name if label else "")
        self.kind = QComboBox()
        self.kind.addItems(LABEL_KINDS)
        if label:
            self.kind.setCurrentText(label.kind if label.kind in LABEL_KINDS else "容器")
        self.note = _line(label.note if label else "")
        self.capacity = QSpinBox()
        self.capacity.setRange(0, 999999)
        self.capacity.setValue(label.capacity if label else 0)
        form.addRow(_label("名称"), self.name)
        form.addRow(_label("类型"), self.kind)
        form.addRow(_label("备注/面"), self.note)
        form.addRow(_label("容量"), self.capacity)
        root.addLayout(form)
        root.addWidget(_hint("标签只用于生成代码/清单，不会自动绑定游戏内方块。"))
        root.addStretch(1)
        foot = QHBoxLayout()
        foot.addStretch(1)
        cancel = CutButton("取消", "ghost", True)
        cancel.clicked.connect(self.reject)
        ok = CutButton("保存", "primary", True)
        ok.clicked.connect(self._accept)
        foot.addWidget(cancel)
        foot.addWidget(ok)
        root.addLayout(foot)

    def _accept(self) -> None:
        if not self.name.text().strip():
            QMessageBox.warning(self, "缺少名称", "标签名不能为空。")
            return
        self.accept()

    def value(self) -> tuple[str, str, str, int]:
        return (
            self.name.text().strip(),
            self.kind.currentText(),
            self.note.text().strip(),
            int(self.capacity.value()),
        )


class CatalogDialog(QDialog):
    """Searchable catalog modelled on SFM Zero Code Studio's resource picker."""

    def __init__(
        self,
        profile_id: str,
        parent: QWidget | None = None,
        select_mode: bool = True,
    ) -> None:
        super().__init__(parent)
        self.profile_id = profile_id
        self.select_mode = select_mode
        self.selected_id = ""
        self.entries = []
        self.info = None
        self.setWindowTitle("资源库 - SFM代码生成工坊")
        self.resize(700, 620)
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 14, 18, 12)
        root.setSpacing(7)

        eyebrow = QLabel("// CATALOG 资源库")
        eyebrow.setObjectName("Eyebrow")
        root.addWidget(eyebrow)
        title = QLabel("资源库")
        title.setFont(ui_font(19, QFont.Weight.Bold))
        root.addWidget(title)
        root.addWidget(
            _hint(
                "按中文名、拼音或物品 ID 搜索。导入游戏内 /sfm export_info false 生成的 "
                "items.json，可获得整合包完整目录；导入后会覆盖当前资源库。"
            )
        )

        cmd_row = QFrame()
        cmd_row.setObjectName("CommandRow")
        cr = QHBoxLayout(cmd_row)
        cr.setContentsMargins(10, 6, 10, 6)
        cr.setSpacing(8)
        command = CutButton("/sfm export_info false", "quiet", True)
        command.setObjectName("CommandChip")
        command.setToolTip("点击复制 /sfm export_info false")
        command.clicked.connect(self._copy_command)
        self.copy_btn = command
        cr.addWidget(command)
        cr.addStretch(1)
        copy_hint = _hint("点击指令即复制")
        cr.addWidget(copy_hint)
        root.addWidget(cmd_row)
        self.copy_hint = _hint(
            "复制后进入游戏聊天框执行；生成的 items.json 再从这里导入。"
        )
        # The search/list are the primary task. The command row above already
        # explains click-to-copy, so keep this guidance out of the first
        # viewport unless a copy/import action needs to report back.
        self.copy_hint.hide()

        search_row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索：铁锭 / tie ding / tieding / td / minecraft:iron_ingot")
        self.search.setClearButtonEnabled(True)
        apply_search_icon(self.search, "search", muted=True)
        self.search.textChanged.connect(self._refresh)
        search_row.addWidget(self.search, 1)
        root.addLayout(search_row)

        self.source = QLabel("")
        self.source.setObjectName("Muted")
        self.source.setFont(ui_font(9))
        root.addWidget(self.source)
        self.result_meta = QLabel("")
        self.result_meta.setObjectName("MonoMuted")
        self.result_meta.setFont(mono_font(10))
        root.addWidget(self.result_meta)

        self.list = QListWidget()
        self.list.setAlternatingRowColors(False)
        self.list.currentItemChanged.connect(self._on_current)
        self.list.itemDoubleClicked.connect(lambda _: self._accept())
        root.addWidget(self.list, 1)

        self.preview = QLabel("")
        self.preview.setObjectName("Muted")
        self.preview.setFont(ui_font(9))
        self.preview.setWordWrap(True)
        root.addWidget(self.preview)

        self.status = _hint("")
        root.addWidget(self.status)

        foot = QHBoxLayout()
        imp = CutButton("导入 items.json", "ghost", True)
        imp.clicked.connect(self._import)
        manual = CutButton("手动输入 ID", "ghost", True)
        manual.clicked.connect(self._manual)
        foot.addWidget(imp)
        foot.addWidget(manual)
        foot.addStretch(1)
        cancel = CutButton("取消", "ghost", True)
        cancel.clicked.connect(self.reject)
        self.use_btn = CutButton("使用此 ID" if select_mode else "复制 ID", "primary", True)
        self.use_btn.clicked.connect(self._accept)
        foot.addWidget(cancel)
        foot.addWidget(self.use_btn)
        root.addLayout(foot)

        self._load_entries()
        self._refresh()

    def _load_entries(self) -> None:
        from ..core.catalog import catalog_info, load_catalog

        try:
            self.entries = load_catalog(self.profile_id)
            self.info = catalog_info(self.profile_id)
            source = self.info.source
            self.source.setText(
                f"目录：{source} · {self.info.count} 项 · 离线可用"
            )
        except Exception as exc:
            self.entries = []
            self.info = None
            self.source.setText("目录：读取失败")
            self.status.setText(f"资源库读取失败：{exc}")

    def _refresh(self) -> None:
        from ..core.catalog import search_entries

        try:
            rows = search_entries(self.entries, self.search.text(), 300)
        except Exception as exc:
            self.status.setText(f"搜索失败：{exc}")
            rows = []
        self.list.clear()
        for entry in rows:
            item = QListWidgetItem(entry.display)
            item.setData(Qt.ItemDataRole.UserRole, entry.id)
            if entry.tags:
                item.setToolTip("标签：" + ", ".join(entry.tags[:12]))
            self.list.addItem(item)
        if self.info is not None:
            self.result_meta.setText(
                f"显示 {len(rows)} / {self.info.count} 项  ·  本地索引，不上传"
            )
        if self.list.count():
            self.list.setCurrentRow(0)
        if not self.search.text().strip():
            self.status.setText("可搜索中文名、拼音全拼、拼音首字母或完整 ID。")
        elif not rows:
            self.status.setText("没有匹配资源；可换关键词、手动输入 ID，或导入新的 items.json。")

    def _on_current(self, current, _previous=None) -> None:
        if current is None:
            self.preview.setText("")
            return
        rid = str(current.data(Qt.ItemDataRole.UserRole) or "")
        entry = next((e for e in self.entries if e.id == rid), None)
        tags = ("　标签：" + ", ".join(entry.tags[:5])) if entry and entry.tags else ""
        self.preview.setText(f"将写入：{rid}{tags}")

    def _copy_command(self) -> None:
        from PySide6.QtWidgets import QApplication

        cmd = "/sfm export_info false"
        QApplication.clipboard().setText(cmd)
        self.copy_hint.setText(
            "已复制 /sfm export_info false。去游戏内使用：进入存档，在聊天框执行，"
            "把生成的 items.json 带回这里导入。"
        )
        self.status.setText("指令已复制到剪贴板。")

    def _import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "导入 SFM items.json", "", "JSON (*.json);;所有文件 (*)")
        if not path:
            return
        try:
            from ..core.catalog import import_items

            entries = import_items(path, self.profile_id)
            self._load_entries()
            self._refresh()
            self.search.clear()
            self.status.setText(f"已导入并持久保存 {len(entries)} 条资源；新的导入会覆盖它。")
        except Exception as exc:
            QMessageBox.critical(
                self,
                "导入失败",
                "无法读取该 items.json，当前资源库保持不变。\n\n"
                "请确认文件来自游戏内 /sfm export_info false，且是有效 JSON。\n\n"
                f"{exc}",
            )

    def _manual(self) -> None:
        from PySide6.QtWidgets import QInputDialog

        text, ok = QInputDialog.getText(self, "手动输入资源 ID", "资源 ID：")
        if ok and text.strip():
            self.selected_id = text.strip()
            if not self.select_mode:
                from PySide6.QtWidgets import QApplication

                QApplication.clipboard().setText(self.selected_id)
                self.status.setText(f"已复制 ID：{self.selected_id}")
            self.accept()

    def _accept(self) -> None:
        item = self.list.currentItem()
        if item is None:
            self.status.setText("先选中一条资源，或手动输入 ID。")
            return
        self.selected_id = str(item.data(Qt.ItemDataRole.UserRole) or "")
        if not self.select_mode:
            from PySide6.QtWidgets import QApplication

            QApplication.clipboard().setText(self.selected_id)
            self.status.setText(f"已复制 ID：{self.selected_id}")
        self.accept()


class LabelLibraryDialog(QDialog):
    """Project label registry / picker.

    ``select_mode`` is used by the task editor's source-label button: it
    returns the clicked label name and closes.  The top workbench button opens
    the editable registry.
    """

    def __init__(
        self,
        project: Project,
        parent: QWidget | None = None,
        select_mode: bool = False,
    ) -> None:
        super().__init__(parent)
        self.project = project
        self.select_mode = select_mode
        self.selected_name = ""
        self._labels = [
            Label(id=x.id, name=x.name, kind=x.kind, note=x.note, capacity=x.capacity)
            for x in project.labels
        ]
        self._original_names = {x.id: x.name for x in project.labels}
        self.renames: dict[str, str] = {}
        self.setWindowTitle("标签库 - SFM代码生成工坊")
        self.resize(520, 560)
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 14, 18, 12)
        root.setSpacing(7)
        eyebrow = QLabel("// LABELS 标签库")
        eyebrow.setObjectName("Eyebrow")
        root.addWidget(eyebrow)
        title = QLabel("标签库")
        title.setFont(ui_font(19, QFont.Weight.Bold))
        root.addWidget(title)
        root.addWidget(
            _hint(
                "登记项目里使用的标签名；真正的位置仍由游戏内标签枪记录。"
                "重命名会同步更新任务中的来源/目标引用。"
            )
        )
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索标签")
        self.search.setClearButtonEnabled(True)
        apply_search_icon(self.search, "search", muted=True)
        self.search.textChanged.connect(self._refresh)
        root.addWidget(self.search)
        self.list = QListWidget()
        self.list.currentItemChanged.connect(self._on_current)
        self.list.itemDoubleClicked.connect(lambda _: self._accept())
        if select_mode:
            # The requested interaction: one click on a label fills the source
            # field and closes the picker.
            self.list.itemClicked.connect(lambda _: self._accept())
        root.addWidget(self.list, 1)
        self.preview = _hint("")
        root.addWidget(self.preview)
        self.status = _hint("")
        root.addWidget(self.status)

        tools = QHBoxLayout()
        if not select_mode:
            add = CutButton("＋ 新增", "ghost", True)
            add.clicked.connect(self._add)
            ren = CutButton("重命名", "ghost", True)
            ren.clicked.connect(self._rename)
            rem = CutButton("删除", "danger", True)
            rem.clicked.connect(self._remove)
            tools.addWidget(add)
            tools.addWidget(ren)
            tools.addWidget(rem)
        else:
            tips = _hint("点击标签即填入来源标签；没有需要的标签请先在“工作台 → 标签库”新增。")
            tools.addWidget(tips, 1)
        tools.addStretch(1)
        root.addLayout(tools)

        foot = QHBoxLayout()
        foot.addStretch(1)
        cancel = CutButton("取消", "ghost", True)
        cancel.clicked.connect(self.reject)
        use = CutButton("使用此标签" if select_mode else "保存", "primary", True)
        use.clicked.connect(self._accept)
        foot.addWidget(cancel)
        foot.addWidget(use)
        root.addLayout(foot)
        self._refresh()

    def _refresh(self) -> None:
        needle = self.search.text().strip().lower()
        self.list.clear()
        for label in self._labels:
            if needle and needle not in label.name.lower() and needle not in label.kind.lower():
                continue
            item = QListWidgetItem(f"{label.name}    ·  {label.kind}")
            item.setData(Qt.ItemDataRole.UserRole, label.id)
            self.list.addItem(item)
        if self.list.count():
            self.list.setCurrentRow(0)
        else:
            self.preview.setText("没有匹配标签。" if needle else "还没有标签；可点“新增”手动输入。")

    def _label_by_id(self, label_id: str) -> Label | None:
        return next((x for x in self._labels if x.id == label_id), None)

    def _on_current(self, current, _previous=None) -> None:
        if current is None:
            self.preview.setText("")
            return
        label = self._label_by_id(str(current.data(Qt.ItemDataRole.UserRole) or ""))
        if label is None:
            self.preview.setText("")
        else:
            note = f"　{label.note}" if label.note else ""
            self.preview.setText(f"{label.name} · {label.kind}{note}")

    def _add(self) -> None:
        from PySide6.QtWidgets import QInputDialog

        name, ok = QInputDialog.getText(self, "新增标签", "标签名（游戏内标签枪名称）：")
        if not ok or not name.strip():
            return
        name = name.strip()
        if any(x.name == name for x in self._labels):
            self.status.setText("标签已存在。")
            return
        self._labels.append(Label(name=name))
        self._refresh()
        self.status.setText(f"已新增：{name}")

    def _rename(self) -> None:
        from PySide6.QtWidgets import QInputDialog

        item = self.list.currentItem()
        if item is None:
            return
        label = self._label_by_id(str(item.data(Qt.ItemDataRole.UserRole) or ""))
        if label is None:
            return
        old = label.name
        name, ok = QInputDialog.getText(self, "重命名标签", "标签名：", text=old)
        if not ok or not name.strip() or name.strip() == old:
            return
        name = name.strip()
        if any(x.name == name and x.id != label.id for x in self._labels):
            self.status.setText("标签已存在。")
            return
        label.name = name
        original = self._original_names.get(label.id)
        if original == name:
            self.renames.pop(label.id, None)
        else:
            self.renames[label.id] = name
        self._refresh()
        self.status.setText(f"已重命名：{old} → {name}")

    def _remove(self) -> None:
        item = self.list.currentItem()
        if item is None:
            return
        label = self._label_by_id(str(item.data(Qt.ItemDataRole.UserRole) or ""))
        if label is None:
            return
        ret = QMessageBox.question(self, "删除标签", f"删除标签“{label.name}”？任务引用会保留并提示。")
        if ret != QMessageBox.StandardButton.Yes:
            return
        self._labels = [x for x in self._labels if x.id != label.id]
        self.renames.pop(label.id, None)
        self._refresh()

    def _accept(self) -> None:
        item = self.list.currentItem()
        if self.select_mode:
            if item is None:
                self.status.setText("先点击一个标签。")
                return
            label = self._label_by_id(str(item.data(Qt.ItemDataRole.UserRole) or ""))
            if label is None:
                return
            self.selected_name = label.name
        self.accept()

    def labels(self) -> list[Label]:
        return [Label(id=x.id, name=x.name, kind=x.kind, note=x.note, capacity=x.capacity) for x in self._labels]


class TemplateRow(QFrame):
    activated = Signal(str)

    def __init__(self, key: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.key = key
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.setFocus()
            self.activated.emit(self.key)
        super().mousePressEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.activated.emit(self.key)
            event.accept()
            return
        super().keyPressEvent(event)


class TemplateDialog(QDialog):
    chosen = Signal(str)

    def __init__(self, parent: QWidget | None = None, project: Project | None = None) -> None:
        super().__init__(parent)
        self.project = project
        self.setWindowTitle("模板库 / Templates")
        self.resize(680, 580)
        self._items: list[Any] = []
        self._rows: dict[str, QFrame] = {}
        self._create_btn: CutButton | None = None
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 12)
        root.setSpacing(8)
        e = QLabel("// TEMPLATES")
        e.setObjectName("Eyebrow")
        root.addWidget(e)
        title = QLabel("预制模板")
        title.setFont(ui_font(18, QFont.Weight.Bold))
        root.addWidget(title)
        sub = _hint("预制模板只读；用户模板在 user 目录。可导入/导出 .sfmproj；选一个创建会话。")
        root.addWidget(sub)

        self.list = QWidget()
        self.list_lay = QVBoxLayout(self.list)
        self.list_lay.setContentsMargins(0, 0, 0, 0)
        self.list_lay.setSpacing(3)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(self.list)
        root.addWidget(scroll, 1)

        divider = QFrame()
        divider.setObjectName("HLine")
        divider.setFixedHeight(1)
        root.addWidget(divider)

        foot = QHBoxLayout()
        self.info = _hint("")
        foot.addWidget(self.info, 1)
        import_btn = CutButton("导入模板", "ghost", True)
        import_btn.setIcon(theme_icon("download", muted=False, size=13))
        import_btn.clicked.connect(self._import_template)
        foot.addWidget(import_btn)
        if project is not None:
            export_btn = CutButton("导出模板", "ghost", True)
            export_btn.setIcon(theme_icon("arrow-up-from-line", muted=False, size=13))
            export_btn.clicked.connect(self._export_template)
            foot.addWidget(export_btn)
        cancel = CutButton("取消", "ghost", True)
        cancel.clicked.connect(self.reject)
        create = CutButton("载入模板", "primary", True)
        create.setIcon(theme_icon("plus", muted=False, size=13))
        create.clicked.connect(self._create)
        self._create_btn = create
        foot.addWidget(cancel)
        foot.addWidget(create)
        root.addLayout(foot)
        self._load()

    def _clear_list(self) -> None:
        while self.list_lay.count():
            item = self.list_lay.takeAt(0)
            if item.widget():
                widget = item.widget()
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()

    def _load(self) -> None:
        from ..core.templates import list_templates

        self._clear_list()
        self._rows.clear()
        try:
            items = list_templates()
        except Exception as exc:
            self.info.setText(f"模板加载失败：{exc}")
            return
        self._items = items
        if not items:
            empty = QFrame()
            empty.setObjectName("TemplateEmpty")
            el = QVBoxLayout(empty)
            el.setContentsMargins(8, 22, 8, 22)
            el.setSpacing(5)
            icon = QLabel()
            icon.setPixmap(theme_icon("layout-template", muted=True, size=24).pixmap(24, 24))
            icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
            el.addWidget(icon)
            label = QLabel("还没有模板。导入一个 .sfmproj，或从空白模板开始。")
            label.setObjectName("Muted")
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setWordWrap(True)
            el.addWidget(label)
            self.list_lay.addWidget(empty)
            if self._create_btn is not None:
                self._create_btn.setEnabled(False)
            self.list_lay.addStretch(1)
            return
        if self._create_btn is not None:
            self._create_btn.setEnabled(True)
        for it in items:
            row = TemplateRow(it.key)
            row.setObjectName("TemplateRow")
            row.setProperty("selected", False)
            rl = QHBoxLayout(row)
            rl.setContentsMargins(9, 7, 9, 7)
            rl.setSpacing(8)
            icon = QLabel()
            icon.setFixedSize(18, 18)
            icon.setPixmap(theme_icon("layout-template", muted=True, size=16).pixmap(16, 16))
            rl.addWidget(icon, 0, Qt.AlignmentFlag.AlignTop)
            col = QVBoxLayout()
            col.setSpacing(1)
            name = QLabel(it.name)
            name.setFont(ui_font(12, QFont.Weight.DemiBold))
            desc = QLabel(it.description)
            desc.setObjectName("Muted")
            desc.setFont(ui_font(10))
            desc.setWordWrap(True)
            col.addWidget(name)
            col.addWidget(desc)
            rl.addLayout(col, 1)
            tag = QLabel("预制" if it.builtin else "我的")
            tag.setObjectName("Eyebrow")
            rl.addWidget(tag, 0, Qt.AlignmentFlag.AlignTop)
            row.activated.connect(self._choose)
            self.list_lay.addWidget(row)
            self._rows[it.key] = row
        self.list_lay.addStretch(1)
        self._choose(items[0].key if items else "")

    def _choose(self, key: str) -> None:
        self._selected = key
        for row_key, row in self._rows.items():
            row.setProperty("selected", row_key == key)
            row.style().unpolish(row)
            row.style().polish(row)
        for it in self._items:
            if it.key == key:
                self.info.setText(f"将载入：{it.name}")
                break

    def _create(self) -> None:
        key = getattr(self, "_selected", "")
        if not key:
            return
        self.chosen.emit(key)

    def _import_template(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "导入模板", "", "SFM 工程/模板 (*.sfmproj);;所有文件 (*)"
        )
        if not path:
            return
        source = Path(path)
        if source.suffix.lower() != ".sfmproj":
            QMessageBox.warning(
                self,
                "导入模板失败",
                f"只能导入 .sfmproj 模板文件：\n{source}",
            )
            return
        try:
            from ..core.templates import load_template
            from ..core.storage import copy_template_to_user

            load_template(str(source))  # validate before copying
            target = copy_template_to_user(source)
            self._load()
            self._choose(target.stem)
            self.info.setText(f"已导入模板：{target.name}")
        except Exception as exc:
            QMessageBox.warning(
                self,
                "导入模板失败",
                f"文件无法导入为模板：\n{source}\n{exc}",
            )

    def _export_template(self) -> None:
        if self.project is None:
            return
        from ..core.storage import user_templates_dir

        safe = "".join(c for c in self.project.name if c not in '\\/:*?"<>|').strip() or "模板"
        default = user_templates_dir() / f"{safe}.sfmproj"
        path, _ = QFileDialog.getSaveFileName(
            self, "导出模板", str(default), "SFM 工程/模板 (*.sfmproj)"
        )
        if not path:
            return
        try:
            from ..core.templates import save_template

            out = save_template(self.project, Path(path))
            self.info.setText(f"已导出模板：{out.name}")
        except Exception as exc:
            QMessageBox.warning(
                self,
                "导出模板失败",
                f"模板无法写入：\n{path}\n{exc}",
            )


class CrashReportDialog(QDialog):
    """Shown on the first launch after an unclean shutdown."""

    def __init__(self, info: Any, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("上次运行未正常退出")
        self.resize(640, 370)
        self.info = info
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 12)
        root.setSpacing(8)
        head = QHBoxLayout()
        icon = QLabel()
        icon.setPixmap(theme_icon("triangle-alert", muted=False, size=26).pixmap(26, 26))
        head.addWidget(icon, 0, Qt.AlignmentFlag.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(3)
        title = QLabel("上次运行可能异常中断")
        title.setFont(ui_font(16, QFont.Weight.Bold))
        desc = QLabel(
            "已保留运行日志和崩溃现场信息，方便定位。日志只保存在本机，不会自动上传。"
        )
        desc.setObjectName("Muted")
        desc.setWordWrap(True)
        col.addWidget(title)
        col.addWidget(desc)
        head.addLayout(col, 1)
        root.addLayout(head)
        started = getattr(info, "previous_started", "未知")
        root.addWidget(_hint(f"上次启动时间：{started}"))

        paths = QPlainTextEdit()
        paths.setReadOnly(True)
        paths.setFont(mono_font(10))
        paths.setMinimumHeight(120)
        paths.setPlainText(
            "\n".join(
                [
                    f"运行日志：\n{getattr(info, 'runtime_log', '')}",
                    f"原生崩溃堆栈：\n{getattr(info, 'faulthandler_log', '')}",
                    f"最近崩溃报告：\n{getattr(info, 'crash_log', '')}",
                    f"日志目录：\n{getattr(info, 'logs_dir', '')}",
                ]
            )
        )
        root.addWidget(paths, 1)
        bottom = QHBoxLayout()
        copy = CutButton("复制路径", "ghost", True)
        copy.clicked.connect(lambda: self._copy_paths())
        open_dir = CutButton("打开日志文件夹", "ghost", True)
        open_dir.clicked.connect(self._open_folder)
        close = CutButton("知道了", "primary", True)
        close.clicked.connect(self.accept)
        bottom.addStretch(1)
        bottom.addWidget(copy)
        bottom.addWidget(open_dir)
        bottom.addWidget(close)
        root.addLayout(bottom)

    def _copy_paths(self) -> None:
        app = QApplication.instance()
        if app is not None:
            app.clipboard().setText(
                "\n".join(
                    [
                        getattr(self.info, "runtime_log", ""),
                        getattr(self.info, "faulthandler_log", ""),
                        getattr(self.info, "crash_log", ""),
                        getattr(self.info, "logs_dir", ""),
                    ]
                )
            )

    def _open_folder(self) -> None:
        folder = getattr(self.info, "logs_dir", "")
        if not folder:
            return
        opened = False
        try:
            opened = bool(QDesktopServices.openUrl(QUrl.fromLocalFile(folder)))
        except Exception:
            opened = False
        if not opened and sys.platform == "win32":
            try:
                os.startfile(folder)  # type: ignore[attr-defined]
                opened = True
            except Exception:
                opened = False
        if not opened:
            QMessageBox.warning(self, "无法打开日志目录", folder)


class AIStatusBar(QFrame):
    """Compact, real-state status bar for the optional AI request.

    Only known phases are marked; there is no invented percentage while the
    network request is pending.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("AIStatus")
        self._started = 0.0
        self._state = "idle"
        self._completed = 0
        self._active = -1
        lay = QHBoxLayout(self)
        lay.setContentsMargins(9, 5, 9, 5)
        lay.setSpacing(8)
        self.icon = QLabel()
        self.icon.setFixedSize(16, 16)
        lay.addWidget(self.icon, 0, Qt.AlignmentFlag.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(2)
        self.title = QLabel("AI 待命")
        self.title.setObjectName("AIStatusTitle")
        self.meta = QLabel("默认关闭 · 点生成后才联网")
        self.meta.setObjectName("Muted")
        self.meta.setFont(ui_font(9))
        col.addWidget(self.title)
        col.addWidget(self.meta)
        lay.addLayout(col, 1)
        self.phase = _PhaseBar()
        self.phase.setToolTip("请求 → 接收 → 本地 L0/L1 校验")
        lay.addWidget(self.phase, 0, Qt.AlignmentFlag.AlignVCenter)
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)
        self.set_state("idle")

    def set_state(self, state: str, title: str = "") -> None:
        self._state = state
        self.setProperty("state", state)
        self.style().unpolish(self)
        self.style().polish(self)
        icon_name = {
            "running": "sparkles",
            "review": "list-checks",
            "done": "circle-check",
            "warning": "triangle-alert",
            "error": "circle-x",
            "cancelled": "circle-pause",
        }.get(state, "sparkles")
        self.icon.setPixmap(theme_icon(icon_name, muted=state == "idle", size=14).pixmap(14, 14))
        if state == "running":
            self._started = time.monotonic()
            self.title.setText(title or "正在生成候选代码")
            self._completed, self._active = 0, 0
            self._timer.start()
        elif state == "review":
            self.title.setText(title or "正在做本地 L0/L1 校验")
            self._completed, self._active = 2, 2
            self._timer.start()
        elif state in ("done", "warning", "error", "cancelled"):
            self.title.setText(title)
            self._completed, self._active = (3, -1) if state == "done" else (0, -1)
            self._timer.stop()
        else:
            self.title.setText(title or "AI 待命")
            self._completed, self._active = 0, -1
            self._timer.stop()
        self.phase.set_progress(self._completed, self._active)
        if state in ("running", "review"):
            self._tick()
        else:
            self.meta.setText({
                "done": "候选未写入工程；请自行检查后复制",
                "warning": "缺少信息，补齐后可重新生成",
                "error": "请求未完成；查看下方原因",
                "cancelled": "后台结果会被忽略",
            }.get(state, "默认关闭 · 点生成后才联网"))

    def _tick(self) -> None:
        if self._state not in ("running", "review"):
            return
        elapsed = max(0, int(time.monotonic() - self._started))
        self.meta.setText(f"已等待 {elapsed}s · 取消不会杀死后台线程，但结果会被忽略")


class _PhaseBar(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.completed = 0
        self.active = -1
        self.setFixedSize(112, 8)

    def set_progress(self, completed: int, active: int) -> None:
        self.completed = completed
        self.active = active
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        t = theme_mod.current()
        p = QPainter(self)
        gap = 3
        width = (self.width() - gap * 2) // 3
        for i in range(3):
            color = t.rule
            if i < self.completed:
                color = t.ink
            elif i == self.active:
                color = t.signal
            p.fillRect(i * (width + gap), 1, width, 6, QColor(color))


class AIDialog(QDialog):
    def __init__(self, project: Project, app_settings, prompt_manager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("AI 生成 / 可选联网功能")
        self.resize(900, 560)
        self.project = project
        self.app_settings = app_settings
        self.prompt_manager = prompt_manager
        self.session_key = ""
        self._request_thread: threading.Thread | None = None
        self._request_queue: queue.Queue | None = None
        self._request_poll = QTimer(self)
        self._request_poll.setInterval(100)
        self._request_poll.timeout.connect(self._poll_ai_result)
        self.last_result = None
        self.candidate_validation = None
        self._cancel_requested = False
        self._ignore_result = False

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 10)
        root.setSpacing(7)
        head = QHBoxLayout()
        e = QLabel("// AI / 可选")
        e.setObjectName("Eyebrow")
        title = QLabel("AI 代码生成")
        title.setFont(ui_font(18, QFont.Weight.Bold))
        self.state = QLabel("默认关闭 · 只有点生成才联网")
        self.state.setObjectName("Muted")
        self.state.setFont(ui_font(9))
        head.addWidget(e)
        head.addWidget(title)
        head.addWidget(self.state)
        head.addStretch(1)
        root.addLayout(head)

        self.tabs = QTabWidget()
        root.addWidget(self.tabs, 1)
        self.tabs.addTab(self._build_settings(), "服务设置")
        self.tabs.addTab(self._build_prompt(), "提示词")
        self.tabs.addTab(self._build_generate(), "生成")
        foot = QHBoxLayout()
        note = _hint("候选代码不会自动改工程；复制或另存 .sfm 后自行导入游戏。")
        foot.addWidget(note, 1)
        close = CutButton("关闭", "ghost", True)
        close.clicked.connect(self.reject)
        foot.addWidget(close)
        root.addLayout(foot)
        self._load_key()
        self._load_prompt()
        self._load_settings()

    # ---- settings tab ----------------------------------------------------
    def _build_settings(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(6, 8, 6, 6)
        lay.setSpacing(7)
        form = QFormLayout()
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(7)
        self.base_url = _line(getattr(self.app_settings, "ai_base_url", "https://api.deepseek.com"))
        self.model = _line(getattr(self.app_settings, "ai_model", "deepseek-chat"))
        self.protocol = _line("DeepSeek 官方 API")
        self.protocol.setReadOnly(True)
        self.key = QLineEdit()
        self.key.setEchoMode(QLineEdit.EchoMode.Password)
        self.key.setPlaceholderText("sk-…（隐藏输入；不写入工程/日志）")
        form.addRow(_label("接口地址"), self.base_url)
        form.addRow(_label("协议"), self.protocol)
        form.addRow(_label("模型"), self.model)
        form.addRow(_label("API Key"), self.key)
        lay.addLayout(form)
        self.session_only = QCheckBox("仅本次会话（不保存 key）")
        lay.addWidget(self.session_only)
        notice = QLabel(
            "密钥隐藏显示，按 DeepSeek Harness 的凭据方式保存（工程只存引用，本机加密）。\n"
            "不写入 .sfmproj / .sfmkit / .sfm、日志、崩溃报告、分享包或导出文件。\n"
            "共享电脑请用“仅本次会话”模式。"
        )
        notice.setWordWrap(True)
        notice.setObjectName("Muted")
        notice.setFont(ui_font(9))
        lay.addWidget(notice)
        btns = QHBoxLayout()
        save = CutButton("保存密钥", "primary", True)
        save.clicked.connect(self._save_key)
        clear = CutButton("清除密钥", "ghost", True)
        clear.clicked.connect(self._clear_key)
        test = CutButton("检查配置", "ghost", True)
        test.setIcon(theme_icon("plugs-connected", muted=False, size=13))
        test.clicked.connect(self._test_connection)
        btns.addWidget(save)
        btns.addWidget(clear)
        btns.addWidget(test)
        btns.addStretch(1)
        lay.addLayout(btns)
        self.settings_status = _hint("")
        lay.addWidget(self.settings_status)
        lay.addStretch(1)
        return w

    # ---- prompt tab ------------------------------------------------------
    def _build_prompt(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(6, 8, 6, 6)
        lay.setSpacing(6)
        lay.addWidget(_hint("默认提示词只读；修改会保存为本地覆盖。‘恢复默认’会恢复内置原文。"))
        self.prompt_edit = QPlainTextEdit()
        self.prompt_edit.setFont(ui_font(10))
        lay.addWidget(self.prompt_edit, 1)
        btns = QHBoxLayout()
        reset = CutButton("恢复默认", "ghost", True)
        reset.clicked.connect(self._reset_prompt)
        save = CutButton("保存覆盖", "primary", True)
        save.clicked.connect(self._save_prompt)
        btns.addWidget(reset)
        btns.addWidget(save)
        btns.addStretch(1)
        self.prompt_status = _hint("")
        btns.addWidget(self.prompt_status)
        lay.addLayout(btns)
        return w

    # ---- generate tab ----------------------------------------------------
    def _build_generate(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(6, 8, 6, 6)
        lay.setSpacing(6)
        lay.addWidget(_label("你想要什么程序？"))
        self.request = QPlainTextEdit()
        self.request.setPlaceholderText("例：每 20 tick 从原料箱取矿，送到熔炉顶面，再把成品送回成品箱；缺少信息请列出来，不要猜。")
        self.request.setFixedHeight(78)
        lay.addWidget(self.request)
        self.context_hint = QLabel(
            f"本次带入 {len(self.project.tasks)} 条规则 · {len(self.project.labels)} 个标签"
        )
        self.context_hint.setObjectName("MonoMuted")
        self.context_hint.setFont(mono_font(10))
        lay.addWidget(self.context_hint)
        row = QHBoxLayout()
        self.generate_btn = CutButton("生成候选代码", "primary", True)
        self.generate_btn.setIcon(theme_icon("code-sparkle", muted=False, size=13))
        self.generate_btn.clicked.connect(self._generate)
        row.addWidget(self.generate_btn)
        self.cancel_btn = CutButton("取消", "ghost", True)
        self.cancel_btn.setIcon(theme_icon("circle-stop", muted=True, size=13))
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self._cancel_generation)
        row.addWidget(self.cancel_btn)
        self.gen_status = _hint("默认关闭；点生成才会访问你填写的接口。")
        row.addWidget(self.gen_status, 1)
        lay.addLayout(row)
        self.ai_status = AIStatusBar()
        lay.addWidget(self.ai_status)
        self.candidate = QPlainTextEdit()
        self.candidate.setReadOnly(True)
        self.candidate.setFont(ui_font(10))
        self.candidate.setPlaceholderText("候选代码会显示在这里；不会自动覆盖工程。")
        lay.addWidget(self.candidate, 1)
        self.review = QLabel("")
        self.review.setWordWrap(True)
        self.review.setObjectName("Muted")
        self.review.setFont(ui_font(9))
        lay.addWidget(self.review)
        btns = QHBoxLayout()
        self.copy_btn = CutButton("复制候选", "ghost", True)
        self.copy_btn.setEnabled(False)
        self.copy_btn.clicked.connect(self._copy_candidate)
        self.save_btn = CutButton("另存 .sfm", "ghost", True)
        self.save_btn.setEnabled(False)
        self.save_btn.clicked.connect(self._save_candidate)
        btns.addWidget(self.copy_btn)
        btns.addWidget(self.save_btn)
        btns.addStretch(1)
        lay.addLayout(btns)
        return w

    def _load_settings(self) -> None:
        # These are non-secret settings only; the key is loaded separately.
        self.base_url.setText(getattr(self.app_settings, "ai_base_url", "https://api.deepseek.com"))
        self.model.setText(getattr(self.app_settings, "ai_model", "deepseek-chat"))
        self.session_only.setChecked(False)

    # ---- key/prompt ------------------------------------------------------
    def _store(self):
        from ..services.credentials import CredentialStore

        return CredentialStore(alias="deepseek-default")

    def _load_key(self) -> None:
        try:
            key = self._store().load()
        except Exception as exc:
            self.settings_status.setText(f"凭据存储不可用：{exc}；将使用仅本次会话。")
            self.session_only.setChecked(True)
            return
        if key:
            self.key.setText(key)
            self.settings_status.setText("已从本机凭据存储载入 key（隐藏）。")
        else:
            self.settings_status.setText("尚未保存 key。")

    def _save_key(self) -> None:
        val = self.key.text().strip()
        if not val:
            self.settings_status.setText("key 为空。")
            return
        if self.session_only.isChecked():
            self.session_key = val
            try:
                self._store().delete()
            except Exception:
                pass
            self.settings_status.setText("已保存到本次会话内存；本机已存 key 已清除。")
            return
        try:
            self._store().save(val)
            self.settings_status.setText("已保存到本机凭据存储（DPAPI/记录）；不会写入工程/日志。")
            self.session_key = ""
        except Exception as exc:
            self.settings_status.setText(f"保存失败：{exc}；请改用仅本次会话。")
            self.session_only.setChecked(True)
            self.session_key = val

    def _clear_key(self) -> None:
        self.key.clear()
        self.session_key = ""
        try:
            self._store().delete()
            self.settings_status.setText("已清除本机凭据。")
        except Exception as exc:
            self.settings_status.setText(f"清除本地凭据失败：{exc}")

    def _test_connection(self) -> None:
        # No request until the user explicitly clicks Generate. This button only
        # validates the local configuration so the label stays truthful.
        self.settings_status.setText("本地配置已检查；连接会在点“生成候选代码”时验证。")

    def _current_key(self) -> str:
        return self.key.text().strip() or self.session_key

    # ---- prompt ----------------------------------------------------------
    def _load_prompt(self) -> None:
        try:
            self.prompt_edit.setPlainText(self.prompt_manager.effective_prompt())
        except Exception:
            self.prompt_edit.setPlainText(getattr(self.prompt_manager, "default_text", ""))

    def _reset_prompt(self) -> None:
        try:
            self.prompt_manager.reset()
            self.app_settings.prompt_override = ""
            self._load_prompt()
            self.prompt_status.setText("已恢复内置默认提示词。")
        except Exception as exc:
            self.prompt_status.setText(f"恢复失败：{exc}")

    def _save_prompt(self) -> None:
        text = self.prompt_edit.toPlainText()
        try:
            self.prompt_manager.set_override(text)
            self.app_settings.prompt_override = text
            self.prompt_status.setText("已保存本地覆盖；未改内置默认。")
        except Exception as exc:
            self.prompt_status.setText(f"保存失败：{exc}")

    # ---- generation ------------------------------------------------------
    def _context(self) -> dict:
        task = self.project.active_task()
        return {
            "project": self.project.name,
            "profile": self.project.profile.label,
            "labels": self.project.label_names(),
            "task": task.name if task else None,
            "existing_code": "",
        }

    def _generate(self) -> None:
        key = self._current_key()
        if not key:
            self.gen_status.setText("未配置 key；请到“服务设置”填写。")
            self.ai_status.set_state("warning", "未配置 API Key")
            self.tabs.setCurrentIndex(0)
            return
        req = self.request.toPlainText().strip()
        if not req:
            self.gen_status.setText("请先写需求。")
            self.ai_status.set_state("warning", "请先写需求")
            return
        try:
            from ..services.ai import AIClient, AISettings

            settings = AISettings(
                base_url=self.base_url.text().strip() or "https://api.deepseek.com",
                model=self.model.text().strip() or "deepseek-chat",
                protocol="DeepSeek 官方 API",
            )
            # persist non-secret settings
            self.app_settings.ai_base_url = settings.base_url
            self.app_settings.ai_model = settings.model
            client = AIClient(prompt_manager=self.prompt_manager)
        except Exception as exc:
            self.gen_status.setText(f"AI 服务不可用：{exc}")
            self.ai_status.set_state("error", "AI 服务不可用")
            return
        self.candidate_validation = None
        self.last_result = None
        self.candidate.clear()
        self.review.clear()
        self.copy_btn.setEnabled(False)
        self.save_btn.setEnabled(False)
        self.candidate.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        self._cancel_requested = False
        self._ignore_result = False
        self.generate_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.gen_status.setText("请求中…（默认只发你写的接口）")
        self.ai_status.set_state("running", "正在请求 AI 生成候选")
        try:
            from ..core.crashlog import log_event

            log_event(f"ai request start model={settings.model!r}")
        except Exception:
            pass
        result_queue: queue.Queue = queue.Queue()
        self._request_queue = result_queue
        self._request_thread = threading.Thread(
            target=self._run_ai_request,
            args=(client, settings, key, self._context(), req, result_queue),
            name="sfm-ai-request",
            daemon=True,
        )
        try:
            self._request_thread.start()
        except Exception as exc:
            self._request_queue = None
            self._request_thread = None
            self.generate_btn.setEnabled(True)
            self.cancel_btn.setEnabled(False)
            self.gen_status.setText(f"无法启动请求线程：{exc}")
            self.ai_status.set_state("error", "请求线程启动失败")
            return
        self._request_poll.start()

    def _run_ai_request(
        self, client, settings, key: str, context: dict, req: str, result_queue: queue.Queue
    ) -> None:
        """Network worker. It must never touch QWidgets.

        A daemon Python thread is used instead of QThread because a blocking
        urllib request cannot be safely terminated during interpreter shutdown.
        """
        try:
            result = client.generate(settings, key, context, req)
        except Exception as exc:  # pragma: no cover - UI boundary
            result = exc
        result_queue.put(result)

    def _poll_ai_result(self) -> None:
        q = self._request_queue
        if q is None:
            self._request_poll.stop()
            return
        try:
            result = q.get_nowait()
        except queue.Empty:
            return
        self._request_queue = None
        self._request_poll.stop()
        if not self._ignore_result:
            self._on_result(result)

    def _detach_worker(self) -> None:
        """Stop observing a request without destroying its thread."""
        self._ignore_result = True
        self._request_queue = None
        self._request_poll.stop()
        self._request_thread = None
        try:
            self.ai_status.set_state("cancelled", "请求已取消")
        except Exception:
            pass
        self.copy_btn.setEnabled(False)
        self.save_btn.setEnabled(False)

    def _cancel_generation(self) -> None:
        self._cancel_requested = True
        try:
            from ..core.crashlog import log_event

            log_event("ai request cancelled by user")
        except Exception:
            pass
        self._detach_worker()
        self.cancel_btn.setEnabled(False)
        self.generate_btn.setEnabled(True)
        self.copy_btn.setEnabled(False)
        self.save_btn.setEnabled(False)
        self.candidate.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        self.gen_status.setText("已取消；后台请求结束会被忽略，可重新生成。")
        self.ai_status.set_state("cancelled", "请求已取消")

    def _confirm_close(self) -> bool:
        if self._request_thread and self._request_thread.is_alive():
            ret = QMessageBox.question(
                self,
                "请求仍在进行",
                "AI 请求仍在后台运行。取消并关闭？后台结果会被忽略。",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            return ret == QMessageBox.StandardButton.Yes
        return True

    def closeEvent(self, event) -> None:  # noqa: N802
        if not self._confirm_close():
            event.ignore()
            return
        self._detach_worker()
        super().closeEvent(event)

    def reject(self) -> None:
        if not self._confirm_close():
            return
        self._detach_worker()
        super().reject()

    def _validate_candidate(self, code: str) -> None:
        if not code.strip():
            self.candidate_validation = None
            self.copy_btn.setEnabled(False)
            self.save_btn.setEnabled(False)
            return
        try:
            from ..core.validate import validate_code

            v = validate_code(code, self.project.profile_id)
            self.candidate_validation = v
            blocked = bool(getattr(v, "blocks", 0) or getattr(v, "syntax_errors", []))
            self.copy_btn.setEnabled(not blocked)
            self.save_btn.setEnabled(not blocked)
            if blocked:
                self.candidate.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
            else:
                self.candidate.setTextInteractionFlags(
                    Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.TextSelectableByKeyboard
                )
            lines = [f"本地 L0/L1：{getattr(v, 'blocks', 0)} 阻断 / {getattr(v, 'warnings', 0)} 提示"]
            for issue in list(getattr(v, "issues", []))[:5]:
                lines.append(f"· [{getattr(issue, 'level', '')}] {getattr(issue, 'code', '')}: {getattr(issue, 'message', '')}")
            for err in list(getattr(v, "syntax_errors", []))[:3]:
                lines.append(f"· [syntax] {err}")
            self.review.setText("\n\n".join([self.review.text(), "\n".join(lines)]).strip())
        except Exception as exc:
            self.candidate_validation = None
            self.copy_btn.setEnabled(False)
            self.save_btn.setEnabled(False)
            self.review.setText(f"本地校验不可用：{exc}")

    def _on_result(self, result) -> None:
        if self._ignore_result:
            return
        self.generate_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.last_result = result
        if self._cancel_requested:
            self._cancel_requested = False
            self.gen_status.setText("已取消；候选未应用。")
            self.ai_status.set_state("cancelled", "请求已取消")
            self.copy_btn.setEnabled(False)
            self.save_btn.setEnabled(False)
            return
        if isinstance(result, Exception):
            self.gen_status.setText(f"生成失败：{result}")
            self.ai_status.set_state("error", "AI 请求失败")
            self.candidate.setPlainText("")
            self.review.setText("")
            self.copy_btn.setEnabled(False)
            self.save_btn.setEnabled(False)
            return
        status = getattr(result, "status", "") or ""
        err = getattr(result, "error", "") or ""
        code = getattr(result, "code", "") or ""
        if code:
            self.candidate.setPlainText(code)
        parts = []
        if getattr(result, "self_review", None):
            parts.append("AI 自审：\n" + "\n".join(f"· {x}" for x in result.self_review))
        if getattr(result, "assumptions", None):
            parts.append("假设：\n" + "\n".join(f"· {x}" for x in result.assumptions))
        if getattr(result, "missing_info", None):
            parts.append("缺失：\n" + "\n".join(f"· {x}" for x in result.missing_info))
        self.review.setText("\n\n".join(parts) if parts else "")
        self.ai_status.set_state("review", "正在做本地 L0/L1 校验")
        self._validate_candidate(code) if code else self._validate_candidate("")
        if status == "needs_input":
            self.gen_status.setText("AI 认为信息不足；请补齐缺失项后重试。")
            self.ai_status.set_state("warning", "AI 需要更多信息")
            self.copy_btn.setEnabled(False)
            self.save_btn.setEnabled(False)
            if not parts:
                self.review.setText("请补充需求中的来源、目标、面或数量。")
            return
        if err or status not in ("", "ok"):
            self.copy_btn.setEnabled(False)
            self.save_btn.setEnabled(False)
            label = {
                "missing_key": "未配置密钥",
                "auth_error": "认证失败",
                "timeout": "请求超时",
                "network_error": "网络不可达",
                "rate_limited": "请求被限流",
                "server_error": "服务端错误",
                "invalid_response": "响应无法解析",
                "empty_response": "响应为空",
                "truncated": "响应被截断",
                "invalid_sfml": "返回的 SFML 未通过语法检查",
                "unsupported_protocol": "不支持的协议",
                "config_error": "配置错误",
                "invalid_request": "请求无效",
                "disabled": "AI 已禁用",
            }.get(status, "生成失败")
            self.gen_status.setText(f"{label}：{err or status}")
            self.ai_status.set_state("error", label)
            raw = getattr(result, "raw", "") or ""
            if raw:
                self.review.setText((self.review.text() + "\n\n原始响应（截断）：\n" + raw[:1000]).strip())
            return
        self.gen_status.setText("已生成候选；请检查本地 L0/L1 后再复制/另存，不会自动改工程。")
        self.ai_status.set_state("done", "候选已生成，未写入工程")
        if not self.review.text():
            self.review.setText("AI 未提供自审信息；请仍以本地校验为准。")

    def _copy_candidate(self) -> None:
        text = self.candidate.toPlainText()
        status = getattr(self.last_result, "status", "") or ""
        if status not in ("", "ok"):
            self.gen_status.setText("当前响应不是可用候选，不能复制。")
            return
        if not text.strip():
            self.gen_status.setText("没有候选代码。")
            return
        blocks = getattr(self.candidate_validation, "blocks", 0) if self.candidate_validation is not None else 1
        if blocks:
            self.gen_status.setText("本地 L0/L1 未通过，不能复制；请先修复候选。")
            return
        from PySide6.QtWidgets import QApplication

        QApplication.clipboard().setText(text)
        self.gen_status.setText("候选代码已复制；不会自动改工程。")

    def _save_candidate(self) -> None:
        text = self.candidate.toPlainText()
        status = getattr(self.last_result, "status", "") or ""
        if status not in ("", "ok"):
            self.gen_status.setText("当前响应不是可用候选，不能另存。")
            return
        if not text.strip():
            self.gen_status.setText("没有候选代码。")
            return
        blocks = getattr(self.candidate_validation, "blocks", 0) if self.candidate_validation is not None else 1
        if blocks:
            self.gen_status.setText("本地 L0/L1 未通过，不能另存；请先修复候选。")
            return
        path, _ = QFileDialog.getSaveFileName(self, "保存 AI 候选", "ai-candidate.sfm", "SFML (*.sfm)")
        if not path:
            return
        from pathlib import Path

        try:
            from ..core.storage import export_sfml

            out = export_sfml(text, path)
            self.gen_status.setText(f"已保存：{out.name}（UTF-8 / LF）")
        except Exception as exc:
            self.gen_status.setText(f"保存失败：{exc}")


class SettingsDialog(QDialog):
    def __init__(self, settings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("设置 / Settings")
        self.resize(480, 380)
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 12)
        root.setSpacing(8)
        e = QLabel("// SETTINGS")
        e.setObjectName("Eyebrow")
        root.addWidget(e)
        title = QLabel("工作台设置")
        title.setFont(ui_font(18, QFont.Weight.Bold))
        root.addWidget(title)
        form = QFormLayout()
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(7)
        self.theme = QComboBox()
        self.theme.addItems(["亮色", "深色"])
        self.theme.setCurrentIndex(1 if getattr(settings, "theme", "light") == "dark" else 0)
        self.reduce = QCheckBox("减少动效")
        self.reduce.setChecked(bool(getattr(settings, "reduced_motion", False)))
        self.scale = QComboBox()
        self.scale.addItems(["100%", "110%", "125%"])
        self.scale.setCurrentText(f"{getattr(settings, 'ui_scale', 100)}%")
        self.lang = QComboBox()
        self.lang.addItems(["中文（MVP）", "English (V1)"])
        self.lang.setCurrentIndex(0)
        form.addRow(_label("主题"), self.theme)
        form.addRow(_label("动效"), self.reduce)
        form.addRow(_label("界面缩放"), self.scale)
        form.addRow(_label("语言"), self.lang)
        root.addLayout(form)
        root.addWidget(_hint("英文界面、110/125% 缩放会在后续版本完善；当前先保存设置。"))
        root.addStretch(1)
        foot = QHBoxLayout()
        foot.addStretch(1)
        cancel = CutButton("取消", "ghost", True)
        cancel.clicked.connect(self.reject)
        ok = CutButton("保存设置", "primary", True)
        ok.clicked.connect(self._accept)
        foot.addWidget(cancel)
        foot.addWidget(ok)
        root.addLayout(foot)

    def _accept(self) -> None:
        self.settings.theme = "dark" if self.theme.currentIndex() == 1 else "light"
        self.settings.reduced_motion = self.reduce.isChecked()
        self.settings.ui_scale = int(self.scale.currentText().replace("%", ""))
        self.settings.language = "zh_CN" if self.lang.currentIndex() == 0 else "en_US"
        self.accept()


class AboutDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("关于 / About")
        self.resize(520, 420)
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 14)
        root.setSpacing(8)
        e = QLabel("// ABOUT")
        e.setObjectName("Eyebrow")
        root.addWidget(e)
        title = QLabel("SFM代码生成工坊")
        title.setFont(ui_font(22, QFont.Weight.Black))
        root.addWidget(title)
        sub = QLabel("把“何时、从哪取、送到哪”变成可编译的 SFML。\nWindows · PySide6 · 离线优先 · 不写世界存档/NBT。")
        sub.setWordWrap(True)
        sub.setObjectName("Muted")
        root.addWidget(sub)
        root.addWidget(_hint("官方 SFML 4.34.0 文法用于本地语法校验；文法/解析器来源保留 MPL-2.0 NOTICE。\nSaira 字体 OFL-1.1。\n本工具不承诺游戏内运行结果；标签/面/库存/服务器配置仍以游戏内为准。"))
        root.addStretch(1)
        close = CutButton("关闭", "primary", True)
        close.clicked.connect(self.accept)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(close)
        root.addLayout(row)
