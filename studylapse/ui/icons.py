"""Tiny inline SVG icon set (stroke icons, 24x24 grid), tinted on demand."""

from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

_STROKE = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
    'stroke="{c}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">{body}</svg>'
)
_FILL = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="{c}">{body}</svg>'

ICONS = {
    "webcam": (_STROKE, '<circle cx="12" cy="10" r="7"/><circle cx="12" cy="10" r="2.6"/><path d="M8 21h8M12 17v4"/>'),
    "screen": (_STROKE, '<rect x="3" y="4" width="18" height="12.5" rx="2"/><path d="M8.5 20.5h7M12 16.5v4"/>'),
    "settings": (
        _STROKE,
        '<path d="M4 6h9M19 6h1M4 12h3M13 12h7M4 18h11M21 18h-1"/>'
        '<circle cx="16" cy="6" r="2.4"/><circle cx="10" cy="12" r="2.4"/><circle cx="18" cy="18" r="2.4"/>',
    ),
    "folder": (_STROKE, '<path d="M3 7.5A2.5 2.5 0 0 1 5.5 5H9l2 2.2h7.5A2.5 2.5 0 0 1 21 9.7v7.8a2.5 2.5 0 0 1-2.5 2.5h-13A2.5 2.5 0 0 1 3 17.5z"/>'),
    "export": (_STROKE, '<rect x="3" y="5" width="18" height="14" rx="2.5"/><path d="M10 9.3v5.4l4.6-2.7z" fill="{c}"/>'),
    "lock": (_STROKE, '<rect x="5" y="11" width="14" height="9.5" rx="2"/><path d="M8.2 11V8a3.8 3.8 0 0 1 7.6 0v3"/>'),
    "unlock": (_STROKE, '<rect x="5" y="11" width="14" height="9.5" rx="2"/><path d="M8.2 11V8a3.8 3.8 0 0 1 7.3-1.5"/>'),
    "eye": (_STROKE, '<path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z"/><circle cx="12" cy="12" r="2.8"/>'),
    "eye-off": (_STROKE, '<path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z"/><circle cx="12" cy="12" r="2.8"/><path d="M4 4l16 16"/>'),
    "stop": (_FILL, '<rect x="6" y="6" width="12" height="12" rx="2.5"/>'),
    "pause": (_FILL, '<rect x="6.5" y="5" width="4" height="14" rx="1.3"/><rect x="13.5" y="5" width="4" height="14" rx="1.3"/>'),
    "play": (_FILL, '<path d="M8 5.5v13a1 1 0 0 0 1.5.86l10.2-6.5a1 1 0 0 0 0-1.72L9.5 4.64A1 1 0 0 0 8 5.5z"/>'),
    "close": (_STROKE, '<path d="M6 6l12 12M18 6L6 18"/>'),
    "camera-check": (_STROKE, '<path d="M4 8.5A2.5 2.5 0 0 1 6.5 6h1.8l1.4-2h4.6l1.4 2h1.8A2.5 2.5 0 0 1 20 8.5v8a2.5 2.5 0 0 1-2.5 2.5h-11A2.5 2.5 0 0 1 4 16.5z"/><circle cx="12" cy="12.3" r="3.3"/>'),
}

APP_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
<stop offset="0" stop-color="#2a3142"/><stop offset="1" stop-color="#11141b"/></linearGradient></defs>
<rect x="2" y="2" width="60" height="60" rx="15" fill="url(#g)"/>
<circle cx="32" cy="32" r="18" fill="none" stroke="#6c8cff" stroke-width="4"
 stroke-linecap="round" stroke-dasharray="85 200" transform="rotate(-90 32 32)"/>
<circle cx="32" cy="32" r="18" fill="none" stroke="#ffffff" stroke-opacity="0.12" stroke-width="4"/>
<circle cx="32" cy="32" r="8" fill="{dot}"/>
</svg>"""


def _render(svg: str, size: int) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    r = QSvgRenderer(QByteArray(svg.encode()))
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    r.render(p, QRectF(0, 0, size, size))
    p.end()
    return pm


@lru_cache(maxsize=128)
def icon(name: str, color: str = "#e9ebf1", disabled: str = "#5d6477") -> QIcon:
    tmpl, body = ICONS[name]
    ic = QIcon()
    for size in (16, 20, 24, 32, 48, 64):
        ic.addPixmap(_render(tmpl.format(c=color, body=body.replace("{c}", color)), size), QIcon.Normal)
        ic.addPixmap(_render(tmpl.format(c=disabled, body=body.replace("{c}", disabled)), size), QIcon.Disabled)
    return ic


@lru_cache(maxsize=4)
def app_icon(recording: bool = False) -> QIcon:
    ic = QIcon()
    svg = APP_SVG.format(dot="#ff4d5e" if recording else "#e9ebf1")
    for size in (16, 24, 32, 48, 64, 128, 256):
        ic.addPixmap(_render(svg, size))
    return ic
