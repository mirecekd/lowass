# lowass/ui.py
"""Floating always-on-top chat window (tkinter). Thread-safe: other threads only use post()."""
from __future__ import annotations

import queue
import tkinter as tk
from collections.abc import Callable
from tkinter import scrolledtext, ttk

from . import __version__
from .popup import HintCard
from .popup_logic import Rect
from .ui_parts import BACKGROUND
from .ui_poll import make_handlers
from .ui_widgets import (
    LOG_COLORS,
    CaptionView,
    ShortcutBar,
    StatsPanel,
    append_log,
    private_button,
    translate_button,
)
from .verdict import compile_verdicts


class FloatingWindow:
    def __init__(self, cfg: dict, on_toggle_auto: Callable[[bool], None], auto: bool,
                 models: list[str], model: str, on_model: Callable[[str], None],
                 on_clear: Callable[[], None] = lambda: None,
                 projects: dict[str, str] | None = None, project: str = "",
                 on_project: Callable[[str], None] = lambda _key: None, *,
                 shortcuts: list[dict] | None = None,
                 on_shortcut: Callable[[str, str], None] = lambda _prompt, _label: None,
                 on_private: Callable[[bool], None] = lambda _on: None,
                 on_translate: Callable[[bool], None] = lambda _on: None, translate_on: bool = False,
                 hint_ttl: float = 25.0, on_copy: Callable[[str], None] | None = None):
        self.root = tk.Tk()
        self.q: queue.Queue[tuple[str, str]] = queue.Queue()
        self.on_toggle_auto = on_toggle_auto
        self.on_clear = on_clear
        # set by bind(): the window is built before the code that does the work
        self.on_submit: Callable[[str], None] = lambda _t: None
        self.on_check: Callable[[], None] = lambda: None
        self.on_screen: Callable[[], None] = lambda: None
        self.verdict_pat, self.verdict_colors = compile_verdicts(cfg.get("verdict_red", []), cfg.get("verdict_blue", []))
        font = (cfg["font"], cfg["font_size"])
        r = self.root
        r.title(f"{cfg['title']} - {__version__}")
        r.attributes("-topmost", True)
        r.attributes("-alpha", cfg["alpha"])
        r.configure(bg=BACKGROUND)
        sw = r.winfo_screenwidth()
        x = cfg["x"] if cfg["x"] >= 0 else sw - cfg["width"] + cfg["x"]
        r.geometry(f"{cfg['width']}x{cfg['height']}+{x}+{cfg['y']}")

        bar = tk.Frame(r, bg=BACKGROUND)
        bar.pack(fill="x", padx=6, pady=(6, 0))
        tk.Button(bar, text="Clear", command=self._clear_all, font=font).pack(side="left")
        tk.Button(bar, text="Screen", command=self._screen, font=font).pack(side="left", padx=4)
        self.private = private_button(bar, font, on_private)
        self.translate = translate_button(bar, font, on_translate, translate_on)
        self.auto_var = tk.BooleanVar(value=auto)
        tk.Checkbutton(bar, text="auto", variable=self.auto_var, command=self._toggle, bg=BACKGROUND, fg="#d4d4d4",
                       selectcolor=BACKGROUND, activebackground=BACKGROUND, font=font).pack(side="left")
        self.model_var = tk.StringVar(value=model)
        box = ttk.Combobox(bar, textvariable=self.model_var, values=models, state="readonly", font=font, width=10)
        box.pack(side="left", fill="x", expand=True, padx=(4, 0))
        box.bind("<<ComboboxSelected>>", lambda _e: on_model(self.model_var.get()))

        # project: one dropdown (names shown, keys reported)
        self._project_keys = dict(projects or {})
        self.project_var = tk.StringVar(value=self._project_keys.get(project, project))
        if self._project_keys:
            names = list(self._project_keys.values())
            pbox = ttk.Combobox(r, textvariable=self.project_var, values=names, state="readonly", font=font)
            pbox.pack(fill="x", padx=6, pady=(4, 0))
            pbox.bind("<<ComboboxSelected>>", lambda _e: on_project(self._key_of(self.project_var.get())))

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
        self.card = HintCard(r, self._geometry, on_copy or self._copy, on_inline=lambda t: self._append("auto", t), ttl_sec=hint_ttl)
        r.after(100, self._poll)

    def _geometry(self) -> Rect:
        """Where the main window is on the screen: the hint card is placed next to it."""
        r = self.root
        r.update_idletasks()
        return Rect(r.winfo_x(), r.winfo_y(), r.winfo_width(), r.winfo_height())

    def _copy(self, text: str) -> None:
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.post("status", "suggested answer copied")

    def bind(self, on_submit: Callable[[str], None], on_check: Callable[[], None],
             on_screen: Callable[[], None]) -> None:
        self.on_submit, self.on_check, self.on_screen = on_submit, on_check, on_screen

    def post(self, kind: str, text: str) -> None:
        """kind: you bot auto err status stats heard project raise screen unhide private caption caption_*"""
        self.q.put((kind, text))

    def _screen(self) -> None:
        """Screen button / hotkey: hide the window so it is not in the picture, then let the app grab the screen.
        The app posts 'unhide' when the grab is done (also on failure)."""
        self.root.withdraw()
        self.root.after(300, self.on_screen)

    def _toggle(self) -> None:
        self.on_toggle_auto(self.auto_var.get())

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
