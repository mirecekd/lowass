# tests/test_facts_logic.py
"""Facts window logic: rows, open-once behaviour and placement."""
from lowass.facts_logic import OpenOnce, sheet_rows


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
