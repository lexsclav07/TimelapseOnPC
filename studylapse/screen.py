"""Screen capture backends.

* Windows / X11 / macOS: ``mss`` - direct, fast, no files, no flicker.
* Wayland (Fedora, Ubuntu etc.): compositors block direct screen reading, so
  we go through the official route:
    - ``grim`` on wlroots desktops (Sway, Hyprland, ...)
    - the XDG Desktop Portal screenshot API on GNOME / KDE / others
    - ``spectacle`` (KDE) as a last resort
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path
from urllib.parse import unquote, urlparse

import cv2
import numpy as np

from .platform_utils import IS_WINDOWS, desktop_name, is_wayland


def scale_to_height(img: np.ndarray, max_h: int) -> np.ndarray:
    if max_h and img.shape[0] > max_h:
        w = int(round(img.shape[1] * max_h / img.shape[0]))
        img = cv2.resize(img, (w, max_h), interpolation=cv2.INTER_AREA)
    return img


class ScreenBackend:
    name = "base"
    supports_monitor_choice = False

    def grab(self, monitor: int) -> np.ndarray | None:
        raise NotImplementedError

    def close(self) -> None:
        pass


class MssBackend(ScreenBackend):
    name = "Direct capture"
    supports_monitor_choice = True

    def __init__(self, cursor: bool = False):
        import mss

        # mss handles are per-thread on Windows; create lazily in the capture thread.
        self._mss_mod = mss
        self._sct = None
        self.cursor = cursor

    def _sct_obj(self):
        if self._sct is None:
            try:
                self._sct = self._mss_mod.mss(with_cursor=self.cursor)
            except TypeError:
                self._sct = self._mss_mod.mss()
        return self._sct

    def monitors(self) -> list[dict]:
        return list(self._sct_obj().monitors)

    def grab(self, monitor: int) -> np.ndarray | None:
        sct = self._sct_obj()
        mons = sct.monitors
        mon = mons[monitor] if 0 <= monitor < len(mons) else mons[0]
        shot = sct.grab(mon)
        img = np.frombuffer(shot.bgra, dtype=np.uint8).reshape(shot.height, shot.width, 4)
        return cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)

    def close(self) -> None:
        if self._sct is not None:
            try:
                self._sct.close()
            except Exception:
                pass
            self._sct = None


class GrimBackend(ScreenBackend):
    name = "grim (Wayland)"

    def __init__(self, cursor: bool = False):
        self.cursor = cursor
        self.tmp = Path(tempfile.gettempdir()) / f"studylapse-{os.getpid()}.ppm"

    def grab(self, monitor: int) -> np.ndarray | None:
        cmd = ["grim", "-t", "ppm"]
        if self.cursor:
            cmd.append("-c")
        cmd.append(str(self.tmp))
        subprocess.run(cmd, check=True, timeout=10, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        img = cv2.imread(str(self.tmp), cv2.IMREAD_COLOR)
        self.tmp.unlink(missing_ok=True)
        return img


class SpectacleBackend(ScreenBackend):
    name = "Spectacle (KDE)"

    def __init__(self, cursor: bool = False):
        self.cursor = cursor
        self.tmp = Path(tempfile.gettempdir()) / f"studylapse-{os.getpid()}.png"

    def grab(self, monitor: int) -> np.ndarray | None:
        cmd = ["spectacle", "-b", "-n", "-f", "-o", str(self.tmp)]
        if self.cursor:
            cmd.insert(1, "-p")
        subprocess.run(cmd, check=True, timeout=15, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        img = cv2.imread(str(self.tmp), cv2.IMREAD_COLOR)
        self.tmp.unlink(missing_ok=True)
        return img


class PortalBackend(ScreenBackend):
    """org.freedesktop.portal.Screenshot over D-Bus (via jeepney, pure Python)."""

    name = "Desktop portal (Wayland)"

    def __init__(self, cursor: bool = False):
        import importlib.util

        if importlib.util.find_spec("jeepney") is None:
            raise ImportError("jeepney is not installed")

        self._conn = None

    def _connection(self):
        if self._conn is None:
            from jeepney.io.blocking import open_dbus_connection

            self._conn = open_dbus_connection(bus="SESSION")
        return self._conn

    def grab(self, monitor: int) -> np.ndarray | None:
        from jeepney import DBusAddress, MatchRule, new_method_call
        from jeepney.bus_messages import message_bus

        conn = self._connection()
        token = "studylapse" + uuid.uuid4().hex[:12]
        sender = conn.unique_name[1:].replace(".", "_")
        req_path = f"/org/freedesktop/portal/desktop/request/{sender}/{token}"
        rule = MatchRule(
            type="signal",
            interface="org.freedesktop.portal.Request",
            member="Response",
            path=req_path,
        )
        portal = DBusAddress(
            "/org/freedesktop/portal/desktop",
            bus_name="org.freedesktop.portal.Desktop",
            interface="org.freedesktop.portal.Screenshot",
        )
        with conn.filter(rule) as queue:
            conn.send_and_get_reply(message_bus.AddMatch(rule), timeout=5)
            msg = new_method_call(
                portal,
                "Screenshot",
                "sa{sv}",
                ("", {"handle_token": ("s", token), "interactive": ("b", False)}),
            )
            conn.send_and_get_reply(msg, timeout=5)
            # The first call may show a one-time permission prompt, so be patient.
            signal = conn.recv_until_filtered(queue, timeout=120)
        try:
            conn.send_and_get_reply(message_bus.RemoveMatch(rule), timeout=5)
        except Exception:
            pass
        response, results = signal.body
        if response != 0:
            raise RuntimeError("Screenshot permission was denied by the desktop")
        uri = results.get("uri", ("s", ""))[1]
        path = Path(unquote(urlparse(uri).path))
        img = cv2.imread(str(path), cv2.IMREAD_COLOR)
        # The portal writes a file (often into ~/Pictures/Screenshots); don't leave clutter.
        try:
            path.unlink()
        except OSError:
            pass
        return img

    def close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None


def make_backend(cursor: bool = False) -> ScreenBackend:
    if not is_wayland():
        return MssBackend(cursor)
    desk = desktop_name()
    is_gnome_or_kde = any(k in desk for k in ("gnome", "kde", "plasma", "cinnamon", "budgie"))
    if shutil.which("grim") and not is_gnome_or_kde:
        return GrimBackend(cursor)
    try:
        return PortalBackend(cursor)
    except ImportError:
        pass
    if shutil.which("spectacle"):
        return SpectacleBackend(cursor)
    if shutil.which("grim"):
        return GrimBackend(cursor)
    return MssBackend(cursor)  # XWayland only - better than nothing


def list_monitors() -> list[tuple[int, str]]:
    """[(mss index, label)] - index 0 is 'all monitors'."""
    out = [(0, "All monitors")]
    if is_wayland():
        return out
    try:
        import mss

        with mss.mss() as sct:
            for i, m in enumerate(sct.monitors[1:], start=1):
                out.append((i, f"Monitor {i}  ({m['width']}×{m['height']})"))
    except Exception:
        pass
    return out


def backend_name() -> str:
    if not is_wayland():
        return "Direct capture" if not IS_WINDOWS else "Direct capture (DXGI/GDI)"
    try:
        b = make_backend()
        return b.name
    except Exception:
        return "unknown"
