# tests/test_voices_core.py
import numpy as np

from scripts.voices_core import (
    UNKNOWN,
    Segment,
    cosine,
    fmt_range,
    fmt_time,
    load_profile,
    longest,
    match_voice,
    mean_embedding,
    merge_segments,
    purity,
    save_profile,
    speaker_stats,
)


def test_merge_joins_same_speaker_within_gap():
    segs = [Segment(0, 1, 0), Segment(1.3, 2, 0), Segment(2.1, 3, 1), Segment(3.2, 4, 0)]
    assert merge_segments(segs, 0.5) == [Segment(0, 2, 0), Segment(2.1, 3, 1), Segment(3.2, 4, 0)]


def test_merge_keeps_far_segments_and_sorts():
    assert merge_segments([Segment(5, 6, 0), Segment(0, 1, 0)], 0.5) == [Segment(0, 1, 0), Segment(5, 6, 0)]


def test_stats_and_longest():
    segs = [Segment(0, 4, 0), Segment(5, 6, 0), Segment(7, 10, 0), Segment(11, 12, 0), Segment(13, 14, 1)]
    assert speaker_stats(segs) == {0: (9.0, 4), 1: (1.0, 1)}
    assert longest(segs, 0, 2) == [Segment(0, 4, 0), Segment(7, 10, 0)]


def test_time_format():
    assert fmt_time(75.34) == "01:15.3"
    assert fmt_range(Segment(0, 62.0, 0)) == "00:00.0-01:02.0"


def test_cosine():
    assert cosine(np.array([1.0, 0.0]), np.array([2.0, 0.0])) == 1.0
    assert abs(cosine(np.array([1.0, 0.0]), np.array([0.0, 1.0]))) < 1e-9
    assert cosine(np.zeros(2), np.array([1.0, 0.0])) == 0.0


def test_match_voice_nearest_and_unknown():
    voices = {"Jan": np.array([1.0, 0.0]), "Eva": np.array([0.0, 1.0])}
    assert match_voice(np.array([0.9, 0.1]), voices, 0.5)[0] == "Jan"
    assert match_voice(np.array([0.1, 0.9]), voices, 0.5)[0] == "Eva"
    assert match_voice(np.array([1.0, 1.0]), voices, 0.95)[0] == UNKNOWN
    assert match_voice(np.array([1.0, 0.0]), {}, 0.1)[0] == UNKNOWN


def test_mean_embedding_is_weighted():
    mean = mean_embedding([np.array([10.0, 0.0]), np.array([0.0, 1.0])], [3.0, 1.0])
    assert np.allclose(mean, [0.75, 0.25])


def test_profile_roundtrip(tmp_path):
    path = tmp_path / "p.json"
    assert load_profile(path) == {}
    save_profile(path, {"Jan": np.array([0.5, -0.25], dtype=np.float32)}, "wespeaker")
    assert np.allclose(load_profile(path)["Jan"], [0.5, -0.25])


def test_purity_maps_labels_and_ignores_silence():
    truth = [Segment(0, 2, "a"), Segment(3, 5, "b")]
    assert purity(truth, [Segment(0, 2, 7), Segment(3, 5, 9)]) > 0.99
    assert purity(truth, [Segment(0, 5, 1)]) < 0.6
