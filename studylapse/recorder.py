"""Background capture loop. Sleeps between shots - zero CPU while waiting."""

from __future__ import annotations

import copy
import json
import threading
import time
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from . import __version__
from .camera import KEEP_OPEN_BELOW, Camera, LockState
from .config import Settings
from .imageio import thumbnail, write_jpeg
from .screen import make_backend, scale_to_height

LOCK_REUSE_SECONDS = 15 * 60  # reuse a recent calibration instead of re-running it


class Recorder(QThread):
    frameCaptured = Signal(int, object, object)  # frame count, webcam thumb, screen thumb
    message = Signal(str)                        # transient status text
    lockChanged = Signal(object)                 # LockState
    phase = Signal(str)                          # calibrating | recording | paused
    stopped = Signal(str, int)                   # session dir, frame count

    def __init__(self, settings: Settings, lock_cache: LockState | None = None, parent=None):
        super().__init__(parent)
        self.s = copy.deepcopy(settings)
        self.interval = max(0.5, float(settings.interval))
        self.exposure_comp = settings.exposure_comp
        self.lock_cache = lock_cache
        self.lock_state: LockState | None = None
        self.want_thumbs = True

        self._stop = threading.Event()
        self._wake = threading.Event()
        self._paused = False
        self._relock = False
        self._comp_dirty = False
        self._want_auto = False

        self._active_accum = 0.0
        self._active_since: float | None = None
        self._time_lock = threading.Lock()

        self.frame_count = 0
        stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        self.session_dir = Path(self.s.output_dir).expanduser() / stamp
        self.camera: Camera | None = None
        self.screen = None
        self._last_err: dict[str, float] = {}

    # ------------------------------------------------------------- controls
    def active_seconds(self) -> float:
        with self._time_lock:
            t = self._active_accum
            if self._active_since is not None:
                t += time.monotonic() - self._active_since
            return t

    def _start_clock(self):
        with self._time_lock:
            if self._active_since is None:
                self._active_since = time.monotonic()

    def _stop_clock(self):
        with self._time_lock:
            if self._active_since is not None:
                self._active_accum += time.monotonic() - self._active_since
                self._active_since = None

    @property
    def paused(self) -> bool:
        return self._paused

    def pause(self):
        if not self._paused:
            self._paused = True
            self._stop_clock()
            self.phase.emit("paused")
            self._wake.set()

    def resume(self):
        if self._paused:
            self._paused = False
            self._start_clock()
            self.phase.emit("recording")
            self._wake.set()

    def stop(self):
        self._stop.set()
        self._wake.set()

    def set_interval(self, seconds: float):
        self.interval = max(0.5, float(seconds))
        self._wake.set()

    def set_exposure_comp(self, stops: float):
        self.exposure_comp = stops
        self._comp_dirty = True

    def request_relock(self):
        self._relock = True
        self._wake.set()

    def request_unlock(self):
        """Hand exposure/focus/WB back to the camera's automatic modes."""
        self.lock_state = None
        self._want_auto = True

    # ------------------------------------------------------------- helpers
    def _keep_camera_open(self) -> bool:
        mode = self.s.keep_camera_open
        if mode == "always":
            return True
        if mode == "never":
            return False
        return self.interval < KEEP_OPEN_BELOW

    def _report(self, key: str, text: str, every: float = 30.0):
        """Rate-limited error reporting so a missing camera doesn't spam the UI."""
        now = time.monotonic()
        if now - self._last_err.get(key, -1e9) >= every:
            self._last_err[key] = now
            self.message.emit(text)

    def _write_session_json(self, **extra):
        info = {
            "app": f"StudyLapse {__version__}",
            "started": self.session_dir.name,
            "interval_seconds": self.interval,
            "sources": [n for n, on in (("webcam", self.s.use_webcam), ("screen", self.s.use_screen)) if on],
            "camera_lock": self.lock_state.to_dict() if self.lock_state else None,
            "screen_backend": getattr(self.screen, "name", None),
            "frames": self.frame_count,
            "active_seconds": round(self.active_seconds(), 1),
        }
        info.update(extra)
        try:
            (self.session_dir / "session.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
        except OSError:
            pass

    def _do_lock(self):
        cam = self.camera
        self.phase.emit("calibrating")
        self.message.emit("Calibrating webcam - hold still for a moment…")
        try:
            if not cam.open():
                self._report("cam", "Webcam not found - check it is connected and not used by another app.")
                return
            st = cam.calibrate_and_lock(settle=2.5, comp=self.exposure_comp)
            st.index = self.s.camera_index  # type: ignore[attr-defined]
            st.resolution = self.s.camera_resolution  # type: ignore[attr-defined]
            self.lock_state = st
            self.lockChanged.emit(st)
            self.message.emit(st.summary())
        finally:
            self.phase.emit("paused" if self._paused else "recording")

    def _grab_camera(self):
        cam = self.camera
        if cam is None:
            return None
        if self._relock:
            self._relock = False
            self._do_lock()
        fresh_open = not cam.is_open
        if fresh_open:
            if not cam.open():
                self._report("cam", "Webcam not found - check it is connected and not used by another app.")
                return None
            cam.read()  # starts the stream on most backends
        if self._want_auto:
            self._want_auto = False
            cam.set_auto()
            cam.warm_up(1.5)
        if self.lock_state and (fresh_open or self._comp_dirty):
            cam.apply_lock(self.lock_state, self.exposure_comp)
            self._comp_dirty = False
        if fresh_open:
            cam.warm_up(0.5 if self.lock_state else 1.5)
        frame = cam.read()
        if frame is None:
            self._report("cam", "Webcam returned no image.")
            cam.close()
        elif not self._keep_camera_open():
            cam.close()
        return frame

    def _grab_screen(self):
        if self.screen is None:
            return None
        try:
            img = self.screen.grab(self.s.monitor)
        except Exception as e:  # noqa: BLE001
            self._report("screen", f"Screen capture failed: {e}")
            return None
        if img is None:
            self._report("screen", "Screen capture returned no image.")
            return None
        return scale_to_height(img, self.s.screen_max_height)

    def _tick(self):
        cam = self._grab_camera() if self.s.use_webcam else None
        scr = self._grab_screen() if self.s.use_screen else None
        if cam is None and scr is None:
            return
        idx = self.frame_count + 1
        name = f"{idx:06d}.jpg"
        q = self.s.jpeg_quality
        try:
            if cam is not None:
                write_jpeg(self.session_dir / "webcam" / name, cam, q)
            if scr is not None:
                write_jpeg(self.session_dir / "screen" / name, scr, q)
            with open(self.session_dir / "frames.csv", "a", encoding="utf-8") as f:
                f.write(
                    f"{idx},{datetime.now().isoformat(timespec='seconds')},"
                    f"{self.active_seconds():.1f},{int(cam is not None)},{int(scr is not None)}\n"
                )
        except OSError as e:
            self._report("disk", f"Could not save frame: {e}", every=10)
            return
        self.frame_count = idx
        if self.want_thumbs:
            self.frameCaptured.emit(idx, thumbnail(cam), thumbnail(scr))
        else:
            self.frameCaptured.emit(idx, None, None)

    # ------------------------------------------------------------- thread
    def run(self):
        try:
            (self.session_dir / "webcam").mkdir(parents=True, exist_ok=True) if self.s.use_webcam else None
            (self.session_dir / "screen").mkdir(parents=True, exist_ok=True) if self.s.use_screen else None
            self.session_dir.mkdir(parents=True, exist_ok=True)
            (self.session_dir / "frames.csv").write_text(
                "index,timestamp,active_seconds,webcam,screen\n", encoding="utf-8"
            )
        except OSError as e:
            self.message.emit(f"Cannot create output folder: {e}")
            self.stopped.emit(str(self.session_dir), 0)
            return

        if self.s.use_webcam:
            self.camera = Camera(self.s.camera_index, self.s.camera_resolution, low_fps=self._keep_camera_open())
            if self.s.lock_camera:
                c = self.lock_cache
                if (
                    c is not None
                    and time.time() - c.when < LOCK_REUSE_SECONDS
                    and getattr(c, "index", None) == self.s.camera_index
                    and getattr(c, "resolution", None) == self.s.camera_resolution
                ):
                    self.lock_state = c
                    self.lockChanged.emit(c)
                else:
                    self._do_lock()
                if not self._keep_camera_open():
                    self.camera.close()
        if self.s.use_screen:
            try:
                self.screen = make_backend(self.s.capture_cursor)
            except Exception as e:  # noqa: BLE001
                self.message.emit(f"Screen capture unavailable: {e}")

        self._write_session_json()
        self.phase.emit("recording")
        self._start_clock()

        last_sched: float | None = None
        try:
            while not self._stop.is_set():
                if self._paused:
                    if self.camera is not None and self.camera.is_open:
                        self.camera.close()  # release the webcam while paused
                    self._wake.wait()
                    self._wake.clear()
                    last_sched = None  # shoot immediately on resume
                    continue
                now = time.monotonic()
                due = now if last_sched is None else last_sched + self.interval
                if due > now:
                    self._wake.wait(due - now)
                    self._wake.clear()
                    if self._relock and not self._paused and not self._stop.is_set():
                        self._grab_camera_relock_only()
                    continue
                self._tick()
                # Stay on the original grid unless we fell behind by a whole interval.
                last_sched = due if time.monotonic() - due < self.interval else time.monotonic()
                if self.frame_count and self.frame_count % 20 == 0:
                    self._write_session_json()
        finally:
            self._stop_clock()
            if self.camera is not None:
                self.camera.close()
            if self.screen is not None:
                self.screen.close()
            self._write_session_json(ended=datetime.now().strftime("%Y-%m-%d_%H-%M-%S"))
            self.stopped.emit(str(self.session_dir), self.frame_count)

    def _grab_camera_relock_only(self):
        if self.camera is None:
            self._relock = False
            return
        self._relock = False
        self._do_lock()
        if not self._keep_camera_open():
            self.camera.close()


class PreviewThread(QThread):
    """Live webcam view for framing your shot. Only runs while idle and visible."""

    frame = Signal(object)
    lockDone = Signal(object)
    failed = Signal(str)

    def __init__(self, settings: Settings, lock_state: LockState | None, parent=None):
        super().__init__(parent)
        self.index = settings.camera_index
        self.resolution = settings.camera_resolution
        self.comp = settings.exposure_comp
        self.lock_state = lock_state
        self._stop = threading.Event()
        self._want_lock = False
        self._want_unlock = False
        self._want_dialog = False
        self._comp_dirty = False

    def stop(self):
        self._stop.set()

    def request_lock(self):
        self._want_lock = True

    def request_unlock(self):
        self._want_unlock = True

    def request_driver_settings(self):
        self._want_dialog = True

    def set_exposure_comp(self, stops: float):
        self.comp = stops
        self._comp_dirty = True

    def run(self):
        cam = Camera(self.index, self.resolution)
        if not cam.open():
            self.failed.emit("Webcam not found - check it is connected and not used by another app.")
            return
        try:
            cam.read()
            if self.lock_state is not None:
                cam.apply_lock(self.lock_state, self.comp)
            while not self._stop.is_set():
                if self._want_lock:
                    self._want_lock = False
                    st = cam.calibrate_and_lock(settle=2.5, comp=self.comp)
                    st.index, st.resolution = self.index, self.resolution  # type: ignore[attr-defined]
                    self.lock_state = st
                    self.lockDone.emit(st)
                if self._want_unlock:
                    self._want_unlock = False
                    cam.set_auto()
                    self.lock_state = None
                if self._want_dialog:
                    self._want_dialog = False
                    cam.show_driver_settings()
                if self._comp_dirty and self.lock_state is not None:
                    self._comp_dirty = False
                    cam.apply_lock(self.lock_state, self.comp)
                f = cam.read()
                if f is None:
                    self.failed.emit("Webcam stopped sending frames.")
                    break
                self.frame.emit(thumbnail(f, 720))
                self._stop.wait(0.1)  # ~10 fps is plenty for framing
        finally:
            cam.close()
