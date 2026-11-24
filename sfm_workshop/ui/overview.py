"""Workbench overview: the project's operational dashboard.

The page is intentionally local-first: every number comes from the current
project, the local validator, or the deterministic TPS estimate.  It follows
the Ingot UI overview-template structure (hero, KPI row, health, quick
actions, activity ledger) but uses the workshop's paper/ink/amber language.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from PySide6.QtCore import QEasingCurve, QPoint, QRectF, QSize, Qt, QTimer, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsOpacityEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..core.model import Project
from . import theme as theme_mod
from .icons import icon as svg_icon
from .theme import mono_font, ui_font
from .widgets import CutButton, SectionHeader


def _fmt_int(value: int | float | None) -> str:
    try:
        return f"{int(value):,}"
    except Exception:
        return "—"


class HeroPanel(QFrame):
    """Dotted field + one signal diagonal, used by the overview hero."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("HeroPanel")
        self.setMinimumHeight(160)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        t = theme_mod.current()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        # Dot field: a quiet technical texture rather than a flat hero.
        p.setPen(Qt.PenStyle.NoPen)
        dot = QColor(t.ink2)
        dot.setAlpha(54 if not t.dark else 68)
        for x in range(18, self.width(), 22):
            for y in range(18, self.height(), 22):
                p.drawEllipse(QRectF(x, y, 1.5, 1.5))
        # Keep the signature diagonal below the status line, so it never
        # crosses the "SAVED / MC version" readout.
        p.setPen(QPen(QColor(t.signal), 1))
        p.drawLine(self.width() - 150, self.height() - 22, self.width() - 58, 88)
        p.setPen(QPen(QColor(t.rule), 1))
        p.drawLine(14, self.height() - 1, self.width() - 14, self.height() - 1)
        p.end()


class StatCard(QFrame):
    clicked = Signal()

    def __init__(self, icon_name: str, label: str, accent: bool = False, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("StatCard")
        self.setProperty("accent", accent)
        self.setMinimumHeight(82)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._icon_name = icon_name
        self._value_anim: QVariantAnimation | None = None
        self._last_numeric: int | None = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(13, 8, 13, 7)
        lay.setSpacing(1)
        top = QHBoxLayout()
        top.setSpacing(7)
        self.icon = QLabel()
        self.icon.setFixedSize(15, 15)
        self.icon.setPixmap(svg_icon(icon_name, theme_mod.current().ink2, 14).pixmap(14, 14))
        top.addWidget(self.icon)
        self.label = QLabel(label)
        self.label.setObjectName("StatLabel")
        self.label.setFont(ui_font(10))
        top.addWidget(self.label, 1)
        lay.addLayout(top)
        self.value = QLabel("—")
        self.value.setObjectName("StatValue")
        self.value.setFont(ui_font(22, QFont.Weight.Bold))
        lay.addWidget(self.value)
        self.hint = QLabel("")
        self.hint.setObjectName("StatHint")
        self.hint.setFont(mono_font(10))
        lay.addWidget(self.hint)
        for child in (self.icon, self.label, self.value, self.hint):
            child.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def set_data(self, value: str, hint: str = "", tone: str = "") -> None:
        self.hint.setText(hint)
        target = None
        try:
            target = int(value.replace(",", ""))
        except (TypeError, ValueError):
            target = None
        if target is None or target == self._last_numeric:
            self.value.setText(value)
            self._last_numeric = target
        else:
            if self._value_anim is not None:
                self._value_anim.stop()
            start = self._last_numeric if self._last_numeric is not None else 0
            anim = QVariantAnimation(self)
            anim.setStartValue(start)
            anim.setEndValue(target)
            anim.setDuration(420)
            anim.setEasingCurve(QEasingCurve.Type.OutCubic)
            anim.valueChanged.connect(
                lambda v, label=self.value: label.setText(f"{int(v):,}")
            )
            anim.finished.connect(lambda: self.value.setText(f"{target:,}"))
            anim.start()
            self._value_anim = anim
            self._last_numeric = target
        if self.property("tone") != tone:
            self.setProperty("tone", tone)
            self.style().unpolish(self)
            self.style().polish(self)

    def refresh_theme(self) -> None:
        self.icon.setPixmap(
            svg_icon(self._icon_name, theme_mod.current().ink2, 14).pixmap(14, 14)
        )

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.clicked.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class QuickTile(QFrame):
    clicked = Signal()

    def __init__(self, icon_name: str, title: str, hint: str, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("QuickTile")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumHeight(54)
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._icon_name = icon_name
        lay = QHBoxLayout(self)
        lay.setContentsMargins(11, 8, 11, 8)
        lay.setSpacing(9)
        self.icon = QLabel()
        self.icon.setFixedSize(18, 18)
        self.icon.setPixmap(svg_icon(icon_name, theme_mod.current().ink2, 16).pixmap(16, 16))
        lay.addWidget(self.icon, 0, Qt.AlignmentFlag.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(1)
        self.title = QLabel(title)
        self.title.setFont(ui_font(11, QFont.Weight.DemiBold))
        self.hint = QLabel(hint)
        self.hint.setObjectName("QuickHint")
        self.hint.setFont(ui_font(10))
        col.addWidget(self.title)
        col.addWidget(self.hint)
        lay.addLayout(col, 1)
        self.arrow = QLabel("↗")
        self.arrow.setObjectName("QuickArrow")
        lay.addWidget(self.arrow, 0, Qt.AlignmentFlag.AlignTop)
        for child in (self.icon, self.title, self.hint, self.arrow):
            child.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.clicked.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    def refresh_theme(self) -> None:
        self.icon.setPixmap(
            svg_icon(self._icon_name, theme_mod.current().ink2, 16).pixmap(16, 16)
        )


class HealthPanel(QFrame):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("HealthPanel")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 11, 14, 11)
        lay.setSpacing(7)
        head = QHBoxLayout()
        self.title = QLabel("执行健康")
        self.title.setFont(ui_font(12, QFont.Weight.Bold))
        head.addWidget(self.title)
        self.badge = QLabel("LOCAL CHECK")
        self.badge.setObjectName("MiniBadge")
        self.badge.setFont(mono_font(8))
        head.addStretch(1)
        head.addWidget(self.badge)
        lay.addLayout(head)
        self.rail = QWidget()
        self.rail.setFixedHeight(8)
        self.rail_lay = QHBoxLayout(self.rail)
        self.rail_lay.setContentsMargins(0, 0, 0, 0)
        self.rail_lay.setSpacing(3)
        self.segments: list[QFrame] = []
        for _ in range(4):
            seg = QFrame()
            seg.setObjectName("HealthSegment")
            seg.setFixedHeight(8)
            self.rail_lay.addWidget(seg, 1)
            self.segments.append(seg)
        lay.addWidget(self.rail)
        self.detail = QLabel("")
        self.detail.setObjectName("Muted")
        self.detail.setWordWrap(True)
        self.detail.setFont(ui_font(9))
        lay.addWidget(self.detail)
        self.footer = QLabel("")
        self.footer.setObjectName("MonoMuted")
        self.footer.setFont(mono_font(8))
        lay.addWidget(self.footer)

    def set_data(self, project: Project, validation: Any, code: str) -> None:
        available = validation is not None
        blocks = int(getattr(validation, "blocks", 0) or 0) if available else 1
        warnings = int(getattr(validation, "warnings", 0) or 0) if available else 0
        issues = len(getattr(validation, "issues", []) or []) if available else 0
        tasks = len(project.tasks)
        batches = sum(len(t.batches) for t in project.tasks)
        sends = sum(len(b.sends) for t in project.tasks for b in t.batches)
        stages = [("触发", tasks > 0), ("取", any(b.take.source for t in project.tasks for b in t.batches)),
                  ("送", sends > 0), ("清空", any(b.clear for t in project.tasks for b in t.batches))]
        for seg, (_, ok) in zip(self.segments, stages):
            seg.setProperty("ok", bool(ok))
            seg.style().unpolish(seg)
            seg.style().polish(seg)
        if not available:
            status, color = "校验不可用", "bad"
        elif blocks:
            status, color = "阻断 / 需修复", "bad"
        elif warnings:
            status, color = "可运行 / 有提示", "warn"
        elif tasks:
            status, color = "本地验证通过", "ok"
        else:
            status, color = "尚未生成", "idle"
        self.badge.setText(status)
        if self.badge.property("tone") != color:
            self.badge.setProperty("tone", color)
            self.badge.style().unpolish(self.badge)
            self.badge.style().polish(self.badge)
        self.detail.setText(
            f"{tasks} 条规则 · {batches} 个批次 · {sends} 个送目标 · "
            f"{issues if available else '—'} 条校验信息"
        )
        self.footer.setText(
            f"{len(code.splitlines()):,} 行 · {len(code):,} 字符 · "
            f"阶段 {'/'.join('✓' if ok else '—' for _, ok in stages)}"
        )


class ActivityFeed(QFrame):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("ActivityFeed")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(0)
        head = QHBoxLayout()
        title = QLabel("最近活动")
        title.setFont(ui_font(12, QFont.Weight.Bold))
        head.addWidget(title)
        head.addStretch(1)
        self.count = QLabel("0")
        self.count.setObjectName("MiniBadge")
        self.count.setFont(mono_font(10))
        self.count.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.count.setFixedHeight(18)
        self.count.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        head.addWidget(self.count)
        lay.addLayout(head)
        self.rows = QVBoxLayout()
        self.rows.setSpacing(0)
        lay.addLayout(self.rows)
        self.empty = QLabel("还没有操作。新建规则、校验或保存后会记录在这里。")
        self.empty.setObjectName("Muted")
        self.empty.setWordWrap(True)
        self.empty.setFont(ui_font(10))
        lay.addWidget(self.empty)
        lay.addStretch(1)

    def set_activity(self, items: list[tuple[str, str, str]]) -> None:
        while self.rows.count():
            item = self.rows.takeAt(0)
            if item.widget():
                w = item.widget()
                w.hide()
                w.setParent(None)
                w.deleteLater()
        self.count.setText(f"{min(len(items), 5):02d}")
        self.empty.setVisible(not items)
        for i, (title, detail, kind) in enumerate(items[:5], 1):
            row = QFrame()
            row.setObjectName("ActivityRow")
            row.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            row.setFixedHeight(38)
            rl = QHBoxLayout(row)
            rl.setContentsMargins(0, 4, 0, 4)
            rl.setSpacing(8)
            n = QLabel(f"{i:02d}")
            n.setObjectName("ActivityNum")
            n.setFont(mono_font(10))
            n.setAlignment(Qt.AlignmentFlag.AlignCenter)
            n.setFixedWidth(20)
            rl.addWidget(n, 0, Qt.AlignmentFlag.AlignVCenter)
            col = QVBoxLayout()
            col.setSpacing(0)
            t = QLabel(title)
            t.setFont(ui_font(10, QFont.Weight.DemiBold))
            d = QLabel(detail)
            d.setObjectName("Muted")
            d.setFont(ui_font(10))
            d.setWordWrap(False)
            d.setToolTip(detail)
            col.addWidget(t)
            if detail:
                col.addWidget(d)
            rl.addLayout(col, 1)
            k = QLabel(kind.upper())
            k.setObjectName("ActivityKind")
            k.setFont(mono_font(9))
            rl.addWidget(k, 0, Qt.AlignmentFlag.AlignVCenter)
            self.rows.addWidget(row)
            if i < len(items[:5]):
                line = QFrame()
                line.setObjectName("HLine")
                line.setFixedHeight(1)
                self.rows.addWidget(line)


class EnvironmentCard(QFrame):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("EnvironmentCard")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(5)
        title = QLabel("目标环境")
        title.setFont(ui_font(12, QFont.Weight.Bold))
        lay.addWidget(title)
        self.profile = QLabel("")
        self.profile.setObjectName("MonoMuted")
        self.profile.setFont(mono_font(9))
        self.profile.setWordWrap(True)
        lay.addWidget(self.profile)
        self.path = QLabel("")
        self.path.setObjectName("Muted")
        self.path.setFont(ui_font(8))
        self.path.setWordWrap(True)
        lay.addWidget(self.path)
        self.note = QLabel("离线 · 无遥测 · 不写游戏目录")
        self.note.setObjectName("MonoMuted")
        self.note.setFont(mono_font(8))
        lay.addWidget(self.note)


class OverviewPage(QWidget):
    newRuleRequested = Signal()
    templateRequested = Signal()
    checkRequested = Signal()
    copyRequested = Signal()
    graphRequested = Signal()
    resourceRequested = Signal()
    labelsRequested = Signal()
    commandRequested = Signal()
    issueRequested = Signal()
    saveRequested = Signal()
    rulesRequested = Signal()
    codeRequested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        scroll.setObjectName("OverviewScroll")
        body = QWidget()
        body.setObjectName("OverviewBody")
        body.setMaximumWidth(1180)
        self._body = body
        self._scroll = scroll
        lay = QVBoxLayout(body)
        lay.setContentsMargins(18, 10, 18, 16)
        lay.setSpacing(10)
        self._body_lay = lay
        self.hero = HeroPanel()
        hl = QHBoxLayout(self.hero)
        hl.setContentsMargins(20, 12, 20, 10)
        hl.setSpacing(12)
        left = QVBoxLayout()
        left.setSpacing(5)
        eyebrow = QLabel("// FIELD CONSOLE · MC / SFM")
        eyebrow.setObjectName("Eyebrow")
        eyebrow.setFont(mono_font(8))
        left.addWidget(eyebrow)
        self.hero_title = QLabel("工作台")
        self.hero_title.setObjectName("HeroTitle")
        self.hero_title.setFont(ui_font(28, QFont.Weight.Bold))
        left.addWidget(self.hero_title)
        self.hero_sub = QLabel("")
        self.hero_sub.setObjectName("HeroSub")
        self.hero_sub.setFont(ui_font(10))
        left.addWidget(self.hero_sub)
        self.hero_meta = QLabel("")
        self.hero_meta.setObjectName("MonoMuted")
        self.hero_meta.setFont(mono_font(8))
        left.addWidget(self.hero_meta)
        hl.addLayout(left, 1)
        actions = QVBoxLayout()
        actions.setSpacing(5)
        self.hero_status = QLabel("LOCAL / NO TELEMETRY")
        self.hero_status.setObjectName("HeroStatus")
        self.hero_status.setFont(mono_font(8))
        self.hero_status.setAlignment(Qt.AlignmentFlag.AlignRight)
        actions.addWidget(self.hero_status)
        btns = QHBoxLayout()
        btns.setSpacing(6)
        btns.addStretch(1)
        self.command_btn = CutButton("命令面板", "ghost", True)
        self.command_btn.setIcon(svg_icon("keyboard", theme_mod.current().ink, 14))
        self.command_btn.clicked.connect(self.commandRequested)
        btns.addWidget(self.command_btn)
        self.open_rule = CutButton("新建规则", "primary", True)
        self.open_rule.setIcon(svg_icon("plus", theme_mod.current().on_signal, 14))
        self.open_rule.clicked.connect(self.newRuleRequested)
        btns.addWidget(self.open_rule)
        actions.addLayout(btns)
        actions.addStretch(1)
        hl.addLayout(actions)
        lay.addWidget(self.hero)

        kpis = QGridLayout()
        kpis.setHorizontalSpacing(8)
        kpis.setVerticalSpacing(8)
        self.card_rules = StatCard("workflow", "规则 / 批次")
        self.card_issues = StatCard("shield-check", "校验", accent=True)
        self.card_tps = StatCard("gauge", "TPS 估算")
        self.card_code = StatCard("code", "代码体量")
        self.card_rules.clicked.connect(self.rulesRequested)
        self.card_issues.clicked.connect(self.issueRequested)
        self.card_tps.clicked.connect(self.graphRequested)
        self.card_code.clicked.connect(self.codeRequested)
        self._kpi_cards = (self.card_rules, self.card_issues, self.card_tps, self.card_code)
        self._kpi_grid = kpis
        for i, c in enumerate(self._kpi_cards):
            kpis.addWidget(c, 0, i)
            kpis.setColumnStretch(i, 1)
        lay.addLayout(kpis)

        mid = QHBoxLayout()
        mid.setSpacing(10)
        self.health = HealthPanel()
        mid.addWidget(self.health, 5)
        self.env = EnvironmentCard()
        mid.addWidget(self.env, 3)
        lay.addLayout(mid)

        lower = QHBoxLayout()
        lower.setSpacing(10)
        quick_wrap = QFrame()
        quick_wrap.setObjectName("OverviewPanel")
        ql = QVBoxLayout(quick_wrap)
        ql.setContentsMargins(12, 8, 12, 8)
        ql.setSpacing(6)
        qhead = QHBoxLayout()
        qt = QLabel("快捷入口")
        qt.setFont(ui_font(12, QFont.Weight.Bold))
        qhead.addWidget(qt)
        qhead.addStretch(1)
        qhint = QLabel("Ctrl K")
        qhint.setObjectName("MonoMuted")
        qhint.setFont(mono_font(7))
        qhead.addWidget(qhint)
        ql.addLayout(qhead)
        grid = QGridLayout()
        grid.setHorizontalSpacing(7)
        grid.setVerticalSpacing(7)
        tiles = [
            ("layout-template", "模板库", "从 9 个已验证模板开始", self.templateRequested),
            ("package", "资源库", "搜索物品 / 方块 ID", self.resourceRequested),
            ("tag", "标签库", "管理取送标签", self.labelsRequested),
            ("list-checks", "本地校验", "L0 / L1 规则检查", self.checkRequested),
            ("workflow", "执行图", "查看触发与送顺序", self.graphRequested),
            ("copy", "复制代码", "当前工程 SFML", self.copyRequested),
        ]
        self._quick_tiles = []
        for i, (icon, title, hint, sig) in enumerate(tiles):
            tile = QuickTile(icon, title, hint)
            tile.clicked.connect(sig)
            grid.addWidget(tile, i // 3, i % 3)
            grid.setColumnStretch(i % 3, 1)
            self._quick_tiles.append(tile)
        ql.addLayout(grid)
        self._quick_grid = grid
        self._quick_wrap = quick_wrap
        lower.addWidget(quick_wrap, 5)
        self.activity = ActivityFeed()
        lower.addWidget(self.activity, 4)
        lay.addLayout(lower)
        lay.addStretch(1)
        scroll.setWidget(body)
        root.addWidget(scroll, 1)

        self._last_title = ""
        self._last_path = ""
        self._last_profile = ""
        self._last_code_len = 0
        self._compact: bool | None = None
        self._entrance_done = False
        self.set_compact(False)

    def play_entrance(self) -> None:
        """One quiet stagger for the overview cards, never on every refresh."""
        if self._entrance_done:
            return
        self._entrance_done = True
        from . import motion

        targets = list(self._kpi_cards) + list(self._quick_tiles[:3])
        for i, widget in enumerate(targets):
            effect = QGraphicsOpacityEffect(widget)
            widget.setGraphicsEffect(effect)
            effect.setOpacity(0.0)
            timer = motion.animate_delay(
                widget,
                25 * i,
                lambda w=widget, e=effect: motion.animate(
                    e,
                    b"opacity",
                    0.0,
                    1.0,
                    150,
                    lambda value, eff=e: eff.setOpacity(value),
                    key="overviewEntrance",
                    on_finished=lambda w=w: w.setGraphicsEffect(None),
                ),
            )
            # The timer is parented to the widget; it dies with a page rebuild.
            _ = timer

    def set_compact(self, compact: bool) -> None:
        compact = bool(compact)
        if self._compact == compact:
            return
        self._compact = compact
        if hasattr(self, "hero_sub"):
            self.hero_sub.setVisible(not compact)
        if hasattr(self, "health"):
            self.health.footer.setVisible(not compact)
        if hasattr(self, "hero"):
            self.hero.setMinimumHeight(150 if compact else 160)
        if hasattr(self, "_body_lay"):
            self._body_lay.setSpacing(6 if compact else 10)
        for card in self._kpi_cards:
            self._kpi_grid.removeWidget(card)
        for tile in self._quick_tiles:
            self._quick_grid.removeWidget(tile)
        for i in range(4):
            self._kpi_grid.setColumnStretch(i, 0)
        for i in range(3):
            self._quick_grid.setColumnStretch(i, 0)
        if compact:
            self._kpi_grid.setColumnStretch(0, 1)
            self._kpi_grid.setColumnStretch(1, 1)
            self._quick_grid.setColumnStretch(0, 1)
            self._quick_grid.setColumnStretch(1, 1)
            for i, card in enumerate(self._kpi_cards):
                self._kpi_grid.addWidget(card, i // 2, i % 2)
            for i, tile in enumerate(self._quick_tiles):
                self._quick_grid.addWidget(tile, i // 2, i % 2)
        else:
            for i in range(4):
                self._kpi_grid.setColumnStretch(i, 1)
            for i in range(3):
                self._quick_grid.setColumnStretch(i, 1)
            for i, card in enumerate(self._kpi_cards):
                self._kpi_grid.addWidget(card, 0, i)
            for i, tile in enumerate(self._quick_tiles):
                self._quick_grid.addWidget(tile, i // 3, i % 3)
        self.updateGeometry()

    def refresh_theme(self) -> None:
        t = theme_mod.current()
        for card in getattr(self, "_kpi_cards", ()):
            card.refresh_theme()
        for tile in getattr(self, "_quick_tiles", ()):
            tile.refresh_theme()
        self.command_btn.setIcon(svg_icon("keyboard", t.ink, 14))
        self.open_rule.setIcon(svg_icon("plus", t.on_signal, 14))

    def set_state(
        self,
        project: Project,
        validation: Any,
        estimate: Any,
        code: str,
        activity: list[tuple[str, str, str]],
        project_path: str = "",
        profile_label: str = "",
        dirty: bool = False,
    ) -> None:
        self._last_title = project.name or "未命名工程"
        self._last_path = project_path
        self._last_profile = profile_label
        self.hero_title.setText(self._last_title)
        self.hero_sub.setText("把规则编译成可导入的 SFM 代码 · 本地优先")
        state = "UNSAVED DRAFT" if dirty else ("SAVED" if project_path else "NEW SESSION")
        self.hero_status.setText(f"{state}  ·  {profile_label or 'SFM 4.34.0'}")
        self.hero_meta.setText(
            f"{datetime.now().strftime('%Y-%m-%d')}  //  "
            f"{len(project.tasks)} 规则  //  {sum(len(t.batches) for t in project.tasks)} 批次"
        )
        self.hero_status.setProperty("dirty", bool(dirty))
        self.hero_status.style().unpolish(self.hero_status)
        self.hero_status.style().polish(self.hero_status)

        tasks = len(project.tasks)
        batches = sum(len(t.batches) for t in project.tasks)
        disabled = sum(1 for t in project.tasks if not t.enabled)
        self.card_rules.set_data(_fmt_int(tasks), f"{batches} 批次 · {disabled} 停用", "ink")
        blocks = int(getattr(validation, "blocks", 0) or 0)
        warnings = int(getattr(validation, "warnings", 0) or 0)
        if validation is None:
            self.card_issues.set_data("—", "校验器不可用", "bad")
        elif not project.tasks:
            self.card_issues.set_data("—", "尚无规则可校验", "idle")
        elif blocks:
            self.card_issues.set_data(str(blocks), f"{warnings} 提示 · 阻断导出", "bad")
        elif warnings:
            self.card_issues.set_data("0", f"{warnings} 提示 · 可复制", "warn")
        else:
            self.card_issues.set_data("0", "无阻断 · 可复制", "ok")
        score = getattr(estimate, "score", None)
        level = getattr(estimate, "level", "")
        self.card_tps.set_data(
            f"{float(score):.0f}" if isinstance(score, (int, float)) else "—",
            f"{level} · 静态估算" if level else "静态估算，不是实测",
            "ink",
        )
        self.card_code.set_data(
            f"{len(code):,}",
            f"{len(code.splitlines())} 行 · {len(code):,} 字符",
            "ink",
        )
        self.health.set_data(project, validation, code)
        profile_display = profile_label or "MC 1.21.1 / NeoForge / SFM 4.34.0"
        pieces = [p.strip() for p in profile_display.split(" / ") if p.strip()]
        if len(pieces) >= 3:
            profile_display = f"{pieces[0]}\n{' / '.join(pieces[1:])}"
        self.env.profile.setText(profile_display)
        self.env.path.setText(project_path or "尚未保存到 .sfmproj")
        self.env.path.setToolTip(project_path or "")
        self.activity.set_activity(activity)


class OverviewPlaceholder(QLabel):
    pass
