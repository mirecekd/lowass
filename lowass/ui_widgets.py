# lowass/ui_widgets.py
"""Small tkinter widgets of the floating window (checked by import, ruff and pyright only: no display here)."""
from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import font as tkfont
from tkinter import ttk
from typing import Any

from .debug import parse_rows
from .ui_parts import (
    BACKGROUND,
    FINAL_COLOR,
    PARTIAL_COLOR,
    PRIVATE_COLOR,
    TRANSLATION_COLOR,
    Captions,
    flow_rows,
    parse_caption,
    parse_translation,
)
from .verdict import color_lines

STATS_COLORS = {"hot": "#b5f2a0", "ok": "#6a9955", "dim": "#7a7a7a", "err": "#f48771"}
LOG_COLORS = {"you": "#9cdcfe", "bot": "#d4d4d4", "auto": "#dcdcaa", "err": "#f48771", "heard": "#808080",
              "red": "#ff5c5c", "blue": "#4fc1ff", "tr": "#4fc1ff"}
LOG_PREFIX = {"you": "> ", "auto": "[auto] ", "err": "[!] ", "heard": "~ ", "tr": "-> "}


def append_log(log: tk.Text, tag: str, text: str, verdict_pat: Any, verdict_colors: dict[str, str]) -> None:
    """Adds one entry to the read-only answer log; answers get their verdict lines coloured (red / blue)."""
    prefix = LOG_PREFIX.get(tag, "")
    lines = color_lines(text, verdict_pat, verdict_colors, tag) if tag in ("bot", "auto") else [(text, tag)]
    log.configure(state="normal")
    for i, (line, line_tag) in enumerate(lines):
        log.insert("end", (prefix if i == 0 else "") + line + "\n", line_tag)
    log.insert("end", "\n") if tag != "tr" else None  # translations follow each other without gaps
    log.configure(state="disabled")
    log.see("end")


class CaptionView:
    """Read-only text area that shows Captions.rows()."""

    def __init__(self, parent: tk.Misc, font: tuple[str, int], lines: int):
        self.captions = Captions(lines)
        self.text = tk.Text(parent, height=lines, wrap="word", state="disabled", bg=BACKGROUND, relief="flat",
                            font=font, borderwidth=0, highlightthickness=0, cursor="arrow")
        for tag, color in (("partial", PARTIAL_COLOR), ("final", FINAL_COLOR), ("translation", TRANSLATION_COLOR)):
            self.text.tag_configure(tag, foreground=color)
        self.text.pack(fill="x", padx=6, pady=(2, 0))

    def show(self) -> None:
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        for tag, line in self.captions.rows():
            self.text.insert("end", line + "\n", tag)
        self.text.configure(state="disabled")

    def update(self, text: str) -> None:
        speaker, state, line = parse_caption(text)
        if speaker:
            self.captions.update(speaker, state, line)
            self.show()

    def translation(self, text: str) -> None:
        speaker, line = parse_translation(text)
        if speaker:
            self.captions.translation(speaker, line)
            self.show()

    def clear(self) -> None:
        self.captions.clear()
        self.show()


class StatsPanel:
    """Debug panel: one coloured row per stage (Ja, Pro, STT, Ag + an error row), packed only while it has text."""

    def __init__(self, parent: tk.Misc, font_size: int, width_px: int):
        self.frame = tk.Frame(parent, bg=BACKGROUND)
        self.frame.pack(fill="x", padx=6)
        self.rows = [tk.Label(self.frame, anchor="w", justify="left", bg=BACKGROUND, wraplength=width_px - 20,
                              font=("Consolas", max(8, font_size - 1))) for _ in range(5)]

    def show(self, text: str) -> None:
        rows = parse_rows(text)[:len(self.rows)]
        for i, label in enumerate(self.rows):
            if i < len(rows):
                level, line = rows[i]
                label.configure(text=line, fg=STATS_COLORS.get(level, "#7a7a7a"))
                if not label.winfo_manager():  # winfo_ismapped is False before the window is shown
                    label.pack(fill="x")
            elif label.winfo_manager():
                label.pack_forget()


class ShortcutBar:
    """Narrow prompt buttons (font one point smaller, padx=2, pady=1) that wrap to new rows with the window width."""

    def __init__(self, parent: tk.Misc, shortcuts: list[dict], font: tuple[str, int],
                 on_shortcut: Callable[[str, str], None]):
        small = (font[0], max(6, font[1] - 1))
        self.frame = tk.Frame(parent, bg=BACKGROUND)
        self.labels = [str(s.get("label", "")) for s in shortcuts]
        prompts = [str(s.get("prompt", "")) for s in shortcuts]
        self.buttons = [tk.Button(self.frame, text=label, font=small, padx=2, pady=1,
                                  command=lambda p=prompt, n=label: on_shortcut(p, n))
                        for label, prompt in zip(self.labels, prompts, strict=True)]
        self.char_px = tkfont.Font(font=small).measure("0")
        self._width = 0
        self.frame.bind("<Configure>", self._layout)
        if shortcuts:
            self.frame.pack(fill="x", padx=6, pady=(0, 4))

    def _layout(self, event: tk.Event) -> None:
        if event.width == self._width:
            return
        self._width = event.width
        for button in self.buttons:
            button.grid_forget()
        for r, row in enumerate(flow_rows(self.labels, event.width, self.char_px)):
            for c, i in enumerate(row):
                self.buttons[i].grid(row=r, column=c, padx=(0, 2), pady=(0, 2), sticky="w")


class ToggleButton:
    """Toolbar toggle: looks like its neighbours when OFF, coloured with white text when ON (Private red, Translate blue)."""

    def __init__(self, parent: tk.Misc, text: str, font: tuple[str, int], color: str,
                 on_change: Callable[[bool], None], on: bool = False):
        self.on = False
        self.color, self.on_change = color, on_change
        self.button = tk.Button(parent, text=text, font=font, command=self._click)
        self.button.pack(side="left", padx=(4, 0))
        keys = ("bg", "fg", "activebackground", "activeforeground")
        self._default = {k: str(self.button.cget(k)) for k in keys}
        if on:
            self.set(True)

    def set(self, on: bool) -> None:
        self.on = on
        lit = {"bg": self.color, "fg": "#ffffff", "activebackground": self.color, "activeforeground": "#ffffff"}
        self.button.configure(**(lit if on else self._default))

    def _click(self) -> None:
        self.set(not self.on)
        self.on_change(self.on)


def private_button(parent: tk.Misc, font: tuple[str, int], on_private: Callable[[bool], None]) -> ToggleButton:
    """Red while on: nothing is captured or sent."""
    return ToggleButton(parent, "Private", font, PRIVATE_COLOR, on_private)


def translate_button(parent: tk.Misc, font: tuple[str, int], on_translate: Callable[[bool], None],
                     on: bool = False) -> ToggleButton:
    """Blue while on: foreign speech is translated, otherwise it is only transcribed."""
    return ToggleButton(parent, "Translate", font, TRANSLATION_COLOR, on_translate, on)


def project_box(parent: tk.Misc, var: tk.StringVar, keys: dict[str, str], font: tuple[str, int],
                on_pick: Callable[[str], None]) -> None:
    """The project dropdown: names are shown, `on_pick` gets the chosen NAME. Nothing is built without projects."""
    if not keys:
        return
    box = ttk.Combobox(parent, textvariable=var, values=list(keys.values()), state="readonly", font=font)
    box.pack(fill="x", padx=6, pady=(4, 0))
    box.bind("<<ComboboxSelected>>", lambda _e: on_pick(var.get()))
