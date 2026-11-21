"""Small OS-specific helpers: process priority, config paths, opening folders."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

IS_WINDOWS = sys.platform.startswith("win")
IS_LINUX = sys.platform.startswith("linux")
IS_MAC = sys.platform == "darwin"


def config_dir() -> Path:
    if IS_WINDOWS:
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        return base / "StudyLapse"
    if IS_MAC:
        return Path.home() / "Library" / "Application Support" / "StudyLapse"
    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "studylapse"


def default_output_dir() -> Path:
    videos = Path.home() / "Videos"
    if IS_LINUX:
        # Respect XDG user dirs if configured (e.g. localised folder names).
        try:
            out = subprocess.run(
                ["xdg-user-dir", "VIDEOS"], capture_output=True, text=True, timeout=2
            ).stdout.strip()
            if out and out != str(Path.home()):
                videos = Path(out)
        except (OSError, subprocess.SubprocessError):
            pass
    return videos / "StudyLapse"


def lower_process_priority() -> None:
    """Make sure we never compete with CAD / heavy apps for CPU or disk.

    Must be called before any worker threads start so they inherit it.
    """
    if IS_WINDOWS:
        try:
            import ctypes
            from ctypes import wintypes

            kernel32 = ctypes.windll.kernel32
            handle = kernel32.GetCurrentProcess()
            BELOW_NORMAL_PRIORITY_CLASS = 0x00004000
            kernel32.SetPriorityClass(handle, BELOW_NORMAL_PRIORITY_CLASS)

            # Windows 11 "Efficiency mode" (EcoQoS): schedule us on efficient cores
            # at low clocks. Perfect for a process that wakes every few seconds.
            class PROCESS_POWER_THROTTLING_STATE(ctypes.Structure):
                _fields_ = [
                    ("Version", wintypes.ULONG),
                    ("ControlMask", wintypes.ULONG),
                    ("StateMask", wintypes.ULONG),
                ]

            ProcessPowerThrottling = 4
            PROCESS_POWER_THROTTLING_EXECUTION_SPEED = 0x1
            state = PROCESS_POWER_THROTTLING_STATE(
                1,
                PROCESS_POWER_THROTTLING_EXECUTION_SPEED,
                PROCESS_POWER_THROTTLING_EXECUTION_SPEED,
            )
            kernel32.SetProcessInformation(
                handle, ProcessPowerThrottling, ctypes.byref(state), ctypes.sizeof(state)
            )
        except Exception:
            pass
    else:
        try:
            os.nice(10)
        except OSError:
            pass
        if IS_LINUX:
            # Idle-class I/O so saving frames never stalls anything else.
            try:
                import ctypes

                libc = ctypes.CDLL(None, use_errno=True)
                SYS_ioprio_set = {"x86_64": 251, "aarch64": 30}.get(os.uname().machine)
                if SYS_ioprio_set:
                    IOPRIO_WHO_PROCESS, IOPRIO_CLASS_IDLE = 1, 3
                    libc.syscall(SYS_ioprio_set, IOPRIO_WHO_PROCESS, 0, IOPRIO_CLASS_IDLE << 13)
            except Exception:
                pass


def open_folder(path: Path) -> None:
    path = Path(path)
    try:
        if IS_WINDOWS:
            os.startfile(str(path))  # type: ignore[attr-defined]
        elif IS_MAC:
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
    except OSError:
        pass


def is_wayland() -> bool:
    return IS_LINUX and (
        os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland"
        or bool(os.environ.get("WAYLAND_DISPLAY"))
    )


def desktop_name() -> str:
    return (
        os.environ.get("XDG_CURRENT_DESKTOP", "") + ":" + os.environ.get("DESKTOP_SESSION", "")
    ).lower()
