# lowass/layout.py
"""Pure window placement inside the work area of ONE monitor: the main window's start rect and the stacked column slots."""
from __future__ import annotations

from .popup_logic import Rect

COLUMN_W = 420  # the transcript window and the facts window: same width, so they stack neatly
GAP = 8


def fit(area: Rect, r: Rect) -> Rect:
    """`r` moved (and shrunk when it is bigger than the area) so that it lies inside `area`."""
    w, h = min(r.w, area.w), min(r.h, area.h)
    return Rect(min(max(r.x, area.x), area.x + area.w - w), min(max(r.y, area.y), area.y + area.h - h), w, h)


def geometry_string(r: Rect) -> str:
    """Tk geometry for `r`. ALWAYS '+x+y': a bare '-N' would mean 'N px from the RIGHT / BOTTOM edge', not a negative
    coordinate, so a window on a monitor left of or above the primary one would land in a completely different place.
    '+-N' is the real negative coordinate."""
    return f"{r.w}x{r.h}+{r.x}+{r.y}"


def moved(wanted: Rect, seen: Rect, tolerance: int = 40) -> bool:
    """True when a window is further from where it was asked to be than borders and shadows can explain."""
    return abs(wanted.x - seen.x) > tolerance or abs(wanted.y - seen.y) > tolerance


def start_rect(area: Rect, width: int, height: int, x: int, y: int) -> Rect:
    """Where the main window starts. A negative x counts from the right edge of the area (so -20 = 20 px from it)."""
    w = min(width, area.w)
    left = area.x + (x if x >= 0 else area.w - w + x)
    return fit(area, Rect(left, area.y + y, w, height))


def column_slots(main: Rect, area: Rect, width: int = COLUMN_W, gap: int = GAP) -> tuple[Rect, Rect]:
    """Two windows ABOVE each other, right NEXT to the main window (its left side), each half of the area's height:
    (top, bottom). The hint card is short-lived and lies over them while it is shown, so no room is kept free for it.
    When there is no room left of the main window they sit at the left edge of the area."""
    w = min(width, area.w)
    x = min(max(main.x - gap - w, area.x), area.x + area.w - w)
    top_h = (area.h - gap) // 2
    return Rect(x, area.y, w, top_h), Rect(x, area.y + top_h + gap, w, area.h - top_h - gap)
