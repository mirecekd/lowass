# tests/test_speaker_names.py
from lowass.speaker_names import SpeakerTimeline, display


def ev(t, name, speaking):
    return {"t": t, "name": name, "speaking": speaking}


def feed_all(tl, *events):
    for e in events:
        tl.feed(e)


def test_longest_lit_wins():
    tl = SpeakerTimeline()
    feed_all(tl, ev(10, "A", True), ev(12, "A", False),
             ev(12, "B", True), ev(15, "B", False))
    assert tl.who(10, 15) == "B"


def test_overlap_of_two_speakers_in_one_sentence():
    tl = SpeakerTimeline()
    feed_all(tl, ev(10, "A", True), ev(14, "A", False),
             ev(13, "B", True), ev(20, "B", False))
    assert tl.who(10, 20) == "B"
    assert tl.who(10, 13) == "A"


def test_open_interval_counts_until_t1():
    tl = SpeakerTimeline()
    feed_all(tl, ev(10, "A", True), ev(11, "A", False), ev(12, "B", True))
    assert tl.who(10, 15) == "B"


def test_interval_began_before_t0():
    tl = SpeakerTimeline()
    feed_all(tl, ev(0, "A", True), ev(10, "A", False),
             ev(8, "B", True), ev(11.5, "B", False))
    # inside [9, 12]: A lit 1.0, B lit 2.5
    assert tl.who(9, 12) == "B"
    assert tl.who(5, 9) == "A"


def test_tie_goes_to_earlier_start():
    tl = SpeakerTimeline()
    feed_all(tl, ev(10, "B", True), ev(12, "B", False),
             ev(10.5, "A", True), ev(12.5, "A", False))
    assert tl.who(10.5, 12) == "B"
    tl2 = SpeakerTimeline()
    feed_all(tl2, ev(10, "A", True), ev(11, "A", False),
             ev(11, "B", True), ev(12, "B", False))
    assert tl2.who(10, 12) == "A"


def test_below_min_overlap_is_none():
    tl = SpeakerTimeline(min_overlap=0.4)
    feed_all(tl, ev(10, "A", True), ev(10.3, "A", False))
    assert tl.who(10, 12) is None


def test_empty_is_none():
    tl = SpeakerTimeline()
    assert tl.who(0, 10) is None
    feed_all(tl, ev(100, "A", True), ev(101, "A", False))
    assert tl.who(0, 10) is None


def test_old_history_is_pruned():
    tl = SpeakerTimeline(history_seconds=100)
    feed_all(tl, ev(0, "A", True), ev(5, "A", False))
    assert tl.who(0, 5) == "A"
    feed_all(tl, ev(500, "B", True), ev(501, "B", False))
    assert tl.who(0, 5) is None
    assert "A" not in tl._intervals
    assert tl.who(500, 501) == "B"


def test_out_of_order_close_is_dropped():
    tl = SpeakerTimeline()
    feed_all(tl, ev(10, "A", True), ev(9, "A", False))
    assert tl.lit_now(12) == "A"
    assert tl.who(10, 12) == "A"


def test_close_without_open_is_ignored():
    tl = SpeakerTimeline()
    tl.feed(ev(10, "A", False))
    assert tl.who(0, 20) is None
    assert tl.lit_now(20) is None


def test_double_open_is_ignored():
    tl = SpeakerTimeline()
    feed_all(tl, ev(10, "A", True), ev(12, "A", True), ev(14, "A", False))
    assert tl.who(10, 14) == "A"
    assert len(tl._intervals["A"]) == 1


def test_lit_now():
    tl = SpeakerTimeline()
    assert tl.lit_now(10) is None
    feed_all(tl, ev(10, "A", True), ev(11, "B", True))
    assert tl.lit_now(12) == "A"
    feed_all(tl, ev(12, "A", False))
    assert tl.lit_now(13) == "B"
    feed_all(tl, ev(13, "B", False))
    assert tl.lit_now(14) is None


def test_display():
    assert display("Speaker 1", "A") == "A"
    assert display("Speaker 1", None) == "Speaker 1"
    assert display("Speaker 1", "") == "Speaker 1"
