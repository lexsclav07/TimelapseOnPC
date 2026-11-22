"""Custom-painted widgets."""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QAbstractButton,
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QWidget,
)

from . import style
from .icons import icon


def ndarray_to_qimage(img: np.ndarray) -> QImage:
    img = np.ascontiguousarray(img)
    h, w = img.shape[:2]
    q = QImage(img.data, w, h, img.strides[0], QImage.Format_BGR888)
    return q.copy()  # detach from numpy buffer


class Switch(QAbstractButton):
    """iOS-style toggle with a text label on the left."""

    def __init__(self, text: str = "", parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setText(text)
        self.setCursor(Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def sizeHint(self) -> QSize:
        fm = self.fontMetrics()
        return QSize(fm.horizontalAdvance(self.text()) + 60, max(26, fm.height() + 8))

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        tw, th = 36, 20
        x = self.width() - tw
        y = (self.height() - th) / 2
        on = self.isChecked()
        track = QColor(style.ACCENT_2 if on else style.SURFACE_3)
        if not self.isEnabled():
            track.setAlpha(90)
        p.setPen(Qt.NoPen)
        p.setBrush(track)
        p.drawRoundedRect(QRectF(x, y, tw, th), th / 2, th / 2)
        p.setBrush(QColor("white") if self.isEnabled() else QColor(style.DIM))
        kx = x + tw - th + 3 if on else x + 3
        p.drawEllipse(QRectF(kx, y + 3, th - 6, th - 6))
        p.setPen(QColor(style.TEXT if self.isEnabled() else style.DIM))
        p.drawText(QRectF(0, 0, x - 10, self.height()), Qt.AlignVCenter | Qt.AlignLeft, self.text())


class RecordButton(QAbstractButton):
    """The big centre button: red dot = start/resume, pause bars = pause."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.mode = "idle"  # idle | recording | paused | busy
        self.setFixedSize(78, 78)
        self.setCursor(Qt.PointingHandCursor)
        self._hover = False

    def set_mode(self, mode: str):
        self.mode = mode
        tips = {
            "idle": "Start recording",
            "recording": "Pause",
            "paused": "Resume",
            "busy": "Calibrating webcam…",
        }
        self.setToolTip(tips.get(mode, ""))
        self.update()

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(3, 3, -3, -3)
        ring = QColor(style.ACCENT if self.mode in ("recording", "busy") else "#3a4050")
        p.setPen(QPen(ring, 3))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(r)

        inner = r.adjusted(8, 8, -8, -8)
        red = QColor(style.ACCENT)
        if self._hover and self.isEnabled():
            red = red.lighter(112)
        if not self.isEnabled():
            red = QColor(style.SURFACE_3)
        p.setPen(Qt.NoPen)
        if self.mode == "recording":
            p.setBrush(QColor(style.SURFACE_2).lighter(130 if self._hover else 100))
            p.drawEllipse(inner)
            p.setBrush(QColor("white"))
            c = inner.center()
            bw, bh = 7, 22
            p.drawRoundedRect(QRectF(c.x() - bw - 3, c.y() - bh / 2, bw, bh), 2, 2)
            p.drawRoundedRect(QRectF(c.x() + 3, c.y() - bh / 2, bw, bh), 2, 2)
        elif self.mode == "busy":
            p.setBrush(QColor(style.SURFACE_2))
            p.drawEllipse(inner)
            p.setBrush(QColor(style.WARN))
            p.drawEllipse(inner.center(), 6, 6)
        else:
            p.setBrush(red)
            p.drawEllipse(inner)


class StatusPill(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.state = "idle"
        self._blink = True
        self._timer = QTimer(self, interval=700, timeout=self._tick)
        self.setFixedHeight(26)
        self.set_state("idle")

    def _tick(self):
        self._blink = not self._blink
        self.update()

    def set_state(self, state: str):
        self.state = state
        self._blink = True
        labels = {"idle": "Ready", "calibrating": "Calibrating", "recording": "Recording", "paused": "Paused"}
        self.text = labels.get(state, state.title())
        f = QFont(self.font())
        f.setPointSizeF(f.pointSizeF() * 0.85)
        f.setWeight(QFont.DemiBold)
        self._font = f
        from PySide6.QtGui import QFontMetrics

        self.setFixedWidth(QFontMetrics(f).horizontalAdvance(self.text) + 36)
        if state in ("recording", "calibrating") and self.isVisible():
            self._timer.start()
        else:
            self._timer.stop()
        self.update()

    def set_animating(self, on: bool):
        if on and self.state in ("recording", "calibrating"):
            self._timer.start()
        else:
            self._timer.stop()
            self._blink = True
            self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        colors = {"idle": style.DIM, "calibrating": style.WARN, "recording": style.ACCENT, "paused": style.WARN}
        c = QColor(colors.get(self.state, style.DIM))
        bg = QColor(c)
        bg.setAlpha(34 if self.state != "idle" else 0)
        p.setPen(QPen(QColor(c.red(), c.green(), c.blue(), 90), 1))
        p.setBrush(bg)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        dot = QColor(c)
        if not self._blink:
            dot.setAlpha(60)
        p.setPen(Qt.NoPen)
        p.setBrush(dot)
        p.drawEllipse(QPointF(14, r.center().y()), 4, 4)
        p.setPen(QColor(style.TEXT if self.state != "idle" else style.MUTED))
        p.setFont(self._font)
        p.drawText(QRectF(24, 0, self.width() - 26, self.height()), Qt.AlignVCenter, self.text)


class Segmented(QFrame):
    changed = Signal(str)

    def __init__(self, options: list[tuple[str, str]], parent=None):
        super().__init__(parent)
        self.setObjectName("SegBox")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(3, 3, 3, 3)
        lay.setSpacing(2)
        self.group = QButtonGroup(self)
        self.buttons: dict[str, QPushButton] = {}
        for key, label in options:
            b = QPushButton(label)
            b.setObjectName("Seg")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            self.group.addButton(b)
            lay.addWidget(b)
            self.buttons[key] = b
            b.clicked.connect(lambda _=False, k=key: self.changed.emit(k))
        self.group.setExclusive(True)

    def set_value(self, key: str):
        if key in self.buttons:
            self.buttons[key].setChecked(True)

    def value(self) -> str:
        for k, b in self.buttons.items():
            if b.isChecked():
                return k
        return ""


class Preview(QWidget):
    """Rounded 16:9 preview surface with overlay controls."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pix: QPixmap | None = None
        self.placeholder = "Press record to start.\nYour latest frame shows up here."
        sp = QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        sp.setHeightForWidth(True)
        self.setSizePolicy(sp)
        self.setMinimumHeight(170)

        self.seg = Segmented([("webcam", "Webcam"), ("screen", "Screen")], self)
        self.live_btn = QToolButton(self)
        self.live_btn.setIcon(icon("eye"))
        self.live_btn.setIconSize(QSize(18, 18))
        self.live_btn.setCheckable(True)
        self.live_btn.setToolTip("Live webcam view - for framing your shot\n(only runs while not recording)")
        self.live_btn.setCursor(Qt.PointingHandCursor)
        self.live_btn.setStyleSheet(
            "QToolButton{background:rgba(10,12,16,0.72);border-radius:9px;padding:5px;}"
            "QToolButton:checked{background:rgba(108,140,255,0.85);}"
        )
        self.badge = QLabel(self)
        self.badge.setStyleSheet(
            "QLabel{background:rgba(10,12,16,0.72);border-radius:9px;padding:4px 9px;"
            "font-size:11px;font-weight:600;color:#cfd5e4;}"
        )
        self.badge.hide()

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, w: int) -> int:
        return int(w * 9 / 16)

    def sizeHint(self) -> QSize:
        return QSize(400, 225)

    def set_image(self, img: np.ndarray | None):
        self._pix = QPixmap.fromImage(ndarray_to_qimage(img)) if img is not None else None
        self.update()

    def clear(self, text: str | None = None):
        self._pix = None
        if text is not None:
            self.placeholder = text
        self.update()

    def set_badge(self, text: str | None):
        if text:
            self.badge.setText(text)
            self.badge.adjustSize()
            self.badge.show()
        else:
            self.badge.hide()
        self._place()

    def resizeEvent(self, e):
        self._place()

    def _place(self):
        m = 10
        self.seg.adjustSize()
        self.seg.move(m, m)
        self.live_btn.adjustSize()
        self.live_btn.move(self.width() - self.live_btn.width() - m, m)
        self.badge.adjustSize()
        self.badge.move(m, self.height() - self.badge.height() - m)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(r, 14, 14)
        p.setClipPath(path)
        p.fillRect(r, QColor("#0a0c10"))
        if self._pix is not None and not self._pix.isNull():
            sz = self._pix.size().scaled(self.size(), Qt.KeepAspectRatio)
            x = (self.width() - sz.width()) / 2
            y = (self.height() - sz.height()) / 2
            p.drawPixmap(QRectF(x, y, sz.width(), sz.height()), self._pix, QRectF(self._pix.rect()))
        else:
            p.setPen(QColor(style.DIM))
            ic = icon("camera-check", style.DIM).pixmap(QSize(30, 30), self.devicePixelRatioF())
            p.drawPixmap(int(self.width() / 2 - 15), int(self.height() / 2 - 40), ic)
            p.drawText(
                QRectF(0, self.height() / 2 - 2, self.width(), 44), Qt.AlignHCenter | Qt.AlignTop, self.placeholder
            )
        p.setClipping(False)
        p.setPen(QPen(QColor(style.BORDER), 1))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(r, 14, 14)


class Stat(QWidget):
    def __init__(self, label: str, value: str = "–", parent=None):
        super().__init__(parent)
        from PySide6.QtWidgets import QVBoxLayout

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(1)
        self.value = QLabel(value)
        self.value.setObjectName("StatValue")
        self.value.setAlignment(Qt.AlignCenter)
        self.label = QLabel(label.upper())
        self.label.setObjectName("StatLabel")
        self.label.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.value)
        lay.addWidget(self.label)

    def set(self, text: str):
        self.value.setText(text)


class Toast(QFrame):
    """Small in-window notification with an optional action."""

    action = Signal()

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setStyleSheet(
            f"QFrame{{background:{style.SURFACE_3};border:1px solid {style.BORDER};border-radius:12px;}}"
            "QLabel{background:transparent;border:none;}"
            f"QPushButton{{background:transparent;border:none;color:{style.ACCENT_2};font-weight:600;padding:4px 6px;}}"
            "QPushButton:hover{color:#9db2ff;}"
        )
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 8, 8, 8)
        lay.setSpacing(8)
        self.label = QLabel()
        self.label.setWordWrap(True)
        self.btn = QPushButton()
        self.btn.setCursor(Qt.PointingHandCursor)
        self.btn.clicked.connect(self._act)
        close = QToolButton()
        close.setIcon(icon("close", style.MUTED))
        close.setIconSize(QSize(14, 14))
        close.clicked.connect(self.hide)
        lay.addWidget(self.label, 1)
        lay.addWidget(self.btn)
        lay.addWidget(close)
        self._timer = QTimer(self, singleShot=True, timeout=self.hide)
        self._cb = None
        self.hide()

    def _act(self):
        self.hide()
        cb, self._cb = self._cb, None
        if cb is not None:
            cb()
        else:
            self.action.emit()

    def set_text(self, text: str):
        self.label.setText(text)

    def show_message(self, text: str, action: str | None = None, ms: int = 6000, callback=None):
        self._cb = callback
        self.label.setText(text)
        self.btn.setVisible(bool(action))
        self.btn.setText(action or "")
        self.reposition()
        self.show()
        self.raise_()
        self._timer.start(ms)

    def reposition(self):
        par = self.parentWidget()
        if not par:
            return
        w = par.width() - 32
        self.setFixedWidth(w)
        self.adjustSize()
        self.move(16, par.height() - self.height() - 16)
