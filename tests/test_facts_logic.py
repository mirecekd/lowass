# tests/test_facts_logic.py
"""Facts window logic: rows, open-once behaviour and placement."""
from lowass.facts_logic import OpenOnce, place_facts, sheet_rows
from lowass.popup_logic import Rect


def test_headings_are_told_from_lines_in_english_and_czech():
    rows = sheet_rows("NUMBERS\n- budget 500\n\nDATES:\n- 15 Dec\nPEOPLE\n- Petr\nNUMBERS are not a heading here and are long")
    assert [t for t, _l in rows] == ["heading", "line", "heading", "line", "heading", "line", "line"]
    assert [t for t, _l in sheet_rows("CISLA\n- 1")] == ["heading", "line"]


def test_empty_sheet_has_no_rows():
    assert sheet_rows("") == [] and sheet_rows("  \n \n") == []


def test_window_opens_by_itself_once_per_meeting_and_not_again_after_the_user_closed_it():
    o = OpenOnce()
    assert not o.should_open("")  # nothing to show yet
    assert o.should_open("NUMBERS\n- 1")
    assert not o.should_open("NUMBERS\n- 1\n- 2")  # the user may have closed it: never forced open again
    o.rearm()  # Clear / project switch / the Facts button
    assert o.should_open("NUMBERS\n- 1")


def test_facts_window_sits_left_of_the_card_or_left_of_the_transcript_window():
    main = Rect(1440, 60, 460, 760)
    x_alone, y = place_facts(main, 340, 420, 380, 520, 1920, 1080, transcript_open=False)
    x_both, _ = place_facts(main, 340, 420, 380, 520, 1920, 1080, transcript_open=True)
    assert x_alone == 1440 - 340 - 8 - 380 - 8 and y == 60
    assert x_both == x_alone - 420 - 8  # one more window to the left


def test_facts_window_stays_on_the_screen_when_there_is_no_room():
    x, y = place_facts(Rect(200, 900, 460, 760), 340, 420, 380, 520, 1920, 1080, transcript_open=True)
    assert x >= 0 and 0 <= y <= 1080 - 48 - 520
