"""Block-face picker with SFM-correct world vs block-relative semantics."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..core.model import SIDE_GROUPS, SIDE_TO_SFML
from .icons import theme_icon
from .theme import ui_font


_SIDE_EN = {
    "上面": "top",
    "下面": "bottom",
    "前面": "front",
    "后面": "back",
    "左面": "left",
    "右面": "right",
    "东面": "east",
    "西面": "west",
    "南面": "south",
    "北面": "north",
    "顶面": "top",
    "底面": "bottom",
    "每个面": "each side",
    "默认面": "null",
}


class FacePickerDialog(QDialog):
    def __init__(self, current: str = "默认面", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.selected_side = current
        self.setWindowTitle("选择方块面 - SFM 4.34")
        self.resize(660, 620)
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 14, 18, 12)
        root.setSpacing(7)

        head = QHBoxLayout()
        icon = QLabel()
        icon.setPixmap(theme_icon("box", muted=False, size=22).pixmap(22, 22))
        head.addWidget(icon)
        title = QLabel("选择方块面")
        title.setFont(ui_font(19, QFont.Weight.Bold))
        head.addWidget(title)
        head.addStretch(1)
        root.addLayout(head)
        root.addWidget(
            QLabel(
                "SFM 4.34 的 side 分三类：上下、固定世界方向、相对方块 facing。\n"
                "前/后/左/右不是玩家视角；方块没有 facing 属性时，SFM 会把它当作 null side。"
            )
        )

        special = QHBoxLayout()
        for side, desc in (
            ("默认面", "不写 side，交给 SFM 默认/空方向"),
            ("每个面", "each side，遍历每个面（更贵）"),
        ):
            b = QPushButton(f"{side}\n{desc}")
            b.setObjectName("FaceOption")
            b.setMinimumHeight(54)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setToolTip(f"{desc}\nSFML: {SIDE_TO_SFML.get(side, '') or 'null'}")
            b.clicked.connect(lambda _=False, s=side: self._choose(s))
            special.addWidget(b)
        root.addLayout(special)

        for group_name, sides, desc in SIDE_GROUPS:
            section = QLabel(f"// {group_name}")
            section.setObjectName("Eyebrow")
            root.addWidget(section)
            hint = QLabel(desc)
            hint.setObjectName("Muted")
            hint.setWordWrap(True)
            hint.setFont(ui_font(9))
            root.addWidget(hint)
            grid = QGridLayout()
            grid.setSpacing(6)
            for i, side in enumerate(sides):
                token = _SIDE_EN.get(side, side)
                b = QPushButton(f"{side}\n{token}")
                b.setObjectName("FaceOption")
                b.setMinimumHeight(52)
                b.setCursor(Qt.CursorShape.PointingHandCursor)
                b.setToolTip(f"{side} → {SIDE_TO_SFML.get(side, '')}")
                if side == current:
                    b.setProperty("current", True)
                b.clicked.connect(lambda _=False, s=side: self._choose(s))
                grid.addWidget(b, i // 2, i % 2)
            root.addLayout(grid)

        root.addStretch(1)
        foot = QHBoxLayout()
        foot.addWidget(
            QLabel("建议：机器/熔炉优先用世界方向；有 facing 的机器可用前后左右。")
        )
        foot.addStretch(1)
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        foot.addWidget(cancel)
        root.addLayout(foot)

    def _choose(self, side: str) -> None:
        self.selected_side = side
        self.accept()
