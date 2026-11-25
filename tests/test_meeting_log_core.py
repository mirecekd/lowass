# tests/test_meeting_log_core.py
"""Tile parsing and event lines of the Teams meeting log (scripts/meeting_log_core.py), fake names only."""
import pytest

from scripts.meeting_log_core import (
    Tile,
    button_muted,
    diff_states,
    parse_tile,
    read_states,
)
from scripts.ui_probe_tree import Node

CTX = "K dispozici je kontextová nabídka."
OWN_TAIL = "video je zapnuté, Přizpůsobit rámečku, Má místní nabídku"
OWN_MUTED = f"Video o mně, Jan Tester, Má kontrolu nad produkčními nástroji, Ztlumený, {OWN_TAIL}"
OWN_UNMUTED = f"Video o mně, Jan Tester, Má kontrolu nad produkčními nástroji, Ztlumení zrušeno, {OWN_TAIL}"


def node(control_type: str, name: str, automation_id: str = "") -> Node:
    return Node(control_type, name, automation_id, "", (0, 0, 1, 1), "p")


@pytest.mark.parametrize(("name", "expected"), [
    (f"Anna Novak, video je zapnuté, Má kontrolu nad produkčními nástroji, ztlumený mikrofon, {CTX}", Tile("Anna Novak", True)),
    (f"Doe, John (EXTERN: Acme GmbH) Externí neznámé, Má kontrolu nad produkčními nástroji, {CTX}",
     Tile("Doe, John (EXTERN: Acme GmbH)", False)),
    (f"Karl Beispiel Neověřeno, video je zapnuté, Má kontrolu nad produkčními nástroji, {CTX}", Tile("Karl Beispiel", False)),
    (f"Eva Svobodova, video je zapnuté. Má kontrolu nad produkčními nástroji, ztlumený mikrofon, {CTX}",
     Tile("Eva Svobodova", True)),
    (OWN_MUTED, Tile("Jan Tester", True, own=True)),
    (OWN_UNMUTED, Tile("Jan Tester", False, own=True)),
    ("John Smith, muted, context menu available.", Tile("John Smith", True)),
    ("Mary Jones, video on, context menu available.", Tile("Mary Jones", False)),
    ("Video of me, Jan Tester, Unmuted, context menu available.", Tile("Jan Tester", False, own=True)),
    (f"Jana   Nova, ZTLUMENY MIKROFON, {CTX}", Tile("Jana Nova", True)),
    (f"Anna Novak, Znovu se připojuje video, {CTX}", Tile("Anna Novak", False)),
])
def test_parse_tile(name, expected):
    assert parse_tile(name) == expected


@pytest.mark.parametrize("name", ["", "Mute", "Anna Novak", "Zrušit ztlumení mikrofonu", f", ztlumený mikrofon, {CTX}"])
def test_parse_tile_rejects_other_elements(name):
    assert parse_tile(name) is None


def test_parse_tile_custom_markers():
    assert parse_tile(f"Anna Novak | guest, {CTX}", markers=(" |",)) == Tile("Anna Novak", False)


@pytest.mark.parametrize(("name", "muted"), [("Zrušit ztlumení mikrofonu", True), ("Ztlumit mikrofon", False),
                                              ("Unmute microphone", True), ("Mute microphone", False), ("Camera", None)])
def test_button_muted(name, muted):
    assert button_muted(name) is muted


def test_read_states_prefers_microphone_button_for_own_tile():
    own = "Video o mně, Jan Tester, Ztlumení zrušeno, Má místní nabídku"
    nodes = [node("MenuItem", own), node("MenuItem", f"Anna Novak, ztlumený mikrofon, {CTX}"),
             node("Text", f"Eva Svobodova, {CTX}"), node("Button", "Zrušit ztlumení mikrofonu", "microphone-button")]
    assert read_states(nodes) == {"Jan Tester": True, "Anna Novak": True}


def test_read_states_own_tile_without_button_uses_tile_text():
    assert read_states([node("MenuItem", "Video o mně, Jan Tester, Ztlumený, Má místní nabídku")]) == {"Jan Tester": True}


def test_diff_start_lists_everyone():
    events = diff_states({}, {"Anna Novak": True, "Eva Svobodova": False}, 5.0)
    assert events == [{"t": 5.0, "name": "Anna Novak", "muted": True, "present": True},
                      {"t": 5.0, "name": "Eva Svobodova", "muted": False, "present": True}]


def test_diff_mute_flip():
    assert diff_states({"Anna Novak": True}, {"Anna Novak": False}, 6.5) == [
        {"t": 6.5, "name": "Anna Novak", "muted": False, "present": True}]


def test_diff_appear_and_disappear_keep_last_muted():
    events = diff_states({"Anna Novak": True, "Eva Svobodova": False}, {"Eva Svobodova": False, "Karl Beispiel": False}, 7.0)
    assert events == [{"t": 7.0, "name": "Karl Beispiel", "muted": False, "present": True},
                      {"t": 7.0, "name": "Anna Novak", "muted": True, "present": False}]


def test_diff_no_change_no_events():
    state = {"Anna Novak": True, "Eva Svobodova": False}
    assert diff_states(state, dict(state), 8.0) == []
    assert diff_states({}, {}, 8.0) == []
