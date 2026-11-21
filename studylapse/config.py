"""Persistent user settings (JSON in the platform config dir)."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from .platform_utils import config_dir, default_output_dir

# Interval slider stops, in seconds.
INTERVAL_STEPS = [1, 2, 3, 5, 10, 15, 20, 30, 45, 60, 90, 120, 180, 300, 600]


@dataclass
class Settings:
    # Sources
    use_webcam: bool = True
    use_screen: bool = True
    interval: float = 10.0

    # Webcam
    camera_index: int = 0
    camera_resolution: str = "1080p"
    lock_camera: bool = True          # auto-calibrate then freeze exposure/focus/WB
    exposure_comp: float = 0.0        # stops, applied on top of the locked exposure
    keep_camera_open: str = "auto"    # auto | always | never

    # Screen
    monitor: int = 0                  # 0 = all monitors, 1..n = a single monitor
    screen_max_height: int = 1080     # 0 = native resolution
    capture_cursor: bool = False

    # Output
    output_dir: str = field(default_factory=lambda: str(default_output_dir()))
    jpeg_quality: int = 90

    # App
    minimize_to_tray: bool = True

    # Export defaults
    export_layout: str = "pip"
    export_fps: int = 30
    export_timer: bool = True
    export_height: int = 1080

    @classmethod
    def path(cls) -> Path:
        return config_dir() / "settings.json"

    @classmethod
    def load(cls) -> "Settings":
        s = cls()
        try:
            data = json.loads(cls.path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return s
        known = {f.name: f for f in fields(cls)}
        for key, value in data.items():
            if key in known:
                default = getattr(s, key)
                # Only accept values of the same basic type as the default.
                if isinstance(default, bool) or default is None:
                    ok = isinstance(value, bool)
                elif isinstance(default, (int, float)):
                    ok = isinstance(value, (int, float)) and not isinstance(value, bool)
                else:
                    ok = isinstance(value, type(default))
                if ok:
                    setattr(s, key, type(default)(value) if default is not None else value)
        return s

    def save(self) -> None:
        try:
            p = self.path()
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(".tmp")
            tmp.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
            tmp.replace(p)
        except OSError:
            pass


def format_interval(seconds: float) -> str:
    seconds = float(seconds)
    if seconds < 60:
        return f"{seconds:g} s"
    if seconds % 60 == 0:
        return f"{int(seconds // 60)} min"
    return f"{int(seconds // 60)} min {int(seconds % 60)} s"


def format_duration(seconds: float) -> str:
    seconds = int(max(0, seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:d}:{m:02d}:{s:02d}"
