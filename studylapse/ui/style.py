"""Colours and the Qt stylesheet."""

BG = "#0e1014"
SURFACE = "#161920"
SURFACE_2 = "#1d212a"
SURFACE_3 = "#262b36"
BORDER = "#2a2f3b"
TEXT = "#e9ebf1"
MUTED = "#8a92a6"
DIM = "#5d6477"
ACCENT = "#ff4d5e"      # record red
ACCENT_2 = "#6c8cff"    # selection / toggles
OK = "#3ecf8e"
WARN = "#f5b84a"

QSS = f"""
* {{
    color: {TEXT};
    outline: none;
}}
QMainWindow, QDialog, #Root {{
    background: {BG};
}}
QToolTip {{
    background: {SURFACE_3};
    color: {TEXT};
    border: 1px solid {BORDER};
    padding: 6px 8px;
    border-radius: 6px;
}}
QLabel#Title {{
    font-size: 15px;
    font-weight: 600;
    letter-spacing: 0.3px;
}}
QLabel#Muted, QLabel#Hint {{
    color: {MUTED};
}}
QLabel#Hint {{
    font-size: 11px;
}}
QLabel#Section {{
    color: {MUTED};
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 1.2px;
    padding-top: 10px;
}}
QLabel#StatValue {{
    font-size: 20px;
    font-weight: 600;
}}
QLabel#StatLabel {{
    color: {DIM};
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 1.2px;
}}
QFrame#Card {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 14px;
}}
QFrame#Divider {{
    background: {BORDER};
    max-height: 1px;
    min-height: 1px;
}}

/* --- buttons --------------------------------------------------------- */
QPushButton {{
    background: {SURFACE_2};
    border: 1px solid {BORDER};
    border-radius: 10px;
    padding: 8px 14px;
    font-weight: 500;
}}
QPushButton:hover {{ background: {SURFACE_3}; }}
QPushButton:pressed {{ background: {BORDER}; }}
QPushButton:disabled {{ color: {DIM}; background: {SURFACE}; }}

QPushButton#Primary {{
    background: {ACCENT_2};
    border: none;
    color: white;
    font-weight: 600;
}}
QPushButton#Primary:hover {{ background: #7f9bff; }}
QPushButton#Primary:disabled {{ background: {SURFACE_3}; color: {DIM}; }}

QPushButton#Chip {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 12px;
    padding: 10px 12px;
    color: {MUTED};
    text-align: center;
}}
QPushButton#Chip:hover {{ background: {SURFACE_2}; }}
QPushButton#Chip:checked {{
    background: rgba(108, 140, 255, 0.14);
    border: 1px solid rgba(108, 140, 255, 0.55);
    color: {TEXT};
}}
QPushButton#Chip:disabled {{ color: {DIM}; }}

QToolButton {{
    background: transparent;
    border: none;
    border-radius: 10px;
    padding: 6px;
}}
QToolButton:hover {{ background: {SURFACE_2}; }}
QToolButton:pressed {{ background: {SURFACE_3}; }}
QToolButton:disabled {{ background: transparent; }}

QToolButton#Round {{
    background: {SURFACE_2};
    border: 1px solid {BORDER};
    border-radius: 22px;
}}
QToolButton#Round:hover {{ background: {SURFACE_3}; }}

QPushButton#Seg {{
    background: transparent;
    border: none;
    border-radius: 7px;
    padding: 4px 10px;
    color: {MUTED};
    font-size: 11px;
    font-weight: 600;
}}
QPushButton#Seg:checked {{
    background: rgba(255,255,255,0.14);
    color: white;
}}
QFrame#SegBox {{
    background: rgba(10, 12, 16, 0.72);
    border-radius: 9px;
}}

/* --- inputs ---------------------------------------------------------- */
QComboBox, QLineEdit, QSpinBox {{
    background: {SURFACE_2};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 6px 10px;
    min-height: 20px;
    selection-background-color: {ACCENT_2};
}}
QComboBox:hover, QLineEdit:hover {{ border-color: #3a4152; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox::down-arrow {{
    image: url(@ARROW@);
    width: 12px;
    height: 12px;
    margin-right: 8px;
}}
QComboBox QAbstractItemView {{
    background: {SURFACE_2};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 4px;
    selection-background-color: {SURFACE_3};
}}

QSlider::groove:horizontal {{
    height: 4px;
    background: {SURFACE_3};
    border-radius: 2px;
}}
QSlider::sub-page:horizontal {{
    background: {ACCENT_2};
    border-radius: 2px;
}}
QSlider::handle:horizontal {{
    background: white;
    width: 16px;
    height: 16px;
    margin: -6px 0;
    border-radius: 8px;
}}
QSlider::handle:horizontal:hover {{ background: #dfe5ff; }}
QSlider::handle:horizontal:disabled {{ background: {DIM}; }}
QSlider::sub-page:horizontal:disabled {{ background: {SURFACE_3}; }}

QCheckBox {{ spacing: 10px; }}
QProgressBar {{
    background: {SURFACE_3};
    border: none;
    border-radius: 4px;
    height: 8px;
    text-align: center;
    color: transparent;
}}
QProgressBar::chunk {{
    background: {ACCENT_2};
    border-radius: 4px;
}}

QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{
    background: transparent; width: 8px; margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: {SURFACE_3}; border-radius: 4px; min-height: 30px;
}}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QMenu {{
    background: {SURFACE_2};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 4px;
}}
QMenu::item {{ padding: 6px 18px; border-radius: 6px; }}
QMenu::item:selected {{ background: {SURFACE_3}; }}
QMenu::separator {{ height: 1px; background: {BORDER}; margin: 4px 6px; }}
"""


_ARROW_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 12 12">'
    '<path d="M3 4.5l3 3 3-3" fill="none" stroke="#8a92a6" stroke-width="1.6" '
    'stroke-linecap="round" stroke-linejoin="round"/></svg>'
)


def build_qss() -> str:
    """Stylesheet with small image assets written to a temp folder (QSS needs file URLs)."""
    import tempfile
    from pathlib import Path

    d = Path(tempfile.gettempdir()) / "studylapse-assets"
    arrow = d / "chevron.svg"
    try:
        d.mkdir(exist_ok=True)
        if not arrow.exists() or arrow.read_text() != _ARROW_SVG:
            arrow.write_text(_ARROW_SVG)
    except OSError:
        return QSS.replace("image: url(@ARROW@);", "image: none;")
    return QSS.replace("@ARROW@", arrow.as_posix())
