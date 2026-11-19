# lowass/monitors.py
"""Which monitors exist and which one LOWASS starts on. Pure logic plus ONE Windows-only enumeration (ctypes)."""
from __future__ import annotations

import ctypes
import logging
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .popup_logic import Rect

log = logging.getLogger("lowass.monitors")


@dataclass(frozen=True)
class Monitor:
    number: int  # as Windows names it: \\.\DISPLAY2 is 2; the order of enumeration when the name has no number
    work: Rect  # usable area without the taskbar, in the coordinates Tk uses; x or y can be negative
    primary: bool


def display_number(device: str, fallback: int) -> int:
    match = re.search(r"DISPLAY(\d+)\s*$", device, re.IGNORECASE)
    return int(match.group(1)) if match else fallback


def pick_monitor(monitors: list[Monitor], which: object = "last") -> Monitor:
    """`which`: 'last' (the highest number, default), 'primary', or a number. A number that does not exist, or an
    unknown word, gives the highest one; with a single monitor every choice is that monitor."""
    if not monitors:
        raise ValueError("no monitor")
    by_number = sorted(monitors, key=lambda m: m.number)
    want = str(which).strip().lower()
    if want == "primary":
        return next((m for m in monitors if m.primary), by_number[0])
    if want.isdigit():
        return next((m for m in monitors if m.number == int(want)), by_number[-1])
    return by_number[-1]


def _overlap(a: Rect, b: Rect) -> int:
    w = min(a.x + a.w, b.x + b.w) - max(a.x, b.x)
    h = min(a.y + a.h, b.y + b.h) - max(a.y, b.y)
    return w * h if w > 0 and h > 0 else 0


def monitor_for_rect(monitors: list[Monitor], rect: Rect) -> Monitor:
    """The monitor a window is on: the one with the biggest overlap, else the one whose centre is nearest."""
    best = max(monitors, key=lambda m: _overlap(m.work, rect))
    if _overlap(best.work, rect) > 0:
        return best
    cx, cy = rect.x + rect.w / 2, rect.y + rect.h / 2
    return min(monitors, key=lambda m: (m.work.x + m.work.w / 2 - cx) ** 2 + (m.work.y + m.work.h / 2 - cy) ** 2)


class _Rect32(ctypes.Structure):
    _fields_ = [("left", ctypes.c_int32), ("top", ctypes.c_int32), ("right", ctypes.c_int32), ("bottom", ctypes.c_int32)]


class _Info(ctypes.Structure):
    """MONITORINFOEXW with fixed-size fields, so the layout (104 bytes) is the same on every platform and testable."""

    _fields_ = [("cbSize", ctypes.c_uint32), ("rcMonitor", _Rect32), ("rcWork", _Rect32), ("dwFlags", ctypes.c_uint32),
                ("szDevice", ctypes.c_uint16 * 32)]


def _enum_windows() -> list[Monitor]:
    c: Any = ctypes  # windll and WINFUNCTYPE exist only on Windows
    user32 = c.windll.user32
    user32.GetMonitorInfoW.argtypes = [c.c_void_p, c.POINTER(_Info)]
    user32.GetMonitorInfoW.restype = c.c_int
    proc_type = c.WINFUNCTYPE(c.c_int, c.c_void_p, c.c_void_p, c.c_void_p, c.c_ssize_t)
    user32.EnumDisplayMonitors.argtypes = [c.c_void_p, c.c_void_p, proc_type, c.c_ssize_t]
    user32.EnumDisplayMonitors.restype = c.c_int
    found: list[tuple[Rect, str, bool]] = []

    def callback(hmon: Any, _hdc: Any, _rect: Any, _data: Any) -> int:
        info = _Info()
        info.cbSize = ctypes.sizeof(_Info)
        if user32.GetMonitorInfoW(hmon, ctypes.byref(info)):
            w = info.rcWork
            name = bytes(info.szDevice).decode("utf-16-le", errors="ignore").split("\x00")[0]
            found.append((Rect(w.left, w.top, w.right - w.left, w.bottom - w.top), name, bool(info.dwFlags & 1)))
        return 1

    handler = proc_type(callback)  # kept alive for the whole call
    user32.EnumDisplayMonitors(None, None, handler, 0)
    return [Monitor(display_number(name, i + 1), rect, primary) for i, (rect, name, primary) in enumerate(found)]


def _none() -> list[Monitor]:
    return []


def list_monitors(fallback: Rect, enum: Callable[[], list[Monitor]] | None = None) -> list[Monitor]:
    """Every monitor, and ALWAYS at least one: when the enumeration is not available (other systems), fails or finds
    nothing, the Tk screen is the single monitor. So one monitor, three monitors and a failure all work."""
    enum = enum or (_enum_windows if sys.platform == "win32" else _none)
    try:
        found = enum()
    except Exception:  # an enumeration problem must never stop the app: one monitor is a valid answer
        log.warning("monitor enumeration failed, using the Tk screen", exc_info=True)
        found = []
    return found or [Monitor(1, fallback, True)]


def tk_screen(root: Any) -> Rect:
    return Rect(0, 0, root.winfo_screenwidth(), root.winfo_screenheight())


def area_for(rect: Rect, fallback: Rect) -> Rect:
    """The work area of the monitor that `rect` (a window) is on."""
    return monitor_for_rect(list_monitors(fallback), rect).work
