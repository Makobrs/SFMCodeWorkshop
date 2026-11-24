"""Small, mechanical motion helpers for the workbench.

The endfield direction asks for short, hard state changes. Qt has no CSS
transitions, so effects are painted from an animated float property. Every
animation is parented to the widget it drives; this makes rebuilds safe (the
widget and its animation die together) and keeps callers from leaking
animation objects.
"""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QEasingCurve, QPointF, QPropertyAnimation, QTimer

SNAP = ((0.16, 1.0), (0.30, 1.0))
MECH = ((0.70, 0.0), (0.20, 1.0))
EASE = ((0.20, 0.7), (0.10, 1.0))

_reduced = False


def set_reduced(value: bool) -> None:
    global _reduced
    _reduced = bool(value)


def reduced() -> bool:
    return _reduced


def curve(kind: tuple[tuple[float, float], tuple[float, float]] = SNAP) -> QEasingCurve:
    (x1, y1), (x2, y2) = kind
    c = QEasingCurve(QEasingCurve.Type.BezierSpline)
    c.addCubicBezierSegment(QPointF(x1, y1), QPointF(x2, y2), QPointF(1.0, 1.0))
    return c


def animate(
    target,
    prop: bytes,
    start: float,
    end: float,
    ms: int,
    setter: Callable[[float], None],
    *,
    key: str,
    easing: tuple[tuple[float, float], tuple[float, float]] = SNAP,
    on_finished: Callable[[], None] | None = None,
) -> QPropertyAnimation | None:
    """Animate a Qt property, or jump to the final value when reduced.

    *setter* is the Python side of the property; it must only call
    ``update()`` (never change geometry or text). *key* is unique per
    widget/property and is used to reuse an in-flight animation.
    """
    old = target.findChild(QPropertyAnimation, key)
    if old is not None:
        old.stop()
    if _reduced or ms <= 0:
        setter(float(end))
        if on_finished is not None:
            on_finished()
        return None
    anim = old
    if anim is None:
        anim = QPropertyAnimation(target, prop, target)
        anim.setObjectName(key)
        anim.valueChanged.connect(lambda value: setter(float(value)))
    anim.setStartValue(float(start))
    anim.setEndValue(float(end))
    anim.setDuration(int(ms))
    anim.setEasingCurve(curve(easing))
    previous = getattr(anim, "_finished_slot", None)
    if previous is not None:
        try:
            anim.finished.disconnect(previous)
        except (RuntimeError, TypeError):
            pass
    anim._finished_slot = on_finished
    if on_finished is not None:
        anim.finished.connect(on_finished)
    anim.start()
    return anim


def animate_delay(target, ms: int, callback: Callable[[], None]) -> QTimer:
    """A one-shot timer parented to *target* so rebuilds cannot leave it live."""
    timer = QTimer(target)
    timer.setSingleShot(True)
    timer.timeout.connect(callback)
    timer.start(int(ms))
    return timer


def stop(target, key: str) -> None:
    old = target.findChild(QPropertyAnimation, key)
    if old is not None:
        old.stop()
