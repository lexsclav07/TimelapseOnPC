"""The main window."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QAction, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSlider,
    QSystemTrayIcon,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..camera import LockState
from ..config import INTERVAL_STEPS, Settings, format_duration, format_interval
from ..platform_utils import IS_WINDOWS, is_wayland, open_folder
from ..recorder import PreviewThread, Recorder
from .export_dialog import ExportDialog
from .icons import app_icon, icon
from .settings_dialog import SettingsDialog
from .widgets import Preview, RecordButton, Stat, StatusPill, Toast


class MainWindow(QMainWindow):
    def __init__(self, settings: Settings):
        super().__init__()
        self.s = settings
        self.recorder: Recorder | None = None
        self.preview: PreviewThread | None = None
        self.lock_state: LockState | None = None
        self.settings_dlg: SettingsDialog | None = None
        self.thumbs = {"webcam": None, "screen": None}
        self.preview_source = "webcam" if settings.use_webcam else "screen"
        self._reset_auto = False
        self._quitting = False
        self._tray_hint_shown = False
        self._last_session: str | None = None

        self.setWindowTitle("StudyLapse")
        self.setWindowIcon(app_icon())
        self.setMinimumSize(380, 600)
        self.resize(420, 680)

        self._build()
        self._build_tray()
        self._sync_sources()
        self._interval_changed(self.interval_slider.value(), save=False)

        self.clock = QTimer(self, interval=1000, timeout=self._refresh_stats)

        QShortcut(QKeySequence("Space"), self, activated=self._record_clicked)
        QShortcut(QKeySequence("Ctrl+,"), self, activated=self._open_settings)
        QShortcut(QKeySequence("Ctrl+E"), self, activated=self._open_export)

    # ================================================================ build
    def _build(self):
        root = QWidget()
        root.setObjectName("Root")
        self.setCentralWidget(root)
        lay = QVBoxLayout(root)
        lay.setContentsMargins(18, 14, 18, 18)
        lay.setSpacing(14)

        # header
        head = QHBoxLayout()
        title = QLabel("StudyLapse")
        title.setObjectName("Title")
        self.pill = StatusPill()
        self.settings_btn = QToolButton()
        self.settings_btn.setIcon(icon("settings"))
        self.settings_btn.setIconSize(QSize(20, 20))
        self.settings_btn.setToolTip("Settings  (Ctrl+,)")
        self.settings_btn.setCursor(Qt.PointingHandCursor)
        self.settings_btn.clicked.connect(self._open_settings)
        head.addWidget(title)
        head.addStretch(1)
        head.addWidget(self.pill)
        head.addSpacing(4)
        head.addWidget(self.settings_btn)
        lay.addLayout(head)

        # preview
        self.preview_w = Preview()
        self.preview_w.seg.set_value(self.preview_source)
        self.preview_w.seg.changed.connect(self._preview_source_changed)
        self.preview_w.live_btn.toggled.connect(self._live_toggled)
        lay.addWidget(self.preview_w)

        # stats
        stats = QHBoxLayout()
        self.st_elapsed = Stat("Study time", "0:00:00")
        self.st_frames = Stat("Frames", "0")
        self.st_video = Stat("Video", "0.0 s")
        for w in (self.st_elapsed, self.st_frames, self.st_video):
            stats.addWidget(w, 1)
        lay.addLayout(stats)

        # transport
        tr = QHBoxLayout()
        tr.setSpacing(26)
        self.folder_btn = QToolButton()
        self.folder_btn.setObjectName("Round")
        self.folder_btn.setFixedSize(46, 46)
        self.folder_btn.setIcon(icon("folder"))
        self.folder_btn.setIconSize(QSize(19, 19))
        self.folder_btn.setToolTip("Open recordings folder")
        self.folder_btn.setCursor(Qt.PointingHandCursor)
        self.folder_btn.clicked.connect(self._open_folder)
        self.rec_btn = RecordButton()
        self.rec_btn.set_mode("idle")
        self.rec_btn.clicked.connect(self._record_clicked)
        self.stop_btn = QToolButton()
        self.stop_btn.setObjectName("Round")
        self.stop_btn.setFixedSize(46, 46)
        self.stop_btn.setIcon(icon("stop"))
        self.stop_btn.setIconSize(QSize(18, 18))
        self.stop_btn.setToolTip("Stop and save session")
        self.stop_btn.setCursor(Qt.PointingHandCursor)
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._stop)
        tr.addStretch(1)
        tr.addWidget(self.folder_btn, 0, Qt.AlignVCenter)
        tr.addWidget(self.rec_btn, 0, Qt.AlignVCenter)
        tr.addWidget(self.stop_btn, 0, Qt.AlignVCenter)
        tr.addStretch(1)
        lay.addLayout(tr)

        # settings card
        card = QFrame()
        card.setObjectName("Card")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(14, 14, 14, 12)
        cl.setSpacing(12)

        chips = QHBoxLayout()
        chips.setSpacing(10)
        self.cam_chip = QPushButton("  Webcam")
        self.scr_chip = QPushButton("  Screen")
        for chip, ic, val in ((self.cam_chip, "webcam", self.s.use_webcam), (self.scr_chip, "screen", self.s.use_screen)):
            chip.setObjectName("Chip")
            chip.setCheckable(True)
            chip.setChecked(val)
            chip.setIcon(icon(ic))
            chip.setIconSize(QSize(18, 18))
            chip.setCursor(Qt.PointingHandCursor)
            chip.toggled.connect(self._sources_changed)
            chips.addWidget(chip, 1)
        cl.addLayout(chips)

        irow = QHBoxLayout()
        ilab = QLabel("Every")
        ilab.setObjectName("Muted")
        self.interval_slider = QSlider(Qt.Horizontal)
        self.interval_slider.setRange(0, len(INTERVAL_STEPS) - 1)
        self.interval_slider.setPageStep(1)
        nearest = min(range(len(INTERVAL_STEPS)), key=lambda i: abs(INTERVAL_STEPS[i] - self.s.interval))
        self.interval_slider.setValue(nearest)
        self.interval_slider.valueChanged.connect(self._interval_changed)
        self.interval_val = QLabel()
        self.interval_val.setMinimumWidth(64)
        self.interval_val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.interval_val.setStyleSheet("font-weight:600;")
        irow.addWidget(ilab)
        irow.addWidget(self.interval_slider, 1)
        irow.addWidget(self.interval_val)
        cl.addLayout(irow)

        self.hint = QLabel()
        self.hint.setObjectName("Hint")
        cl.addWidget(self.hint)
        lay.addWidget(card)

        lay.addStretch(1)

        self.export_btn = QPushButton("  Export video")
        self.export_btn.setIcon(icon("export"))
        self.export_btn.setIconSize(QSize(18, 18))
        self.export_btn.setCursor(Qt.PointingHandCursor)
        self.export_btn.setMinimumHeight(42)
        self.export_btn.setToolTip("Turn a recorded session into an MP4  (Ctrl+E)")
        self.export_btn.clicked.connect(self._open_export)
        lay.addWidget(self.export_btn)

        # Space is the global start/pause key, so buttons must not grab keyboard focus.
        for w in (self.settings_btn, self.folder_btn, self.rec_btn, self.stop_btn,
                  self.cam_chip, self.scr_chip, self.export_btn, self.preview_w.live_btn,
                  *self.preview_w.seg.buttons.values()):
            w.setFocusPolicy(Qt.NoFocus)

        self.toast = Toast(root)
        self.toast.action.connect(lambda: self._open_export(self._last_session))

    def _build_tray(self):
        self.tray = None
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self.tray = QSystemTrayIcon(app_icon(), self)
        self.tray.setToolTip("StudyLapse")
        menu = QMenu()
        self.act_show = QAction("Show StudyLapse", self, triggered=self._show_from_tray)
        self.act_pause = QAction("Pause", self, triggered=self._record_clicked)
        self.act_stop = QAction("Stop && save", self, triggered=self._stop)
        self.act_quit = QAction("Quit", self, triggered=self._quit)
        menu.addAction(self.act_show)
        menu.addSeparator()
        menu.addAction(self.act_pause)
        menu.addAction(self.act_stop)
        menu.addSeparator()
        menu.addAction(self.act_quit)
        self.tray_menu = menu
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(
            lambda r: self._show_from_tray() if r in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick) else None
        )
        self._update_tray()
        self.tray.show()

    def _update_tray(self):
        if not self.tray:
            return
        rec = self.recorder is not None
        paused = rec and self.recorder.paused
        self.act_pause.setText("Resume" if paused else ("Pause" if rec else "Start recording"))
        self.act_stop.setEnabled(rec)
        self.tray.setIcon(app_icon(rec and not paused))
        if rec:
            self.tray.setToolTip(
                f"StudyLapse - {'paused' if paused else 'recording'}  ·  {self.recorder.frame_count} frames"
            )
        else:
            self.tray.setToolTip("StudyLapse")

    # ================================================================ helpers
    def _sync_sources(self):
        both = self.s.use_webcam and self.s.use_screen
        self.preview_w.seg.setVisible(both)
        if not both:
            self.preview_source = "webcam" if self.s.use_webcam else "screen"
            self.preview_w.seg.set_value(self.preview_source)
        idle = self.recorder is None
        self.preview_w.live_btn.setVisible(idle and self.s.use_webcam)
        if not self.s.use_webcam and self.preview is not None:
            self.preview_w.live_btn.setChecked(False)
        self._show_thumb()
        self._update_lock_badge()

    def _show_thumb(self):
        img = self.thumbs.get(self.preview_source)
        if img is not None:
            self.preview_w.set_image(img)
        elif self.recorder is None:
            if self.preview_source == "webcam":
                self.preview_w.clear("Press record to start.\nTap the eye to frame your webcam.")
            else:
                self.preview_w.clear("Press record to start.\nYour latest frame shows up here.")
        else:
            self.preview_w.clear("Waiting for the first frame…")

    def _update_lock_badge(self):
        if not self.s.use_webcam or self.preview_source != "webcam":
            self.preview_w.set_badge(None)
            return
        if not self.s.lock_camera:
            self.preview_w.set_badge("Auto exposure")
        elif self.lock_state and any(self.lock_state.locked.values()):
            self.preview_w.set_badge("🔒 Locked")
        else:
            self.preview_w.set_badge(None)

    def _fps(self) -> int:
        return self.s.export_fps or 30

    def _refresh_stats(self):
        r = self.recorder
        if r is None:
            return
        self.st_elapsed.set(format_duration(r.active_seconds()))
        self.st_frames.set(f"{r.frame_count:,}")
        self.st_video.set(f"{r.frame_count / self._fps():.1f} s")

    # ================================================================ slots
    def _interval_changed(self, idx: int, save: bool = True):
        sec = INTERVAL_STEPS[idx]
        self.s.interval = float(sec)
        self.interval_val.setText(format_interval(sec))
        per_hour = 3600 / sec
        self.hint.setText(
            f"1 hour of study  →  {per_hour / self._fps():.0f} s of video at {self._fps()} fps  ·  "
            f"{per_hour:,.0f} frames"
        )
        if self.recorder is not None:
            self.recorder.set_interval(sec)
        if save:
            self.s.save()

    def _sources_changed(self):
        self.s.use_webcam = self.cam_chip.isChecked()
        self.s.use_screen = self.scr_chip.isChecked()
        self.s.save()
        self._sync_sources()

    def _preview_source_changed(self, key: str):
        self.preview_source = key
        if key == "screen" and self.preview is not None:
            self.preview_w.live_btn.setChecked(False)
        if key == "screen" and self.recorder is None and self.thumbs["screen"] is None:
            self._grab_screen_preview()
        self._show_thumb()
        self._update_lock_badge()

    def _grab_screen_preview(self):
        if is_wayland():
            return  # would trigger the portal; wait for the real recording
        try:
            from ..imageio import thumbnail
            from ..screen import MssBackend

            b = MssBackend()
            img = b.grab(self.s.monitor)
            b.close()
            self.thumbs["screen"] = thumbnail(img)
        except Exception:
            pass

    # ------------------------------------------------------------ live preview
    def _live_toggled(self, on: bool):
        if on:
            self._start_preview()
        else:
            self._stop_preview()

    def _start_preview(self):
        if self.preview is not None or self.recorder is not None:
            return
        if self.preview_source != "webcam":
            self.preview_source = "webcam"
            self.preview_w.seg.set_value("webcam")
            self._update_lock_badge()
        lock = self.lock_state if self.s.lock_camera else None
        self.preview = PreviewThread(self.s, lock, self)
        if self._reset_auto:
            self.preview.request_unlock()
            self._reset_auto = False
        self.preview.frame.connect(self._on_preview_frame)
        self.preview.lockDone.connect(self._on_lock)
        self.preview.failed.connect(self._on_preview_failed)
        self.preview.finished.connect(self._on_preview_finished)
        self.preview.start()
        self.preview_w.live_btn.blockSignals(True)
        self.preview_w.live_btn.setChecked(True)
        self.preview_w.live_btn.blockSignals(False)
        self.preview_w.clear("Opening webcam…")

    def _stop_preview(self, wait: bool = False):
        p = self.preview
        if p is None:
            return
        p.stop()
        if wait:
            p.wait(5000)

    def _on_preview_frame(self, img):
        self.thumbs["webcam"] = img
        if self.preview_source == "webcam":
            self.preview_w.set_image(img)

    def _on_preview_failed(self, msg: str):
        self.toast.show_message(msg)

    def _on_preview_finished(self):
        self.preview = None
        self.preview_w.live_btn.blockSignals(True)
        self.preview_w.live_btn.setChecked(False)
        self.preview_w.live_btn.blockSignals(False)
        self._show_thumb()

    def _on_lock(self, st: LockState):
        self.lock_state = st
        self._update_lock_badge()
        if self.settings_dlg is not None:
            self.settings_dlg.set_lock_summary(st.summary())

    # ------------------------------------------------------------ recording
    def _record_clicked(self):
        r = self.recorder
        if r is None:
            self._start()
        elif self.rec_btn.mode == "busy":
            return
        elif r.paused:
            r.resume()
        else:
            r.pause()

    def _start(self):
        if not (self.s.use_webcam or self.s.use_screen):
            self.toast.show_message("Turn on Webcam or Screen first.")
            return
        out = Path(self.s.output_dir).expanduser()
        try:
            out.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            self.toast.show_message(f"Can't use the output folder: {e}")
            return
        self._stop_preview(wait=True)
        self.preview = None
        self.s.save()
        self.thumbs = {"webcam": None, "screen": None}

        lock_cache = self.lock_state if self.s.lock_camera else None
        r = Recorder(self.s, lock_cache, self)
        r.want_thumbs = self.isVisible()
        r.frameCaptured.connect(self._on_frame)
        r.message.connect(lambda m: self.toast.show_message(m))
        r.lockChanged.connect(self._on_lock)
        r.phase.connect(self._on_phase)
        r.stopped.connect(self._on_stopped)
        self.recorder = r
        if self._reset_auto and self.s.use_webcam:
            # The user turned locking off: hand control back to the camera's auto modes once.
            from ..camera import Camera

            c = Camera(self.s.camera_index, self.s.camera_resolution)
            if c.open():
                c.set_auto()
                c.close()
            self._reset_auto = False

        self.cam_chip.setEnabled(False)
        self.scr_chip.setEnabled(False)
        self.export_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.st_elapsed.set("0:00:00")
        self.st_frames.set("0")
        self.st_video.set("0.0 s")
        self._sync_sources()
        self.rec_btn.set_mode("busy")
        self.pill.set_state("calibrating" if (self.s.use_webcam and self.s.lock_camera) else "recording")
        self.clock.start()
        r.start()
        self._update_tray()

    def _on_phase(self, phase: str):
        if self.recorder is None:
            return
        self.pill.set_state(phase)
        self.rec_btn.set_mode({"calibrating": "busy", "recording": "recording", "paused": "paused"}[phase])
        self._update_tray()

    def _on_frame(self, n: int, cam, scr):
        if cam is not None:
            self.thumbs["webcam"] = cam
        if scr is not None:
            self.thumbs["screen"] = scr
        if cam is not None or scr is not None:
            self._show_thumb()
        self._refresh_stats()
        self._update_tray()

    def _stop(self):
        if self.recorder is not None:
            self.stop_btn.setEnabled(False)
            self.recorder.stop()

    def _on_stopped(self, session_dir: str, frames: int):
        r = self.recorder
        self.recorder = None
        if r is not None:
            r.wait(3000)
        self.clock.stop()
        self.rec_btn.set_mode("idle")
        self.pill.set_state("idle")
        self.cam_chip.setEnabled(True)
        self.scr_chip.setEnabled(True)
        self.export_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self._sync_sources()
        self._update_tray()
        if self._quitting:
            QApplication.quit()
            return
        if frames > 0:
            self._last_session = session_dir
            self.toast.show_message(f"Saved {frames:,} frames.", "Export", ms=10000)
        else:
            self.toast.show_message("Nothing was captured in that session.")

    # ------------------------------------------------------------ dialogs
    def _open_settings(self):
        if self.settings_dlg is not None:
            return
        summary = self.lock_state.summary() if (self.lock_state and self.s.lock_camera) else ""
        if not self.s.lock_camera:
            summary = "Auto (not locked)"
        dlg = SettingsDialog(self.s, self.recorder is not None, summary, self)
        self.settings_dlg = dlg
        dlg.lockRequested.connect(self._lock_now)
        dlg.unlockRequested.connect(self._unlock)
        dlg.driverSettingsRequested.connect(self._driver_settings)
        dlg.exposureCompChanged.connect(self._comp_changed)
        dlg.changed.connect(self._settings_changed)
        dlg.exec()
        self.settings_dlg = None
        self.s.save()
        self._sync_sources()
        self._interval_changed(self.interval_slider.value(), save=False)

    def _settings_changed(self):
        # Camera device / resolution changes invalidate a stored lock.
        st = self.lock_state
        if st is not None and (
            getattr(st, "index", None) != self.s.camera_index
            or getattr(st, "resolution", None) != self.s.camera_resolution
        ):
            self.lock_state = None
            if self.preview is not None:
                self._stop_preview(wait=True)
        self._update_lock_badge()

    def _lock_now(self):
        if self.recorder is not None:
            self.recorder.request_relock()
            return
        if self.preview is None:
            self._start_preview()
        if self.preview is not None:
            self.preview.request_lock()

    def _unlock(self):
        self.lock_state = None
        if self.recorder is not None:
            self.recorder.request_unlock()
        if self.preview is not None:
            self.preview.request_unlock()
        else:
            self._reset_auto = True
        self._update_lock_badge()

    def _driver_settings(self):
        if self.preview is None:
            self._start_preview()
        if self.preview is not None:
            self.preview.request_driver_settings()

    def _comp_changed(self, v: float):
        if self.recorder is not None:
            self.recorder.set_exposure_comp(v)
        if self.preview is not None:
            self.preview.set_exposure_comp(v)

    def _open_export(self, preselect: str | None = None):
        if self.recorder is not None:
            self.toast.show_message("Stop recording before exporting.")
            return
        self._stop_preview()
        dlg = ExportDialog(self.s, preselect if isinstance(preselect, str) else None, self)
        dlg.exec()

    def _open_folder(self):
        target = Path(self.s.output_dir).expanduser()
        if self.recorder is not None:
            target = self.recorder.session_dir
        target.mkdir(parents=True, exist_ok=True)
        open_folder(target)

    # ================================================================ window
    def _show_from_tray(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def showEvent(self, e):
        super().showEvent(e)
        if self.recorder is not None:
            self.recorder.want_thumbs = True
            self.clock.start()
            self._refresh_stats()
            self._show_thumb()
        self.pill.set_animating(True)
        if IS_WINDOWS:
            _dark_title_bar(self)

    def hideEvent(self, e):
        super().hideEvent(e)
        # Nothing to draw - stop every UI timer and skip making thumbnails.
        if self.recorder is not None:
            self.recorder.want_thumbs = False
        self.clock.stop()
        self.pill.set_animating(False)
        if self.preview is not None:
            self._stop_preview()

    def changeEvent(self, e):
        super().changeEvent(e)
        if e.type() == e.Type.WindowStateChange and self.isMinimized():
            if self.recorder is not None:
                self.recorder.want_thumbs = False
            self.clock.stop()
            self.pill.set_animating(False)
            if self.preview is not None:
                self._stop_preview()
        elif e.type() == e.Type.WindowStateChange and self.recorder is not None and not self.isMinimized():
            self.recorder.want_thumbs = True
            self.clock.start()
            self.pill.set_animating(True)
            self._refresh_stats()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.toast.isVisible():
            self.toast.reposition()

    def closeEvent(self, e):
        if self._quitting:
            e.accept()
            return
        if self.recorder is not None:
            if self.tray is not None and self.s.minimize_to_tray:
                e.ignore()
                self.hide()
                if not self._tray_hint_shown:
                    self._tray_hint_shown = True
                    self.tray.showMessage(
                        "StudyLapse is still recording",
                        "It keeps running in the tray. Right-click the icon to pause or stop.",
                        app_icon(True),
                        4000,
                    )
                return
            ans = QMessageBox.question(self, "Stop recording?", "A session is recording. Stop it and quit?")
            if ans != QMessageBox.Yes:
                e.ignore()
                return
            self._quit()
            e.ignore()
            return
        self._stop_preview(wait=True)
        self.s.save()
        e.accept()
        QApplication.quit()

    def _quit(self):
        self._quitting = True
        self._stop_preview(wait=True)
        self.s.save()
        if self.recorder is not None:
            self.recorder.stop()  # _on_stopped will quit once files are flushed
        else:
            QApplication.quit()


def _dark_title_bar(win: QMainWindow):
    try:
        import ctypes

        hwnd = int(win.winId())
        val = ctypes.c_int(1)
        for attr in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE (new / old builds)
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(val), ctypes.sizeof(val)) == 0:
                break
    except Exception:
        pass
