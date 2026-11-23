# lowass/ui_toolbar.py
"""The two toolbar rows of the floating window.
Row 1: Close meeting, Screen, auto, model, language.   Row 2: Private, Translate, Facts, project."""
from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from dataclasses import dataclass
from tkinter import ttk
from typing import Literal

from .languages import DEFAULT
from .tooltip import attach
from .ui_parts import BACKGROUND
from .ui_widgets import ToggleButton, facts_button, private_button, translate_button

Font = tuple[str, int]
MODEL_WIDTH, LANG_WIDTH, PROJECT_WIDTH = 14, 8, 14  # characters; the model and project boxes also grow with the window


@dataclass
class Toolbar:
    private: ToggleButton
    translate: ToggleButton
    facts: ToggleButton
    auto_var: tk.BooleanVar
    model_var: tk.StringVar
    project_var: tk.StringVar
    lang_var: tk.StringVar


def _combo(parent: tk.Misc, var: tk.StringVar, values: list[str], font: Font, width: int,
           on_pick: Callable[[str], None], side: Literal["left", "right"] = "left", grow: bool = False) -> ttk.Combobox:
    box = ttk.Combobox(parent, textvariable=var, values=values, state="readonly", font=font, width=width)
    box.pack(side=side, padx=(4, 0), fill="x" if grow else "none", expand=grow)
    box.bind("<<ComboboxSelected>>", lambda _e: on_pick(var.get()))
    return box


def build_toolbar(root: tk.Misc, font: Font, *, auto: bool, models: list[str], model: str, projects: dict[str, str],
                  project: str, translate_on: bool, languages: list[str], on_clear: Callable[[], None],
                  on_screen: Callable[[], None], on_auto: Callable[[bool], None], on_model: Callable[[str], None],
                  on_private: Callable[[bool], None], on_translate: Callable[[bool], None],
                  on_facts: Callable[[bool], None], on_project: Callable[[str], None],
                  on_language: Callable[[str], None]) -> Toolbar:
    """`on_project` gets the chosen project NAME; `on_language` the chosen code or 'default'. No dropdown is built for an
    empty list (no projects, no languages)."""
    first = tk.Frame(root, bg=BACKGROUND)
    first.pack(fill="x", padx=6, pady=(6, 0))
    close = tk.Button(first, text="Close meeting", command=on_clear, font=font)
    close.pack(side="left")
    attach(close, "Ends this meeting: stops listening (Private), then the summary, the memory and agentmemory finish. "
                  "The status line says when it is done. Press Private to listen again.")
    tk.Button(first, text="Screen", command=on_screen, font=font).pack(side="left", padx=4)
    auto_var = tk.BooleanVar(value=auto)
    tk.Checkbutton(first, text="auto", variable=auto_var, command=lambda: on_auto(auto_var.get()), bg=BACKGROUND, fg="#d4d4d4",
                   selectcolor=BACKGROUND, activebackground=BACKGROUND, font=font).pack(side="left")
    model_var, lang_var = tk.StringVar(value=model), tk.StringVar(value=DEFAULT)
    if languages:  # packed FIRST on the right: it keeps its width, the model box then takes all the room that is left
        _combo(first, lang_var, [DEFAULT, *languages], font, LANG_WIDTH, on_language, side="right")
    _combo(first, model_var, models, font, MODEL_WIDTH, on_model, grow=True)

    second = tk.Frame(root, bg=BACKGROUND)
    second.pack(fill="x", padx=6, pady=(4, 0))
    private = private_button(second, font, on_private)
    translate = translate_button(second, font, on_translate, translate_on)
    facts = facts_button(second, font, on_facts)
    project_var = tk.StringVar(value=projects.get(project, project))
    if projects:
        _combo(second, project_var, list(projects.values()), font, PROJECT_WIDTH, on_project, grow=True)
    return Toolbar(private, translate, facts, auto_var, model_var, project_var, lang_var)
