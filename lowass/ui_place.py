# lowass/ui_place.py
"""Where the windows of LOWASS go: on which monitor the main window starts, and the slots of the side windows."""
from __future__ import annotations

from typing import Any

from .layout import column_slots, start_rect
from .monitors import area_for, list_monitors, pick_monitor, tk_screen
from .popup_logic import Rect


def main_geometry(root: Any) -> Rect:
    """Where the main window is on the (virtual) screen right now."""
    root.update_idletasks()
    return Rect(root.winfo_x(), root.winfo_y(), root.winfo_width(), root.winfo_height())


def work_area(root: Any) -> Rect:
    """The usable area (no taskbar) of the monitor the main window is on. One monitor or many: always a real rectangle."""
    return area_for(main_geometry(root), tk_screen(root))


def start_geometry(root: Any, cfg: dict) -> str:
    """Tk geometry string for the first position: on `[ui].monitor` ('last' = the highest number, 'primary' or a number)."""
    monitors = list_monitors(tk_screen(root))
    area = pick_monitor(monitors, cfg.get("monitor", "last")).work
    r = start_rect(area, int(cfg["width"]), int(cfg["height"]), int(cfg["x"]), int(cfg["y"]))
    return f"{r.w}x{r.h}{r.x:+d}{r.y:+d}"


def side_slots(root: Any) -> tuple[Rect, Rect]:
    """(top, bottom): the transcript and the facts window, one above the other, each half of the monitor's height."""
    return column_slots(main_geometry(root), work_area(root))
