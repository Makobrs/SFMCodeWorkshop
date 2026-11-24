"""Theme-coloured SVG icons for the workbench.

Line icons are from AI Canvas Icons (aicanvas.me); see
``sfm_workshop/resources/icons/README.md``.  The SVG files use
``currentColor``; this module substitutes the active theme colour and caches
the QIcon/pixmap. No network access is performed.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import QByteArray, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from ..core.storage import resource_root
from . import theme as theme_mod


# One family, one grid: AI Canvas/Lucide line icons at 24; Ingot-style
# small sizes (14/16) get a slightly heavier optical stroke for Windows 100%.
ICON_SMALL = 14
ICON_BODY = 16
ICON_LARGE = 20


def _dir() -> Path:
    return resource_root() / "icons"


@lru_cache(maxsize=128)
def icon(name: str, color: str, size: int = 16) -> QIcon:
    path = _dir() / f"{name}.svg"
    if not path.exists():
        return QIcon()
    try:
        svg = path.read_text(encoding="utf-8").replace("currentColor", color)
        if size <= ICON_SMALL:
            svg = svg.replace('stroke-width="1.5"', 'stroke-width="1.9"')
    except Exception:
        return QIcon()
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    dpr = float(app.devicePixelRatio()) if app is not None else 1.0
    dpr = max(1.0, dpr)
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    pix = QPixmap(QSize(int(size * dpr), int(size * dpr)))
    pix.fill(Qt.GlobalColor.transparent)
    pix.setDevicePixelRatio(dpr)
    painter = QPainter(pix)
    renderer.render(painter)
    painter.end()
    return QIcon(pix)


def theme_icon(name: str, muted: bool = False, size: int = 16) -> QIcon:
    t = theme_mod.current()
    return icon(name, t.ink2 if muted else t.ink, size)


def apply_search_icon(field, name: str = "search", muted: bool = True) -> None:
    """Add a leading icon to a QLineEdit, replacing a previous one."""
    from PySide6.QtWidgets import QLineEdit

    if not isinstance(field, QLineEdit):
        return
    # Remove previous leading actions; keep any trailing clear button intact.
    for action in list(field.actions()):
        if action.property("dshSearchIcon"):
            field.removeAction(action)
    q = theme_icon(name, muted=muted, size=14)
    act = field.addAction(q, QLineEdit.ActionPosition.LeadingPosition)
    act.setProperty("dshSearchIcon", True)
