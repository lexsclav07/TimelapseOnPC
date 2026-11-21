"""Settings panel. Changes apply live and are saved on close."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSlider,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..camera import RESOLUTIONS, list_cameras
from ..config import Settings
from ..platform_utils import IS_WINDOWS, is_wayland
from ..screen import backend_name, list_monitors
from . import style
from .icons import icon
from .widgets import Switch


def _section(text: str) -> QLabel:
    lab = QLabel(text.upper())
    lab.setObjectName("Section")
    return lab


def _hint(text: str) -> QLabel:
    lab = QLabel(text)
    lab.setObjectName("Hint")
    lab.setWordWrap(True)
    return lab


class SettingsDialog(QDialog):
    lockRequested = Signal()
    unlockRequested = Signal()
    driverSettingsRequested = Signal()
    exposureCompChanged = Signal(float)
    changed = Signal()

    def __init__(self, settings: Settings, recording: bool, lock_summary: str, parent=None):
        super().__init__(parent)
        self.s = settings
        self.recording = recording
        self.setWindowTitle("Settings")
        self.setModal(True)
        self.resize(440, 640)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        outer.addWidget(scroll)
        body = QWidget()
        scroll.setWidget(body)
        lay = QVBoxLayout(body)
        lay.setContentsMargins(22, 14, 22, 18)
        lay.setSpacing(10)

        def row(label: str, widget: QWidget) -> QWidget:
            w = QWidget()
            h = QHBoxLayout(w)
            h.setContentsMargins(0, 0, 0, 0)
            lab = QLabel(label)
            lab.setMinimumWidth(120)
            h.addWidget(lab)
            h.addWidget(widget, 1)
            return w

        locked_while_recording = "Stop recording to change this."

        # ---------------------------------------------------------- webcam
        lay.addWidget(_section("Webcam"))
        self.cam_combo = QComboBox()
        for idx, name in list_cameras():
            self.cam_combo.addItem(name, idx)
        i = self.cam_combo.findData(settings.camera_index)
        if i < 0:
            self.cam_combo.addItem(f"Camera {settings.camera_index + 1}", settings.camera_index)
            i = self.cam_combo.count() - 1
        self.cam_combo.setCurrentIndex(i)
        self.cam_combo.currentIndexChanged.connect(self._cam_changed)
        lay.addWidget(row("Device", self.cam_combo))

        self.res_combo = QComboBox()
        for k in RESOLUTIONS:
            self.res_combo.addItem(k, k)
        self.res_combo.setCurrentIndex(max(0, self.res_combo.findData(settings.camera_resolution)))
        self.res_combo.currentIndexChanged.connect(self._res_changed)
        lay.addWidget(row("Resolution", self.res_combo))
        for w in (self.cam_combo, self.res_combo):
            w.setEnabled(not recording)
            if recording:
                w.setToolTip(locked_while_recording)

        self.lock_switch = Switch("Lock focus, exposure & white balance")
        self.lock_switch.setChecked(settings.lock_camera)
        self.lock_switch.toggled.connect(self._lock_toggled)
        lay.addWidget(self.lock_switch)
        lay.addWidget(
            _hint(
                "When recording starts, the webcam auto-adjusts for a couple of seconds, then "
                "every setting is frozen so frames don't flicker or hunt for focus."
            )
        )

        lock_row = QHBoxLayout()
        self.lock_status = QLabel(lock_summary or "Not locked yet")
        self.lock_status.setObjectName("Muted")
        self.lock_btn = QPushButton(" Lock now")
        self.lock_btn.setIcon(icon("lock"))
        self.lock_btn.setIconSize(QSize(15, 15))
        self.lock_btn.setToolTip("Re-calibrate now (e.g. after the lighting changed)")
        self.lock_btn.clicked.connect(self._lock_now)
        lock_row.addWidget(self.lock_status, 1)
        lock_row.addWidget(self.lock_btn)
        lay.addLayout(lock_row)

        self.comp_slider = QSlider(Qt.Horizontal)
        self.comp_slider.setRange(-6, 6)  # thirds of a stop
        self.comp_slider.setPageStep(1)
        self.comp_slider.setValue(round(settings.exposure_comp * 3))
        self.comp_val = QLabel()
        self.comp_val.setMinimumWidth(48)
        self.comp_val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.comp_slider.valueChanged.connect(self._comp_changed)
        comp_w = QWidget()
        ch = QHBoxLayout(comp_w)
        ch.setContentsMargins(0, 0, 0, 0)
        ch.addWidget(self.comp_slider, 1)
        ch.addWidget(self.comp_val)
        lay.addWidget(row("Brightness", comp_w))
        self._update_comp_label()

        self.keep_combo = QComboBox()
        for key, label in (("auto", "Automatic"), ("always", "Always on"), ("never", "Off between shots")):
            self.keep_combo.addItem(label, key)
        self.keep_combo.setCurrentIndex(max(0, self.keep_combo.findData(settings.keep_camera_open)))
        self.keep_combo.currentIndexChanged.connect(
            lambda: self._set("keep_camera_open", self.keep_combo.currentData())
        )
        lay.addWidget(row("Between shots", self.keep_combo))
        lay.addWidget(
            _hint(
                "Automatic keeps the webcam streaming only for short intervals and releases it "
                "between shots otherwise - lowest CPU use, and the camera light stays off."
            )
        )

        if IS_WINDOWS:
            drv = QPushButton("Camera driver settings…")
            drv.setToolTip(
                "Opens the webcam driver's own settings window.\n"
                "Turn off the lock above if you want to keep settings you make here."
            )
            drv.clicked.connect(self.driverSettingsRequested)
            drv.setEnabled(not recording)
            lay.addWidget(drv)

        # ---------------------------------------------------------- screen
        lay.addWidget(_section("Screen"))
        self.mon_combo = QComboBox()
        for idx, label in list_monitors():
            self.mon_combo.addItem(label, idx)
        self.mon_combo.setCurrentIndex(max(0, self.mon_combo.findData(settings.monitor)))
        self.mon_combo.currentIndexChanged.connect(lambda: self._set("monitor", self.mon_combo.currentData()))
        self.mon_combo.setEnabled(not recording and self.mon_combo.count() > 1)
        lay.addWidget(row("Capture", self.mon_combo))

        self.scale_combo = QComboBox()
        for h, label in ((0, "Native"), (2160, "Up to 4K"), (1440, "Up to 1440p"), (1080, "Up to 1080p"), (720, "Up to 720p")):
            self.scale_combo.addItem(label, h)
        self.scale_combo.setCurrentIndex(max(0, self.scale_combo.findData(settings.screen_max_height)))
        self.scale_combo.currentIndexChanged.connect(
            lambda: self._set("screen_max_height", self.scale_combo.currentData())
        )
        self.scale_combo.setEnabled(not recording)
        lay.addWidget(row("Resolution", self.scale_combo))

        self.cursor_switch = Switch("Include mouse cursor")
        self.cursor_switch.setChecked(settings.capture_cursor)
        self.cursor_switch.toggled.connect(lambda v: self._set("capture_cursor", v))
        self.cursor_switch.setEnabled(not recording)
        lay.addWidget(self.cursor_switch)
        method = backend_name()
        hint = f"Capture method: {method}."
        if is_wayland():
            hint += (
                " On Wayland the desktop captures all monitors through its screenshot service; "
                "the first shot may ask for permission."
            )
        lay.addWidget(_hint(hint))

        # ---------------------------------------------------------- output
        lay.addWidget(_section("Output"))
        folder_w = QWidget()
        fh = QHBoxLayout(folder_w)
        fh.setContentsMargins(0, 0, 0, 0)
        self.folder_edit = QLineEdit(settings.output_dir)
        self.folder_edit.editingFinished.connect(lambda: self._set("output_dir", self.folder_edit.text().strip()))
        browse = QToolButton()
        browse.setIcon(icon("folder"))
        browse.setIconSize(QSize(18, 18))
        browse.setToolTip("Choose folder")
        browse.clicked.connect(self._browse)
        fh.addWidget(self.folder_edit, 1)
        fh.addWidget(browse)
        folder_w.setEnabled(not recording)
        lay.addWidget(row("Save to", folder_w))

        self.q_slider = QSlider(Qt.Horizontal)
        self.q_slider.setRange(60, 100)
        self.q_slider.setValue(settings.jpeg_quality)
        self.q_val = QLabel(f"{settings.jpeg_quality}")
        self.q_val.setMinimumWidth(48)
        self.q_val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.q_slider.valueChanged.connect(self._q_changed)
        qw = QWidget()
        qh = QHBoxLayout(qw)
        qh.setContentsMargins(0, 0, 0, 0)
        qh.addWidget(self.q_slider, 1)
        qh.addWidget(self.q_val)
        qw.setEnabled(not recording)
        lay.addWidget(row("JPEG quality", qw))

        # ---------------------------------------------------------- app
        lay.addWidget(_section("App"))
        self.tray_switch = Switch("Hide to system tray while recording")
        self.tray_switch.setChecked(settings.minimize_to_tray)
        self.tray_switch.toggled.connect(lambda v: self._set("minimize_to_tray", v))
        lay.addWidget(self.tray_switch)
        lay.addStretch(1)

        # footer
        foot = QFrame()
        foot.setStyleSheet(f"QFrame{{background:{style.BG};border-top:1px solid {style.BORDER};}}")
        fl = QHBoxLayout(foot)
        fl.setContentsMargins(22, 12, 22, 12)
        fl.addStretch(1)
        done = QPushButton("Done")
        done.setObjectName("Primary")
        done.setDefault(True)
        done.clicked.connect(self.accept)
        fl.addWidget(done)
        outer.addWidget(foot)

    # ------------------------------------------------------------------
    def _set(self, key, value):
        setattr(self.s, key, value)
        self.changed.emit()

    def _cam_changed(self):
        self._set("camera_index", self.cam_combo.currentData())
        self.set_lock_summary("Not locked yet")

    def _res_changed(self):
        self._set("camera_resolution", self.res_combo.currentData())
        self.set_lock_summary("Not locked yet")

    def _lock_toggled(self, on: bool):
        self._set("lock_camera", on)
        if on and self.recording and self.lock_btn.isEnabled():
            self._lock_now()
        if not on:
            self.unlockRequested.emit()
            self.set_lock_summary("Auto (not locked)")

    def _lock_now(self):
        self.lock_switch.setChecked(True)
        self.set_lock_summary("Calibrating… hold still")
        self.lock_btn.setEnabled(False)
        self.lockRequested.emit()

    def set_lock_summary(self, text: str):
        self.lock_status.setText(text)
        if not text.startswith("Calibrating"):
            self.lock_btn.setEnabled(True)

    def _update_comp_label(self):
        v = self.comp_slider.value() / 3
        self.comp_val.setText("0 EV" if v == 0 else f"{v:+.1f} EV")

    def _comp_changed(self):
        self._update_comp_label()
        v = round(self.comp_slider.value() / 3, 2)
        self._set("exposure_comp", v)
        self.exposureCompChanged.emit(v)

    def _q_changed(self, v: int):
        self.q_val.setText(str(v))
        self._set("jpeg_quality", v)

    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, "Save timelapses to", self.folder_edit.text())
        if d:
            self.folder_edit.setText(d)
            self._set("output_dir", d)
