# lowass/hotkeys.py
"""Global hotkeys via Win32 RegisterHotKey (own message-loop thread). No-op on other platforms."""
from __future__ import annotations

import logging
import sys
import threading
from collections.abc import Callable

log = logging.getLogger("lowass.hotkeys")

MODS = {"alt": 0x1, "ctrl": 0x2, "shift": 0x4, "win": 0x8}
NOREPEAT = 0x4000
WM_HOTKEY = 0x0312


def parse(spec: str) -> tuple[int, int]:
    """'ctrl+alt+space' -> (modifiers, virtual-key)."""
    parts = [p.strip().lower() for p in spec.split("+") if p.strip()]
    if not parts:
        raise ValueError("empty hotkey")
    mods = 0
    for m in parts[:-1]:
        if m not in MODS:
            raise ValueError(f"unknown modifier '{m}' in '{spec}'")
        mods |= MODS[m]
    key = parts[-1]
    if key == "space":
        vk = 0x20
    elif len(key) == 1 and key.isalnum():
        vk = ord(key.upper())
    elif key.startswith("f") and key[1:].isdigit() and 1 <= int(key[1:]) <= 24:
        vk = 0x70 + int(key[1:]) - 1
    else:
        raise ValueError(f"unsupported key '{key}' in '{spec}'")
    return mods | NOREPEAT, vk


def start(bindings: dict[str, Callable[[], None]]) -> threading.Thread | None:
    """bindings: hotkey spec -> callback. Returns the thread, or None when not on Windows."""
    if sys.platform != "win32":
        log.info("hotkeys disabled (not Windows)")
        return None
    import ctypes
    from ctypes import wintypes

    parsed = {i + 1: (*parse(spec), cb) for i, (spec, cb) in enumerate(bindings.items())}

    def loop() -> None:
        user32 = ctypes.windll.user32  # type: ignore[attr-defined]
        for hid, (mods, vk, _cb) in parsed.items():
            if not user32.RegisterHotKey(None, hid, mods, vk):
                log.error("RegisterHotKey failed for id %s (already taken?)", hid)
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
            if msg.message == WM_HOTKEY and msg.wParam in parsed:
                try:
                    parsed[msg.wParam][2]()
                except Exception:
                    log.exception("hotkey callback failed")

    t = threading.Thread(target=loop, daemon=True, name="hotkeys")
    t.start()
    return t


def app_bindings(cfg: dict, hint_cfg: dict, flow: object, controls: object, post: Callable[[str, str], None]) -> dict[str, Callable[[], None]]:
    """The hotkeys of the app: spec -> action. The copy key (copies the suggested answer on the card) is optional."""
    keys: dict[str, Callable[[], None]] = {
        cfg["check_now"]: flow.check_now,  # type: ignore[attr-defined]
        cfg["show"]: lambda: post("raise", ""),
        cfg["screen"]: lambda: post("screen", ""),
        cfg["private"]: controls.toggle_private,  # type: ignore[attr-defined]
    }
    if hint_cfg.get("copy_hotkey"):
        keys[hint_cfg["copy_hotkey"]] = lambda: post("hint_copy", "")
    return keys
