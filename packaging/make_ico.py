"""Render the app icon to packaging/studylapse.ico (used by the Windows build)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtGui import QGuiApplication  # noqa: E402

app = QGuiApplication([])
from studylapse.ui.icons import app_icon  # noqa: E402

out = Path(__file__).with_name("studylapse.ico")
app_icon().pixmap(256, 256).save(str(out), "ICO")
print("wrote", out)
