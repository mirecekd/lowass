# tests/test_transcript_window.py
"""Transcript window logic (pure): lines, translation under the last final line, placement left of the hint card."""
from lowass.transcript_logic import TranscriptLines


def test_partial_becomes_final_and_translation_hangs_under_it():
    t = TranscriptLines()
    t.update("Pro", "partial", "Der Ser")
    t.update("Pro", "partial", "Der Server ist")
    t.update("Pro", "final", "Der Server ist weg")
    t.translate("Pro", "Server je pryc")
    assert [(e.text, e.final, e.translation) for e in t.entries] == [("Der Server ist weg", True, "Server je pryc")]


def test_each_speaker_has_its_own_open_line_and_empty_finals_vanish():
    t = TranscriptLines()
    t.update("Ja", "partial", "ahoj")
    t.update("Pro", "partial", "hallo")
    t.update("Pro", "final", "   ")
    assert [e.speaker for e in t.entries] == ["Ja"]


def test_translation_without_a_final_line_is_ignored_and_old_lines_are_dropped():
    t = TranscriptLines(keep=3)
    t.translate("Pro", "nic")
    for i in range(6):
        t.update("Ja", "final", f"veta {i}")
    assert [e.text for e in t.entries] == ["veta 3", "veta 4", "veta 5"]


def test_clear_empties_everything():
    t = TranscriptLines()
    t.update("Ja", "final", "x")
    t.clear()
    assert t.entries == []


def test_a_late_translation_lands_on_its_own_sentence_not_on_the_newest_one():
    """Screenshot bug: the translation arrives about a second late, when the next sentence is already final."""
    t = TranscriptLines()
    for text in ("A: Sie sind passiv", "B: Daher kommen wir zu Level 2", "C: Du kombinierst dein LLM"):
        t.update("Pro", "final", text)
    t.translate("Pro", "preklad B", "B: Daher kommen wir zu Level 2")  # B is translated AFTER C is final
    t.translate("Pro", "preklad A", "A: Sie sind passiv")
    assert [(e.text[0], e.translation) for e in t.entries] == [("A", "preklad A"), ("B", "preklad B"), ("C", "")]


def test_translation_without_a_source_still_goes_to_the_newest_final_line():
    t = TranscriptLines()
    t.update("Pro", "final", "A")
    t.update("Pro", "final", "B")
    t.translate("Pro", "x")  # old two-field message
    assert [e.translation for e in t.entries] == ["", "x"]


def test_the_same_sentence_said_twice_gets_one_translation_each():
    t = TranscriptLines()
    t.update("Pro", "final", "Das heisst")
    t.update("Pro", "final", "Das heisst")
    t.translate("Pro", "To znamena", "Das heisst")
    t.translate("Pro", "To znamena 2", "Das heisst")
    assert [e.translation for e in t.entries] == ["To znamena 2", "To znamena"]


def test_closing_the_transcript_window_with_the_x_turns_translation_off(monkeypatch):
    """Field bug: the X hid the window but the Translate button stayed blue and translation kept running."""
    from lowass import transcript_window

    calls = []
    window = object.__new__(transcript_window.TranscriptWindow)
    window._window, window._on_closed = None, lambda: calls.append("off")
    window._user_close()
    assert calls == ["off"]
    window.close()  # the button path (translate switched off) must NOT call back, or the toggle would loop
    assert calls == ["off"]
