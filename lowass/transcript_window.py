# lowass/transcript_window.py
"""A second small window with the running transcript and the translations; opened by the Translate button."""
from __future__ import annotations

import sys
import tkinter as tk
from collections.abc import Callable
from tkinter import scrolledtext, ttk

from .languages import DEFAULT, translate_from_choices, translate_to_choices
from .layout import geometry_string
from .popup import _disable_activation
from .popup_logic import Rect
from .transcript_logic import TranscriptLines
from .ui_parts import (
    BACKGROUND,
    FINAL_COLOR,
    PARTIAL_COLOR,
    TRANSLATION_COLOR,
    parse_caption,
    parse_translation,
)


class TranscriptWindow:
    """Never takes the keyboard focus (same trick as the hint card); can be dragged and closed with the Translate button."""

    def __init__(self, root: tk.Tk, slot: Callable[[], Rect], font: tuple[str, int],
                 on_closed: Callable[[], None] = lambda: None, languages: list[str] | None = None,
                 on_rule: Callable[[str, str], None] = lambda _f, _t: None):
        self._root, self._slot, self._font = root, slot, font
        self._on_closed = on_closed  # the user closed the window with the X: the Translate button must go off too
        self._languages, self._on_rule = list(languages or []), on_rule  # FROM / TO dropdowns (none without languages)
        self._from, self._to = tk.StringVar(master=root, value=DEFAULT), tk.StringVar(master=root, value=DEFAULT)
        self._lines = TranscriptLines()
        self._window: tk.Toplevel | None = None
        self._text: scrolledtext.ScrolledText | None = None

    def is_open(self) -> bool:
        return self._window is not None and self._window.state() != "withdrawn"

    def open(self) -> None:
        window = self._ensure()
        slot = self._slot()
        window.geometry(geometry_string(slot))
        window.deiconify()
        window.lift()
        self._render()

    def close(self) -> None:
        if self._window is not None:
            self._window.withdraw()

    def _user_close(self) -> None:
        """The X of the window: hide it AND tell the owner (the Translate button turns off and translation stops)."""
        self.close()
        self._on_closed()

    def caption(self, text: str) -> None:
        speaker, state, line = parse_caption(text)
        if speaker:
            self._lines.update(speaker, state, line)
            self._render()

    def translation(self, text: str) -> None:
        speaker, line, source = parse_translation(text)
        if speaker:
            self._lines.translate(speaker, line, source)
            self._render()

    def clear(self) -> None:
        self._lines.clear()
        self._render()

    def _ensure(self) -> tk.Toplevel:
        if self._window is not None:
            return self._window
        window = tk.Toplevel(self._root)
        window.title("LOWASS - transcript")
        window.attributes("-topmost", True)
        window.configure(bg=BACKGROUND)
        window.protocol("WM_DELETE_WINDOW", self._user_close)  # the X = the Translate button off; the button opens it again
        self._rule_bar(window)
        text = scrolledtext.ScrolledText(window, wrap="word", state="disabled", bg="#252526", fg=FINAL_COLOR,
                                         font=self._font, relief="flat", borderwidth=0, highlightthickness=0)
        text.pack(fill="both", expand=True, padx=4, pady=4)
        for tag, color in (("partial", PARTIAL_COLOR), ("final", FINAL_COLOR), ("translation", TRANSLATION_COLOR)):
            text.tag_configure(tag, foreground=color)
        self._window, self._text = window, text
        if sys.platform == "win32":
            _disable_activation(window)
        return window

    def _rule_bar(self, window: tk.Toplevel) -> None:
        """FROM -> TO: what is translated. 'default' = the configured pair (de-DE to cs-CZ); FROM also offers 'any'."""
        if not self._languages:
            return
        bar = tk.Frame(window, bg=BACKGROUND)
        bar.pack(fill="x", padx=4, pady=(4, 0))
        tk.Label(bar, text="FROM", bg=BACKGROUND, fg=FINAL_COLOR, font=self._font).pack(side="left")
        for var, values in ((self._from, translate_from_choices(self._languages, "x")), (self._to, translate_to_choices(self._languages))):
            box = ttk.Combobox(bar, textvariable=var, values=values, state="readonly", font=self._font, width=9)
            box.pack(side="left", padx=(4, 8))
            box.bind("<<ComboboxSelected>>", lambda _e: self._on_rule(self._from.get(), self._to.get()))
            if var is self._from:
                tk.Label(bar, text="TO", bg=BACKGROUND, fg=FINAL_COLOR, font=self._font).pack(side="left")

    def _render(self) -> None:
        if self._text is None or not self.is_open():
            return
        text = self._text
        at_end = text.yview()[1] >= 0.999  # keep the scroll position when the user scrolled up to read
        text.configure(state="normal")
        text.delete("1.0", "end")
        for entry in self._lines.entries:
            text.insert("end", f"{entry.speaker}: {entry.text}\n", "final" if entry.final else "partial")
            if entry.translation:
                text.insert("end", f"-> {entry.translation}\n", "translation")
        text.configure(state="disabled")
        if at_end:
            text.see("end")
