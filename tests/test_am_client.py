# tests/test_am_client.py
from __future__ import annotations

import logging

import httpx
import pytest

from lowass.am_client import AgentMemoryClient

FAKE_KEY = "fake-" + "key-1234"


class FakeResponse:
    def __init__(self, status: int = 200, body: object = None, bad_json: bool = False):
        self.status_code = status
        self._body = body
        self._bad_json = bad_json

    def json(self) -> object:
        if self._bad_json:
            raise ValueError("not json")
        return self._body


class Fake:

    def __init__(self, answer: FakeResponse | Exception):
        self.answer = answer
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, url: str, **kwargs: object) -> FakeResponse:
        self.calls.append((url, dict(kwargs)))
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


def client(answer: FakeResponse | Exception, base: str = "http://h:3111") -> tuple[AgentMemoryClient, Fake]:
    fake = Fake(answer)
    return AgentMemoryClient(base, FAKE_KEY, post=fake, get=fake), fake


def test_health_true_only_on_200():
    c, fake = client(FakeResponse(200, {}))
    assert c.health() is True
    assert fake.calls[0][0] == "http://h:3111/agentmemory/livez"
    assert client(FakeResponse(503, {}))[0].health() is False




def test_start_session_sends_id_unchanged_with_bearer_header():
    c, fake = client(FakeResponse(200, {"context": "", "session": {}}))
    assert c.start_session("lowass-abc", "proj", "/x") is True
    url, kw = fake.calls[0]
    assert url == "http://h:3111/agentmemory/session/start"
    assert kw["json"] == {"sessionId": "lowass-abc", "project": "proj", "cwd": "/x"}
    assert kw["headers"]["Authorization"] == f"Bearer {FAKE_KEY}"
    assert kw["timeout"] == 10.0




def test_end_session_needs_success_true():
    assert client(FakeResponse(200, {"ended": True, "success": True}))[0].end_session("s") is True
    for answer in (FakeResponse(200, {"success": False}), FakeResponse(200, {}), FakeResponse(200, bad_json=True)):
        assert client(answer)[0].end_session("s") is False


def test_observe_accepted_and_duplicate_are_success():
    payload = {"hookType": "prompt_submit", "sessionId": "s"}
    c, fake = client(FakeResponse(200, {"status": "accepted", "state": "x"}))
    assert c.observe(payload) is True
    assert fake.calls[0][1]["json"] == payload
    assert client(FakeResponse(200, {"status": "duplicate"}))[0].observe(payload) is True


def test_observe_unknown_status_or_bad_body_is_failure():
    for answer in (FakeResponse(200, {"status": "weird"}), FakeResponse(200, bad_json=True), FakeResponse(200, ["x"])):
        assert client(answer)[0].observe({}) is False


def test_observe_400_logs_server_error_text(caplog: pytest.LogCaptureFixture):
    err = "hookType, sessionId, project, cwd, and timestamp are required strings"
    c, _ = client(FakeResponse(400, {"error": err}))
    with caplog.at_level(logging.WARNING):
        assert c.observe({}) is False
    assert any(err in r.getMessage() and r.levelno == logging.WARNING for r in caplog.records)


def test_http_500_is_false_for_every_post():
    c, _ = client(FakeResponse(500, {"error": "boom"}))
    assert c.start_session("s", "p") is False
    assert c.end_session("s") is False
    assert c.observe({}) is False
    assert c.remember({}) is False
    assert c.search("q") is None


@pytest.mark.parametrize("exc", [httpx.ConnectError("refused"), httpx.ReadTimeout("slow"), RuntimeError("odd")])
def test_transport_errors_never_raise(exc: Exception):
    c, _ = client(exc)
    assert c.health() is False
    assert c.start_session("s", "p") is False
    assert c.end_session("s") is False
    assert c.observe({}) is False
    assert c.remember({}) is False
    assert c.search("q") is None


def test_remember_201_and_non_json_body():
    c, fake = client(FakeResponse(201, {"memory": {}}))
    payload = {"content": "fact", "project": "p", "concepts": ["a"]}
    assert c.remember(payload) is True
    assert fake.calls[0][0] == "http://h:3111/agentmemory/remember"
    assert client(FakeResponse(201, bad_json=True))[0].remember(payload) is True
    assert client(FakeResponse(400, {"error": "bad"}))[0].remember(payload) is False


@pytest.mark.parametrize("base", [
    "http://h:3111", "http://h:3111/", "http://h:3111/agentmemory", "http://h:3111/agentmemory/", " http://h:3111 ",
])
def test_url_normalisation(base: str):
    c, fake = client(FakeResponse(200, {"results": []}), base=base)
    c.search("q")
    assert fake.calls[0][0] == "http://h:3111/agentmemory/search"


def full_result() -> dict:
    return {"results": [{
        "layer": "memory", "score": 0.75, "sessionId": "s",
        "observation": {"id": "o1", "title": "T", "narrative": "full text", "timestamp": "2026-01-01T00:00:00Z"},
    }]}


def test_search_maps_full_hits():
    c, fake = client(FakeResponse(200, full_result()))
    hits = c.search("what", project="proj", limit=3)
    assert hits == [{"layer": "memory", "title": "T", "text": "full text", "project": "proj",
                     "ts": "2026-01-01T00:00:00Z", "score": 0.75}]
    assert fake.calls[0][1]["json"] == {"query": "what", "limit": 3, "project": "proj"}


def test_search_without_project_omits_filter_and_reports_empty_project():
    c, fake = client(FakeResponse(200, full_result()))
    hits = c.search("what")
    assert hits is not None and hits[0]["project"] == ""
    assert "project" not in fake.calls[0][1]["json"]


@pytest.mark.parametrize("limit,expected", [(0, 1), (-5, 1), (1, 1), (7, 7), (10, 10), (99, 10)])
def test_search_limit_is_clamped(limit: int, expected: int):
    c, fake = client(FakeResponse(200, {"results": []}))
    c.search("q", limit=limit)
    assert fake.calls[0][1]["json"]["limit"] == expected


def test_search_empty_list_versus_none():
    assert client(FakeResponse(200, {"results": []}))[0].search("q") == []
    assert client(httpx.ConnectError("x"))[0].search("q") is None
    assert client(FakeResponse(500, {}))[0].search("q") is None
    assert client(FakeResponse(200, bad_json=True))[0].search("q") is None


@pytest.mark.parametrize("body", [{}, {"results": None}, {"results": "x"}, {"results": {"a": 1}}, ["x"]])
def test_search_malformed_results_is_none(body: object):
    assert client(FakeResponse(200, body))[0].search("q") is None




def test_search_hit_without_narrative_falls_back_to_title():
    body = {"results": [{"layer": "observation", "score": 1, "observation": {"title": "Only title"}}]}
    hits = client(FakeResponse(200, body))[0].search("q", project="p")
    assert hits is not None
    assert hits[0]["text"] == "Only title" and hits[0]["title"] == "Only title" and hits[0]["ts"] == ""




def test_search_skips_junk_items():
    body = {"results": ["junk", 3, None, {"layer": "memory", "observation": "oops", "score": "high"}]}
    hits = client(FakeResponse(200, body))[0].search("q")
    assert hits == [{"layer": "memory", "title": "", "text": "", "project": "", "ts": "", "score": 0.0}]


def test_secret_never_logged_or_returned(caplog: pytest.LogCaptureFixture):
    leaky = [
        httpx.ConnectError(f"cannot connect with Bearer {FAKE_KEY}"),
        FakeResponse(400, {"error": f"bad token {FAKE_KEY}"}),
        FakeResponse(200, {"status": FAKE_KEY}),
    ]
    with caplog.at_level(logging.DEBUG):
        for answer in leaky:
            c, _ = client(answer)
            results = [c.health(), c.start_session("s", "p"), c.end_session("s"), c.observe({}), c.remember({}), c.search("q")]
            assert FAKE_KEY not in repr(results) and FAKE_KEY not in str(results)
    assert caplog.records
    for record in caplog.records:
        assert FAKE_KEY not in record.getMessage()
        assert FAKE_KEY not in str(record.args) and FAKE_KEY not in str(record.exc_info)

