# PyInstaller spec - build with:  pyinstaller packaging/studylapse.spec
# Produces a single-folder app in dist/StudyLapse (starts faster than one-file).
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files

root = Path(SPECPATH).parent
icon = None
if sys.platform == "win32" and (root / "packaging" / "studylapse.ico").exists():
    icon = str(root / "packaging" / "studylapse.ico")

a = Analysis(
    [str(root / "packaging" / "launcher.py")],
    pathex=[str(root)],
    hiddenimports=["studylapse.ui.main_window", "imageio_ffmpeg"],
    datas=collect_data_files("imageio_ffmpeg", includes=["binaries/*"]),  # bundled H.264 ffmpeg
    excludes=["tkinter", "matplotlib", "PySide6.QtWebEngineCore", "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtPdf"],
)
# Drop Qt translations and plugins we never load (saves ~20 MB).
_skip = ("translations", "qtvirtualkeyboard", "qwebgl", "qpdf", "networkinformation", "tls")
a.datas = [d for d in a.datas if not any(k in d[0].lower() for k in _skip)]
a.binaries = [b for b in a.binaries if not any(k in b[0].lower() for k in _skip[1:])]

pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="StudyLapse",
    console=False,
    icon=icon,
)
coll = COLLECT(exe, a.binaries, a.datas, name="StudyLapse")
