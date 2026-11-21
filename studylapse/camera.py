"""Webcam access with exposure / focus / white-balance locking.

How locking works
-----------------
1. Let the camera run in full auto for a couple of seconds so its own
   algorithms settle on good exposure, focus and white balance for the room.
2. Record a reference frame and read back the values the camera chose.
3. Switch every auto control to manual. Most UVC webcams simply *hold* their
   current values when you do this.
4. Verify against the reference frame (brightness, sharpness, colour balance).
   If a camera reset itself when going manual, write the values we read back,
   and if exposure is still off, run a short exposure search to match the
   reference brightness.

The final values are stored so they can be re-applied every time the camera
is re-opened (for long intervals we release the camera between shots, which
saves CPU, USB bandwidth and keeps the webcam LED off).
"""

from __future__ import annotations

import math
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

os.environ.setdefault("OPENCV_LOG_LEVEL", "ERROR")
import cv2  # noqa: E402
import numpy as np  # noqa: E402

from .platform_utils import IS_LINUX, IS_WINDOWS  # noqa: E402

cv2.setNumThreads(1)  # never fan out across cores - we are a background app

RESOLUTIONS = {
    "480p": (640, 480),
    "720p": (1280, 720),
    "1080p": (1920, 1080),
    "1440p": (2560, 1440),
    "4K": (3840, 2160),
}

if IS_WINDOWS:
    BACKEND = cv2.CAP_DSHOW          # DirectShow: best manual-control support + driver dialog
    AE_AUTO, AE_MANUAL = 1, 0
    KEEP_OPEN_BELOW = 8.0            # DirectShow decodes every frame while open
elif IS_LINUX:
    BACKEND = cv2.CAP_V4L2
    AE_AUTO, AE_MANUAL = 3, 1        # V4L2_EXPOSURE_APERTURE_PRIORITY / V4L2_EXPOSURE_MANUAL
    KEEP_OPEN_BELOW = 20.0           # V4L2 idles cheaply when we don't decode
else:
    BACKEND = cv2.CAP_ANY
    AE_AUTO, AE_MANUAL = 0.75, 0.25
    KEEP_OPEN_BELOW = 10.0

P = cv2  # shorthand for property constants


def _valid(v) -> bool:
    return v is not None and isinstance(v, (int, float)) and math.isfinite(v) and v != -1


@dataclass
class FrameStats:
    lum: float
    sharp: float
    bg: float  # blue / green
    rg: float  # red / green

    @classmethod
    def of(cls, frame: np.ndarray) -> "FrameStats":
        h, w = frame.shape[:2]
        tw = 320
        small = cv2.resize(frame, (tw, max(1, int(h * tw / w))), interpolation=cv2.INTER_AREA)
        b, g, r = (float(x) for x in small.reshape(-1, 3).mean(axis=0))
        g = max(g, 1.0)
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        sharp = float(cv2.Laplacian(gray, cv2.CV_32F).var())
        lum = 0.114 * b + 0.587 * g + 0.299 * r
        return cls(lum, sharp, b / g, r / g)


@dataclass
class LockState:
    """Values we froze the camera at. Stored per session in session.json."""

    exposure: float | None = None
    gain: float | None = None
    focus: float | None = None
    wb: float | None = None
    locked: dict = field(default_factory=dict)  # control -> bool
    when: float = 0.0

    def summary(self) -> str:
        names = {"exposure": "exposure", "focus": "focus", "wb": "white balance"}
        got = [names[k] for k in ("exposure", "focus", "wb") if self.locked.get(k)]
        if not got:
            return "Camera does not expose manual controls"
        return "Locked " + ", ".join(got)

    def to_dict(self) -> dict:
        return {
            "exposure": self.exposure,
            "gain": self.gain,
            "focus": self.focus,
            "white_balance": self.wb,
            "locked": self.locked,
        }


def list_cameras() -> list[tuple[int, str]]:
    """Return [(index, friendly name)]. Cheap: never opens a device."""
    cams: list[tuple[int, str]] = []
    if IS_LINUX:
        base = Path("/sys/class/video4linux")
        if base.exists():
            for dev in sorted(base.glob("video*"), key=lambda p: int(p.name[5:] or 0)):
                try:
                    # Each UVC camera exposes a capture node (index 0) and a metadata node.
                    if (dev / "index").read_text().strip() != "0":
                        continue
                    name = (dev / "name").read_text().strip()
                except OSError:
                    continue
                cams.append((int(dev.name[5:]), name))
    elif IS_WINDOWS:
        try:
            from pygrabber.dshow_graph import FilterGraph  # optional, gives real names

            cams = list(enumerate(FilterGraph().get_input_devices()))
        except Exception:
            cams = []
    if not cams:
        cams = [(i, f"Camera {i + 1}") for i in range(3)]
    return cams


class Camera:
    def __init__(self, index: int = 0, resolution: str = "1080p", low_fps: bool = False):
        self.index = index
        self.resolution = resolution
        self.low_fps = low_fps
        self.cap: cv2.VideoCapture | None = None
        self._flush = 1

    # ------------------------------------------------------------------ basics
    @property
    def is_open(self) -> bool:
        return self.cap is not None and self.cap.isOpened()

    def open(self) -> bool:
        if self.is_open:
            return True
        cap = cv2.VideoCapture(self.index, BACKEND)
        if not cap.isOpened():
            cap.release()
            cap = cv2.VideoCapture(self.index)
        if not cap.isOpened():
            cap.release()
            return False
        w, h = RESOLUTIONS.get(self.resolution, RESOLUTIONS["1080p"])
        # MJPG lets USB2 webcams deliver 1080p; without it many fall back to 480p/5fps.
        cap.set(P.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        cap.set(P.CAP_PROP_FRAME_WIDTH, w)
        cap.set(P.CAP_PROP_FRAME_HEIGHT, h)
        if IS_LINUX:
            if self.low_fps:
                cap.set(P.CAP_PROP_FPS, 5)
            self._flush = 2 if cap.set(P.CAP_PROP_BUFFERSIZE, 1) else 5
        else:
            self._flush = 1
        self.cap = cap
        return True

    def close(self) -> None:
        if self.cap is not None:
            try:
                self.cap.release()
            finally:
                self.cap = None

    def _get(self, prop) -> float | None:
        try:
            v = self.cap.get(prop)
        except cv2.error:
            return None
        return v if _valid(v) else None

    def _set(self, prop, value) -> bool:
        try:
            return bool(self.cap.set(prop, value))
        except cv2.error:
            return False

    def read(self) -> np.ndarray | None:
        """Return the newest frame (drains stale buffered frames)."""
        if not self.is_open:
            return None
        if IS_LINUX:
            for _ in range(self._flush):
                self.cap.grab()
            ok, frame = self.cap.retrieve()
        else:
            ok, frame = self.cap.read()
        if not ok or frame is None or frame.size == 0:
            return None
        if frame.ndim == 2:
            frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
        return frame

    def warm_up(self, seconds: float) -> np.ndarray | None:
        """Stream for a moment (first frames after opening are often dark/garbage)."""
        last = None
        end = time.monotonic() + seconds
        n = 0
        while time.monotonic() < end or n < 2:
            ok, f = self.cap.read()
            if ok and f is not None:
                last = f
            n += 1
            if n > 200:
                break
        return last

    # ---------------------------------------------------------------- locking
    def set_auto(self) -> None:
        if not self.is_open:
            return
        self._set(P.CAP_PROP_AUTO_EXPOSURE, AE_AUTO)
        self._set(P.CAP_PROP_AUTOFOCUS, 1)
        self._set(P.CAP_PROP_AUTO_WB, 1)

    def _set_exposure(self, base: float, comp: float) -> bool:
        if base <= 0:   # DirectShow style: log2(seconds), integer steps
            return self._set(P.CAP_PROP_EXPOSURE, round(base + comp))
        return self._set(P.CAP_PROP_EXPOSURE, max(1.0, round(base * (2.0 ** comp))))

    def apply_lock(self, state: LockState, comp: float = 0.0) -> None:
        """Re-apply a previously calibrated lock (e.g. after re-opening)."""
        if not self.is_open:
            return
        if state.locked.get("focus"):
            self._set(P.CAP_PROP_AUTOFOCUS, 0)
            if state.focus is not None:
                self._set(P.CAP_PROP_FOCUS, state.focus)
        if state.locked.get("wb"):
            self._set(P.CAP_PROP_AUTO_WB, 0)
            if state.wb is not None:
                self._set(P.CAP_PROP_WB_TEMPERATURE, state.wb)
        if state.locked.get("exposure"):
            self._set(P.CAP_PROP_AUTO_EXPOSURE, AE_MANUAL)
            if state.exposure is not None:
                self._set_exposure(state.exposure, comp)
            if state.gain is not None:
                self._set(P.CAP_PROP_GAIN, state.gain)

    def _settled(self, seconds: float = 0.45) -> FrameStats | None:
        f = self.warm_up(seconds)
        return FrameStats.of(f) if f is not None else None

    def calibrate_and_lock(self, settle: float = 2.5, comp: float = 0.0) -> LockState:
        state = LockState(when=time.time())
        if not self.open():
            return state
        self.set_auto()
        ref_frame = self.warm_up(settle)
        if ref_frame is None:
            return state
        ref = FrameStats.of(ref_frame)

        auto = {
            "exposure": self._get(P.CAP_PROP_EXPOSURE),
            "gain": self._get(P.CAP_PROP_GAIN),
            "focus": self._get(P.CAP_PROP_FOCUS),
            "wb": self._get(P.CAP_PROP_WB_TEMPERATURE),
        }

        # Switch to manual - most cameras hold whatever auto had chosen.
        state.locked["focus"] = self._set(P.CAP_PROP_AUTOFOCUS, 0)
        state.locked["wb"] = self._set(P.CAP_PROP_AUTO_WB, 0)
        state.locked["exposure"] = self._set(P.CAP_PROP_AUTO_EXPOSURE, AE_MANUAL)

        cur = self._settled()
        if cur is None:
            return state

        # Exposure: did the camera keep its brightness?
        def lum_off(s: FrameStats) -> float:
            return abs(s.lum - ref.lum) / max(ref.lum, 1.0)

        if state.locked["exposure"] and lum_off(cur) > 0.15 and auto["exposure"] is not None:
            self._set(P.CAP_PROP_EXPOSURE, auto["exposure"])
            if auto["gain"] is not None:
                self._set(P.CAP_PROP_GAIN, auto["gain"])
            cur = self._settled() or cur
        if state.locked["exposure"] and lum_off(cur) > 0.15:
            cur = self._match_brightness(ref.lum) or cur

        # Focus: did sharpness collapse?
        if state.locked["focus"] and cur.sharp < 0.6 * ref.sharp and auto["focus"] is not None:
            self._set(P.CAP_PROP_FOCUS, auto["focus"])
            cur = self._settled() or cur

        # White balance: did the colour cast change?
        if (
            state.locked["wb"]
            and auto["wb"] is not None
            and (abs(cur.bg - ref.bg) > 0.08 or abs(cur.rg - ref.rg) > 0.08)
        ):
            self._set(P.CAP_PROP_WB_TEMPERATURE, auto["wb"])

        state.exposure = self._get(P.CAP_PROP_EXPOSURE)
        state.gain = self._get(P.CAP_PROP_GAIN)
        state.focus = self._get(P.CAP_PROP_FOCUS)
        state.wb = self._get(P.CAP_PROP_WB_TEMPERATURE)
        if comp and state.exposure is not None:
            self._set_exposure(state.exposure, comp)
        return state

    def _match_brightness(self, target: float) -> FrameStats | None:
        exp = self._get(P.CAP_PROP_EXPOSURE)
        if exp is None:
            return None
        log_scale = exp <= 0
        cur = None
        for _ in range(6):
            cur = self._settled(0.35)
            if cur is None:
                return None
            if abs(cur.lum - target) / max(target, 1.0) < 0.08:
                break
            ratio = min(4.0, max(0.25, target / max(cur.lum, 1.0)))
            new = round(exp + math.log2(ratio)) if log_scale else max(1.0, exp * ratio)
            if new == exp:
                break
            exp = new
            self._set(P.CAP_PROP_EXPOSURE, exp)
        return cur

    def show_driver_settings(self) -> bool:
        """Windows only: the camera driver's own property sheet."""
        if IS_WINDOWS and self.is_open:
            return self._set(P.CAP_PROP_SETTINGS, 1)
        return False
