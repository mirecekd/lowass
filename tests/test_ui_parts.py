# tests/test_ui_parts.py
from lowass.ui_parts import Captions, flow_rows, parse_caption, parse_translation


def _width(label: str, char_px: int = 7) -> int:
    return len(label) * char_px + 2 * 2 + 2 * 2 + 2


def test_flow_rows_empty():
    assert flow_rows([], 300, 7) == []


def test_flow_rows_one_row():
    assert flow_rows(["Sum", "Ask", "Go"], 400, 7) == [[0, 1, 2]]


def test_flow_rows_wraps_when_a_row_would_exceed_the_width():
    labels = ["abcd", "abcd", "abcd"]
    width = _width("abcd") * 2  # exactly two fit
    assert flow_rows(labels, width, 7) == [[0, 1], [2]]
    assert flow_rows(labels, width - 1, 7) == [[0], [1], [2]]


def test_flow_rows_label_wider_than_window_gets_own_row():
    assert flow_rows(["ab", "a very long label", "cd"], 60, 7) == [[0], [1], [2]]


def test_flow_rows_uses_pad():
    assert flow_rows(["a", "a"], 2 * _width("a", 7) - 1, 7, pad_px=2) == [[0], [1]]
    assert flow_rows(["a", "a"], 2 * _width("a", 7) - 1, 7, pad_px=0) == [[0, 1]]


def test_parse_caption_splits_and_keeps_tabs_in_text():
    assert parse_caption("Bob\tfinal\thello\tworld") == ("Bob", "final", "hello\tworld")
    assert parse_caption("Bob\tpartial\t") == ("Bob", "partial", "")


def test_parse_caption_malformed_returns_empty():
    for bad in ("", "Bob", "Bob\tfinal", "Bob\tmaybe\ttext", "\tfinal\ttext"):
        assert parse_caption(bad) == ("", "", "")


def test_parse_translation():
    assert parse_translation("Bob\tahoj\tsvete") == ("Bob", "ahoj", "svete")  # the third field is the source sentence
    assert parse_translation("Bob\tahoj") == ("Bob", "ahoj", "")  # the old two-field form still works
    for bad in ("", "Bob", "\ttext"):
        assert parse_translation(bad) == ("", "", "")


def test_partial_replaces_partial():
    c = Captions()
    c.update("Bob", "partial", "he")
    c.update("Bob", "partial", "hello")
    assert c.rows() == [("partial", "Bob: hello")]


def test_final_closes_the_line():
    c = Captions()
    c.update("Bob", "partial", "hello")
    c.update("Bob", "final", "hello there")
    c.update("Bob", "partial", "next")
    assert c.rows() == [("final", "Bob: hello there"), ("partial", "Bob: next")]


def test_two_speakers_interleave():
    c = Captions()
    c.update("Bob", "partial", "one")
    c.update("Ann", "partial", "two")
    c.update("Bob", "partial", "one more")
    c.update("Ann", "final", "two done")
    assert c.rows() == [("partial", "Bob: one more"), ("final", "Ann: two done")]


def test_translation_attaches_to_the_last_final_line_of_that_speaker():
    c = Captions(max_lines=10)
    c.update("Bob", "final", "first")
    c.update("Ann", "final", "other")
    c.update("Bob", "final", "second")
    c.translation("Bob", "druhy")
    assert c.rows() == [("final", "Bob: first"), ("final", "Ann: other"), ("final", "Bob: second"),
                        ("translation", "-> druhy")]


def test_translation_without_final_line_is_ignored():
    c = Captions()
    c.update("Bob", "partial", "hello")
    c.translation("Bob", "ahoj")
    assert c.rows() == [("partial", "Bob: hello")]


def test_rows_limited_to_max_lines_and_translation_counts():
    c = Captions(max_lines=3)
    for n in range(4):
        c.update("Bob", "final", f"line {n}")
    c.translation("Bob", "radek 3")
    assert c.rows() == [("final", "Bob: line 2"), ("final", "Bob: line 3"), ("translation", "-> radek 3")]


def test_clear():
    c = Captions()
    c.update("Bob", "final", "hello")
    c.update("Ann", "partial", "hi")
    c.clear()
    assert c.rows() == []
    c.translation("Bob", "ahoj")
    assert c.rows() == []
