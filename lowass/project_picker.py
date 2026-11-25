# lowass/project_picker.py
"""The 'which project is starting?' dialog: one big button per project. Tk thread only."""
from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from typing import Any

from .ui_parts import BACKGROUND
from .ui_place import main_geometry

TITLE = "Which project is starting?"
FONT = ("Segoe UI", 13)


class ProjectPicker:
    def __init__(self, root: tk.Misc):
        self.root = root
        self._top: Any = None  # the open dialog, None when there is none (never two at once)

    def ask(self, projects: dict[str, str], current: str, on_choice: Callable[[str], None],
            on_cancel: Callable[[], None]) -> None:
        """`projects`: key -> display name. A button calls on_choice(key); Esc or the window X calls on_cancel()."""
        if self._top is not None:
            self._top.lift()
            return
        top = self._top = tk.Toplevel(self.root)
        top.title(TITLE)
        top.configure(bg=BACKGROUND)
        top.attributes("-topmost", True)
        top.resizable(False, False)
        tk.Label(top, text=TITLE, bg=BACKGROUND, fg="#d4d4d4", font=FONT).pack(padx=16, pady=(14, 8))
        for key, name in projects.items():
            mark = key == current
            tk.Button(top, text=f"{name}  (current)" if mark else name, font=(FONT[0], FONT[1], "bold" if mark else "normal"),
                      width=28, pady=8, command=lambda k=key: self._done(lambda: on_choice(k))).pack(padx=16, pady=4)
        tk.Frame(top, height=10, bg=BACKGROUND).pack()
        top.protocol("WM_DELETE_WINDOW", lambda: self._done(on_cancel))
        top.bind("<Escape>", lambda _e: self._done(on_cancel))
        self._centre(top)
        top.wait_visibility()  # grab_set on a window that is not on screen yet raises TclError on Windows
        try:
            top.grab_set()
            top.focus_force()
        except tk.TclError:  # the dialog still works without the grab: only a click elsewhere is then possible
            pass

    def _done(self, action: Callable[[], None]) -> None:
        top, self._top = self._top, None
        if top is not None:
            top.destroy()
            action()

    def _centre(self, top: Any) -> None:
        """On the main window (so on its monitor)."""
        top.update_idletasks()
        m = main_geometry(self.root)
        x = m.x + max(0, (m.w - top.winfo_reqwidth()) // 2)
        y = m.y + max(0, (m.h - top.winfo_reqheight()) // 3)
        top.geometry(f"+{x}+{y}")
