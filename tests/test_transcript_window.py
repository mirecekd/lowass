# tests/test_transcript_window.py
"""Transcript window logic (pure): lines, translation under the last final line, placement left of the hint card."""
from lowass.popup_logic import Rect
from lowass.transcript_logic import TranscriptLines, place_transcript


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


def test_window_sits_left_of_the_card_which_sits_left_of_the_main_window():
    main = Rect(1440, 60, 460, 760)  # right edge of a 1920 screen
    x, y = place_transcript(main, 340, 420, 520, 1920, 1080)
    assert x == 1440 - 340 - 8 - 420 - 8 and y == 60  # card width + gaps + own width


def test_window_stays_on_screen_when_there_is_no_room():
    x, y = place_transcript(Rect(300, 900, 460, 760), 340, 420, 520, 1920, 1080)
    assert x >= 0 and 0 <= y <= 1080 - 48 - 520
