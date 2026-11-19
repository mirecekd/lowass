# lowass/ui_toolbar.py
"""The two toolbar rows of the floating window. Row 1: Clear, Screen, auto, model. Row 2: Private, Translate, Facts, project."""
from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from dataclasses import dataclass
from tkinter import ttk

from .ui_parts import BACKGROUND
from .ui_widgets import ToggleButton, facts_button, private_button, translate_button

Font = tuple[str, int]


@dataclass
class Toolbar:
    private: ToggleButton
    translate: ToggleButton
    facts: ToggleButton
    auto_var: tk.BooleanVar
    model_var: tk.StringVar
    project_var: tk.StringVar


def build_toolbar(root: tk.Misc, font: Font, *, auto: bool, models: list[str], model: str, projects: dict[str, str],
                  project: str, translate_on: bool, on_clear: Callable[[], None], on_screen: Callable[[], None],
                  on_auto: Callable[[bool], None], on_model: Callable[[str], None], on_private: Callable[[bool], None],
                  on_translate: Callable[[bool], None], on_facts: Callable[[bool], None],
                  on_project: Callable[[str], None]) -> Toolbar:
    """`on_project` gets the chosen project NAME. Without projects the dropdown is not built."""
    first = tk.Frame(root, bg=BACKGROUND)
    first.pack(fill="x", padx=6, pady=(6, 0))
    tk.Button(first, text="Clear", command=on_clear, font=font).pack(side="left")
    tk.Button(first, text="Screen", command=on_screen, font=font).pack(side="left", padx=4)
    auto_var = tk.BooleanVar(value=auto)
    tk.Checkbutton(first, text="auto", variable=auto_var, command=lambda: on_auto(auto_var.get()), bg=BACKGROUND, fg="#d4d4d4",
                   selectcolor=BACKGROUND, activebackground=BACKGROUND, font=font).pack(side="left")
    model_var = tk.StringVar(value=model)
    box = ttk.Combobox(first, textvariable=model_var, values=models, state="readonly", font=font, width=10)
    box.pack(side="left", fill="x", expand=True, padx=(4, 0))
    box.bind("<<ComboboxSelected>>", lambda _e: on_model(model_var.get()))

    second = tk.Frame(root, bg=BACKGROUND)
    second.pack(fill="x", padx=6, pady=(4, 0))
    private = private_button(second, font, on_private)
    translate = translate_button(second, font, on_translate, translate_on)
    facts = facts_button(second, font, on_facts)
    project_var = tk.StringVar(value=projects.get(project, project))
    if projects:
        pbox = ttk.Combobox(second, textvariable=project_var, values=list(projects.values()), state="readonly", font=font)
        pbox.pack(side="left", fill="x", expand=True, padx=(4, 0))
        pbox.bind("<<ComboboxSelected>>", lambda _e: on_project(project_var.get()))
    return Toolbar(private, translate, facts, auto_var, model_var, project_var)
