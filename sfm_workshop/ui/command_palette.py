"""Ctrl+K command surface for the workshop.

This is deliberately a desktop command palette, not a web search modal: every
entry maps to a stable action already present in the File menu or toolbar, and
the exact shortcut is shown next to it. Inspired by MicroKit/Motiq command
interaction patterns and Ingot-style compact dashboards.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from PySide6.QtCore import QEvent, QRect, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QKeySequence, QPainter, QPen
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QVBoxLayout,
    QWidget,
)

from . import theme as theme_mod
from .icons import icon as svg_icon
from .theme import mono_font, ui_font


@dataclass
class Command:
    title: str
    hint: str
    icon: str
    shortcut: str
    action: Callable[[], None]
    group: str = "GENERAL"


class CommandDelegate(QStyledItemDelegate):
    """Three-column painted rows: title, hint, right-aligned shortcut."""

    def sizeHint(self, option, index):
        return QSize(0, 22 if index.data(Qt.ItemDataRole.UserRole) is None else 32)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        t = theme_mod.current()
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = option.rect
        command = index.data(Qt.ItemDataRole.UserRole)
        if command is None:
            painter.setPen(QColor(t.ink2))
            f = mono_font(9)
            f.setBold(True)
            painter.setFont(f)
            painter.drawText(rect.adjusted(10, 4, -8, -2), Qt.AlignmentFlag.AlignLeft, index.data())
            painter.setPen(QPen(QColor(t.rule), 1))
            painter.drawLine(rect.left() + 10, rect.bottom() - 3, rect.right() - 10, rect.bottom() - 3)
            painter.restore()
            return
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        if selected:
            painter.fillRect(rect, QColor(t.chip))
            painter.fillRect(rect.left(), rect.top() + 2, 2, rect.height() - 4, QColor(t.signal))
        icon = index.data(Qt.ItemDataRole.DecorationRole)
        if icon is not None:
            icon.paint(painter, QRect(rect.left() + 12, rect.center().y() - 8, 16, 16))
        title_x = rect.left() + 36
        painter.setPen(QColor(t.ink))
        title_font = ui_font(11, QFont.Weight.DemiBold)
        painter.setFont(title_font)
        title_w = painter.fontMetrics().horizontalAdvance(command.title) + 4
        painter.drawText(
            QRect(title_x, rect.top() + 5, min(title_w + 8, rect.width() - 60), 20),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            command.title,
        )
        painter.setPen(QColor(t.ink2))
        painter.setFont(ui_font(10))
        hint_x = title_x + title_w + 10
        hint_w = rect.right() - 86 - hint_x
        if hint_w > 20:
            painter.drawText(
                QRect(hint_x, rect.top() + 5, hint_w, 20),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                painter.fontMetrics().elidedText(
                    command.hint, Qt.TextElideMode.ElideRight, hint_w
                ),
            )
        if command.shortcut:
            painter.setPen(QColor(t.ink2))
            painter.setFont(mono_font(9))
            painter.drawText(
                QRect(rect.right() - 104, rect.top() + 5, 88, 20),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                command.shortcut,
            )
        painter.restore()


class CommandPaletteDialog(QDialog):
    def __init__(self, commands: list[Command], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("命令面板")
        self.setObjectName("CommandPalette")
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.FramelessWindowHint)
        self.setModal(True)
        self.resize(620, 430)
        self.commands = commands
        self._filtered: list[Command] = []
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        head = QFrame()
        head.setObjectName("PaletteHead")
        hl = QHBoxLayout(head)
        hl.setContentsMargins(14, 11, 14, 9)
        hl.setSpacing(9)
        glyph = QLabel()
        glyph.setPixmap(svg_icon("keyboard", theme_mod.current().signal, 16).pixmap(16, 16))
        hl.addWidget(glyph)
        self.search = QLineEdit()
        self.search.setObjectName("PaletteSearch")
        self.search.setPlaceholderText("输入命令、页面或动作…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._filter)
        self.search.installEventFilter(self)
        hl.addWidget(self.search, 1)
        esc = QLabel("ESC")
        esc.setObjectName("Kbd")
        esc.setFont(mono_font(10))
        hl.addWidget(esc)
        root.addWidget(head)
        self.list = QListWidget()
        self.list.setObjectName("PaletteList")
        self.list.setAlternatingRowColors(False)
        self.list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.list.setItemDelegate(CommandDelegate(self.list))
        self.list.itemClicked.connect(self._activate)
        root.addWidget(self.list, 1)
        foot = QFrame()
        foot.setObjectName("PaletteFoot")
        fl = QHBoxLayout(foot)
        fl.setContentsMargins(14, 7, 14, 7)
        fl.setSpacing(12)
        for key, label in (("↑↓", "移动"), ("↵", "执行"), ("ESC", "关闭")):
            k = QLabel(key)
            k.setObjectName("Kbd")
            k.setFont(mono_font(10))
            fl.addWidget(k)
            l = QLabel(label)
            l.setObjectName("Muted")
            l.setFont(ui_font(10))
            fl.addWidget(l)
        fl.addStretch(1)
        self.count_label = QLabel("")
        self.count_label.setObjectName("MonoMuted")
        self.count_label.setFont(mono_font(10))
        fl.addWidget(self.count_label)
        root.addWidget(foot)
        self._filter("")
        self.search.setFocus()
        QTimer.singleShot(0, self.search.setFocus)

    def _filter(self, text: str) -> None:
        q = text.strip().lower()
        self._filtered = [
            c
            for c in self.commands
            if not q or q in c.title.lower() or q in c.hint.lower() or q in c.group.lower()
        ]
        self.list.clear()
        last_group = ""
        for c in self._filtered:
            if c.group != last_group:
                item = QListWidgetItem(f"// {c.group}")
                item.setFlags(Qt.ItemFlag.NoItemFlags)
                item.setSizeHint(QSize(0, 22))
                f = item.font()
                f.setPixelSize(10)
                f.setBold(True)
                item.setFont(f)
                item.setForeground(QColor(theme_mod.current().ink2))
                self.list.addItem(item)
                last_group = c.group
            item = QListWidgetItem(self._label_for(c))
            item.setData(Qt.ItemDataRole.UserRole, c)
            item.setIcon(svg_icon(c.icon, theme_mod.current().ink2, 15))
            item.setSizeHint(QSize(0, 30))
            self.list.addItem(item)
            if not self.list.currentItem():
                self.list.setCurrentItem(item)
        self.count_label.setText(f"{len(self._filtered)} 条")
        groups = len({c.group for c in self._filtered})
        height = min(590, max(230, 158 + len(self._filtered) * 32 + groups * 22))
        self.resize(620, height)
        if self._filtered:
            first = self.list.item(1) if self.list.count() > 1 else self.list.item(0)
            if first is not None:
                self.list.setCurrentItem(first)

    def _label_for(self, c: Command) -> str:
        return f"{c.title}    {c.hint}" + (f"    {c.shortcut}" if c.shortcut else "")

    def _activate(self, item: QListWidgetItem) -> None:
        c = item.data(Qt.ItemDataRole.UserRole)
        if c is None:
            return
        self.accept()
        QTimer.singleShot(0, c.action)

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if obj is self.search and event.type() == QEvent.Type.KeyPress:
            key = event.key()
            if key == Qt.Key.Key_Down:
                self._move(1)
                return True
            if key == Qt.Key.Key_Up:
                self._move(-1)
                return True
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                item = self.list.currentItem()
                if item is not None:
                    self._activate(item)
                return True
            if key == Qt.Key.Key_Escape:
                self.reject()
                return True
        return super().eventFilter(obj, event)

    def _move(self, delta: int) -> None:
        if not self.list.count():
            return
        row = self.list.currentRow()
        nxt = row + delta
        while 0 <= nxt < self.list.count():
            item = self.list.item(nxt)
            if item.flags() & Qt.ItemFlag.ItemIsEnabled:
                self.list.setCurrentRow(nxt)
                return
            nxt += delta
