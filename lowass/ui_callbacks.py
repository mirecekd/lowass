# lowass/ui_callbacks.py
"""What the window tells the app. One object instead of a dozen constructor arguments, so a new button is one field."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


def _noop(*_args: object) -> None:
    return None


@dataclass
class Callbacks:
    on_toggle_auto: Callable[[bool], None] = _noop
    on_model: Callable[[str], None] = _noop
    on_clear: Callable[[], None] = _noop
    on_project: Callable[[str], None] = _noop  # gets the project KEY
    on_shortcut: Callable[[str, str], None] = _noop
    on_private: Callable[[bool], None] = _noop
    on_translate: Callable[[bool], None] = _noop
    on_language: Callable[[str], None] = _noop  # the recognition dropdown: 'default' or a language code
    on_rule: Callable[[str, str], None] = _noop  # the transcript window's FROM and TO
    on_copy: Callable[[str], None] | None = None  # None = the window copies to the clipboard itself
