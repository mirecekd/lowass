# scripts/meeting_log_core.py
"""Pure logic of scripts/meeting_log.py (no Windows, no pywinauto): reads participant tiles of a Teams meeting from the
names of UI Automation elements and turns two snapshots into JSONL event lines."""
from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from scripts.ui_probe_tree import Node

# Words in a tile name that identify it as a participant tile (folded: lower case, no diacritics).
TILE_HINTS = ("k dispozici je kontextova nabidka", "ma mistni nabidku", "context menu", "video of me")
# Prefix of the own tile.
OWN_PREFIXES = ("Video o mně, ", "Video of me, ")
# The display name ends at the first of these; trust labels sit glued to the name, the rest follows after a comma.
NAME_END_MARKERS = (", video je zapnuté", " Neověřeno", " Externí neznámé", ", Má kontrolu", ", ztlumený mikrofon",
                    ", K dispozici", ", Ztlumení zrušeno", ", Ztlumený", ", Přizpůsobit", ", Má místní", ", muted",
                    ", unmuted", ", video on", ", video off", ", video je vypnuté", ", context menu",
                    ", Znovu se připojuje", ", Reconnecting")
MUTED_TILE = re.compile(r"ztlumeny mikrofon|(?<![a-z])muted")
OWN_MUTED_SEGMENT = "ztlumeny"  # own tile: a whole comma segment ("Ztlumení zrušeno" is the unmuted one)
MIC_BUTTON_ID = "microphone-button"
UNMUTE_WORDS = ("zrusit ztlumeni", "unmute")  # the button offers to unmute: the microphone is muted
MUTE_WORDS = ("ztlumit", "mute")


@dataclass(frozen=True)
class Tile:
    name: str
    muted: bool
    own: bool = False


def fold(text: str) -> str:
    """Lower case without diacritics, character for character (so indexes of the folded text fit the original)."""
    out = []
    for char in text:
        base = unicodedata.normalize("NFD", char)[0].lower()
        out.append(base if len(base) == 1 else char)
    return "".join(out)


def is_tile_name(name: str) -> bool:
    folded = fold(name)
    return any(hint in folded for hint in TILE_HINTS)


def parse_tile(name: str, markers: Sequence[str] = NAME_END_MARKERS) -> Tile | None:
    """Display name and mute state from the name of a tile element; None when it is not a participant tile."""
    if not is_tile_name(name):
        return None
    text = " ".join(name.split())
    folded = fold(text)
    own = False
    for prefix in OWN_PREFIXES:
        if folded.startswith(fold(prefix)):
            text, folded, own = text[len(prefix):], folded[len(prefix):], True
            break
    cuts = [i for i in (folded.find(fold(m)) for m in markers) if i >= 0]
    display = text[:min(cuts)] if cuts else text
    display = display.strip(" ,.")
    if not display:
        return None
    if own:
        muted = OWN_MUTED_SEGMENT in [part.strip(" .") for part in folded.split(",")]
    else:
        muted = MUTED_TILE.search(folded) is not None
    return Tile(display, muted, own)


def button_muted(name: str) -> bool | None:
    """Mute state from the name of the microphone button ('Zrusit ztlumeni mikrofonu' = muted); None if not recognised."""
    folded = fold(name)
    if any(word in folded for word in UNMUTE_WORDS):
        return True
    if any(word in folded for word in MUTE_WORDS):
        return False
    return None


def read_states(nodes: Iterable[Node]) -> dict[str, bool]:
    """Participant name -> muted for all tiles of a snapshot; the own tile takes its state from the microphone button."""
    tiles = [t for n in nodes if n.control_type == "MenuItem" and (t := parse_tile(n.name))]
    button = [muted for n in nodes if n.control_type == "Button" and n.automation_id == MIC_BUTTON_ID
              and (muted := button_muted(n.name)) is not None]
    states = {}
    for tile in tiles:
        states[tile.name] = button[0] if tile.own and button else tile.muted
    return states


def diff_states(prev: dict[str, bool], current: dict[str, bool], now: float) -> list[dict]:
    """Event lines between two snapshots (name -> muted of the participants present). A new participant (all of them at
    the start) is present, a missing one is not present and keeps the last muted value."""
    events = []
    for name, muted in current.items():
        if name not in prev or prev[name] != muted:
            events.append({"t": now, "name": name, "muted": muted, "present": True})
    for name, muted in prev.items():
        if name not in current:
            events.append({"t": now, "name": name, "muted": muted, "present": False})
    return events
