# tests/test_voices_match_core.py
"""Tests for scripts/voices_match_core.py: timeline parsing, weighted evidence, assignment. Invented names only."""
import json

import numpy as np
import pytest

from scripts.voices_core import Segment
from scripts.voices_match_core import assign, evidence_matrix, load_timeline

T0 = 1_000_000.0


def write_timeline(tmp_path, rows):
    path = tmp_path / "meeting.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return path


def solve(segments, intervals, min_confidence=0.5):
    names, speakers, matrix = evidence_matrix(segments, intervals)
    return names, speakers, matrix, assign(matrix, min_confidence)


def named(names, matches):
    return {m.row: (names[m.col] if m.known else "unknown") for m in matches}


def test_load_timeline_turns_state_changes_into_audio_intervals(tmp_path):
    path = write_timeline(tmp_path, [
        {"t": T0 - 5, "event": "start", "app": "x"},
        {"t": T0 - 5, "name": "Anna", "muted": True, "present": True},
        {"t": T0 + 10, "name": "Anna", "muted": False, "present": True},
        {"t": T0 + 20, "name": "Anna", "muted": True, "present": True},
        {"t": T0 + 30, "name": "Boris", "muted": False, "present": True},
        {"t": T0 + 40, "name": "Boris", "muted": False, "present": False},
        {"t": T0 + 50, "name": "Cyril", "muted": False, "present": True},
    ])
    got = load_timeline(path, T0, 60.0)
    assert got == {"Anna": [(10.0, 20.0)], "Boris": [(30.0, 40.0)], "Cyril": [(50.0, 60.0)]}


def test_load_timeline_clips_to_audio_and_keeps_names_that_were_never_unmuted(tmp_path):
    path = write_timeline(tmp_path, [
        {"t": T0 - 100, "name": "Anna", "muted": False, "present": True},
        {"t": T0 + 500, "name": "Anna", "muted": True, "present": True},
        {"t": T0 - 100, "name": "Boris", "muted": True, "present": True},
    ])
    assert load_timeline(path, T0, 60.0) == {"Anna": [(0.0, 60.0)], "Boris": []}


def test_single_unmuted_person_is_unambiguous():
    names, _, matrix, matches = solve([Segment(0, 10, 0)], {"Anna": [(0, 10)]})
    assert matrix.tolist() == [[10.0]]
    assert named(names, matches) == {0: "Anna"}
    assert matches[0].confidence == pytest.approx(1.0)


def test_two_people_alternately_unmuted():
    segments = [Segment(0, 10, "a"), Segment(10, 20, "b"), Segment(20, 30, "a"), Segment(30, 40, "b")]
    intervals = {"Anna": [(0, 10), (20, 30)], "Boris": [(10, 20), (30, 40)]}
    names, speakers, matrix, matches = solve(segments, intervals)
    assert speakers == ["a", "b"]
    assert matrix.tolist() == [[20.0, 0.0], [0.0, 20.0]]
    assert named(names, matches) == {0: "Anna", 1: "Boris"}
    assert all(m.confidence == pytest.approx(1.0) for m in matches)


def test_shared_moment_is_split_by_the_number_of_unmuted_people():
    intervals = {"Anna": [(0, 12)], "Boris": [(0, 6)], "Cyril": [(0, 6)]}
    _, _, matrix = evidence_matrix([Segment(0, 12, 0)], intervals)
    assert matrix[0].tolist() == pytest.approx([6.0 + 2.0, 2.0, 2.0])


def test_person_open_the_whole_time_while_silent_does_not_steal_a_voice():
    # Boris never mutes. While Anna or Cyril speak he is open too, so the evidence ties (10 s each).
    # The one-to-one assignment resolves it: voice b, speaking while only Boris is open, claims Boris for good,
    # which leaves Anna and Cyril to the voices a and c (confidence 0.5: without the claim the tie would remain).
    segments = [Segment(0, 20, "a"), Segment(20, 40, "c"), Segment(40, 60, "b")]
    intervals = {"Anna": [(0, 20)], "Boris": [(0, 60)], "Cyril": [(20, 40)]}
    names, _, matrix, matches = solve(segments, intervals)
    assert matrix.tolist() == [[10.0, 10.0, 0.0], [0.0, 10.0, 10.0], [0.0, 20.0, 0.0]]
    assert named(names, matches) == {0: "Anna", 1: "Cyril", 2: "Boris"}
    assert [m.confidence for m in matches] == pytest.approx([0.5, 0.5, 1.0])


def test_open_mic_person_who_is_never_alone_stays_ambiguous_and_unknown():
    # Boris is open the whole time and nobody speaks while he is alone: nothing tells him from Anna or Cyril.
    segments = [Segment(0, 20, "a"), Segment(20, 40, "c")]
    intervals = {"Anna": [(0, 20)], "Boris": [(0, 40)], "Cyril": [(20, 40)]}
    names, _, matrix, matches = solve(segments, intervals)
    assert matrix.tolist() == [[10.0, 10.0, 0.0], [0.0, 10.0, 10.0]]
    assert [m.confidence for m in matches] == pytest.approx([0.0, 0.0])
    assert set(named(names, matches).values()) == {"unknown"}


def test_voice_without_any_unmuted_person_is_unknown():
    segments = [Segment(0, 10, 0), Segment(20, 30, 1)]
    names, _, matrix, matches = solve(segments, {"Anna": [(0, 10)]})
    assert matrix.tolist() == [[10.0], [0.0]]
    assert named(names, matches) == {0: "Anna", 1: "unknown"}
    assert matches[1].col is None
    assert matches[1].runner_up is None


def test_more_voices_than_names_leaves_a_voice_unassigned():
    segments = [Segment(0, 10, 0), Segment(10, 20, 1), Segment(20, 25, 2)]
    intervals = {"Anna": [(0, 10), (20, 25)], "Boris": [(10, 20)]}
    names, _, _, matches = solve(segments, intervals, min_confidence=0.4)
    assert named(names, matches) == {0: "Anna", 1: "Boris", 2: "unknown"}
    assert matches[2].col is None
    assert matches[2].runner_up == 0


def test_more_names_than_voices_leaves_a_name_unused():
    segments = [Segment(0, 10, 0), Segment(10, 20, 1)]
    intervals = {"Anna": [(0, 10)], "Boris": [(10, 20)], "Cyril": [(0, 5)]}
    names, _, matrix, matches = solve(segments, intervals, min_confidence=0.4)
    assert matrix.tolist() == [[7.5, 0.0, 2.5], [0.0, 10.0, 0.0]]
    assert named(names, matches) == {0: "Anna", 1: "Boris"}
    assert matches[0].runner_up == 2


def test_confidence_below_minimum_is_reported_as_unknown():
    intervals = {"Anna": [(0, 10)], "Boris": [(0, 6)]}
    names, _, matrix, strict = solve([Segment(0, 10, 0)], intervals, min_confidence=0.9)
    assert matrix[0].tolist() == pytest.approx([7.0, 3.0])
    assert strict[0].confidence == pytest.approx(0.4)
    assert (strict[0].col, strict[0].runner_up, strict[0].known) == (0, 1, False)
    assert named(names, strict) == {0: "unknown"}
    assert named(names, solve([Segment(0, 10, 0)], intervals, min_confidence=0.3)[3]) == {0: "Anna"}


def test_confidence_without_competition_is_margin_over_runner_up_per_total_evidence():
    match = assign(np.array([[8.0, 2.0]]), 0.5)[0]
    assert match.confidence == pytest.approx((8.0 - 2.0) / 10.0)
    assert match.evidence == 8.0


def test_competition_for_one_name_lowers_the_confidence_of_both_voices():
    first, second = assign(np.array([[9.0, 1.0], [8.0, 2.0]]), 0.0)
    assert (first.col, second.col) == (0, 1)
    assert first.confidence == pytest.approx((11.0 - 9.0) / 10.0)
    assert second.confidence == pytest.approx((11.0 - 9.0) / 10.0)


def test_empty_matrices_give_no_names():
    assert assign(np.zeros((0, 0)), 0.5) == []
    assert [m.known for m in assign(np.zeros((2, 0)), 0.5)] == [False, False]
