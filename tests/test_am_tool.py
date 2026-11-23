# tests/test_am_tool.py
from __future__ import annotations

from typing import cast

from lowass.am_tool import NOTHING, UNREACHABLE, clean_text, make_memory_tool
from lowass.memlink import MemoryClient


def hit(text: object, layer: str = "observation", score: object = 0.5, project: str = "ACME", ts: object = "2026-11-20T10:00:00Z") -> dict:
    return {"layer": layer, "title": "t", "text": text, "project": project, "ts": ts, "score": score}


class FakeClient:
    def __init__(self, by_project=None, default=None, boom=False):
        self.by_project = by_project or {}
        self.default = default
        self.boom = boom
        self.calls: list[tuple[str, str | None, int]] = []

    def search(self, query, project=None, limit=5):
        self.calls.append((query, project, limit))
        if self.boom:
            raise RuntimeError("secret-token exploded")
        return self.by_project.get(project, self.default)


def tool_for(client, names=None, status=None, current="acme"):
    return make_memory_tool(cast(MemoryClient, client), lambda: current, names, status)


def test_default_scope_searches_the_memory_and_the_transcript_project():
    c = FakeClient(default=[])
    tool_for(c)(query="x")
    assert [p for _, p, _ in c.calls] == ["acme", "lowass-acme"]


def test_scope_all_searches_once_without_a_project():
    c = FakeClient(default=[hit("a")])
    out = tool_for(c)(query="x", scope="all")
    assert [p for _, p, _ in c.calls] == [None]
    assert out.startswith("[1] 2026-11-20 | ACME | observation | score 0.50\na")


def test_an_unknown_scope_means_project():
    c = FakeClient(default=[])
    tool_for(c)(query="x", scope="everything")
    assert len(c.calls) == 2 and None not in [p for _, p, _ in c.calls]


def test_the_names_mapping_is_applied():
    c = FakeClient(default=[])
    tool_for(c, names={"acme": "ACME"})(query="x")
    assert [p for _, p, _ in c.calls] == ["ACME", "lowass-ACME"]


def test_empty_results_say_nothing_matched():
    assert tool_for(FakeClient(default=[]))(query="x") == NOTHING


def test_none_from_both_says_unreachable_and_appends_the_status():
    assert tool_for(FakeClient(default=None))(query="x") == UNREACHABLE
    out = tool_for(FakeClient(default=None), status=lambda: "tunnel down")(query="x")
    assert out == UNREACHABLE + " [tunnel down]"
    assert tool_for(FakeClient(default=None), status=lambda: "")(query="x") == UNREACHABLE


def test_a_failing_status_callback_does_not_hide_the_message():
    def bad() -> str:
        raise RuntimeError("no")
    assert tool_for(FakeClient(default=None), status=bad)(query="x") == UNREACHABLE


def test_one_source_down_returns_the_other_with_a_note():
    c = FakeClient(by_project={"acme": [hit("durable", layer="memory")], "lowass-acme": None})
    out = tool_for(c)(query="x")
    assert "durable" in out and "[1]" in out
    assert out.count("could not be reached") == 1 and "meeting transcripts" in out
    c = FakeClient(by_project={"acme": None, "lowass-acme": []})
    out = tool_for(c)(query="x")
    assert out.startswith(NOTHING) and "durable notes" in out


def test_duplicate_texts_are_removed():
    c = FakeClient(by_project={"acme": [hit("same", "memory", 0.9)], "lowass-acme": [hit("same", "observation", 0.8), hit("other", score=0.1)]})
    out = tool_for(c)(query="x")
    assert out.count("same") == 1 and "other" in out


def test_order_is_by_score_and_a_memory_wins_a_tie():
    c = FakeClient(by_project={"acme": [hit("alpha", "memory", 0.5), hit("low", "memory", 0.1)],
                               "lowass-acme": [hit("beta", "observation", 0.5), hit("top", "observation", 0.9)]})
    out = tool_for(c)(query="x")
    order = [out.index(w) for w in ("top", "alpha", "beta", "low")]
    assert order == sorted(order)


def test_text_is_cut_to_600_and_control_characters_are_removed():
    raw = "ab\x00c\x1b[31m\u202e" + "x" * 2000
    out = tool_for(FakeClient(default=[hit(raw)]))(query="x", scope="all")
    body = out.split("\n", 1)[1]
    assert len(body) == 600 and "\x00" not in out and "\x1b" not in out and "\u202e" not in out
    assert clean_text("a\n\n  \n\n\nb\r\n\r\nc") == "a\nb\nc"


def test_limit_is_clamped_and_caps_the_hits():
    c = FakeClient(default=[hit(f"t{i}", score=i / 100) for i in range(30)])
    out = tool_for(c)(query="x", limit=0, scope="all")
    assert c.calls[-1][2] == 1 and out.count("[1]") == 1 and "[2]" not in out
    out = tool_for(c)(query="x", limit=99, scope="all")
    assert c.calls[-1][2] == 10 and "[10]" in out and "[11]" not in out


def test_an_exception_from_the_client_gives_the_unreachable_message_without_the_error_text():
    out = tool_for(FakeClient(boom=True))(query="x")
    assert out == UNREACHABLE and "secret-token" not in out


def test_an_exception_from_the_project_callback_is_swallowed():
    def bad() -> str:
        raise RuntimeError("no project")
    assert make_memory_tool(cast(MemoryClient, FakeClient(default=[])), bad)(query="x") == UNREACHABLE


def test_a_very_long_query_is_cut_before_it_is_sent():
    c = FakeClient(default=[])
    tool_for(c)(query="q" * 100_000)
    assert all(len(q) == 500 for q, _, _ in c.calls)


def test_non_string_text_and_odd_fields_do_not_break_the_output():
    odd = [hit(12345, ts=None, score="high"), hit(None, score=0.2), {"layer": "memory", "text": {"a": 1}, "ts": 1_700_000_000, "score": 1.0}, "junk"]
    out = tool_for(FakeClient(default=odd))(query="x", scope="all")
    assert "12345" in out and "score 0.00" in out and "2023-11-14" in out and "junk" not in out
