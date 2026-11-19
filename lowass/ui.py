# lowass/ui.py
"""Floating always-on-top chat window (tkinter). Thread-safe: other threads only use post()."""
from __future__ import annotations

import queue
import tkinter as tk
from collections.abc import Callable
from tkinter import scrolledtext

from . import __version__
from .facts_window import FactsWindow
from .popup import HintCard
from .popup_logic import Rect
from .transcript_window import TranscriptWindow
from .ui_callbacks import Callbacks
from .ui_parts import BACKGROUND
from .ui_place import check_placed, main_geometry, side_slots, start_geometry, work_area
from .ui_poll import make_handlers
from .ui_toolbar import build_toolbar
from .ui_widgets import (
    LOG_COLORS,
    CaptionView,
    ShortcutBar,
    StatsPanel,
    append_log,
)
from .verdict import compile_verdicts


class FloatingWindow:
    def __init__(self, cfg: dict, cb: Callbacks, auto: bool, models: list[str], model: str,
                 projects: dict[str, str] | None = None, project: str = "", *, languages: list[str] | None = None,
                 shortcuts: list[dict] | None = None, translate_on: bool = False, hint_ttl: float = 25.0,
                 default_rule: tuple[str, str] = ("de-DE", "cs-CZ")):
        self.root = tk.Tk()
        self.q: queue.Queue[tuple[str, str]] = queue.Queue()
        self.cb = cb
        self.on_clear = cb.on_clear
        on_toggle_auto, on_model, on_project, on_shortcut, on_private = (
            cb.on_toggle_auto, cb.on_model, cb.on_project, cb.on_shortcut, cb.on_private)
        on_translate, on_copy = cb.on_translate, cb.on_copy
        # set by bind(): the window is built before the code that does the work
        self.on_submit: Callable[[str], None] = lambda _t: None
        self.on_check: Callable[[], None] = lambda: None
        self.on_screen: Callable[[], None] = lambda: None
        self.verdict_pat, self.verdict_colors = compile_verdicts(
            cfg.get("verdict_red", []), cfg.get("verdict_blue", []), cfg.get("verdict_green", []),
            cfg.get("verdict_info", []), cfg.get("verdict_opinion", []))
        font = (cfg["font"], cfg["font_size"])
        r = self.root
        r.title(f"{cfg['title']} - {__version__}")
        r.attributes("-topmost", True)
        r.attributes("-alpha", cfg["alpha"])
        r.configure(bg=BACKGROUND)
        r.geometry(start_geometry(r, cfg))  # on [ui].monitor: by default the monitor with the highest number
        r.after(600, lambda: check_placed(r))  # logs where Windows REALLY put it (a scaling problem shows up)

        tb = build_toolbar(
            r, font, auto=auto, models=models, model=model, projects=dict(projects or {}), project=project,
            translate_on=translate_on, languages=list(languages or []), on_clear=self._clear_all, on_screen=self._screen,
            on_auto=on_toggle_auto, on_model=on_model, on_private=on_private, on_translate=self._translate_toggled,
            on_facts=self._facts_toggled, on_project=lambda name: on_project(self._key_of(name)),
            on_language=cb.on_language)
        self.private, self.translate, self.facts_btn = tb.private, tb.translate, tb.facts
        self.auto_var, self.model_var, self.project_var = tb.auto_var, tb.model_var, tb.project_var
        self._project_keys = dict(projects or {})

        self.status = tk.Label(r, text="starting...", anchor="w", bg=BACKGROUND, fg="#8a8a8a", font=font)
        self.status.pack(fill="x", padx=6, pady=(4, 0))

        # live captions (read-only), then the debug panel
        self.captions = CaptionView(r, font, cfg.get("caption_lines", 4))
        self.stats = StatsPanel(r, cfg["font_size"], cfg["width"])

        self.log = scrolledtext.ScrolledText(r, wrap="word", state="disabled", bg="#252526", fg="#d4d4d4",
                                             insertbackground="#d4d4d4", font=font, relief="flat")
        self.log.pack(fill="both", expand=True, padx=6, pady=6)
        for tag, color in LOG_COLORS.items():
            self.log.tag_configure(tag, foreground=color)

        ShortcutBar(r, shortcuts or [], font, on_shortcut)
        self.entry = tk.Entry(r, bg="#3c3c3c", fg="#ffffff", insertbackground="#ffffff", font=font, relief="flat")
        self.entry.pack(fill="x", padx=6, pady=(0, 6), ipady=4)
        self.entry.bind("<Return>", self._submit)
        self.card = HintCard(r, self._geometry, on_copy or self._copy, ttl_sec=hint_ttl,
                             on_inline=lambda t: self._append("auto", t), area=self._area)
        self._on_translate = on_translate
        self.transcript = TranscriptWindow(r, lambda: side_slots(r)[0], font, self._transcript_closed,
                                           list(languages or []), cb.on_rule)
        self.facts = FactsWindow(r, lambda: side_slots(r)[1], font, self.facts_btn.set)
        if translate_on:
            self.show_transcript(True)
        r.after(100, self._poll)

    def _facts_toggled(self, on: bool) -> None:
        if on:
            self.facts.open()
        else:
            self.facts.close()

    def _transcript_closed(self) -> None:
        """The user closed the transcript window with the X: the button goes off and translation stops."""
        self.translate.set(False)
        self._on_translate(False)

    def _translate_toggled(self, on: bool) -> None:
        self.show_transcript(on)
        self._on_translate(on)

    def show_transcript(self, on: bool) -> None:
        """Translate on = the transcript window opens (left of the hint card); off = it closes."""
        if on:
            self.transcript.open()
        else:
            self.transcript.close()

    def _geometry(self) -> Rect:
        """Where the main window is."""
        return main_geometry(self.root)

    def _area(self) -> Rect:
        """The work area of the monitor the main window is on (the card must stay on that monitor)."""
        return work_area(self.root)

    def _copy(self, text: str) -> None:
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.post("status", "suggested answer copied")

    def bind(self, on_submit: Callable[[str], None], on_check: Callable[[], None],
             on_screen: Callable[[], None]) -> None:
        self.on_submit, self.on_check, self.on_screen = on_submit, on_check, on_screen

    def post(self, kind: str, text: str) -> None:
        """kind: you bot auto err status stats heard project raise screen unhide private caption* hint*"""
        self.q.put((kind, text))

    def _screen(self) -> None:
        """The Screen button: hide the window, then the app grabs the screen and posts 'unhide'."""
        self.root.withdraw()
        self.root.after(300, self.on_screen)

    def _submit(self, _event=None) -> None:
        text = self.entry.get().strip()
        if text:
            self.entry.delete(0, "end")
            self.on_submit(text)

    def _clear_all(self) -> None:
        """Clear button: wipe the window AND the LLM context."""
        self.clear()
        self.on_clear()

    def clear(self) -> None:
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

    def _key_of(self, name: str) -> str:
        return next((k for k, v in self._project_keys.items() if v == name), name)

    def _append(self, tag: str, text: str) -> None:
        append_log(self.log, tag, text, self.verdict_pat, self.verdict_colors)

    def _poll(self) -> None:
        handlers = make_handlers(self)
        try:
            while True:
                kind, text = self.q.get_nowait()
                handler = handlers.get(kind)
                if handler is not None:
                    handler(text)
                else:
                    self._append(kind, text)
        except queue.Empty:
            pass
        self.card.tick()
        self.root.after(100, self._poll)

    def run(self) -> None:
        self.root.mainloop()
