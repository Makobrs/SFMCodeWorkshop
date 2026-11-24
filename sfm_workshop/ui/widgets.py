"""Reusable Qt widgets for the SFM Code Workshop console UI."""
from __future__ import annotations

from dataclasses import dataclass
from html import escape
from pathlib import Path
from typing import Iterable

from PySide6.QtCore import (
    QEvent,
    QMimeData,
    QPoint,
    Property,
    QPropertyAnimation,
    QRect,
    QRectF,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QDrag,
    QFont,
    QFontMetrics,
    QPainter,
    QPainterPath,
    QPen,
    QRadialGradient,
    QTextCharFormat,
    QTextCursor,
    QTextFormat,
)
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..core.model import Project, Task
from . import motion
from . import theme as theme_mod
from .icons import apply_search_icon, icon as svg_icon, theme_icon
from .theme import Theme, mono_font, ui_font


# ---------------------------------------------------------------------------
# small primitives
# ---------------------------------------------------------------------------

def cut_path(rect: QRect, cut: int = 7) -> QPainterPath:
    r = rect.adjusted(0, 0, -1, -1)
    c = max(2, min(cut, min(r.width(), r.height()) // 3))
    p = QPainterPath()
    p.moveTo(r.left(), r.top())
    p.lineTo(r.right(), r.top())
    p.lineTo(r.right(), r.bottom() - c)
    p.lineTo(r.right() - c, r.bottom())
    p.lineTo(r.left(), r.bottom())
    p.closeSubpath()
    return p


class CutButton(QPushButton):
    """Square button with one cut corner; pressable things only."""

    def __init__(
        self,
        text: str = "",
        variant: str = "ghost",
        small: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(text, parent)
        self.variant = variant
        self.small = small
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setFlat(True)
        self.setFont(ui_font(10 if small else 11, QFont.Weight.DemiBold))
        self.setMinimumHeight(24 if small else 28)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self._wipe = 0.0
        self._edge = 0.0

    def _get_wipe(self) -> float:
        return self._wipe

    def _set_wipe(self, value: float) -> None:
        self._wipe = max(0.0, min(1.0, float(value)))
        self.update()

    wipe = Property(float, _get_wipe, _set_wipe)

    def _get_edge(self) -> float:
        return self._edge

    def _set_edge(self, value: float) -> None:
        self._edge = max(0.0, min(1.0, float(value)))
        self.update()

    edge = Property(float, _get_edge, _set_edge)

    def sizeHint(self) -> QSize:
        fm = QFontMetrics(self.font())
        icon_w = 18 if not self.icon().isNull() else 0
        w = fm.horizontalAdvance(self.text()) + (26 if self.small else 32) + icon_w
        return QSize(max(38, w), 24 if self.small else 28)

    def _colors(self, t: Theme) -> tuple[QColor, QColor, QColor]:
        if not self.isEnabled() and self.variant == "primary":
            return QColor(0, 0, 0, 0), QColor(t.ink2), QColor(t.rule)
        if self.variant == "primary":
            return QColor(t.signal), QColor(t.on_signal), QColor(t.ink)
        if self.variant == "command":
            if not self.isEnabled():
                return QColor(0, 0, 0, 0), QColor(t.command_muted), QColor(t.command_rule)
            return QColor(0, 0, 0, 0), QColor(t.command_ink), QColor(t.command_rule)
        if self.variant == "danger":
            return QColor(0, 0, 0, 0), QColor(t.danger), QColor(t.danger)
        if self.variant == "attention":
            return QColor(0, 0, 0, 0), QColor(t.signal), QColor(t.signal)
        if self.variant == "quiet":
            return QColor(0, 0, 0, 0), QColor(t.ink2), QColor(0, 0, 0, 0)
        if not self.isEnabled():
            return QColor(0, 0, 0, 0), QColor(t.ink2), QColor(t.rule)
        return QColor(0, 0, 0, 0), QColor(t.ink), QColor(t.rule)

    def paintEvent(self, event) -> None:  # noqa: N802
        t = theme_mod.current()
        bg, fg, border = self._colors(t)
        r = self.rect()
        if self.isDown():
            r = r.translated(0, 1)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        path = cut_path(r, 6 if self.small else 7)
        if bg.alpha() > 0:
            p.fillPath(path, bg)
        if self.isEnabled() and self._wipe > 0 and self.variant in ("ghost", "quiet", "danger", "attention"):
            fill = QColor(t.danger_bg if self.variant == "danger" else t.signal)
            if fill.alpha() == 0:
                fill = QColor(t.signal)
            p.save()
            p.setClipRect(QRectF(0, 0, r.width() * self._wipe, r.height()))
            p.fillPath(path, fill)
            p.restore()
            if self.variant in ("ghost", "quiet", "attention") and self._wipe > 0.45:
                fg = QColor(t.on_signal)
        if self.isEnabled() and self._edge > 0 and self.variant in ("primary", "command"):
            # The sweep is a transient highlight, not a border. Without the
            # fade it parks on the right edge as a black/white strip.
            fade = max(0.0, min(1.0, 1.0 - max(0.0, self._edge - 0.62) / 0.38))
            edge = QColor(t.on_signal if self.variant == "primary" else t.command_ink)
            edge.setAlphaF(fade)
            x = max(1, min(r.width() - 4, int((r.width() - 4) * self._edge)))
            p.save()
            p.setClipPath(path)
            p.fillRect(QRect(x, 3, 3, max(0, r.height() - 6)), edge)
            p.restore()
        if border.alpha() > 0:
            p.setPen(QPen(border, 1))
            p.drawPath(path)
        if self.hasFocus():
            focus = QColor(t.on_signal if self.variant == "primary" else (t.signal if t.dark else t.ink))
            p.setPen(QPen(focus, 1))
            p.drawPath(cut_path(r.adjusted(3, 3, -3, -3), 4))
        p.setPen(fg)
        p.setFont(self.font())
        icon = self.icon()
        if not icon.isNull() and bool(self.property("iconTextCentered")):
            gap = 7
            pix = icon.pixmap(14, 14)
            text_w = QFontMetrics(self.font()).horizontalAdvance(self.text())
            start = max(6, (r.width() - (14 + gap + text_w)) // 2)
            p.drawPixmap(start, max(1, (r.height() - 14) // 2), pix)
            p.drawText(
                QRect(start + 14 + gap, 0, max(0, r.width() - start - 14 - gap - 7), r.height()),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                self.text(),
            )
            return
        text_rect = r.adjusted(7, 0, -7, 0)
        if not icon.isNull():
            size = 14
            pix = icon.pixmap(size, size)
            p.drawPixmap(8, max(1, (r.height() - size) // 2), pix)
            text_rect = r.adjusted(24, 0, -7, 0)
        p.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, self.text())

    def _animate_hover(self, entering: bool) -> None:
        if not self.isEnabled():
            return
        if self.variant in ("primary", "command"):
            if entering:
                motion.animate(
                    self, b"edge", self._edge, 1.0,
                    300, self._set_edge, key="cut-edge", easing=motion.MECH,
                )
            else:
                motion.stop(self, "cut-edge")
                self._set_edge(0.0)
            return
        motion.animate(
            self, b"wipe", self._wipe, 1.0 if entering else 0.0,
            280 if entering else 180, self._set_wipe, key="cut-wipe", easing=motion.MECH,
        )

    def enterEvent(self, event) -> None:  # noqa: N802
        self._animate_hover(True)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._animate_hover(False)
        super().leaveEvent(event)

    def focusInEvent(self, event) -> None:  # noqa: N802
        if self.variant not in ("primary", "command"):
            self._animate_hover(True)
        super().focusInEvent(event)

    def focusOutEvent(self, event) -> None:  # noqa: N802
        self._animate_hover(False)
        super().focusOutEvent(event)

    def changeEvent(self, event) -> None:  # noqa: N802
        if event.type() == QEvent.Type.EnabledChange and not self.isEnabled():
            self._set_wipe(0.0)
            self._set_edge(0.0)
        super().changeEvent(event)


class ScrubSpinBox(QSpinBox):
    """Spin box with click-to-type and horizontal drag-to-scrub.

    MicroKit's number scrubber is useful for tick/quantity fields where the
    user needs a fast relative adjustment but must still be able to type an
    exact value. No layout or focus semantics change for keyboard users.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAccelerated(True)
        self.setKeyboardTracking(True)
        self.setMouseTracking(True)
        self._press_pos: QPoint | None = None
        self._start_value = 0
        self._scrubbing = False

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_pos = event.position().toPoint()
            self._start_value = self.value()
            self._scrubbing = False
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if (
            self._press_pos is not None
            and event.buttons() & Qt.MouseButton.LeftButton
            and (event.position().toPoint() - self._press_pos).manhattanLength()
            >= QApplication.startDragDistance()
        ):
            dx = event.position().toPoint().x() - self._press_pos.x()
            step = max(1, self.singleStep())
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                step *= 10
            value = self._start_value + int(dx / 10) * step
            self.setValue(max(self.minimum(), min(self.maximum(), value)))
            self._scrubbing = True
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        was_scrubbing = self._scrubbing
        self._press_pos = None
        self._scrubbing = False
        if was_scrubbing:
            event.accept()
            return
        super().mouseReleaseEvent(event)


class MiniCap(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.value = 0
        self.cap = 16
        self.setFixedHeight(8)
        self.setMinimumWidth(80)

    def set_value(self, value: int, cap: int) -> None:
        self.value = max(0, min(int(value), int(cap)))
        self.cap = max(1, int(cap))
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        t = theme_mod.current()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        n = min(24, self.cap)
        gap = 2
        w = max(2, (self.width() - (n - 1) * gap) / n)
        for i in range(n):
            x = i * (w + gap)
            filled = (i + 1) <= round(n * self.value / self.cap)
            p.fillRect(QRect(int(x), 0, int(w), 8), QColor(t.ink if filled else t.rule))


class Toast(QWidget):
    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self._text = ""
        self._reveal = 0.0
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._hide_animated)
        self.hide()

    def _get_reveal(self) -> float:
        return self._reveal

    def _set_reveal(self, value: float) -> None:
        self._reveal = max(0.0, min(1.0, float(value)))
        self.update()

    reveal = Property(float, _get_reveal, _set_reveal)

    def sizeHint(self) -> QSize:  # noqa: N802
        fm = QFontMetrics(ui_font(11, QFont.Weight.DemiBold))
        return QSize(fm.horizontalAdvance(self._text) + 30, 34)

    def paintEvent(self, event) -> None:  # noqa: N802
        t = theme_mod.current()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        p.save()
        p.setClipRect(QRectF(0, 0, self.width() * self._reveal, self.height()))
        p.fillRect(self.rect(), QColor(t.command))
        p.fillRect(QRect(0, 0, 3, self.height()), QColor(t.signal))
        p.setPen(QPen(QColor(t.command_rule), 1))
        p.drawRect(self.rect().adjusted(0, 0, -1, -1))
        p.setPen(QColor(t.command_ink))
        p.setFont(ui_font(11, QFont.Weight.DemiBold))
        p.drawText(
            self.rect().adjusted(14, 0, -12, 0),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            self._text,
        )
        p.restore()

    def show_message(self, text: str, ms: int = 2200) -> None:
        was_visible = self.isVisible()
        self._text = text
        self.adjustSize()
        parent = self.parentWidget()
        if parent:
            x = max(10, (parent.width() - self.width()) // 2)
            y = max(10, parent.height() - self.height() - 48)
            self.move(x, y)
        self._timer.stop()
        motion.stop(self, "toast-reveal")
        if was_visible:
            self._set_reveal(1.0)
        else:
            self._set_reveal(0.0)
        self.show()
        self.raise_()
        if not was_visible:
            motion.animate(
                self, b"reveal", 0.0, 1.0, 280, self._set_reveal,
                key="toast-reveal", easing=motion.MECH,
            )
        self._timer.start(ms)

    def _hide_animated(self) -> None:
        if not self.isVisible():
            return
        anim = motion.animate(
            self, b"reveal", self._reveal, 0.0, 160, self._set_reveal,
            key="toast-reveal", easing=motion.MECH, on_finished=self.hide,
        )
        if anim is None:
            self.hide()


class AnimatedStatusIcon(QLabel):
    """Tiny Lucide-style icon pulse for state changes.

    The source motion is an icon-level opacity/scale cue rather than a looping
    animation; it fires only when a status changes and stays still afterwards.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._effect)
        self._effect.setOpacity(1.0)

    def pulse(self) -> None:
        self._effect.setOpacity(0.35)
        motion.animate(
            self._effect,
            b"opacity",
            0.35,
            1.0,
            220,
            self._effect.setOpacity,
            key="icon-pulse",
            easing=motion.SNAP,
        )


class InlineStatus(QFrame):
    """Andromeda-style inline alert: icon, title, description, one action."""

    actionRequested = Signal()
    dismissed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("InlineStatus")
        self.setProperty("level", "info")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMaximumHeight(76)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(9, 6, 8, 6)
        lay.setSpacing(8)
        self.icon = AnimatedStatusIcon()
        self.icon.setFixedSize(18, 18)
        self.icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.icon, 0, Qt.AlignmentFlag.AlignVCenter)
        col = QVBoxLayout()
        col.setSpacing(0)
        self.title = QLabel("")
        self.title.setObjectName("InlineTitle")
        self.detail = QLabel("")
        self.detail.setObjectName("InlineDetail")
        self.detail.setWordWrap(True)
        col.addWidget(self.title)
        col.addWidget(self.detail)
        lay.addLayout(col, 1)
        self.action = CutButton("定位第一个", "ghost", True)
        self.action.clicked.connect(lambda _=False: self.actionRequested.emit())
        lay.addWidget(self.action, 0, Qt.AlignmentFlag.AlignVCenter)
        self.close = CutButton("", "quiet", True)
        self.close.setFixedSize(22, 22)
        self.close.setIcon(theme_icon("x", muted=False, size=14))
        self.close.setToolTip("关闭提示")
        self.close.clicked.connect(self._dismiss)
        lay.addWidget(self.close, 0, Qt.AlignmentFlag.AlignVCenter)
        self.hide()

    def _dismiss(self) -> None:
        self.hide()
        self.dismissed.emit()

    def set_message(
        self,
        level: str,
        title: str,
        detail: str,
        *,
        action_text: str = "定位第一个",
        action: bool = True,
    ) -> None:
        names = {
            "block": "triangle-alert",
            "possible": "triangle-alert",
            "reminder": "circle-alert",
            "info": "info",
        }
        self.setProperty("level", level)
        self.title.setText(title)
        self.detail.setText(detail)
        self.setAccessibleName(title)
        self.setAccessibleDescription(detail)
        self.detail.setVisible(bool(detail))
        self.action.setText(action_text)
        self.action.setVisible(action)
        self.icon.setPixmap(
            theme_icon(names.get(level, "info"), muted=level == "info", size=14).pixmap(14, 14)
        )
        self.icon.pulse()
        self.style().unpolish(self)
        self.style().polish(self)
        self._show_animated()

    def _show_animated(self) -> None:
        if self.isVisible() and self.maximumHeight() >= 76:
            return
        if motion.reduced():
            self.setMaximumHeight(76)
            self.show()
            return
        self.setMaximumHeight(0)
        self.show()
        anim = QPropertyAnimation(self, b"maximumHeight", self)
        anim.setStartValue(0)
        anim.setEndValue(76)
        anim.setDuration(140)
        anim.setEasingCurve(motion.curve(motion.SNAP))
        anim.start()
        self._reveal_anim = anim


class SectionHeader(QWidget):
    def __init__(self, eyebrow: str, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.lay = QHBoxLayout(self)
        self.lay.setContentsMargins(0, 0, 0, 0)
        self.lay.setSpacing(8)
        self.eyebrow = QLabel(eyebrow)
        self.eyebrow.setObjectName("Eyebrow")
        self.title = QLabel(title)
        f = ui_font(15, QFont.Weight.Bold)
        self.title.setFont(f)
        self.lay.addWidget(self.eyebrow)
        self.lay.addWidget(self.title)
        self.meta = QLabel("")
        self.meta.setObjectName("Muted")
        self.meta.setFont(ui_font(10))
        self.lay.addWidget(self.meta)
        self.lay.addStretch(1)
        self.right = QHBoxLayout()
        self.right.setSpacing(5)
        self.lay.addLayout(self.right)

    def add_right(self, w: QWidget) -> None:
        self.right.addWidget(w)

    def set_meta(self, text: str) -> None:
        self.meta.setText(text)


class MiniLabel(QWidget):
    def __init__(self, text: str = "", active: bool = True, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.text = text
        self.active = active
        self.setFixedSize(7, 7)

    def paintEvent(self, event) -> None:  # noqa: N802
        t = theme_mod.current()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        p.fillRect(self.rect(), QColor(t.trace if self.active else t.panel))
        if not self.active:
            p.setPen(QPen(QColor(t.ink2), 1))
            p.drawRect(self.rect().adjusted(0, 0, -1, -1))


# ---------------------------------------------------------------------------
# command bar
# ---------------------------------------------------------------------------

class CommandBar(QFrame):
    themeToggled = Signal()
    profileChanged = Signal(str)
    checkRequested = Signal()
    copyRequested = Signal()
    aiRequested = Signal()
    settingsRequested = Signal()
    fileRequested = Signal()
    paletteRequested = Signal()
    sidebarToggleRequested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("CommandBar")
        self.setFixedHeight(56)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 0, 14, 0)
        lay.setSpacing(9)

        self.project_label = QLabel("// WORKBENCH")
        self.project_label.setObjectName("CommandProject")
        lay.addWidget(self.project_label)
        self.dirty = QLabel("● 未保存")
        self.dirty.setObjectName("CommandMuted")
        self.dirty.setFont(ui_font(9))
        lay.addWidget(self.dirty)

        lay.addStretch(1)

        self.palette_btn = CutButton("Ctrl K  命令", "command", True)
        self.palette_btn.setIcon(theme_icon("keyboard", muted=False, size=14))
        self.palette_btn.setToolTip("打开命令面板（Ctrl+K）")
        self.palette_btn.clicked.connect(self.paletteRequested)
        lay.addWidget(self.palette_btn)

        self.file_btn = CutButton("文件", "command", True)
        self.file_btn.clicked.connect(self.fileRequested)
        lay.addWidget(self.file_btn)

        self.sidebar_btn = CutButton("", "command", True)
        self.sidebar_btn.setFixedWidth(30)
        self.sidebar_btn.setIcon(theme_icon("panel-left-open", muted=False, size=14))
        self.sidebar_btn.setToolTip("展开侧栏（Ctrl+B）")
        self.sidebar_btn.clicked.connect(self.sidebarToggleRequested)
        self.sidebar_btn.hide()
        lay.addWidget(self.sidebar_btn)

        self.profile = QComboBox()
        self.profile.setObjectName("CommandCombo")
        self.profile.setFixedHeight(28)
        self.profile.setMinimumWidth(112)
        self.profile.setFont(ui_font(10, QFont.Weight.DemiBold))
        self.profile.currentIndexChanged.connect(self._profile_changed)
        lay.addWidget(self.profile)

        self.theme_btn = CutButton("深色", "command", True)
        self.theme_btn.clicked.connect(self.themeToggled)
        lay.addWidget(self.theme_btn)

        self.check_btn = CutButton("校验 0", "command", True)
        self.check_btn.clicked.connect(self.checkRequested)
        lay.addWidget(self.check_btn)

        self.ai_btn = CutButton("AI 生成", "command", True)
        self.ai_btn.clicked.connect(self.aiRequested)
        lay.addWidget(self.ai_btn)

        self.copy_btn = CutButton("复制代码", "primary", True)
        self.copy_btn.clicked.connect(self.copyRequested)
        lay.addWidget(self.copy_btn)

        self.settings_btn = CutButton("设置", "command", True)
        self.settings_btn.clicked.connect(self.settingsRequested)
        lay.addWidget(self.settings_btn)

        self._profiles: list[str] = []

    def _profile_changed(self, idx: int) -> None:
        if 0 <= idx < len(self._profiles):
            self.profileChanged.emit(self._profiles[idx])

    def set_profiles(self, profiles: list[tuple[str, str]], current: str) -> None:
        self._profiles = [p[0] for p in profiles]
        self.profile.blockSignals(True)
        self.profile.clear()
        for pid, label in profiles:
            self.profile.addItem(label, pid)
        if current in self._profiles:
            self.profile.setCurrentIndex(self._profiles.index(current))
        self.profile.blockSignals(False)

    def set_project(self, name: str, dirty: bool, has_path: bool = True) -> None:
        self.project_label.setText("// WORKBENCH")
        self.dirty.setText("● 未保存" if dirty or not has_path else "已保存")

    def set_check(self, count: int, blocked: bool) -> None:
        self.check_btn.setText(f"校验 {count}")
        self.check_btn.variant = "attention" if blocked else "command"
        t = theme_mod.current()
        color = t.signal if blocked else t.command_ink
        self.check_btn.setIcon(svg_icon("list-checks", color, 14))
        self.check_btn.update()

    def set_theme_label(self, dark: bool) -> None:
        self.theme_btn.setText("浅色" if dark else "深色")

    def set_ai_enabled(self, enabled: bool) -> None:
        self.ai_btn.setEnabled(True)  # entry is always available; default off inside
        self.ai_btn.setToolTip("AI 生成是可选功能，默认关闭；点击进入配置/生成")


# Avoid a circular import at module import time.
# QComboBox is imported at the top.


# ---------------------------------------------------------------------------
# rule cards
# ---------------------------------------------------------------------------

class RuleCard(QFrame):
    clicked = Signal(str)
    editRequested = Signal(str)
    deleteRequested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("RuleCard")
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMouseTracking(True)
        self._spot = None
        self._spot_hover = False
        self.task_id = ""
        self.active = False
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.accent = QFrame()
        self.accent.setFixedWidth(3)
        lay.addWidget(self.accent)
        body = QVBoxLayout()
        body.setContentsMargins(10, 7, 10, 8)
        body.setSpacing(5)
        lay.addLayout(body, 1)

        top = QHBoxLayout()
        top.setSpacing(6)
        self.rid = QLabel("R.00")
        self.rid.setObjectName("Signal")
        self.rid.setFont(ui_font(10, QFont.Weight.Black))
        self.rid.setFixedHeight(20)
        self.name = QLabel("任务")
        self.name.setFont(ui_font(12, QFont.Weight.Bold))
        self.trigger = QLabel("每 20 tick")
        self.trigger.setObjectName("Muted")
        self.trigger.setFont(ui_font(9))
        top.addWidget(self.rid)
        top.addWidget(self.name)
        top.addWidget(self.trigger)
        top.addStretch(1)
        self.status = QLabel("未校验")
        self.status.setFont(ui_font(10, QFont.Weight.DemiBold))
        self.status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status.setMinimumWidth(44)
        self.status.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.status_icon = QLabel()
        self.status_icon.setFixedSize(12, 12)
        self.status_box = QWidget()
        self.status_box.setFixedHeight(20)
        status_lay = QHBoxLayout(self.status_box)
        status_lay.setContentsMargins(3, 1, 5, 1)
        status_lay.setSpacing(3)
        status_lay.addWidget(self.status_icon)
        status_lay.addWidget(self.status)
        top.addWidget(self.status_box, 0, Qt.AlignmentFlag.AlignVCenter)
        self.delete = CutButton("", "quiet", True)
        self.delete.setFixedWidth(26)
        self.delete.setIcon(theme_icon("trash", muted=True, size=12))
        self.delete.setToolTip("删除这条规则")
        self.delete.clicked.connect(lambda: self.deleteRequested.emit(self.task_id))
        self.delete.hide()
        top.addWidget(self.delete)
        body.addLayout(top)

        mid = QHBoxLayout()
        mid.setSpacing(10)
        self.sentence = QLabel("")
        self.sentence.setWordWrap(True)
        self.sentence.setFont(ui_font(11))
        self.sentence.setTextFormat(Qt.TextFormat.RichText)
        self.sentence.setMinimumHeight(32)
        mid.addWidget(self.sentence, 1)
        basket = QVBoxLayout()
        basket.setSpacing(2)
        basket.setContentsMargins(0, 0, 0, 0)
        self.basket_label = QLabel("参考 0 / 16")
        self.basket_label.setObjectName("Muted")
        self.basket_label.setFont(ui_font(10))
        self.basket_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.basket_label.setToolTip("产品估算概念，不是 SFM 的硬限制")
        self.basket = MiniCap()
        self.basket.setFixedWidth(84)
        basket.addWidget(self.basket_label)
        basket.addWidget(self.basket)
        self.basket_label.setFixedWidth(84)
        mid.addLayout(basket)
        body.addLayout(mid)

        self.setMinimumHeight(86)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def update_task(self, task: Task, index: int, active: bool, status: str | None = None) -> None:
        t = theme_mod.current()
        self.task_id = task.id
        self.active = active
        self.rid.setText(f"R.{index + 1:02d}")
        self.name.setText(task.name or "未命名任务")
        if task.trigger_kind == "pulse":
            self.trigger.setText("红石脉冲")
        else:
            unit = "秒" if task.unit == "SECONDS" else "tick"
            self.trigger.setText(f"每 {task.interval} {unit}")
        b = task.batches[0] if task.batches else None
        if b is None:
            self.sentence.setText("还没有批次")
            self.basket_label.setText("取货篮参考 0 / 16")
            self.basket.set_value(0, 16)
        else:
            take = b.take
            sends = b.sends
            send_txt = "、".join(f"{escape(s.target or '未选目标')} / {escape(s.side)}" for s in sends) or "未选目标"
            cond = f" <span style='color:{t.ink2}'>条件</span> {escape(b.condition)} " if b.condition else ""
            self.sentence.setText(
                f"取 <b>{escape(take.source or '未选来源')}</b> / {escape(take.side)}"
                f" <span style='color:{t.ink2}'>→</span> 送 <b>{send_txt}</b>"
                + ("，清空" if b.clear else "")
                + (f"　<span style='color:{t.ink2}'>共 {len(task.batches)} 批次</span>" if len(task.batches) > 1 else "")
            )            # A product-level mini basket: use number of sends/with filters as a light proxy.
            used = min(16, len(sends) + (1 if take.with_filter else 0) + (1 if take.without_filter else 0) + (1 if take.resource_id else 0))
            self.basket_label.setText(f"参考 {used} / 16")
            self.basket.set_value(used, 16)
        if status is None:
            status = "已校验" if task.enabled else "停用"
        self.status.setText(status)
        icon_name = {
            "需修复": "triangle-alert",
            "已校验": "circle-check",
            "停用": "circle-pause",
            "未校验": "circle-dashed",
        }.get(status, "circle-dashed")
        self.status_icon.setPixmap(
            svg_icon(
                icon_name,
                t.on_signal if status == "需修复" else t.ink2,
                11,
            ).pixmap(11, 11)
        )
        if status == "需修复":
            self.status_box.setStyleSheet(
                f"background: {t.signal}; border: 1px solid {t.ink};"
            )
            self.status.setStyleSheet(
                f"color: {t.on_signal}; border: 0; padding: 0; font-size: 9px;"
            )
        elif status == "停用":
            self.status_box.setStyleSheet(
                f"background: transparent; border: 1px dashed {t.rule};"
            )
            self.status.setStyleSheet(
                f"color: {t.ink2}; border: 0; padding: 0; font-size: 9px;"
            )
        else:
            self.status_box.setStyleSheet(
                f"background: transparent; border: 1px solid {t.rule};"
            )
            self.status.setStyleSheet(
                f"color: {t.ink2}; border: 0; padding: 0; font-size: 9px;"
            )
        self.accent.setStyleSheet(f"background: {t.trace if active else 'transparent'};")
        self.setStyleSheet(
            f"QFrame#RuleCard {{ background: {t.panel}; border: 0; border-bottom: 1px solid {t.rule}; }}"
            f"QFrame#RuleCard:hover {{ background: {t.chip}; }}"
        )
        self.basket.update()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            QTimer.singleShot(0, self, lambda: self.clicked.emit(self.task_id))
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        QTimer.singleShot(0, self, lambda: self.editRequested.emit(self.task_id))
        super().mouseDoubleClickEvent(event)

    def enterEvent(self, event) -> None:  # noqa: N802
        self._spot_hover = True
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._spot_hover = False
        self._spot = None
        self.update()
        super().leaveEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        self._spot = event.position()
        if self._spot_hover:
            self.update()
        super().mouseMoveEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        if not self._spot_hover or self._spot is None:
            return
        t = theme_mod.current()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        g = QRadialGradient(self._spot, 170)
        color = QColor(t.signal)
        color.setAlpha(18 if not t.dark else 24)
        g.setColorAt(0.0, color)
        color.setAlpha(0)
        g.setColorAt(1.0, color)
        p.fillRect(self.rect(), g)
        p.end()

    def contextMenuEvent(self, event) -> None:  # noqa: N802
        menu = QMenu(self)
        edit = menu.addAction(theme_icon("pen", muted=False, size=13), "编辑规则")
        edit.triggered.connect(lambda _=False: self.editRequested.emit(self.task_id))
        menu.addSeparator()
        delete = menu.addAction(theme_icon("trash", muted=False, size=13), "删除规则")
        delete.triggered.connect(lambda _=False: self.deleteRequested.emit(self.task_id))
        menu.exec(event.globalPos())
        menu.deleteLater()


# ---------------------------------------------------------------------------
# sidebar
# ---------------------------------------------------------------------------

class Sidebar(QWidget):
    templateRequested = Signal()
    newProjectRequested = Signal()
    openProjectRequested = Signal()
    addLabelRequested = Signal()
    editLabelRequested = Signal(str)
    checkLabelsRequested = Signal()
    labelFilterRequested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedWidth(264)
        self.project: Project | None = None
        self._label_rows: list[QWidget] = []
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        head = QWidget()
        head_lay = QHBoxLayout(head)
        head_lay.setContentsMargins(12, 10, 12, 6)
        head_lay.setSpacing(6)
        eyebrow = QLabel("// ASSETS")
        eyebrow.setObjectName("Eyebrow")
        title = QLabel("零件架")
        title.setFont(ui_font(17, QFont.Weight.Bold))
        head_lay.addWidget(eyebrow)
        head_lay.addWidget(title)
        head_lay.addStretch(1)
        self.count = QLabel("00 设备 / 00 标签")
        self.count.setObjectName("Muted")
        self.count.setFont(ui_font(9))
        head_lay.addWidget(self.count)
        root.addWidget(head)

        search_wrap = QWidget()
        sl = QHBoxLayout(search_wrap)
        sl.setContentsMargins(12, 2, 12, 8)
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索设备 / 标签")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._apply_search)
        sl.addWidget(self.search)
        root.addWidget(search_wrap)

        line = QFrame()
        line.setObjectName("HLine")
        line.setFixedHeight(1)
        root.addWidget(line)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget()
        self.content_lay = QVBoxLayout(content)
        self.content_lay.setContentsMargins(12, 8, 12, 8)
        self.content_lay.setSpacing(4)
        scroll.setWidget(content)
        root.addWidget(scroll, 1)

        # projects
        self.projects_head = QLabel("// PROJECTS 工程")
        self.projects_head.setObjectName("Eyebrow")
        self.content_lay.addWidget(self.projects_head)
        self.project_row = QFrame()
        self.project_row.setObjectName("Panel")
        pr = QVBoxLayout(self.project_row)
        pr.setContentsMargins(8, 6, 8, 6)
        pr.setSpacing(2)
        self.project_name = QLabel("熔炉自动线")
        self.project_name.setFont(ui_font(11, QFont.Weight.DemiBold))
        self.project_meta = QLabel("4 设备 / 3 规则")
        self.project_meta.setObjectName("Muted")
        self.project_meta.setFont(ui_font(9))
        pr.addWidget(self.project_name)
        pr.addWidget(self.project_meta)
        self.project_row.mousePressEvent = lambda e: self.newProjectRequested.emit()  # type: ignore[method-assign]
        self.content_lay.addWidget(self.project_row)

        proj_btns = QHBoxLayout()
        proj_btns.setSpacing(4)
        b = CutButton("模板库", "ghost", True)
        b.clicked.connect(self.templateRequested)
        proj_btns.addWidget(b)
        b2 = CutButton("打开", "ghost", True)
        b2.clicked.connect(self.openProjectRequested)
        proj_btns.addWidget(b2)
        self.content_lay.addLayout(proj_btns)

        line2 = QFrame()
        line2.setObjectName("HLine")
        line2.setFixedHeight(1)
        self.content_lay.addWidget(line2)

        self.assets_head = QLabel("// ASSETS 设备与标签")
        self.assets_head.setObjectName("Eyebrow")
        self.content_lay.addWidget(self.assets_head)
        self.label_box = QVBoxLayout()
        self.label_box.setSpacing(1)
        self.content_lay.addLayout(self.label_box)
        add_label = CutButton("＋ 新建标签", "ghost", True)
        add_label.clicked.connect(self.addLabelRequested)
        self.content_lay.addWidget(add_label)

        line3 = QFrame()
        line3.setObjectName("HLine")
        line3.setFixedHeight(1)
        self.content_lay.addWidget(line3)
        self.content_lay.addStretch(1)

        self.labels_head = QLabel("// LABELS 标签核对")
        self.labels_head.setObjectName("Eyebrow")
        self.content_lay.addWidget(self.labels_head)
        self.label_meta = QLabel("已绑定 00 / 00\n待核对 00")
        self.label_meta.setObjectName("Muted")
        self.label_meta.setFont(ui_font(10))
        self.content_lay.addWidget(self.label_meta)
        check = CutButton("查看清单", "ghost", True)
        check.clicked.connect(self.checkLabelsRequested)
        self.content_lay.addWidget(check)

    def set_project(self, project: Project) -> None:
        self.project = project
        self.project_name.setText(project.name)
        self.project_meta.setText(f"{len(project.labels)} 设备 / {len(project.tasks)} 规则")
        self.count.setText(f"{len(project.labels):02d} 设备 / {len(project.labels):02d} 标签")
        self.label_meta.setText(f"已声明 {len(project.labels):02d} / {len(project.labels):02d}\n待核对 —")
        # clear old rows immediately; deleteLater alone leaves a visible stale row
        while self.label_box.count():
            item = self.label_box.takeAt(0)
            if item.widget():
                w = item.widget()
                w.hide()
                w.setParent(None)
                w.deleteLater()
        for label in project.labels:
            row = LabelRow(label.name, label.kind, label.note)
            row.clicked.connect(self.labelFilterRequested)
            row.editRequested.connect(lambda name=label.id: self.editLabelRequested.emit(name))
            self.label_box.addWidget(row)
        self._label_rows = [self.label_box.itemAt(i).widget() for i in range(self.label_box.count()) if self.label_box.itemAt(i).widget()]
        self._apply_search(self.search.text())

    def _apply_search(self, text: str) -> None:
        needle = text.strip().lower()
        for row in self._label_rows:
            if not row:
                continue
            label = getattr(row, "label_name", "")
            row.setVisible(not needle or needle in label.lower())


class WorkspaceRow(QFrame):
    """Folder header in the DSH-style workspace tree."""

    toggled = Signal(str)
    createSessionRequested = Signal(str)

    def __init__(
        self,
        name: str,
        path: str,
        depth: int = 0,
        expanded: bool = True,
        active: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.path = path
        self.setObjectName("WorkspaceRow")
        self.setProperty("active", active)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(path or "未分组")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(6 + depth * 12, 0, 6, 0)
        lay.setSpacing(3)
        self.arrow = QLabel()
        self.arrow.setObjectName("WorkspaceArrow")
        self.arrow.setPixmap(
            theme_icon("chevron-down" if expanded else "chevron-right", muted=True, size=10).pixmap(10, 10)
        )
        self.arrow.setFixedWidth(10)
        self.arrow.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.arrow)
        self.folder = QLabel()
        self.folder.setPixmap(
            theme_icon("folder-open" if expanded else "folder", muted=not active, size=14).pixmap(14, 14)
        )
        lay.addWidget(self.folder)
        self.name = QLabel(name)
        self.name.setObjectName("WorkspaceName")
        self.name.setProperty("active", active)
        self.name.setFont(ui_font(10, QFont.Weight.DemiBold if active else QFont.Weight.Normal))
        self.name.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.name.setToolTip(path or name)
        lay.addWidget(self.name, 1)
        self.plus = QPushButton("")
        self.plus.setObjectName("WorkspaceAction")
        self.plus.setIcon(theme_icon("plus", muted=True, size=12))
        self.plus.setIconSize(QSize(12, 12))
        self.plus.setFixedSize(26, 26)
        self.plus.setCursor(Qt.CursorShape.PointingHandCursor)
        self.plus.setToolTip("在此工作区新建会话")
        self.plus.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.plus.clicked.connect(self._request_new_session)
        lay.addWidget(self.plus, 0, Qt.AlignmentFlag.AlignRight)
        if not path:
            self.plus.hide()

    def _request_new_session(self) -> None:
        # Finish the button's click/release cycle before the menu rebuilds the
        # sidebar; creating a project deletes and recreates this very row.
        QTimer.singleShot(0, self, lambda: self.createSessionRequested.emit(self.path))

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            QTimer.singleShot(0, self, lambda: self.toggled.emit(self.path))
        super().mousePressEvent(event)


class SessionRow(QFrame):
    """One code/project session inside a workspace folder."""

    clicked = Signal(str)
    deleteRequested = Signal(str, str)
    openRequested = Signal(str)
    renameRequested = Signal(str)
    revealRequested = Signal(str)
    dropRequested = Signal(str, str, bool)
    dragFinished = Signal()
    SESSION_MIME = "application/x-sfm-session"

    def __init__(
        self,
        name: str,
        path: str,
        meta: str,
        current: bool = False,
        depth: int = 0,
        workspace_path: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.path = path
        self.workspace_path = workspace_path
        self._press_pos: QPoint | None = None
        self._dragged = False
        self._menu_choice = ""
        self._drag_order_pending = False
        self.setAcceptDrops(True)
        self.setObjectName("SessionRow")
        self.setProperty("current", current)
        self.setMinimumHeight(26)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(path or name)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14 + depth * 12, 0, 8, 0)
        lay.setSpacing(6)
        file_icon = QLabel()
        file_icon.setFixedSize(14, 14)
        file_icon.setPixmap(
            theme_icon("file-code", muted=not current, size=13).pixmap(13, 13)
        )
        lay.addWidget(file_icon, 0, Qt.AlignmentFlag.AlignVCenter)
        self.name = QLabel(name)
        self.name.setObjectName("SessionTitle")
        self.name.setFont(ui_font(10, QFont.Weight.DemiBold if current else QFont.Weight.Normal))
        self.name.setToolTip(name)
        self.name.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.meta = QLabel(meta)
        self.meta.setObjectName("SessionTime")
        self.meta.setProperty("current", current)
        self.meta.setFont(ui_font(8, QFont.Weight.DemiBold if current else QFont.Weight.Normal))
        self.meta.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        lay.addWidget(self.name, 1)
        lay.addWidget(self.meta, 0)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_pos = event.position().toPoint()
            self._dragged = False
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if (
            self._press_pos is not None
            and event.buttons() & Qt.MouseButton.LeftButton
            and self.path
            and (event.position().toPoint() - self._press_pos).manhattanLength()
            >= QApplication.startDragDistance()
        ):
            self._press_pos = None
            self._dragged = True
            drag = QDrag(self)
            mime = QMimeData()
            mime.setData(self.SESSION_MIME, str(self.path).encode("utf-8"))
            drag.setMimeData(mime)
            drag.setPixmap(self.grab())
            drag.exec(Qt.DropAction.MoveAction)
            self.dragFinished.emit()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            if self._press_pos is not None and not self._dragged:
                QTimer.singleShot(0, self, lambda: self.clicked.emit(self.path))
            self._press_pos = None
            self._dragged = False
        super().mouseReleaseEvent(event)

    def _build_menu(self) -> QMenu:
        menu = QMenu(self)
        open_action = menu.addAction(theme_icon("folder-open", muted=False, size=13), "打开")
        open_action.triggered.connect(lambda _=False: self._choose_menu("open"))
        rename_action = menu.addAction(theme_icon("pen", muted=False, size=13), "重命名")
        rename_action.triggered.connect(lambda _=False: self._choose_menu("rename"))
        reveal_action = menu.addAction(theme_icon("folder", muted=True, size=13), "在文件夹中显示")
        reveal_action.triggered.connect(lambda _=False: self._choose_menu("reveal"))
        menu.addSeparator()
        delete = menu.addAction(theme_icon("trash", muted=False, size=13), "删除")
        delete.triggered.connect(lambda _=False: self._choose_menu("delete"))
        return menu

    def _choose_menu(self, choice: str) -> None:
        # Do not emit into MainWindow while QMenu.exec() is on the stack:
        # opening a session rebuilds the sidebar and can destroy this row.
        self._menu_choice = choice

    def contextMenuEvent(self, event) -> None:  # noqa: N802
        if not self.path:
            return
        self._menu_choice = ""
        menu = self._build_menu()
        menu.exec(event.globalPos())
        choice = self._menu_choice
        menu.deleteLater()
        if choice == "open":
            self.openRequested.emit(self.path)
        elif choice == "rename":
            self.renameRequested.emit(self.path)
        elif choice == "reveal":
            self.revealRequested.emit(self.path)
        elif choice == "delete":
            self.deleteRequested.emit(self.path, self.workspace_path)

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasFormat(self.SESSION_MIME):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasFormat(self.SESSION_MIME):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event) -> None:  # noqa: N802
        if not event.mimeData().hasFormat(self.SESSION_MIME):
            return event.ignore()
        raw = bytes(event.mimeData().data(self.SESSION_MIME)).decode("utf-8", "replace")
        after = event.position().toPoint().y() > self.height() // 2
        self.dropRequested.emit(raw, self.path, after)
        event.acceptProposedAction()


class DSHSidebar(QWidget):
    """DeepSeek-Harness-like workspace rail.

    The current project detail lives in the rules area; this rail only holds
    create/open actions, the recent-project workspace and device-level status.
    """

    templateRequested = Signal()
    newProjectRequested = Signal()
    newSessionRequested = Signal()
    openProjectRequested = Signal()
    recentRequested = Signal(str)
    workspaceAddRequested = Signal()
    sessionCreateRequested = Signal(str)
    sessionDeleteRequested = Signal(str, str)
    sessionOrderChanged = Signal(str, list)
    sessionOpenRequested = Signal(str)
    sessionRenameRequested = Signal(str)
    sessionRevealRequested = Signal(str)
    recycleRequested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedWidth(264)
        self._groups: list[dict] = []
        self._collapsed: set[str] = set()
        self._current_name = ""
        self._current_path = ""
        self._drag_order_changed = False
        self._pending_session_order: tuple[str, list[str]] | None = None
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        brand = QWidget()
        bl = QHBoxLayout(brand)
        bl.setContentsMargins(12, 12, 12, 8)
        bl.setSpacing(8)
        mark = QLabel("S")
        mark.setObjectName("BrandMark")
        mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mark.setFixedSize(28, 28)
        bl.addWidget(mark)
        names = QVBoxLayout()
        names.setSpacing(0)
        n1 = QLabel("SFM")
        n1.setFont(ui_font(13, QFont.Weight.Black))
        n2 = QLabel("CODE WORKSHOP")
        n2.setObjectName("Muted")
        n2.setFont(ui_font(8))
        n2.setStyleSheet("letter-spacing: 1px;")
        names.addWidget(n1)
        names.addWidget(n2)
        bl.addLayout(names)
        bl.addStretch(1)
        root.addWidget(brand)

        new_wrap = QWidget()
        nl = QVBoxLayout(new_wrap)
        nl.setContentsMargins(12, 3, 12, 7)
        newb = CutButton("＋ 新建会话", "ghost", True)
        newb.setMinimumHeight(32)
        newb.clicked.connect(self.newSessionRequested)
        nl.addWidget(newb)
        root.addWidget(new_wrap)

        nav = QWidget()
        navl = QVBoxLayout(nav)
        navl.setContentsMargins(6, 0, 6, 0)
        navl.setSpacing(1)
        self._nav_buttons: list[QPushButton] = []
        for text, icon_name, slot in (
            ("模板库", "layout-template", self.templateRequested),
        ):
            b = QPushButton(f"{text}")
            b.setObjectName("SidebarNav")
            b.setIcon(theme_icon(icon_name, muted=True, size=14))
            b.setIconSize(QSize(14, 14))
            b.setProperty("dshIcon", icon_name)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(slot)
            navl.addWidget(b)
            self._nav_buttons.append(b)
        root.addWidget(nav)

        sep = QFrame()
        sep.setObjectName("HLine")
        sep.setFixedHeight(1)
        root.addWidget(sep)

        ws = QWidget()
        wl = QVBoxLayout(ws)
        wl.setContentsMargins(12, 10, 12, 5)
        wl.setSpacing(5)
        head = QHBoxLayout()
        h = QLabel("工作区")
        h.setObjectName("Muted")
        h.setFont(ui_font(9))
        head.addWidget(h)
        head.addStretch(1)
        count = QLabel("")
        count.setObjectName("Muted")
        count.setFont(ui_font(8))
        head.addWidget(count)
        add_ws = QPushButton("")
        add_ws.setObjectName("SidebarPlus")
        add_ws.setIcon(theme_icon("folder-plus", muted=True, size=12))
        add_ws.setIconSize(QSize(12, 12))
        add_ws.setProperty("dshIcon", "folder-plus")
        add_ws.setToolTip("添加工作区文件夹")
        add_ws.setFixedSize(20, 20)
        add_ws.setCursor(Qt.CursorShape.PointingHandCursor)
        add_ws.clicked.connect(self.workspaceAddRequested)
        head.addWidget(add_ws)
        wl.addLayout(head)
        self.search = QLineEdit()
        self.search.setObjectName("SidebarSearch")
        self.search.setPlaceholderText("搜索工作区 / 会话")
        self.search.setClearButtonEnabled(True)
        apply_search_icon(self.search, "search", muted=True)
        self.search.textChanged.connect(self._refresh_workspaces)
        wl.addWidget(self.search)
        root.addWidget(ws)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setObjectName("SidebarScroll")
        content = QWidget()
        content.setObjectName("SidebarContent")
        self.recent_lay = QVBoxLayout(content)
        self.recent_lay.setContentsMargins(8, 2, 8, 8)
        self.recent_lay.setSpacing(2)
        self.scroll.setWidget(content)
        root.addWidget(self.scroll, 1)

        bottom = QFrame()
        bottom.setObjectName("SidebarStatus")
        bl2 = QVBoxLayout(bottom)
        bl2.setContentsMargins(12, 9, 12, 10)
        bl2.setSpacing(2)
        self.profile_label = QLabel("本地优先 · 无遥测")
        self.profile_label.setFont(ui_font(9, QFont.Weight.DemiBold))
        bl2.addWidget(self.profile_label)
        self.recycle_btn = QPushButton("回收站")
        self.recycle_btn.setObjectName("SidebarRecycle")
        self.recycle_btn.setIcon(theme_icon("trash", muted=True, size=14))
        self.recycle_btn.setIconSize(QSize(14, 14))
        self.recycle_btn.setMinimumHeight(28)
        self.recycle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.recycle_btn.setToolTip("打开应用回收站文件夹")
        self.recycle_btn.clicked.connect(lambda _=False: self.recycleRequested.emit())
        bl2.addWidget(self.recycle_btn)
        bottom_wrap = QWidget()
        bwl = QHBoxLayout(bottom_wrap)
        bwl.setContentsMargins(12, 0, 12, 6)
        bwl.setSpacing(0)
        bwl.addWidget(bottom)
        root.addWidget(bottom_wrap)
        self._empty = QLabel("尚未保存工程。保存后可在这里快速打开。")
        self._empty.setObjectName("Muted")
        self._empty.setFont(ui_font(8))
        self._empty.setWordWrap(True)
        self._empty.setContentsMargins(8, 8, 8, 8)
        self.recent_lay.addWidget(self._empty)
        self._count = count
        self._workspace_add = add_ws
        self._refresh_workspaces()

    def apply_theme_icons(self) -> None:
        for b in getattr(self, "_nav_buttons", []):
            name = b.property("dshIcon")
            if name:
                b.setIcon(theme_icon(str(name), muted=True, size=14))
        if hasattr(self, "_workspace_add"):
            self._workspace_add.setIcon(theme_icon("folder-plus", muted=True, size=12))
        if hasattr(self, "recycle_btn"):
            self.recycle_btn.setIcon(theme_icon("trash", muted=True, size=13))
        apply_search_icon(self.search, "search", muted=True)

    def set_profile(self, label: str) -> None:
        self.profile_label.setText("本地优先 · 无遥测")
        self.profile_label.setToolTip(label)
        apply_search_icon(self.search, "search", muted=True)

    def set_workspaces(self, groups: list[dict], current_name: str = "", current_path: str = "") -> None:
        self._groups = [g for g in groups if isinstance(g, dict)]
        self._current_name = current_name
        self._current_path = current_path
        self._refresh_workspaces()

    def expand_workspace(self, path: str) -> None:
        by_path = {str(g.get("path") or ""): g for g in self._groups if isinstance(g, dict)}
        current = path
        seen: set[str] = set()
        while current and current not in seen:
            seen.add(current)
            self._collapsed.discard(current)
            group = by_path.get(current)
            current = str(group.get("parent_path") or "") if group else ""

    def set_recent(self, recent: list[dict], current_name: str = "", current_path: str = "") -> None:
        # Compatibility for callers that still pass a flat recent list.
        from ..core.workspaces import group_projects

        self.set_workspaces(group_projects(recent, current_name=current_name, current_path=current_path), current_name, current_path)

    def _refresh_workspaces(self) -> None:
        needle = self.search.text().strip().lower()
        scroll_value = self.scroll.verticalScrollBar().value() if hasattr(self, "scroll") else 0
        while self.recent_lay.count():
            item = self.recent_lay.takeAt(0)
            if item.widget():
                w = item.widget()
                w.hide()
                w.setParent(None)
                w.deleteLater()

        groups = [g for g in self._groups if isinstance(g, dict)]
        by_path = {str(g.get("path") or ""): g for g in groups}
        children: dict[str, list[dict]] = {}
        roots: list[dict] = []
        for group in groups:
            parent = str(group.get("parent_path") or "")
            if parent and parent in by_path and parent != group.get("path"):
                children.setdefault(parent, []).append(group)
            else:
                roots.append(group)
        for buckets in children.values():
            buckets.sort(key=lambda g: str(g.get("name") or "").lower())
        roots.sort(key=lambda g: (0 if g.get("default") else 1 if g.get("id") != "ungrouped" else 2, str(g.get("name") or "").lower()))

        try:
            current_key = str(Path(self._current_path).resolve()) if self._current_path else ""
        except Exception:
            current_key = self._current_path

        def canonical(path: str) -> str:
            try:
                return str(Path(path).resolve()) if path else ""
            except Exception:
                return path

        def session_matches(item: dict) -> bool:
            if not needle:
                return True
            return needle in str(item.get("name") or "").lower() or needle in str(item.get("path") or "").lower()

        def group_contains_current(group: dict, seen: set[str] | None = None) -> bool:
            seen = seen or set()
            key = str(group.get("path") or "")
            if key in seen:
                return False
            seen.add(key)
            for item in group.get("projects", []):
                if item.get("current"):
                    return True
                path = str(item.get("path") or "")
                if current_key and canonical(path) == current_key:
                    return True
            return any(group_contains_current(child, seen) for child in children.get(key, []))

        total = 0

        def visible_group(group: dict, force_all: bool = False) -> tuple[list[dict], list[tuple[dict, bool]]]:
            path = str(group.get("path") or "")
            name = str(group.get("name") or "")
            group_hit = bool(needle) and (needle in name.lower() or needle in path.lower())
            show_all = force_all or group_hit
            direct = [p for p in group.get("projects", []) if show_all or session_matches(p)]
            child_rows = []
            for child in children.get(path, []):
                child_direct, child_children = visible_group(child, show_all)
                if not needle or child_direct or child_children:
                    child_rows.append(child)
            return direct, [(child, show_all) for child in child_rows]

        def render(group: dict, depth: int, force_all: bool = False) -> int:
            nonlocal total
            path = str(group.get("path") or "")
            name = str(group.get("name") or "")
            group_hit = bool(needle) and (needle in name.lower() or needle in path.lower())
            show_all = force_all or group_hit
            direct = [p for p in group.get("projects", []) if show_all or session_matches(p)]
            child_rows = children.get(path, [])
            # Decide child visibility before adding the header, without drawing.
            children_visible = []
            for child in child_rows:
                c_direct, c_children = visible_group(child, show_all)
                if not needle or group_hit or c_direct or c_children:
                    children_visible.append(child)
            if needle and not group_hit and not direct and not children_visible:
                return 0
            expanded = bool(needle) or path not in self._collapsed or not path
            active = group_contains_current(group)
            header = WorkspaceRow(name or "工作区", path, depth, expanded, active)
            header.toggled.connect(self._toggle_group)
            header.createSessionRequested.connect(self.sessionCreateRequested)
            if not path:
                header.plus.hide()
            self.recent_lay.addWidget(header)

            if expanded:
                for child in children_visible:
                    render(child, depth + 1, show_all)
                for item in direct:
                    item_path = str(item.get("path") or "")
                    current = bool(item.get("current")) or bool(current_key and canonical(item_path) == current_key)
                    meta = _relative_time(str(item.get("at") or "")) or "刚刚"
                    if current:
                        meta += " · 当前"
                    row = SessionRow(
                        str(item.get("name") or "未命名会话"),
                        item_path,
                        meta,
                        current,
                        depth,
                        path,
                    )
                    row.clicked.connect(self.recentRequested)
                    row.deleteRequested.connect(self.sessionDeleteRequested)
                    row.openRequested.connect(self.sessionOpenRequested)
                    row.renameRequested.connect(self.sessionRenameRequested)
                    row.revealRequested.connect(self.sessionRevealRequested)
                    row.dropRequested.connect(self._on_session_drop)
                    row.dragFinished.connect(self._after_session_drag)
                    self.recent_lay.addWidget(row)
                    total += 1
                if path and not direct and not child_rows and not needle:
                    empty = QLabel("空工作区 · 点 + 新建会话")
                    empty.setObjectName("Muted")
                    empty.setFont(ui_font(8))
                    empty.setContentsMargins(22 + depth * 12, 2, 8, 4)
                    self.recent_lay.addWidget(empty)
            return 1

        for group in roots:
            render(group, 0)

        if total == 0 and needle:
            empty = QLabel("没有匹配的工作区或会话。")
            empty.setObjectName("Muted")
            empty.setFont(ui_font(8))
            empty.setWordWrap(True)
            empty.setContentsMargins(8, 8, 8, 8)
            self.recent_lay.addWidget(empty)
        elif not groups:
            empty = QLabel("还没有工作区。用上方 + 添加一个目录。")
            empty.setObjectName("Muted")
            empty.setFont(ui_font(8))
            empty.setWordWrap(True)
            empty.setContentsMargins(8, 8, 8, 8)
            self.recent_lay.addWidget(empty)
        self.recent_lay.addStretch(1)
        self._count.setText(f"{total}" if total else "")
        if hasattr(self, "scroll"):
            QTimer.singleShot(0, lambda: self.scroll.verticalScrollBar().setValue(scroll_value))

    def _toggle_group(self, path: str) -> None:
        if path in self._collapsed:
            self._collapsed.remove(path)
        else:
            self._collapsed.add(path)
        self._refresh_workspaces()

    def _on_session_drop(self, source_path: str, target_path: str, after: bool) -> None:
        def canonical(value: str) -> str:
            try:
                return str(Path(value).resolve()) if value else ""
            except Exception:
                return value

        source_key = canonical(source_path)
        target_key = canonical(target_path)
        if not source_key or source_key == target_key:
            return
        source_group = None
        target_group = None
        source_item = None
        target_index = -1
        for group in self._groups:
            projects = group.get("projects", [])
            for index, item in enumerate(projects):
                key = canonical(str(item.get("path") or ""))
                if key == source_key:
                    source_group = group
                    source_item = item
                if key == target_key:
                    target_group = group
                    target_index = index
        if source_group is None or target_group is None or source_group is not target_group:
            return
        projects = source_group["projects"]
        if source_item not in projects:
            return
        source_index = projects.index(source_item)
        projects.pop(source_index)
        if source_index < target_index:
            target_index -= 1
        if after:
            target_index += 1
        target_index = max(0, min(target_index, len(projects)))
        projects.insert(target_index, source_item)
        order = [str(p.get("path") or "") for p in projects if p.get("path")]
        self._pending_session_order = (str(source_group.get("path") or ""), order)
        self._drag_order_changed = True

    def _after_session_drag(self) -> None:
        if not self._drag_order_changed:
            return
        self._drag_order_changed = False
        pending = self._pending_session_order
        self._pending_session_order = None
        if pending is not None:
            self.sessionOrderChanged.emit(pending[0], pending[1])
        # QDrag has returned at this point. Rebuild on the next main-loop
        # iteration, never inside the drag event loop.
        QTimer.singleShot(0, self, self._refresh_workspaces)


def _relative_time(value: str) -> str:
    try:
        from datetime import datetime

        dt = datetime.fromisoformat(value)
        seconds = max(0, int((datetime.now() - dt).total_seconds()))
        if seconds < 60:
            return "刚刚"
        if seconds < 3600:
            return f"{seconds // 60} 分钟"
        if seconds < 86400:
            return f"{seconds // 3600} 小时"
        return f"{seconds // 86400} 天"
    except Exception:
        return ""


class LabelRow(QFrame):
    clicked = Signal(str)
    editRequested = Signal(str)

    def __init__(self, name: str, kind: str, note: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.label_name = name
        self.setObjectName("LabelRow")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(4, 5, 4, 5)
        lay.setSpacing(7)
        dot = MiniLabel()
        lay.addWidget(dot)
        col = QVBoxLayout()
        col.setSpacing(1)
        n = QLabel(name)
        n.setFont(ui_font(11, QFont.Weight.DemiBold))
        k = QLabel(f"{kind} / {note or '未备注'}")
        k.setObjectName("Muted")
        k.setFont(ui_font(9))
        col.addWidget(n)
        col.addWidget(k)
        lay.addLayout(col, 1)
        self.setStyleSheet(
            f"QFrame#LabelRow {{ border-bottom: 1px solid {theme_mod.current().rule}; }}"
        )
        self.setToolTip("单击筛选；双击编辑标签")

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.label_name)
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        self.editRequested.emit(self.label_name)
        super().mouseDoubleClickEvent(event)


# ---------------------------------------------------------------------------
# code view
# ---------------------------------------------------------------------------

class LineNumberArea(QWidget):
    def __init__(self, editor: "CodeView") -> None:
        super().__init__(editor)
        self.editor = editor

    def sizeHint(self) -> QSize:
        return QSize(self.editor.line_number_width(), 0)

    def paintEvent(self, event) -> None:  # noqa: N802
        self.editor.line_number_paint(event)


# QSyntaxHighlighter is imported separately to keep the class list tidy.
from PySide6.QtGui import QSyntaxHighlighter, QTextDocument  # noqa: E402


class _Highlighter(QSyntaxHighlighter):
    def __init__(self, document: QTextDocument) -> None:
        super().__init__(document)
        self.rehighlight()

    def highlightBlock(self, text: str) -> None:  # noqa: N802
        t = theme_mod.current()
        # comments first
        idx = text.find("--")
        code = text if idx < 0 else text[:idx]
        if idx >= 0:
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(t.ink2))
            fmt.setFontItalic(True)
            self.setFormat(idx, len(text) - idx, fmt)
        # strings
        import re

        for m in re.finditer(r'"(?:\\.|[^"\\])*"', code):
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(t.ink2 if not t.dark else t.trace))
            self.setFormat(m.start(), m.end() - m.start(), fmt)
        # keywords
        kw = (
            r"\b(EVERY|DO|END|INPUT|OUTPUT|FORGET|IF|THEN|ELSE|FROM|TO|SIDE|"
            r"RETAIN|EACH|WITH|WITHOUT|ROUND|ROBIN|BY|LABEL|BLOCK|SLOTS|"
            r"TICKS|TICK|SECONDS|SECOND|REDSTONE|PULSE|GLOBAL|PLUS|EXCEPT|"
            r"NOT|AND|OR|HAS|OVERALL|EMPTY)\b"
        )
        for m in re.finditer(kw, code, re.IGNORECASE):
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(t.ink))
            fmt.setFontWeight(QFont.Weight.DemiBold)
            self.setFormat(m.start(), m.end() - m.start(), fmt)
        for m in re.finditer(r"\b\d+\b", code):
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(t.trace))
            self.setFormat(m.start(), m.end() - m.start(), fmt)


class CodeView(QPlainTextEdit):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("CodeView")
        self.setReadOnly(True)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setFont(mono_font(11))
        self.setTabStopDistance(QFontMetrics(self.font()).horizontalAdvance(" ") * 4)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.line_area = LineNumberArea(self)
        self.blockCountChanged.connect(self._update_width)
        self.updateRequest.connect(self._update_area)
        self.cursorPositionChanged.connect(self._highlight_current)
        self._highlighter = _Highlighter(self.document())
        self._issue_lines: dict[int, str] = {}
        self._update_width()

    def set_code(self, text: str) -> None:
        if text == self.toPlainText():
            return
        self.setPlainText(text)
        self.setExtraSelections([])
        self._highlighter.rehighlight()
        self._update_width()

    def set_issue_lines(self, lines: dict[int, str]) -> None:
        self._issue_lines = {int(k): str(v) for k, v in lines.items() if k}
        self.line_area.update()

    def jump_to_line(self, line: int) -> None:
        if line <= 0:
            return
        block = self.document().findBlockByNumber(min(line - 1, max(0, self.blockCount() - 1)))
        if not block.isValid():
            return
        cursor = QTextCursor(block)
        self.setTextCursor(cursor)
        self.centerCursor()
        sel = QTextEdit.ExtraSelection()
        sel.cursor = cursor
        sel.format.setBackground(QColor(255, 179, 31, 32))
        sel.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
        self.setExtraSelections([sel])

    def refresh_theme(self) -> None:
        self._highlighter.rehighlight()
        self._highlight_current()
        self.line_area.update()

    def line_number_width(self) -> int:
        digits = max(2, len(str(max(1, self.blockCount()))))
        return 12 + QFontMetrics(self.font()).horizontalAdvance("9") * digits

    def _update_width(self, _: int = 0) -> None:
        self.setViewportMargins(self.line_number_width(), 0, 0, 0)

    def _update_area(self, rect, dy: int) -> None:
        if dy:
            self.line_area.scroll(0, dy)
        else:
            self.line_area.update(0, rect.y(), self.line_area.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self._update_width()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        cr = self.contentsRect()
        self.line_area.setGeometry(QRect(cr.left(), cr.top(), self.line_number_width(), cr.height()))

    def line_number_paint(self, event) -> None:
        t = theme_mod.current()
        p = QPainter(self.line_area)
        p.fillRect(event.rect(), QColor(t.paper))
        block = self.firstVisibleBlock()
        num = block.blockNumber()
        top = round(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom = top + round(self.blockBoundingRect(block).height())
        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                level = self._issue_lines.get(num + 1)
                if level:
                    color = {
                        "block": t.signal,
                        "possible": t.signal,
                        "reminder": t.ink2,
                        "info": t.rule,
                    }.get(level, t.rule)
                    p.fillRect(QRect(2, top + 4, 5, 5), QColor(color))
                p.setPen(QColor(t.ink2))
                p.setFont(ui_font(9))
                p.drawText(0, top, self.line_area.width() - 6, self.fontMetrics().height(),
                           Qt.AlignmentFlag.AlignRight, str(num + 1))
            block = block.next()
            top = bottom
            bottom = top + round(self.blockBoundingRect(block).height())
            num += 1

    def _highlight_current(self) -> None:
        if self.isReadOnly():
            return
        t = theme_mod.current()
        sel = QTextEdit.ExtraSelection()
        sel.format.setBackground(QColor(t.signal))
        sel.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
        sel.cursor = self.textCursor()
        sel.cursor.clearSelection()
        self.setExtraSelections([sel])


# ---------------------------------------------------------------------------
# issues and efficiency
# ---------------------------------------------------------------------------

@dataclass
class IssueView:
    level: str
    title: str
    detail: str
    ref: str
    line: int = 0


class IssueRow(QWidget):
    clicked = Signal(int)

    def __init__(self, issue: IssueView, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.issue = issue
        self.setObjectName("IssueRow")
        self.setCursor(Qt.CursorShape.PointingHandCursor if issue.line else Qt.CursorShape.ArrowCursor)
        if issue.line:
            self.setToolTip(f"定位到代码 L.{issue.line}")
        t = theme_mod.current()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(2, 5, 2, 5)
        lay.setSpacing(7)
        icon_name = {
            "block": "circle-x",
            "possible": "triangle-alert",
            "reminder": "circle-alert",
            "info": "info",
        }.get(issue.level, "info")
        badge = QLabel()
        badge.setFixedSize(20, 20)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setPixmap(theme_icon(icon_name, muted=issue.level in ("info", "reminder"), size=14).pixmap(14, 14))
        if issue.level in ("block", "possible"):
            badge.setStyleSheet(
                f"background: {t.signal}; border: 1px solid {t.ink};"
            )
        else:
            badge.setStyleSheet(f"background: transparent; border: 1px solid {t.rule};")
        lay.addWidget(badge, 0, Qt.AlignmentFlag.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(1)
        top = QHBoxLayout()
        kind = QLabel({"block": "阻断", "possible": "可能", "reminder": "提醒"}.get(issue.level, "信息"))
        kind.setFont(ui_font(9, QFont.Weight.DemiBold))
        kind.setStyleSheet(f"color: {t.ink2};")
        kind.setFixedWidth(30)
        kind.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        title = QLabel(issue.title)
        title.setFont(ui_font(10, QFont.Weight.DemiBold))
        title.setWordWrap(True)
        top.addWidget(kind, 0, Qt.AlignmentFlag.AlignTop)
        top.addWidget(title, 1, Qt.AlignmentFlag.AlignTop)
        col.addLayout(top)
        bottom = QHBoxLayout()
        bottom.setSpacing(6)
        if issue.detail:
            detail = QLabel(issue.detail)
            detail.setObjectName("Muted")
            detail.setFont(ui_font(9))
            detail.setWordWrap(True)
            bottom.addWidget(detail, 1)
        else:
            bottom.addStretch(1)
        ref = QLabel(issue.ref)
        ref.setObjectName("Muted")
        ref.setFont(ui_font(9))
        ref.setMinimumWidth(34)
        ref.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom)
        bottom.addWidget(ref, 0, Qt.AlignmentFlag.AlignBottom)
        col.addLayout(bottom)
        lay.addLayout(col, 1)
        # QLabel word-wrap does not always propagate its full wrapped height
        # through nested layouts; keep a readable minimum so issue rows never
        # overlap when a batch produces several messages.
        self.setMinimumHeight(58)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(int(self.issue.line or 0))
        super().mousePressEvent(event)


class IssueList(QWidget):
    issueActivated = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(0, 0, 0, 0)
        self.lay.setSpacing(0)
        self.set_issues([], 0)

    def set_issues(self, issues: list[IssueView], total: int) -> None:
        while self.lay.count():
            item = self.lay.takeAt(0)
            if item.widget():
                w = item.widget()
                w.hide()
                w.setParent(None)
                w.deleteLater()
        if not issues:
            empty = QWidget()
            empty_lay = QVBoxLayout(empty)
            empty_lay.setContentsMargins(2, 10, 2, 10)
            empty_lay.setSpacing(4)
            icon = QLabel()
            icon.setPixmap(theme_icon("shield-check", muted=True, size=20).pixmap(20, 20))
            icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty_lay.addWidget(icon)
            empty_label = QLabel("没有发现问题。\n复制前仍会做本地语法/语义检查。")
            empty_label.setObjectName("Muted")
            empty_label.setFont(ui_font(10))
            empty_label.setWordWrap(True)
            empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty_lay.addWidget(empty_label)
            self.lay.addWidget(empty)
        else:
            for issue in issues:
                row = IssueRow(issue)
                row.clicked.connect(self.issueActivated)
                self.lay.addWidget(row)
        self.lay.addStretch(1)


class EstimateBar(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.value = 0.0
        self.setFixedHeight(10)
        self.setMinimumWidth(100)

    def set_value(self, value: float) -> None:
        self.value = max(0.0, min(1.0, float(value)))
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        t = theme_mod.current()
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(t.chip))
        w = int(self.width() * self.value)
        p.fillRect(QRect(0, 0, w, self.height()), QColor(t.trace))
        p.setPen(QPen(QColor(t.rule), 1))
        p.drawRect(self.rect().adjusted(0, 0, -1, -1))


class EfficiencyPanel(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(2, 8, 2, 4)
        self.lay.setSpacing(6)
        head = QHBoxLayout()
        title = QLabel("TPS 影响估算")
        title.setFont(ui_font(12, QFont.Weight.Bold))
        self.level = QLabel("启发式")
        self.level.setObjectName("Signal")
        self.level.setFont(ui_font(9, QFont.Weight.Bold))
        head.addWidget(title)
        head.addWidget(self.level)
        head.addStretch(1)
        self.note = QLabel("基于代码静态估算，不是实测")
        self.note.setObjectName("Muted")
        self.note.setFont(ui_font(9))
        head.addWidget(self.note)
        self.lay.addLayout(head)
        self.score = QLabel("—")
        self.score.setFont(ui_font(28, QFont.Weight.Black))
        self.lay.addWidget(self.score)
        self.bar = EstimateBar()
        self.lay.addWidget(self.bar)
        self.summary = QLabel("")
        self.summary.setObjectName("Muted")
        self.summary.setFont(ui_font(9))
        self.summary.setWordWrap(True)
        self.lay.addWidget(self.summary)
        self.warnings = QLabel("")
        self.warnings.setFont(ui_font(9))
        self.warnings.setWordWrap(True)
        self.lay.addWidget(self.warnings)
        self.factors = QLabel("")
        self.factors.setFont(ui_font(9))
        self.factors.setWordWrap(True)
        self.lay.addWidget(self.factors)
        self.suggestions = QLabel("")
        self.suggestions.setFont(ui_font(9))
        self.suggestions.setWordWrap(True)
        self.lay.addWidget(self.suggestions)
        self.lay.addStretch(1)

    def set_estimate(self, est) -> None:
        if est is None:
            self.score.setText("—")
            self.summary.setText("生成代码后自动估算。")
            return
        t = theme_mod.current()
        level = getattr(est, "level", "未知")
        score = float(getattr(est, "score", 0.0))
        self.level.setText(f"相对 {level}")
        self.score.setText(f"{score:.1f}")
        self.score.setStyleSheet(f"color: {t.ink};")
        self.bar.set_value(min(1.0, score / 100.0))
        self.summary.setText(getattr(est, "note", "静态估算，不是实测") + "；相对指数，不是通过/不通过。")
        warns = getattr(est, "warnings", []) or []
        self.warnings.setText("<br>".join(f"⚠ {escape(str(w))}" for w in warns[:4]))
        fs = getattr(est, "factors", []) or []
        self.factors.setText(
            "<br>".join(
                f"<span style='color:{t.ink2}'>{escape(str(getattr(f, 'name', '')))}</span> × {getattr(f, 'value', '')}"
                for f in fs[:6]
            )
        )
        sugs = getattr(est, "suggestions", []) or []
        self.suggestions.setText(
            "<br>".join(f"· {escape(str(s))}" for s in sugs[:4])
        )
