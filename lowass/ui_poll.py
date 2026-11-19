# lowass/ui_poll.py
"""What the floating window does with each message that other threads post() to it (kind -> handler)."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any


def make_handlers(win: Any) -> dict[str, Callable[[str], None]]:
    """Message kind -> action on the window `win` (a FloatingWindow). Any other kind is a line of the answer log."""

    def hint(text: str) -> None:  # 'who<TAB>waited seconds<TAB>text'
        who, _, rest = text.partition("\t")
        waited, _, body = rest.partition("\t")
        win.card.show(who, float(waited) if waited.replace(".", "", 1).isdigit() else 0.0, body)

    def raise_window(_text: str) -> None:
        win.root.deiconify()
        win.root.lift()
        win.entry.focus_force()

    def status(text: str) -> None:
        win.status.configure(text=text[:70])  # configure() returns the options: discarded here

    return {
        "status": status,
        "stats": win.stats.show,
        "private": lambda t: win.private.set(t == "1"),      # from a hotkey: no on_private call
        "translate": lambda t: win.translate.set(t == "1"),  # from the app: no on_translate call
        "caption": win.captions.update,
        "caption_tr": win.captions.translation,
        "caption_clear": lambda _t: win.captions.clear(),
        "hint": hint,
        "hint_clear": lambda _t: win.card.hide(),
        "hint_copy": lambda _t: win.card.copy(),  # the hotkey: copy what the visible card says
        "project": lambda t: win.project_var.set(win._project_keys.get(t, t)),  # a failed switch resets the dropdown
        "screen": lambda _t: win._screen(),
        "unhide": lambda _t: win.root.deiconify(),
        "raise": raise_window,
    }
