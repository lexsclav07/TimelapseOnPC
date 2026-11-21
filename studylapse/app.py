"""Entry point."""

from __future__ import annotations

import os
import sys


def main() -> int:
    os.environ.setdefault("OPENCV_LOG_LEVEL", "ERROR")
    # Before anything spawns threads: run below normal priority / efficiency mode.
    from .platform_utils import IS_WINDOWS, config_dir, lower_process_priority

    lower_process_priority()

    if IS_WINDOWS:
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("StudyLapse.App")
        except Exception:
            pass

    from PySide6.QtCore import QLockFile, Qt
    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import QApplication, QMessageBox

    from . import APP_NAME
    from .config import Settings
    from .ui.icons import app_icon
    from .ui.main_window import MainWindow
    from .ui.style import build_qss

    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setDesktopFileName("studylapse")
    app.setWindowIcon(app_icon())
    app.setQuitOnLastWindowClosed(False)  # we may live in the tray
    app.setStyle("Fusion")
    font = QFont()
    font.setFamilies(["Segoe UI Variable Text", "Segoe UI", "Inter", "Cantarell", "Noto Sans", "Ubuntu", "sans-serif"])
    font.setPointSizeF(10)
    app.setFont(font)
    app.setStyleSheet(build_qss())

    # One instance only - two would fight over the webcam.
    config_dir().mkdir(parents=True, exist_ok=True)
    lock = QLockFile(str(config_dir() / "instance.lock"))
    lock.setStaleLockTime(0)
    if not lock.tryLock(100):
        QMessageBox.information(None, APP_NAME, "StudyLapse is already running (check the system tray).")
        return 0

    win = MainWindow(Settings.load())
    win.show()
    code = app.exec()
    lock.unlock()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
