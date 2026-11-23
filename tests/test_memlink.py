# tests/test_memlink.py
"""The agentmemory contract: payloads, project names, exclusions and the bounded outbox."""
import pytest

from lowass import memlink
from lowass.memlink import (
    FACTS,
    SENTENCE,
    SUMMARY,
    TURN,
    Event,
    Outbox,
    allowed,
    iso,
    memory_project,
    observe_payload,
    remember_payload,
    session_id,
    session_project,
)

NAMES = {"acme": "ACME", "gx": "globex-corp"}


def ev(kind=SENTENCE, project="acme", text="rozpocet je petset tisic", seq=1, ts=1_795_000_000.0, **kw):
    return Event(kind, project, "20261123-070000000", text, ts, seq=seq, **kw)


def test_private_and_testing_never_go_out_whatever_the_case():
    for project in ("private", "Private", " TESTING ", "testing"):
        assert not allowed(project)
    for project in ("acme", "general", "privateer", "test"):
        assert allowed(project)  # only the exact names are excluded
    assert not allowed("secret", excluded=("secret",)) and allowed("private", excluded=())


def test_a_summary_goes_to_the_project_of_the_user_and_the_transcript_to_lowass_prefixed_one():
    assert memory_project("acme", NAMES) == "ACME" and session_project("acme", NAMES) == "lowass-ACME"
    assert memory_project("unknown") == "unknown" and session_project("unknown") == "lowass-unknown"  # no mapping: as it is
    assert memory_project("gx", NAMES) == "globex-corp" and session_project("gx", NAMES) == "lowass-globex-corp"


def test_session_ids_cannot_collide_with_other_agents():
    assert session_id("20261123-070000000") == "lowass-20261123-070000000"


def test_an_observation_has_every_required_field_and_a_unique_text_per_sequence_number():
    p = observe_payload(ev(speaker="Protistrana", seq=7), NAMES)
    assert {"hookType", "sessionId", "project", "cwd", "timestamp", "data"} <= set(p)
    assert all(isinstance(p[k], str) and p[k] for k in ("hookType", "sessionId", "project", "cwd", "timestamp"))
    assert p["project"] == "lowass-ACME" and p["sessionId"].startswith("lowass-") and p["timestamp"].endswith("Z")
    assert p["data"]["prompt"].startswith("[#7 ") and "Protistrana: rozpocet je petset tisic" in p["data"]["prompt"]
    again = observe_payload(ev(speaker="Protistrana", seq=8), NAMES)
    assert again["data"]["prompt"] != p["data"]["prompt"]  # the server drops identical text in the same second


def test_a_sentence_without_a_speaker_has_no_empty_label():
    assert ": : " not in observe_payload(ev(speaker=""))["data"]["prompt"]


def test_a_summary_becomes_a_durable_memory_with_concepts_and_the_meeting_id():
    p = remember_payload(ev(SUMMARY, text="Topics: migrace"), NAMES, "Kickoff")
    assert p["project"] == "ACME" and p["content"].startswith("LOWASS meeting summary (20261123-070000000) Kickoff\n")
    assert "lowass-summary" in p["concepts"] and "lowass-meeting-20261123-070000000" in p["concepts"]
    assert remember_payload(ev(FACTS, text="NUMBERS"), NAMES)["concepts"][1] == "lowass-facts"
    assert memlink.is_memory(ev(SUMMARY)) and memlink.is_memory(ev(FACTS)) and not memlink.is_memory(ev(TURN))


def test_the_timestamp_is_utc_and_in_the_format_the_server_accepts():
    assert iso(0) == "1970-01-01T00:00:00Z" and len(iso(1_795_000_000.0)) == 20


def test_the_outbox_keeps_order_and_removes_only_what_was_sent():
    box = Outbox(10)
    a, b, c = ev(seq=1), ev(seq=2), ev(seq=3)
    for e in (a, b, c):
        box.put(e)
    first = box.take(2)
    assert first == [a, b] and len(box) == 3  # taking does not remove: a failed send must not lose them
    box.done(first)
    assert box.take(5) == [c] and len(box) == 1
    box.done([c, c])  # sending the same event twice is harmless
    assert len(box) == 0 and box.take(0) == []


def test_a_full_outbox_drops_the_oldest_sentence_first_and_never_a_summary_before_a_sentence():
    box = Outbox(3)
    summary = ev(SUMMARY, text="S")
    box.put(summary)
    for i in range(1, 6):
        box.put(ev(seq=i))
    kinds = [e.kind for e in box.take(10)]
    assert len(box) == 3 and box.dropped == 3 and SUMMARY in kinds  # three sentences went, the summary stayed
    assert [e.seq for e in box.take(10) if e.kind == SENTENCE] == [4, 5]  # the newest sentences stayed


def test_an_outbox_of_nothing_but_summaries_still_accepts_a_new_one():
    box = Outbox(2)
    for i in range(4):
        box.put(ev(SUMMARY, text=f"S{i}"))
    assert len(box) == 2 and [e.text for e in box.take(5)] == ["S2", "S3"] and box.dropped == 2


def test_private_throws_everything_away_and_a_meeting_end_only_its_own_events():
    box = Outbox(10)
    box.put(ev(seq=1))
    box.put(Event(SENTENCE, "acme", "other", "x", 1.0))
    assert box.clear(session="other") == 1 and len(box) == 1
    assert box.clear() == 1 and len(box) == 0 and box.clear() == 0


def test_a_limit_below_one_is_raised_to_one():
    box = Outbox(0)
    box.put(ev())
    assert box.limit == 1 and len(box) == 1


@pytest.mark.parametrize("kind", memlink.KINDS)
def test_every_kind_is_known(kind):
    assert kind in (SENTENCE, TURN, SUMMARY, FACTS)
