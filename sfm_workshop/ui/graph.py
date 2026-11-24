"""Structured execution graph for the workbench.

Not a free data-flow editor: edges are derived from the structured program.
Sends can be dragged to change their order; other edits happen in the task
inspector. This keeps invalid graphs hard to construct.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import QPointF, QPropertyAnimation, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGraphicsItem,
    QGraphicsObject,
    QGraphicsPathItem,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..core.model import Task
from . import motion
from . import theme as theme_mod
from .theme import mono_font, ui_font
from .widgets import CutButton, cut_path


NODE_W = 144
NODE_H = 86
GAP = 28
X0 = 24
Y0 = 72


@dataclass
class NodeSpec:
    key: str
    kind: str
    eyebrow: str
    title: str
    field: str
    index: int = 0


class NodeItem(QGraphicsObject):
    moved = Signal()
    double_clicked = Signal(str)

    def __init__(self, spec: NodeSpec, parent=None) -> None:
        super().__init__(parent)
        self.spec = spec
        self.original_pos = QPointF(0, 0)
        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsMovable
            | QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
            | QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges
        )
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setAcceptHoverEvents(True)
        self._hover = False

    def boundingRect(self) -> QRectF:  # noqa: N802
        return QRectF(0, 0, NODE_W, NODE_H)

    def shape(self) -> QPainterPath:
        return cut_path(QRectF(0, 0, NODE_W, NODE_H).toRect(), 8)

    def paint(self, painter: QPainter, option, widget=None) -> None:
        t = theme_mod.current()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        selected = self.isSelected()
        path = cut_path(QRectF(0, 0, NODE_W, NODE_H).toRect(), 8)
        painter.fillPath(path, QColor(t.panel))
        # top signal line, clipped to the cut card
        painter.save()
        painter.setClipPath(path)
        painter.fillRect(QRectF(0, 0, NODE_W, 3), QColor(t.trace))
        painter.restore()
        border = QColor(t.signal if selected else (t.ink2 if self._hover else t.rule))
        painter.setPen(QPen(border, 2 if selected else 1))
        painter.drawPath(path)
        painter.setPen(QColor(t.ink2))
        painter.setFont(ui_font(11, QFont.Weight.DemiBold))
        painter.drawText(QRectF(8, 7, NODE_W - 16, 14), Qt.AlignmentFlag.AlignLeft, self.spec.eyebrow)
        painter.setPen(QColor(t.ink))
        painter.setFont(ui_font(16, QFont.Weight.Bold))
        painter.drawText(QRectF(8, 22, NODE_W - 16, 22), Qt.AlignmentFlag.AlignLeft, self.spec.title)
        painter.setPen(QColor(t.ink2))
        painter.setFont(ui_font(12))
        fm = QFontMetrics(painter.font())
        field = fm.elidedText(self.spec.field, Qt.TextElideMode.ElideRight, NODE_W - 16)
        painter.drawText(QRectF(8, 46, NODE_W - 16, 17), Qt.AlignmentFlag.AlignLeft, field)
        if selected:
            painter.setPen(QPen(QColor(t.signal if t.dark else t.ink), 1))
            painter.drawPath(cut_path(QRectF(4, 4, NODE_W - 8, NODE_H - 8).toRect(), 5))

    def hoverEnterEvent(self, event) -> None:  # noqa: N802
        self._hover = True
        self.update()
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event) -> None:  # noqa: N802
        self._hover = False
        self.update()
        super().hoverLeaveEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        # Do not rebuild the scene while this QGraphicsItem is still handling
        # the mouse event. The editor/render refresh is scheduled after the
        # item event returns.
        QTimer.singleShot(0, self, self._emit_double_click)
        super().mouseDoubleClickEvent(event)

    def _emit_double_click(self) -> None:
        self.double_clicked.emit(self.spec.key)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        super().mouseReleaseEvent(event)
        self.moved.emit()

    def itemChange(self, change, value):  # noqa: N802
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            self.moved.emit()
        return super().itemChange(change, value)


class EdgeItem(QGraphicsPathItem):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setZValue(-1)
        self.arrow = QPainterPath()

    def set_edge(self, a: QPointF, b: QPointF) -> None:
        mid = (a.x() + b.x()) / 2
        p = QPainterPath(a)
        p.cubicTo(QPointF(mid, a.y()), QPointF(mid, b.y()), b)
        self.setPath(p)
        # arrowhead pointing right
        ah = 4
        self.arrow = QPainterPath(QPointF(b.x(), b.y()))
        self.arrow.lineTo(b.x() - ah, b.y() - ah)
        self.arrow.lineTo(b.x() - ah, b.y() + ah)
        self.arrow.closeSubpath()
        self.update()

    def paint(self, painter: QPainter, option, widget=None) -> None:
        t = theme_mod.current()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(QPen(QColor(t.trace if t.dark else t.ink), 1))
        painter.drawPath(self.path())
        painter.fillPath(self.arrow, QColor(t.trace if t.dark else t.ink))


class GraphView(QGraphicsView):
    editRequested = Signal(str)
    sendOrderChanged = Signal(list, int)
    zoomChanged = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.NoAnchor)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.NoAnchor)
        self.scene_ = QGraphicsScene(self)
        self.setScene(self.scene_)
        self.task: Task | None = None
        self.batch_index = 0
        self.nodes: list[NodeItem] = []
        self.edges: list[EdgeItem] = []
        self._send_nodes: list[NodeItem] = []
        self._building = False
        self._last_task_id = ""
        self._last_batch = -1
        self._scroll_x = 0
        self._empty = True
        self.setMinimumHeight(280)

    def set_task(self, task: Task | None, batch_index: int = 0) -> None:
        same = bool(task and task.id == self._last_task_id and batch_index == self._last_batch)
        animate_nodes = not same and not motion.reduced()
        saved_scroll = self.horizontalScrollBar().value() if same else 0
        self.task = task
        self._last_task_id = task.id if task else ""
        self._last_batch = batch_index
        self._empty = task is None or not task.batches
        self.batch_index = max(0, batch_index)
        self._building = True
        self.scene_.clear()
        self.nodes = []
        self.edges = []
        self._send_nodes = []
        if task is None or not task.batches:
            self.setSceneRect(QRectF(0, 0, 720, max(360, self.viewport().height() - 20)))
            self._building = False
            return
        self.batch_index = min(self.batch_index, len(task.batches) - 1)
        b = task.batches[self.batch_index]
        specs: list[NodeSpec] = []
        if task.trigger_kind == "pulse":
            specs.append(NodeSpec("trigger", "trigger", "TASK / 01", "红石脉冲", "REDSTONE PULSE"))
        else:
            unit = "秒" if task.unit == "SECONDS" else "tick"
            specs.append(NodeSpec("trigger", "trigger", "TASK / 01", "定时", f"每 {task.interval} {unit}"))
        if b.condition.strip():
            specs.append(NodeSpec("condition", "condition", "IF / 条件", "条件", b.condition.strip()))
        specs.append(
            NodeSpec(
                "batch",
                "batch",
                "BATCH / 02",
                "批次",
                f"{self.batch_index + 1} / {len(task.batches)}",
            )
        )
        specs.append(NodeSpec("take", "take", "TAKE / 03", "取", f"{b.take.source or '未选来源'} / {b.take.side}"))
        for i, send in enumerate(b.sends):
            specs.append(NodeSpec(f"send:{i}", "send", f"SEND / {4 + i:02d}", "送", f"{send.target or '未选目标'} / {send.side}", i))
        if b.clear:
            specs.append(NodeSpec("clear", "clear", "CLEAR / 05", "清空", "自动 forget"))
        width = max(720, X0 + len(specs) * (NODE_W + GAP) + 24)
        scene_h = max(360, self.viewport().height() - 20)
        self.setSceneRect(QRectF(0, 0, width, scene_h))
        top = max(Y0, (scene_h - NODE_H) // 2)
        for i, spec in enumerate(specs):
            n = NodeItem(spec)
            n.setPos(X0 + i * (NODE_W + GAP), top)
            n.original_pos = QPointF(n.pos())
            n.moved.connect(self._on_node_moved)
            n.double_clicked.connect(
                lambda _key, task_id=task.id: self.editRequested.emit(task_id)
            )
            if animate_nodes:
                n.setOpacity(0.0)
            self.scene_.addItem(n)
            if animate_nodes:
                QTimer.singleShot(
                    35 * i,
                    n,
                    lambda item=n: self._reveal_node(item),
                )
            else:
                n.setOpacity(1.0)
            self.nodes.append(n)
            if spec.kind == "send":
                self._send_nodes.append(n)
        for _ in range(len(self.nodes) - 1):
            e = EdgeItem()
            self.scene_.addItem(e)
            self.edges.append(e)
        self._update_edges()
        self._building = False
        self.horizontalScrollBar().setValue(saved_scroll)
        self.zoomChanged.emit()

    def _on_node_moved(self) -> None:
        if self._building:
            return
        self._update_edges()

    def _reveal_node(self, node: NodeItem) -> None:
        motion.animate(
            node,
            b"opacity",
            0.0,
            1.0,
            170,
            node.setOpacity,
            key="node-entrance",
            easing=motion.SNAP,
        )

    def _update_edges(self) -> None:
        for i, edge in enumerate(self.edges):
            if i + 1 >= len(self.nodes):
                continue
            a = self.nodes[i].pos() + QPointF(NODE_W, NODE_H / 2)
            b = self.nodes[i + 1].pos() + QPointF(0, NODE_H / 2)
            edge.set_edge(a, b)
        if self.nodes:
            self.scene_.update()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        super().mouseReleaseEvent(event)
        if not self.task or not self.task.batches:
            return
        selected = [n for n in self._send_nodes if n.isSelected()]
        if not selected:
            return
        # If a send was dragged, derive the new order from x positions.
        old = list(self._send_nodes)
        ordered = sorted(old, key=lambda n: n.pos().x())
        new_order = [n.spec.index for n in ordered]
        if new_order != list(range(len(old))):
            self.sendOrderChanged.emit(new_order, self.batch_index)
        # Snap non-send nodes back; sends will be rebuilt after reorder.
        for n in self.nodes:
            if n.spec.kind != "send":
                n.setPos(n.original_pos)
        self._update_edges()

    def wheelEvent(self, event) -> None:  # noqa: N802
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            factor = 1.12 if event.angleDelta().y() > 0 else 1 / 1.12
            current = self.transform().m11()
            if 0.6 <= current * factor <= 1.8:
                self.scale(factor, factor)
            self.zoomChanged.emit()
            event.accept()
            return
        super().wheelEvent(event)

    def drawBackground(self, painter: QPainter, rect: QRectF) -> None:  # noqa: N802
        t = theme_mod.current()
        painter.fillRect(rect, QColor(t.paper))
        painter.setPen(QPen(QColor(t.grid), 1, Qt.PenStyle.DotLine))
        left = int(rect.left()) - (int(rect.left()) % 22)
        top = int(rect.top()) - (int(rect.top()) % 22)
        x = left
        while x < rect.right():
            painter.drawLine(int(x), int(rect.top()), int(x), int(rect.bottom()))
            x += 22
        y = top
        while y < rect.bottom():
            painter.drawLine(int(rect.left()), int(y), int(rect.right()), int(y))
            y += 22

    def drawForeground(self, painter: QPainter, rect: QRectF) -> None:  # noqa: N802
        super().drawForeground(painter, rect)
        if not self._empty:
            return
        t = theme_mod.current()
        center = self.sceneRect().center()
        painter.setPen(QColor(t.ink2))
        painter.setFont(ui_font(15, QFont.Weight.Bold))
        painter.drawText(
            QRectF(center.x() - 280, center.y() - 24, 560, 26),
            Qt.AlignmentFlag.AlignCenter,
            "还没有执行图",
        )
        painter.setFont(ui_font(11))
        painter.setPen(QColor(t.ink2))
        painter.drawText(
            QRectF(center.x() - 280, center.y() + 8, 560, 22),
            Qt.AlignmentFlag.AlignCenter,
            "先新建规则，或从左侧选择一条规则查看 触发 → 取 → 送 → 清空",
        )


class GraphPanel(QWidget):
    editRequested = Signal(str)
    addSendRequested = Signal()
    addConditionRequested = Signal()
    willChange = Signal()
    changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.task: Task | None = None
        self._batch_index = 0
        self._fit_mode = True
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        head = QWidget()
        head_lay = QHBoxLayout(head)
        head_lay.setContentsMargins(16, 8, 16, 6)
        head_lay.setSpacing(8)
        e = QLabel("// EXECUTION")
        e.setObjectName("Eyebrow")
        self.title = QLabel("执行主干")
        self.title.setFont(ui_font(17, QFont.Weight.Bold))
        self.task_name = QLabel("")
        self.task_name.setObjectName("Signal")
        self.task_name.setFont(ui_font(9, QFont.Weight.Bold))
        head_lay.addWidget(e)
        head_lay.addWidget(self.title)
        head_lay.addWidget(self.task_name)
        self.batch_combo = QComboBox()
        self.batch_combo.setObjectName("GraphBatch")
        self.batch_combo.setMinimumWidth(120)
        self.batch_combo.currentIndexChanged.connect(self._choose_batch)
        head_lay.addWidget(self.batch_combo)
        head_lay.addStretch(1)
        self.edit_btn = CutButton("编辑任务", "ghost", True)
        self.edit_btn.clicked.connect(self._edit)
        head_lay.addWidget(self.edit_btn)
        self.add_send_btn = CutButton("＋送", "ghost", True)
        self.add_send_btn.clicked.connect(self.addSendRequested)
        head_lay.addWidget(self.add_send_btn)
        self.add_cond_btn = CutButton("＋条件", "ghost", True)
        self.add_cond_btn.clicked.connect(self.addConditionRequested)
        head_lay.addWidget(self.add_cond_btn)
        root.addWidget(head)

        self.graph = GraphView()
        self.graph.editRequested.connect(self.editRequested)
        self.graph.zoomChanged.connect(self._sync_zoom)
        self.graph.sendOrderChanged.connect(self._reorder_sends)
        root.addWidget(self.graph, 1)

        foot = QWidget()
        fl = QHBoxLayout(foot)
        fl.setContentsMargins(16, 4, 16, 6)
        fl.setSpacing(10)
        hint = QLabel("拖动送节点调整顺序；双击节点编辑")
        hint.setObjectName("Muted")
        hint.setFont(ui_font(9))
        self.meta = QLabel("")
        self.meta.setObjectName("Muted")
        self.meta.setFont(ui_font(9))
        self.zoom_label = QLabel("100%")
        self.zoom_label.setObjectName("MonoMuted")
        self.zoom_label.setFont(mono_font(10))
        self.zoom_out = CutButton("−", "ghost", True)
        self.zoom_out.setFixedWidth(28)
        self.zoom_out.clicked.connect(lambda: self._zoom(1 / 1.15))
        self.zoom_in = CutButton("+", "ghost", True)
        self.zoom_in.setFixedWidth(28)
        self.zoom_in.clicked.connect(lambda: self._zoom(1.15))
        self.zoom_fit = CutButton("适应", "ghost", True)
        self.zoom_fit.clicked.connect(self._fit)
        fl.addWidget(hint)
        fl.addStretch(1)
        fl.addWidget(self.zoom_out)
        fl.addWidget(self.zoom_label)
        fl.addWidget(self.zoom_in)
        fl.addWidget(self.zoom_fit)
        fl.addWidget(self.meta)
        root.addWidget(foot)

    def _zoom(self, factor: float) -> None:
        current = self.graph.transform().m11()
        if 0.6 <= current * factor <= 1.8:
            self.graph.scale(factor, factor)
            self._fit_mode = False
        self._sync_zoom()

    def _fit(self) -> None:
        rect = self.graph.sceneRect()
        if not rect.isEmpty():
            self.graph.fitInView(rect, Qt.AspectRatioMode.KeepAspectRatio)
            if self.graph.transform().m11() > 1.15:
                ratio = 1.15 / self.graph.transform().m11()
                self.graph.scale(ratio, ratio)
            self._fit_mode = True
        self._sync_zoom()

    def _sync_zoom(self) -> None:
        self.zoom_label.setText(f"{round(self.graph.transform().m11() * 100)}%")

    def set_task(self, task: Task | None, batch_index: int | None = None) -> None:
        self.task = task
        self.task_name.setText(task.name if task else "")
        self._batch_index = max(0, batch_index or 0)
        self.batch_combo.blockSignals(True)
        self.batch_combo.clear()
        if task:
            for i in range(len(task.batches)):
                self.batch_combo.addItem(f"批次 {i + 1} / {len(task.batches)}")
            self._batch_index = min(self._batch_index, max(0, len(task.batches) - 1))
        self.batch_combo.setCurrentIndex(self._batch_index)
        self.batch_combo.blockSignals(False)
        has_task = task is not None and bool(task.batches)
        self.task_name.setVisible(has_task)
        self.batch_combo.setVisible(has_task)
        for btn in (self.edit_btn, self.add_send_btn, self.add_cond_btn):
            btn.setEnabled(has_task)
        self.graph.set_task(task, self._batch_index)
        self._refresh_meta()
        self._sync_zoom()
        if self._fit_mode:
            QTimer.singleShot(0, self, self._fit)

    def current_batch_index(self) -> int:
        return max(0, self.batch_combo.currentIndex())

    def _choose_batch(self, index: int) -> None:
        if not self.task or not self.task.batches:
            return
        self._batch_index = max(0, min(index, len(self.task.batches) - 1))
        self.graph.set_task(self.task, self._batch_index)
        self._refresh_meta()

    def _refresh_meta(self) -> None:
        if self.task and self.task.batches:
            index = max(0, min(self.batch_combo.currentIndex(), len(self.task.batches) - 1))
            b = self.task.batches[index]
            self.meta.setText(
                f"批次 {index + 1}/{len(self.task.batches)} │ {len(b.sends)} 个送 │ "
                f"{'清空' if b.clear else '不清空'}"
            )
            self.edit_btn.setEnabled(True)
            self.add_send_btn.setEnabled(True)
            self.add_cond_btn.setEnabled(True)
            self.add_cond_btn.setText("编辑条件" if b.condition else "＋条件")
        else:
            self.meta.setText("无任务")
            self.edit_btn.setEnabled(False)
            self.add_send_btn.setEnabled(False)
            self.add_cond_btn.setEnabled(False)

    def _edit(self) -> None:
        if self.task:
            self.editRequested.emit(self.task.id)

    def _reorder_sends(self, order: list[int], batch_index: int) -> None:
        if not self.task or not self.task.batches:
            return
        if batch_index < 0 or batch_index >= len(self.task.batches):
            return
        b = self.task.batches[batch_index]
        if sorted(order) != list(range(len(b.sends))):
            return
        self.willChange.emit()
        b.sends = [b.sends[i] for i in order]
        self.graph.set_task(self.task, batch_index)
        self._refresh_meta()
        self.changed.emit()
