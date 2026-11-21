"""Turn a session folder into an MP4.

Uses ffmpeg (H.264, small files) when it is installed, otherwise OpenCV's
built-in MPEG-4 writer. Runs at low priority in a background thread.
"""

from __future__ import annotations

import csv
import shutil
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from PySide6.QtCore import QThread, Signal

from .config import format_duration
from .imageio import read_image
from .platform_utils import IS_WINDOWS

LAYOUTS = {
    "pip": "Screen + webcam corner",
    "side": "Side by side",
    "vertical": "Vertical (phone)",
    "screen": "Screen only",
    "webcam": "Webcam only",
}


@dataclass
class SessionInfo:
    path: Path
    frames: list[tuple[int, float]]  # (index, active_seconds)
    has_webcam: bool
    has_screen: bool

    @property
    def label(self) -> str:
        name = self.path.name.replace("_", "  ", 1)
        name = name[:12] + name[12:].replace("-", ":")
        dur = format_duration(self.frames[-1][1]) if self.frames else "0:00:00"
        return f"{name}   ·   {len(self.frames)} frames   ·   {dur}"

    @classmethod
    def load(cls, path: Path) -> "SessionInfo | None":
        csv_path = path / "frames.csv"
        if not csv_path.exists():
            return None
        frames: list[tuple[int, float]] = []
        try:
            with open(csv_path, newline="", encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    try:
                        frames.append((int(row["index"]), float(row["active_seconds"])))
                    except (KeyError, ValueError):
                        continue
        except OSError:
            return None
        return cls(path, frames, (path / "webcam").is_dir(), (path / "screen").is_dir())


def find_sessions(output_dir: Path) -> list[SessionInfo]:
    out = []
    root = Path(output_dir).expanduser()
    if not root.is_dir():
        return out
    for d in sorted((p for p in root.iterdir() if p.is_dir()), reverse=True):
        info = SessionInfo.load(d)
        if info and info.frames:
            out.append(info)
    return out


def _even(x: float) -> int:
    return max(2, int(round(x / 2)) * 2)


def _fit(img: np.ndarray, w: int, h: int) -> np.ndarray:
    """Scale to fill (w, h), cropping the overflow (centre crop)."""
    ih, iw = img.shape[:2]
    s = max(w / iw, h / ih)
    nw, nh = max(w, round(iw * s)), max(h, round(ih * s))
    interp = cv2.INTER_AREA if s < 1 else cv2.INTER_LINEAR
    r = cv2.resize(img, (nw, nh), interpolation=interp)
    x, y = (nw - w) // 2, (nh - h) // 2
    return r[y : y + h, x : x + w]


def _contain(img: np.ndarray, w: int, h: int) -> np.ndarray:
    ih, iw = img.shape[:2]
    s = min(w / iw, h / ih)
    nw, nh = max(1, round(iw * s)), max(1, round(ih * s))
    interp = cv2.INTER_AREA if s < 1 else cv2.INTER_LINEAR
    return cv2.resize(img, (nw, nh), interpolation=interp)


def _rounded_mask(w: int, h: int, r: int) -> np.ndarray:
    # Draw at 4x and downsample for smooth anti-aliased corners.
    k = 4
    m = np.zeros((h * k, w * k), np.uint8)
    rr = r * k
    cv2.rectangle(m, (rr, 0), (w * k - rr, h * k), 255, -1)
    cv2.rectangle(m, (0, rr), (w * k, h * k - rr), 255, -1)
    for cx, cy in ((rr, rr), (w * k - rr, rr), (rr, h * k - rr), (w * k - rr, h * k - rr)):
        cv2.circle(m, (cx, cy), rr, 255, -1, lineType=cv2.LINE_AA)
    m = cv2.resize(m, (w, h), interpolation=cv2.INTER_AREA)
    return (m.astype(np.float32) / 255.0)[..., None]


class Compositor:
    def __init__(self, layout: str, height: int, cam_shape, scr_shape):
        self.layout = layout
        cam_ar = cam_shape[1] / cam_shape[0] if cam_shape else 16 / 9
        scr_ar = scr_shape[1] / scr_shape[0] if scr_shape else 16 / 9
        H = height
        if layout == "webcam":
            self.size = (_even(H * cam_ar), _even(H))
        elif layout == "screen" or layout == "pip":
            self.size = (_even(H * scr_ar), _even(H))
        elif layout == "side":
            w = H * cam_ar + H * scr_ar
            if w > 3840:  # keep within 4K width
                H = H * 3840 / w
            self.size = (_even(H * cam_ar + H * scr_ar), _even(H))
            self.split = _even(H * cam_ar)
        elif layout == "vertical":
            W = _even(H * 9 / 16)
            self.size = (W, _even(H))
        else:
            raise ValueError(layout)

        W, H = self.size
        if layout == "pip":
            pw = _even(W * 0.26)
            ph = _even(pw / cam_ar)
            m = max(8, _even(W * 0.02))
            self.pip_rect = (W - pw - m, H - ph - m, pw, ph)
            self.pip_mask = _rounded_mask(pw, ph, max(4, pw // 18))
        self.font_scale = H / 900

    def compose(self, cam, scr) -> np.ndarray:
        W, H = self.size
        lay = self.layout
        canvas = np.zeros((H, W, 3), np.uint8)
        canvas[:] = (24, 20, 18)
        if lay == "webcam" and cam is not None:
            canvas[:] = _fit(cam, W, H)
        elif lay == "screen" and scr is not None:
            canvas[:] = _fit(scr, W, H)
        elif lay == "pip":
            if scr is not None:
                canvas[:] = _fit(scr, W, H)
            elif cam is not None:
                canvas[:] = _fit(cam, W, H)
            if cam is not None and scr is not None:
                x, y, pw, ph = self.pip_rect
                # soft shadow
                sh = canvas[y + 4 : y + ph + 4, x + 2 : x + pw + 2].astype(np.float32)
                canvas[y + 4 : y + ph + 4, x + 2 : x + pw + 2] = (sh * (1 - 0.35 * self.pip_mask)).astype(np.uint8)
                inset = _fit(cam, pw, ph).astype(np.float32)
                bg = canvas[y : y + ph, x : x + pw].astype(np.float32)
                canvas[y : y + ph, x : x + pw] = (inset * self.pip_mask + bg * (1 - self.pip_mask)).astype(np.uint8)
        elif lay == "side":
            s = self.split
            if cam is not None:
                canvas[:, :s] = _fit(cam, s, H)
            if scr is not None:
                canvas[:, s:] = _fit(scr, W - s, H)
        elif lay == "vertical":
            top = H // 2
            if cam is not None:
                canvas[:top] = _fit(cam, W, top)
            if scr is not None:
                img = _contain(scr, W, H - top)
                ih, iw = img.shape[:2]
                y0 = top + (H - top - ih) // 2
                canvas[y0 : y0 + ih, (W - iw) // 2 : (W - iw) // 2 + iw] = img
        return canvas

    def draw_timer(self, img: np.ndarray, seconds: float) -> None:
        text = format_duration(seconds)
        font = cv2.FONT_HERSHEY_DUPLEX
        fs = 1.15 * self.font_scale
        th = max(1, int(round(2 * self.font_scale)))
        (tw, tht), base = cv2.getTextSize(text, font, fs, th)
        pad = int(14 * self.font_scale)
        x0, y0 = int(24 * self.font_scale), int(24 * self.font_scale)
        x1, y1 = x0 + tw + 2 * pad, y0 + tht + base + 2 * pad
        roi = img[y0:y1, x0:x1]
        if roi.size:
            img[y0:y1, x0:x1] = (roi.astype(np.float32) * 0.45).astype(np.uint8)
        cv2.putText(img, text, (x0 + pad, y1 - pad - base // 2), font, fs, (255, 255, 255), th, cv2.LINE_AA)


def find_ffmpeg() -> str | None:
    return shutil.which("ffmpeg")


class Exporter(QThread):
    progress = Signal(int, int)
    done = Signal(str)     # output path
    failed = Signal(str)

    def __init__(self, session: SessionInfo, layout: str, fps: int, height: int, timer: bool, parent=None):
        super().__init__(parent)
        self.session = session
        self.layout = layout
        self.fps = fps
        self.height = height
        self.timer = timer
        self._cancel = threading.Event()
        self.output = session.path / f"timelapse_{layout}.mp4"

    def cancel(self):
        self._cancel.set()

    def _frame(self, sub: str, idx: int):
        p = self.session.path / sub / f"{idx:06d}.jpg"
        return read_image(p) if p.exists() else None

    def run(self):
        try:
            self._run()
        except Exception as e:  # noqa: BLE001
            self.failed.emit(str(e))

    def _run(self):
        s = self.session
        need_cam = self.layout in ("webcam", "pip", "side", "vertical") and s.has_webcam
        need_scr = self.layout in ("screen", "pip", "side", "vertical") and s.has_screen
        if not (need_cam or need_scr):
            self.failed.emit("This session has no frames for that layout.")
            return

        # Find the first available frame of each source to size the canvas.
        first_cam = first_scr = None
        for idx, _ in s.frames:
            if need_cam and first_cam is None:
                first_cam = self._frame("webcam", idx)
            if need_scr and first_scr is None:
                first_scr = self._frame("screen", idx)
            if (first_cam is not None or not need_cam) and (first_scr is not None or not need_scr):
                break
        comp = Compositor(
            self.layout,
            self.height,
            first_cam.shape if first_cam is not None else None,
            first_scr.shape if first_scr is not None else None,
        )
        W, H = comp.size

        ffmpeg = find_ffmpeg()
        proc = writer = None
        tmp_out = self.output.with_suffix(".part.mp4")
        if ffmpeg:
            cmd = [
                ffmpeg, "-y", "-loglevel", "error",
                "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}", "-r", str(self.fps), "-i", "-",
                "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
                "-movflags", "+faststart", "-threads", "2", str(tmp_out),
            ]
            kwargs = {}
            if IS_WINDOWS:
                kwargs["creationflags"] = 0x08000000 | 0x00004000  # CREATE_NO_WINDOW | BELOW_NORMAL
            else:
                kwargs["preexec_fn"] = lambda: __import__("os").nice(15)
            proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE, **kwargs)
        else:
            writer = cv2.VideoWriter(str(tmp_out), cv2.VideoWriter_fourcc(*"mp4v"), self.fps, (W, H))
            if not writer.isOpened():
                self.failed.emit("Could not open a video writer (install ffmpeg for best results).")
                return

        last_cam, last_scr = first_cam, first_scr
        total = len(s.frames)
        try:
            for n, (idx, active) in enumerate(s.frames, start=1):
                if self._cancel.is_set():
                    break
                if need_cam:
                    f = self._frame("webcam", idx)
                    last_cam = f if f is not None else last_cam
                if need_scr:
                    f = self._frame("screen", idx)
                    last_scr = f if f is not None else last_scr
                img = comp.compose(last_cam, last_scr)
                if self.timer:
                    comp.draw_timer(img, active)
                if proc:
                    try:
                        proc.stdin.write(img.tobytes())
                    except BrokenPipeError:
                        err = proc.stderr.read().decode(errors="replace")
                        raise RuntimeError(f"ffmpeg stopped: {err.strip()[:300]}")
                else:
                    writer.write(img)
                if n % 5 == 0 or n == total:
                    self.progress.emit(n, total)
        finally:
            if proc:
                try:
                    proc.stdin.close()
                except OSError:
                    pass
                proc.wait()
            if writer:
                writer.release()

        if self._cancel.is_set():
            tmp_out.unlink(missing_ok=True)
            self.failed.emit("Export cancelled.")
            return
        if proc and proc.returncode != 0:
            err = proc.stderr.read().decode(errors="replace") if proc.stderr else ""
            tmp_out.unlink(missing_ok=True)
            self.failed.emit(f"ffmpeg failed: {err.strip()[:300]}")
            return
        tmp_out.replace(self.output)
        self.done.emit(str(self.output))
