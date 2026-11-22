"""Export a recorded session to an MP4."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from ..config import Settings, format_duration
from ..exporter import LAYOUTS, Exporter, available_layouts, encoder_description, find_sessions, output_path
from ..platform_utils import open_file, open_folder
from .widgets import Switch


class ExportDialog(QDialog):
    def __init__(self, settings: Settings, preselect: str | None = None, parent=None):
        super().__init__(parent)
        self.s = settings
        self.worker: Exporter | None = None
        self.last_output: Path | None = None
        self.setWindowTitle("Export timelapse")
        self.setModal(True)
        self.setMinimumWidth(460)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 18)
        lay.setSpacing(14)

        title = QLabel("Export timelapse")
        title.setObjectName("Title")
        lay.addWidget(title)

        self.sessions = find_sessions(Path(settings.output_dir))
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(10)
        grid.setColumnStretch(1, 1)

        self.session_combo = QComboBox()
        for info in self.sessions:
            self.session_combo.addItem(info.label, str(info.path))
        if preselect:
            i = self.session_combo.findData(preselect)
            if i >= 0:
                self.session_combo.setCurrentIndex(i)
        grid.addWidget(QLabel("Session"), 0, 0)
        grid.addWidget(self.session_combo, 0, 1)

        self.layout_combo = QComboBox()
        grid.addWidget(QLabel("Layout"), 1, 0)
        grid.addWidget(self.layout_combo, 1, 1)

        self.fps_combo = QComboBox()
        for fps in (24, 30, 60):
            self.fps_combo.addItem(f"{fps} fps", fps)
        self.fps_combo.setCurrentIndex(max(0, self.fps_combo.findData(settings.export_fps)))
        grid.addWidget(QLabel("Speed"), 2, 0)
        grid.addWidget(self.fps_combo, 2, 1)

        self.h_combo = QComboBox()
        for h in (720, 1080, 1440, 2160):
            self.h_combo.addItem(f"{h}p" if h != 2160 else "4K", h)
        self.h_combo.setCurrentIndex(max(0, self.h_combo.findData(settings.export_height)))
        grid.addWidget(QLabel("Quality"), 3, 0)
        grid.addWidget(self.h_combo, 3, 1)
        lay.addLayout(grid)

        self.timer_switch = Switch("Show study timer")
        self.timer_switch.setChecked(settings.export_timer)
        lay.addWidget(self.timer_switch)

        self.info = QLabel()
        self.info.setObjectName("Hint")
        self.info.setWordWrap(True)
        lay.addWidget(self.info)

        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.hide()
        lay.addWidget(self.progress)

        btns = QHBoxLayout()
        self.open_btn = QPushButton("Show in folder")
        self.open_btn.hide()
        self.open_btn.clicked.connect(self._open)
        self.play_btn = QPushButton("▶  Play")
        self.play_btn.setObjectName("Primary")
        self.play_btn.setToolTip("Open the MP4 in your video player")
        self.play_btn.hide()
        self.play_btn.clicked.connect(self._play)
        self.close_btn = QPushButton("Close")
        self.close_btn.clicked.connect(self._close_or_cancel)
        self.go_btn = QPushButton("Export")
        self.go_btn.setObjectName("Primary")
        self.go_btn.setDefault(True)
        self.go_btn.clicked.connect(self._start)
        btns.addWidget(self.open_btn)
        btns.addStretch(1)
        btns.addWidget(self.close_btn)
        btns.addWidget(self.go_btn)
        btns.addWidget(self.play_btn)
        lay.addLayout(btns)

        self.session_combo.currentIndexChanged.connect(self._session_changed)
        self.layout_combo.currentIndexChanged.connect(self._update_info)
        self.h_combo.currentIndexChanged.connect(self._update_info)
        self.timer_switch.toggled.connect(self._update_info)
        self.fps_combo.currentIndexChanged.connect(self._update_info)
        self._session_changed()
        if not self.sessions:
            self.go_btn.setEnabled(False)
            self.info.setText("No recordings found in your output folder yet.")

    def _current(self):
        i = self.session_combo.currentIndex()
        return self.sessions[i] if 0 <= i < len(self.sessions) else None

    def _session_changed(self):
        info = self._current()
        prev = self.layout_combo.currentData() or self.s.export_layout
        self.layout_combo.blockSignals(True)
        self.layout_combo.clear()
        if info:
            for key in available_layouts(info):
                self.layout_combo.addItem(LAYOUTS[key], key)
        i = self.layout_combo.findData(prev)
        self.layout_combo.setCurrentIndex(max(0, i))
        self.layout_combo.blockSignals(False)
        self._update_info()

    def _update_info(self):
        info = self._current()
        if not info:
            return
        fps = self.fps_combo.currentData() or 30
        n = len(info.frames)
        study = info.frames[-1][1] if info.frames else 0
        self.info.setText(
            f"{n} frames  ·  {format_duration(study)} of study  →  {n / fps:.1f} s video\n"
            f"{encoder_description()}"
        )
        # Already exported? Offer to play it straight away.
        layout = self.layout_combo.currentData()
        existing = output_path(info, layout) if layout else None
        if self.worker is None:
            if existing is not None and existing.exists():
                self.last_output = existing
                self.go_btn.setText("Export again")
                self.go_btn.setObjectName("")
                self.play_btn.show()
                self.open_btn.show()
            else:
                self.go_btn.setText("Export")
                self.go_btn.setObjectName("Primary")
                self.play_btn.hide()
                self.open_btn.hide()
            self.go_btn.style().unpolish(self.go_btn)
            self.go_btn.style().polish(self.go_btn)

    def _start(self):
        info = self._current()
        if not info or self.layout_combo.count() == 0:
            return
        layout = self.layout_combo.currentData()
        fps = self.fps_combo.currentData()
        h = self.h_combo.currentData()
        timer = self.timer_switch.isChecked()
        self.s.export_layout, self.s.export_fps, self.s.export_height, self.s.export_timer = layout, fps, h, timer
        self.s.save()

        self.worker = Exporter(info, layout, fps, h, timer, self)
        self.worker.progress.connect(self._progress)
        self.worker.done.connect(self._done)
        self.worker.failed.connect(self._failed)
        self.progress.setRange(0, len(info.frames))
        self.progress.setValue(0)
        self.progress.show()
        self.open_btn.hide()
        self.play_btn.hide()
        self._set_inputs(False)
        self.close_btn.setText("Cancel")
        self.info.setText("Exporting… you can keep working, this runs at low priority.")
        self.worker.start()

    def _set_inputs(self, on: bool):
        for w in (self.session_combo, self.layout_combo, self.fps_combo, self.h_combo, self.timer_switch,
                  self.go_btn, self.play_btn):
            w.setEnabled(on)

    def _progress(self, n: int, total: int):
        self.progress.setValue(n)

    def _done(self, path: str):
        self.last_output = Path(path)
        self.worker = None
        self._set_inputs(True)
        self.close_btn.setText("Close")
        self.progress.setValue(self.progress.maximum())
        self.info.setText(f"Saved  {Path(path).name}  ·  {Path(path).stat().st_size / 1e6:.1f} MB")
        self.go_btn.setText("Export again")
        self.go_btn.setObjectName("")
        self.go_btn.style().unpolish(self.go_btn)
        self.go_btn.style().polish(self.go_btn)
        self.open_btn.show()
        self.play_btn.show()
        self.play_btn.setFocus()

    def _failed(self, msg: str):
        self.worker = None
        self._set_inputs(True)
        self.close_btn.setText("Close")
        self.progress.hide()
        self.info.setText(msg)

    def _play(self):
        if self.last_output and self.last_output.exists():
            open_file(self.last_output)

    def _open(self):
        if self.last_output:
            open_folder(self.last_output.parent)

    def _close_or_cancel(self):
        if self.worker is not None:
            self.worker.cancel()
        else:
            self.accept()

    def reject(self):
        if self.worker is not None:
            self.worker.cancel()
            self.worker.wait(5000)
        super().reject()
