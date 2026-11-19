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


def test_headings_with_czech_diacritics_are_recognised_but_ordinary_lines_are_not():
    for heading in ("\u010c\u00cdSLA", "Term\u00edny:", "LID\u00c9", "OTEV\u0158EN\u00c9 BODY", "Otev\u0159en\u00e9 body:", "DOMLUVENO"):
        assert sheet_rows(heading)[0][0] == "heading", heading
    for line in ("- Term\u00edn v deset hodin", "Term\u00edn je v deset hodin dopoledne", "- NUMBERS of items",
                 "OPENING the meeting at nine", "Dates of the meeting are fixed"):
        assert sheet_rows(line)[0][0] == "line", line


def test_the_facts_prompt_pins_the_sheet_to_the_language_of_the_transcript_not_of_the_previous_sheet():
    from lowass.config import ROOT, load

    prompt = load(ROOT, "lowass.toml.sample").section("prompts")["facts"]
    assert "NEW TRANSCRIPT is mostly spoken" in prompt and "PREVIOUS SHEET does not matter" in prompt
    assert "never add an English" in prompt.lower() or "never add an english" in prompt.lower()
