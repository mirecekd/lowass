# lowass/popup_logic.py
"""Pure logic of the hint card: placement, slide animation and card queue."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    w: int
    h: int


@dataclass
class Card:
    who: str
    waited_sec: float
    text: str
    shown_at: float


def place_card(
    main: Rect,
    card_w: int,
    card_h: int,
    area: Rect,
    gap: int = 8,
) -> tuple[int, int, str]:
    """Return (x, y, side); side is 'left', 'below' or 'inside'. Everything is inside `area`: the work area (no taskbar)
    of the monitor the main window is on, so on a second monitor the card stays on that monitor."""
    left_x = main.x - card_w - gap
    if left_x >= area.x:
        max_y = max(area.y, area.y + area.h - card_h)
        return left_x, min(max(main.y, area.y), max_y), "left"
    below_y = main.y + main.h + gap
    fits_horizontally = main.x + card_w <= area.x + area.w
    if fits_horizontally and below_y + card_h <= area.y + area.h:
        return main.x, below_y, "below"
    return main.x, main.y, "inside"


def slide_positions(
    x: int, side: str, distance: int = 24, steps: int = 6
) -> list[int]:
    """X positions of the slide-in; only the 'left' side slides."""
    if side != "left" or steps < 1:
        return [x]
    return [x + distance - round(distance * i / steps) for i in range(steps + 1)]


class CardQueue:
    """One visible card at a time; a newer hint replaces the shown one."""

    def __init__(
        self,
        ttl_sec: float = 25.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._ttl = ttl_sec
        self._clock = clock
        self._card: Card | None = None
        self._extra = 0

    def show(self, who: str, waited_sec: float, text: str) -> None:
        if self.current() is not None:
            self._extra += 1
        else:
            self._extra = 0
        self._card = Card(who, waited_sec, text, self._clock())

    def current(self) -> Card | None:
        card = self._card
        if card is None:
            return None
        if self._clock() - card.shown_at >= self._ttl:
            self._card = None
            self._extra = 0
            return None
        return card

    def remaining(self) -> float:
        card = self.current()
        if card is None or self._ttl <= 0:
            return 0.0
        left = 1.0 - (self._clock() - card.shown_at) / self._ttl
        return min(1.0, max(0.0, left))

    def dismiss(self) -> None:
        self._card = None
        self._extra = 0

    def extra(self) -> int:
        if self.current() is None:
            return 0
        return self._extra
