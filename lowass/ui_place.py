# lowass/ui_place.py
"""Where the windows of LOWASS go: on which monitor the main window starts, and the slots of the side windows."""
from __future__ import annotations

import logging
from typing import Any

from .layout import (
    column_slots,
    frame_height,
    full_client_height,
    geometry_string,
    moved,
    start_rect,
)
from .monitors import area_for, list_monitors, pick_monitor, tk_screen
from .popup_logic import Rect

log = logging.getLogger("lowass.place")
CHROME_GUESS = 40  # the title bar plus the borders at 100 % scaling; fit_full_height replaces the guess with the real value
_wanted: dict[int, Rect] = {}  # id of the Tk root -> where the main window was asked to be (for check_placed)
_area: dict[int, Rect] = {}  # id of the Tk root -> the work area of the monitor it was placed on (for fit_full_height)


def main_geometry(root: Any) -> Rect:
    """Where the main window is on the (virtual) screen right now."""
    root.update_idletasks()
    return Rect(root.winfo_x(), root.winfo_y(), root.winfo_width(), root.winfo_height())


def work_area(root: Any) -> Rect:
    """The usable area (no taskbar) of the monitor the main window is on. One monitor or many: always a real rectangle."""
    return area_for(main_geometry(root), tk_screen(root))


def start_geometry(root: Any, cfg: dict) -> str:
    """Tk geometry string for the first position: on `[ui].monitor` ('last' = the highest number, 'primary' or a number).
    Everything that decides the position is written to the log, so a window in the wrong place can be diagnosed."""
    monitors = list_monitors(tk_screen(root))
    chosen = pick_monitor(monitors, cfg.get("monitor", "last"))
    r = start_rect(chosen.work, int(cfg["width"]), cfg["height"], int(cfg["x"]), int(cfg["y"]), chrome=CHROME_GUESS)
    _wanted[id(root)] = r
    _area[id(root)] = chosen.work
    log.info("monitors: %s", "; ".join(f"#{m.number}{'*' if m.primary else ''} {m.work.w}x{m.work.h}{m.work.x:+d}{m.work.y:+d}"
                                       for m in monitors))
    log.info("tk screen %dx%d, tk scaling %.2f; [ui] monitor=%r -> #%d; wanted %s",
             root.winfo_screenwidth(), root.winfo_screenheight(), float(root.tk.call("tk", "scaling")),
             cfg.get("monitor", "last"), chosen.number, geometry_string(r))
    return geometry_string(r)


def fit_full_height(root: Any, cfg: dict) -> None:
    """`height = "full"` only: once the window is shown, measure what Windows really put around the client area (the title
    bar, the borders) and make the OUTER window end exactly at the bottom of the work area. The first guess in
    start_geometry is only good for the first frame, the real frame size depends on the display scaling."""
    area = _area.get(id(root))
    if area is None or str(cfg.get("height")).strip().lower() != "full":
        return
    root.update_idletasks()
    frame = frame_height(root.winfo_rooty() - root.winfo_y(), root.winfo_rootx() - root.winfo_x())
    height = full_client_height(area, frame)
    log.info("full height: frame %d px (title bar %d + border %d), client height %d, work area %d", frame,
             root.winfo_rooty() - root.winfo_y(), root.winfo_rootx() - root.winfo_x(), height, area.h)
    root.geometry(geometry_string(Rect(root.winfo_x(), area.y, root.winfo_width(), height)))


def check_placed(root: Any) -> None:
    """After the window is shown: where did Windows really put it? A big difference is the clue to a scaling problem."""
    wanted = _wanted.get(id(root))
    seen = main_geometry(root)
    if wanted is not None and moved(wanted, seen):
        log.warning("the main window is NOT where it was asked to be: wanted %s, is at %s (a display scaling problem?)",
                    geometry_string(wanted), geometry_string(seen))
    else:
        log.info("the main window is at %s", geometry_string(seen))


def side_slots(root: Any) -> tuple[Rect, Rect]:
    """(top, bottom): the transcript and the facts window, one above the other, each half of the monitor's height."""
    return column_slots(main_geometry(root), work_area(root))
