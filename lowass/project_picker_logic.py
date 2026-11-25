# lowass/project_picker_logic.py
"""When the 'which project is starting?' dialog is shown (pure, no tkinter)."""
from __future__ import annotations


def should_ask(enabled: bool, project_count: int, meeting_empty: bool) -> bool:
    """Ask only for a NEW meeting (nothing heard or stored in it yet), only when there is something to choose from and
    only when `[ui].ask_project` allows it. A pause and resume in the middle of a meeting never asks."""
    return enabled and project_count > 1 and meeting_empty
