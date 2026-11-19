# lowass/popup.py
"""Tk hint card: shown next to the main window, never takes keyboard focus."""

from __future__ import annotations

import sys
import tkinter as tk
from collections.abc import Callable

from lowass.popup_logic import CardQueue, Rect, place_card, slide_positions

BG = "#1e1e1e"
FG = "#e6e6e6"
ACCENT = "#4fc1ff"
BAR_HEIGHT = 3
SLIDE_STEP_MS = 15
PAD = 12

WS_EX_NOACTIVATE = 0x08000000
WS_EX_TOOLWINDOW = 0x00000080
GWL_EXSTYLE = -20


def _disable_activation(window: tk.Toplevel) -> None:
    """Windows only: the card must not take focus from the meeting app."""
    if sys.platform != "win32":
        return
    import ctypes

    window.update_idletasks()
    user32 = ctypes.windll.user32
    hwnd = user32.GetParent(window.winfo_id()) or window.winfo_id()
    style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    user32.SetWindowLongW(
        hwnd, GWL_EXSTYLE, style | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW
    )


class HintCard:
    def __init__(
        self,
        root: tk.Tk,
        main_geometry: Callable[[], Rect],
        on_copy: Callable[[str], None] | None = None,
        width: int = 340,
        on_inline: Callable[[str], None] | None = None,
        ttl_sec: float = 25.0,
    ) -> None:
        self._root = root
        self._main_geometry = main_geometry
        self._on_copy = on_copy
        self._on_inline = on_inline
        self._width = width
        self._queue = CardQueue(ttl_sec)
        self._window: tk.Toplevel | None = None
        self._header: tk.Label | None = None
        self._body: tk.Label | None = None
        self._badge: tk.Label | None = None
        self._bar: tk.Canvas | None = None
        self._bar_rect: int = 0
        self._slide_job: str | None = None

    def show(self, who: str, waited_sec: float, text: str) -> None:
        self._cancel_slide()
        self._queue.show(who, waited_sec, text)
        window = self._ensure_window()
        assert self._header is not None and self._body is not None
        self._header.config(text=f"{who}, waiting {int(waited_sec)} s")
        self._body.config(text=text)
        self._update_badge()
        window.update_idletasks()
        card_h = window.winfo_reqheight()
        x, y, side = place_card(
            self._main_geometry(),
            self._width,
            card_h,
            self._root.winfo_screenwidth(),
            self._root.winfo_screenheight(),
        )
        if side == "inside":
            self._queue.dismiss()
            window.withdraw()
            if self._on_inline is not None:
                self._on_inline(text)
            return
        self._update_bar()
        positions = slide_positions(x, side)
        window.geometry(f"{self._width}x{card_h}+{positions[0]}+{y}")
        window.deiconify()
        window.lift()
        self._slide(positions[1:], y, card_h)

    def hide(self) -> None:
        self._cancel_slide()
        self._queue.dismiss()
        if self._window is not None:
            self._window.withdraw()

    def tick(self) -> None:
        if self._window is None or self._window.state() == "withdrawn":
            return
        if self._queue.current() is None:
            self.hide()
            return
        self._update_bar()

    def _ensure_window(self) -> tk.Toplevel:
        if self._window is not None:
            return self._window
        window = tk.Toplevel(self._root)
        window.withdraw()
        window.overrideredirect(True)
        window.attributes("-topmost", True)
        window.config(bg=BG, highlightthickness=1, highlightbackground=ACCENT)
        wrap = self._width - 2 * PAD
        self._header = tk.Label(
            window, bg=BG, fg=ACCENT, anchor="w", font=("Segoe UI", 9, "bold")
        )
        self._header.pack(fill="x", padx=PAD, pady=(PAD // 2, 0))
        self._body = tk.Label(
            window, bg=BG, fg=FG, anchor="w", justify="left", wraplength=wrap,
            font=("Segoe UI", 10),
        )
        self._body.pack(fill="x", padx=PAD, pady=PAD // 2)
        self._badge = tk.Label(window, bg=BG, fg=ACCENT, anchor="e")
        self._bar = tk.Canvas(
            window, height=BAR_HEIGHT, bg=BG, highlightthickness=0
        )
        self._bar_rect = self._bar.create_rectangle(
            0, 0, 0, BAR_HEIGHT, fill=ACCENT, width=0
        )
        self._bar.pack(side="bottom", fill="x")
        for widget in (window, self._header, self._body, self._badge, self._bar):
            widget.bind("<Button-1>", self._on_click)
        _disable_activation(window)
        self._window = window
        return window

    def _update_badge(self) -> None:
        assert self._badge is not None and self._bar is not None
        extra = self._queue.extra()
        if extra > 0:
            self._badge.config(text=f"+{extra}")
            self._badge.pack(side="bottom", fill="x", padx=PAD, before=self._bar)
        else:
            self._badge.pack_forget()

    def _update_bar(self) -> None:
        if self._bar is None:
            return
        width = self._bar.winfo_width()
        if width <= 1:
            width = self._width
        self._bar.coords(
            self._bar_rect, 0, 0, width * self._queue.remaining(), BAR_HEIGHT
        )

    def _slide(self, remaining: list[int], y: int, card_h: int) -> None:
        if not remaining or self._window is None:
            self._slide_job = None
            return
        self._window.geometry(f"{self._width}x{card_h}+{remaining[0]}+{y}")
        self._slide_job = self._root.after(
            SLIDE_STEP_MS, self._slide, remaining[1:], y, card_h
        )

    def _cancel_slide(self) -> None:
        if self._slide_job is not None:
            self._root.after_cancel(self._slide_job)
            self._slide_job = None

    def copy(self) -> None:
        """The hotkey: copy the text of the visible card (nothing happens when no card is shown)."""
        card = self._queue.current()
        if card is not None and self._on_copy is not None:
            self._on_copy(card.text)
            self.hide()

    def _on_click(self, _event: object) -> None:
        self.copy()
        self.hide()
