# lowass/ui_build.py
"""Builds the floating window from the config and the app's actions (keeps app.py small)."""
from __future__ import annotations

from typing import Any

from .ui import FloatingWindow
from .ui_callbacks import Callbacks


def build_window(cfg: Any, app: Any, auto: bool, models: list[str], model: str, projects: dict[str, str],
                 project: str) -> FloatingWindow:
    """`app` provides the actions the window reports to; it needs `controls` and `lang` only when they are CALLED, so the
    window can be built before them."""
    tc, tr = cfg.section("transcribe"), cfg.section("translate")
    cb = Callbacks(
        on_toggle_auto=app._set_auto, on_model=app._set_model, on_clear=app.clear_context, on_project=app.switch_project,
        on_shortcut=lambda p, label: app.controls.on_shortcut(p, label), on_private=lambda on: app.controls.set_private(on),
        on_translate=app._translate, on_language=lambda c: app.lang.set_recognition(c),
        on_rule=lambda f, t: app.lang.set_translation(f, t))
    return FloatingWindow(cfg.section("ui"), cb, auto, models, model, projects, project, languages=list(tc.get("languages", [])),
                          shortcuts=cfg.shortcuts(), hint_ttl=float(cfg.section("hint").get("card_sec", 25)),
                          translate_on=bool(tr.get("on_start", False) and tr.get("enabled", True)),
                          default_rule=(str(tr.get("from_default", "de-DE")), str(tr.get("to_default", "cs-CZ"))))
