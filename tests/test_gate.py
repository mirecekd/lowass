# tests/test_gate.py
from lowass.gate import Gate, GateEvent

LOUD = 0.5
QUIET = 0.0


def make_gate(**overrides) -> Gate:
    settings = {"threshold": 0.1, "silence_sec": 0.5, "max_sec": 5.0, "min_speech": 0.3, "preroll_sec": 0.3}
    settings.update(overrides)
    return Gate(**settings)


def chunk(label: int) -> bytes:
    return bytes([label]) * 4


def feed_all(gate: Gate, items: list[tuple[int, float]]) -> list[GateEvent]:
    events: list[GateEvent] = []
    for label, rms in items:
        events.extend(gate.feed(chunk(label), rms, 0.1))
    return events


def kinds(events: list[GateEvent]) -> list[str]:
    return [event.kind for event in events]


def test_silence_emits_nothing():
    gate = make_gate()
    assert feed_all(gate, [(i, QUIET) for i in range(20)]) == []


def test_loud_chunk_emits_start_and_audio_with_preroll():
    gate = make_gate()
    feed_all(gate, [(i, QUIET) for i in range(1, 6)])
    events = gate.feed(chunk(9), LOUD, 0.1)
    assert kinds(events) == ["start", "audio"]
    assert events[1].pcm == chunk(3) + chunk(4) + chunk(5) + chunk(9)


def test_trailing_silence_ends_utterance_with_kept():
    gate = make_gate()
    events = feed_all(gate, [(i, LOUD) for i in range(4)] + [(10 + i, QUIET) for i in range(5)])
    assert kinds(events) == ["start"] + ["audio"] * 9 + ["end"]
    assert events[-1].kept is True


def test_short_blip_is_not_kept():
    gate = make_gate()
    events = feed_all(gate, [(1, LOUD)] + [(10 + i, QUIET) for i in range(5)])
    assert events[-1].kind == "end"
    assert events[-1].kept is False


def test_max_sec_cuts_and_next_loud_chunk_starts_new_utterance():
    gate = make_gate(max_sec=1.0)
    events = feed_all(gate, [(i, LOUD) for i in range(10)])
    assert kinds(events) == ["start"] + ["audio"] * 10 + ["end"]
    assert events[-1].kept is True
    again = gate.feed(chunk(99), LOUD, 0.1)
    assert kinds(again) == ["start", "audio"]


def test_flush_closes_running_utterance():
    gate = make_gate()
    feed_all(gate, [(i, LOUD) for i in range(4)])
    events = gate.flush()
    assert len(events) == 1
    assert events[0].kind == "end"
    assert events[0].kept is True
    assert gate.flush() == []


def test_flush_when_idle_returns_nothing():
    assert make_gate().flush() == []


def test_audio_events_concatenate_to_preroll_plus_all_fed_chunks():
    gate = make_gate()
    items = [(1, QUIET), (2, QUIET), (3, QUIET), (4, QUIET)]
    items += [(10, LOUD), (11, LOUD), (12, QUIET), (13, LOUD)] + [(20 + i, QUIET) for i in range(5)]
    events = feed_all(gate, items)
    assert events[0].kind == "start"
    assert events[-1].kind == "end"
    audio = b"".join(event.pcm for event in events if event.kind == "audio")
    expected = b"".join(chunk(label) for label, _ in items[1:])
    assert audio == expected
