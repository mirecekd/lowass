# lowass/facts_window.py
"""A small window with the rolling facts sheet. Opens by itself with the first sheet of a meeting; the Facts button toggles it."""
from __future__ import annotations

import sys
import tkinter as tk
from collections.abc import Callable
from tkinter import scrolledtext

from .facts_logic import OpenOnce, sheet_rows
from .layout import geometry_string
from .popup import _disable_activation
from .popup_logic import Rect
from .ui_parts import BACKGROUND, FINAL_COLOR

HEADING_COLOR = "#e7ac80"


class FactsWindow:
    """Never takes the keyboard focus (same as the card). The X only hides it; the Facts button opens it again."""

    def __init__(self, root: tk.Tk, slot: Callable[[], Rect], font: tuple[str, int],
                 on_visible: Callable[[bool], None] = lambda _v: None):
        self._root, self._slot, self._font = root, slot, font
        self._on_visible = on_visible
        self._auto = OpenOnce()
        self._sheet = ""
        self._window: tk.Toplevel | None = None
        self._text: scrolledtext.ScrolledText | None = None

    def is_open(self) -> bool:
        return self._window is not None and self._window.state() != "withdrawn"

    def show_sheet(self, sheet: str) -> None:
        """A new version of the sheet: shown, and the window opens by itself the first time a meeting has one."""
        self._sheet = sheet
        if self._auto.should_open(sheet):
            self.open()
        else:
            self._render()

    def reset(self) -> None:
        """A new meeting (Clear, project switch): empty sheet, closed window, auto-open armed again."""
        self._sheet = ""
        self._auto.rearm()
        self.close()

    def toggle(self) -> None:
        if self.is_open():
            self.close()
        else:
            self.open()

    def open(self) -> None:
        window = self._ensure()
        slot = self._slot()
        window.geometry(geometry_string(slot))
        window.deiconify()
        window.lift()
        self._render()
        self._on_visible(True)

    def close(self) -> None:
        if self._window is not None:
            self._window.withdraw()
        self._on_visible(False)

    def _ensure(self) -> tk.Toplevel:
        if self._window is not None:
            return self._window
        window = tk.Toplevel(self._root)
        window.title("LOWASS - facts")
        window.attributes("-topmost", True)
        window.configure(bg=BACKGROUND)
        window.protocol("WM_DELETE_WINDOW", self.close)
        text = scrolledtext.ScrolledText(window, wrap="word", state="disabled", bg="#252526", fg=FINAL_COLOR, font=self._font,
                                         relief="flat", borderwidth=0, highlightthickness=0)
        text.pack(fill="both", expand=True, padx=4, pady=4)
        text.tag_configure("heading", foreground=HEADING_COLOR, font=(self._font[0], self._font[1], "bold"), spacing1=6)
        text.tag_configure("line", foreground=FINAL_COLOR)
        self._window, self._text = window, text
        if sys.platform == "win32":
            _disable_activation(window)
        return window

    def _render(self) -> None:
        if self._text is None or not self.is_open():
            return
        text = self._text
        text.configure(state="normal")
        text.delete("1.0", "end")
        for tag, line in sheet_rows(self._sheet) or [("line", "(no facts yet)")]:
            text.insert("end", line + "\n", tag)
        text.configure(state="disabled")
