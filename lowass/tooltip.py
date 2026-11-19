# lowass/tooltip.py
"""The classic yellow hover tooltip: the shortcut buttons show their whole prompt (or their own `hint`) above the button."""
from __future__ import annotations

import sys
import tkinter as tk

from .popup import _disable_activation

DELAY_MS = 350
WRAP_PX = 380
BG, FG = "#ffffe1", "#000000"


def tip_position(wx: int, wy: int, ww: int, wh: int, tw: int, th: int, sw: int, sh: int, gap: int = 6) -> tuple[int, int]:
    """Top-left of the tooltip: above the widget, below it when there is no room above; always kept on the screen."""
    x = min(max(0, wx), max(0, sw - tw))
    y = wy - th - gap
    if y < 0:
        y = min(wy + wh + gap, max(0, sh - th))
    return x, y


class Tooltip:
    """Shown after a short delay, hidden on leave or click. A tooltip window never takes the keyboard focus."""

    def __init__(self, widget: tk.Misc, text: str):
        self._widget, self._text = widget, text
        self._job: str | None = None
        self._window: tk.Toplevel | None = None
        for event, handler in (("<Enter>", self._schedule), ("<Leave>", self._hide), ("<ButtonPress>", self._hide)):
            widget.bind(event, handler, add="+")

    def _schedule(self, _event: object = None) -> None:
        self._cancel()
        self._job = self._widget.after(DELAY_MS, self._show)

    def _cancel(self) -> None:
        if self._job is not None:
            self._widget.after_cancel(self._job)
            self._job = None

    def _hide(self, _event: object = None) -> None:
        self._cancel()
        if self._window is not None:
            self._window.destroy()
            self._window = None

    def _show(self) -> None:
        self._job = None
        if self._window is not None:
            return
        w = self._widget
        window = tk.Toplevel(w)
        window.withdraw()
        window.overrideredirect(True)
        window.attributes("-topmost", True)
        tk.Label(window, text=self._text, justify="left", wraplength=WRAP_PX, bg=BG, fg=FG, relief="solid", borderwidth=1,
                 padx=6, pady=4, font=("Segoe UI", 9)).pack()
        window.update_idletasks()
        x, y = tip_position(w.winfo_rootx(), w.winfo_rooty(), w.winfo_width(), w.winfo_height(),
                            window.winfo_reqwidth(), window.winfo_reqheight(), w.winfo_screenwidth(), w.winfo_screenheight())
        window.geometry(f"+{x}+{y}")
        if sys.platform == "win32":
            _disable_activation(window)
        window.deiconify()
        self._window = window


def attach(widget: tk.Misc, text: str) -> None:
    """Give `widget` a tooltip; an empty text means no tooltip."""
    if text.strip():
        Tooltip(widget, text.strip())
