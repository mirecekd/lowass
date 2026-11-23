# tests/test_am_service.py
"""The agentmemory link wired together: config -> MemoryLink, Meeting -> Sink -> MemorySync, Private, project exclusion."""
from pathlib import Path
from types import SimpleNamespace

from lowass import memlink
from lowass.am_service import AM_ENV_VAR, MemoryLink
from lowass.am_sync import MemorySync
from lowass.meeting import Meeting
from lowass.meeting_sink import Sink


class FakeClient:
    def __init__(self):
        self.calls = []

    def health(self):
        return True

    def start_session(self, session, project, cwd="/lowass"):
        self.calls.append(("start", session, project))
        return True

    def end_session(self, session):
        self.calls.append(("end", session))
        return True

    def observe(self, payload):
        self.calls.append(("observe", payload["project"], payload["data"]["prompt"]))
        return True

    def remember(self, payload):
        self.calls.append(("remember", payload["project"], payload["content"][:40]))
        return True

    def search(self, query, project=None, limit=5):
        return []


def cfg(env=None, **section):
    data = {"agentmemory": {"enabled": True, "host": "h.example", "projects": {"acme": "ACME"}, **section}}
    return SimpleNamespace(section=lambda n: data.get(n, {}), env=lambda n: (env if env is not None else {AM_ENV_VAR: "k"}).get(n, ""))


def meeting(tmp_path: Path, sink, project="acme"):
    store = SimpleNamespace(add=lambda *a: None, start_session=lambda *a: None, end_session=lambda *a: None, last_error="")
    return Meeting(tmp_path, store, project, chunk_words=10_000, chunk_seconds=10_000, background=False, sink=sink)  # type: ignore[arg-type]


def test_off_by_default_is_a_quiet_no_op_so_the_app_never_has_to_ask():
    link = MemoryLink(cfg(enabled=False), lambda: "acme")
    assert not link.on and link.sink is None and link.tools() == [] and link.status_text() == ""
    link.start()
    link.set_private(True)
    link.end_meeting("s", "acme")
    link.reset()
    link.stop()  # all harmless


def test_enabled_without_the_secret_says_so_and_stays_off():
    link = MemoryLink(cfg(env={}), lambda: "acme")
    assert not link.on and AM_ENV_VAR in link.problem and AM_ENV_VAR in link.status_text()


def test_a_bad_host_or_port_in_the_config_is_reported_not_raised():
    for bad in ({"host": ""}, {"host": "-oProxyCommand=x"}, {"local_port": 0}):
        link = MemoryLink(cfg(**bad), lambda: "acme")
        assert not link.on and "agentmemory is off" in link.problem and link.sink is None


def test_enabled_builds_everything_and_the_tool_exists_only_when_reading_is_on():
    link = MemoryLink(cfg(), lambda: "acme")
    assert link.on and link.sink is not None and len(link.tools()) == 1
    assert MemoryLink(cfg(read=False), lambda: "acme").tools() == []


def test_a_meeting_sends_sentences_turns_facts_and_a_summary_through_the_sink(tmp_path):
    client = FakeClient()
    sync = MemorySync(client, {"acme": "ACME"}, wait=lambda s: None)
    m = meeting(tmp_path, Sink(sync.add))
    m.transcript_line("Protistrana", "rozpocet je petset tisic")
    m.transcript_line("Protistrana", "rozpocet je petset tisic")  # the same sentence twice: two observations
    m.turn("co to znamena", "Je to 500 tisic.", "assistant")
    m.save_facts("NUMBERS\n- 500 tisic")
    closed = m.rotate()
    m.finish(closed, "Souhrn schuzky")
    sync.end_meeting(closed.sid, closed.project)
    sync.flush(wait_on_failure=False)
    kinds = [c[0] for c in client.calls]
    assert kinds[0] == "start" and kinds.count("observe") == 3 and kinds.count("remember") == 2 and kinds[-1] == "end"
    observes = [c for c in client.calls if c[0] == "observe"]
    assert all(c[1] == "lowass-ACME" for c in observes)  # the transcript goes to lowass-<project>
    assert observes[0][2] != observes[1][2]  # numbered, so the server does not drop the second as a duplicate
    assert all(c[1] == "ACME" for c in client.calls if c[0] == "remember")  # the summary and the facts go to the user's project


def test_facts_go_out_once_at_the_end_not_with_every_update(tmp_path):
    seen = []
    m = meeting(tmp_path, lambda kind, *a: seen.append(kind))
    m.transcript_line("Protistrana", "nejaka veta")
    for i in range(5):  # the facts window refreshes every ~30 s
        m.save_facts(f"NUMBERS\n- verze {i}")
    assert "facts" not in seen  # nothing sent while the meeting runs
    m.finish(m.rotate(), "souhrn")
    assert seen.count("facts") == 1  # the last sheet, once


def test_nothing_is_sent_for_private_and_testing_projects(tmp_path):
    client = FakeClient()
    sync = MemorySync(client, wait=lambda s: None)
    for project in ("private", "Testing"):
        m = meeting(tmp_path / project, Sink(sync.add), project)
        m.transcript_line("Ja", "tajna veta")
        m.finish(m.rotate(), "tajny souhrn")
    sync.flush(wait_on_failure=False)
    assert client.calls == [] and sync.status["waiting"] == 0


def test_private_mode_stops_new_events_and_throws_away_the_waiting_ones(tmp_path):
    client = FakeClient()
    sync = MemorySync(client, wait=lambda s: None)
    link = SimpleNamespace(set_private=sync.set_private)
    m = meeting(tmp_path, Sink(sync.add))
    m.transcript_line("Protistrana", "pred privatnim rezimem")
    assert sync.status["waiting"] == 1
    link.set_private(True)  # what Controls.set_private calls
    assert sync.status["waiting"] == 0  # not even what was waiting is sent
    m.transcript_line("Protistrana", "behem privatniho rezimu")
    sync.flush(wait_on_failure=False)
    assert client.calls == []
    link.set_private(False)
    m.transcript_line("Protistrana", "po privatnim rezimu")
    sync.flush(wait_on_failure=False)
    sent = [c[2] for c in client.calls if c[0] == "observe"]
    assert len(sent) == 1 and sent[0].endswith("po privatnim rezimu")


def test_a_failing_sink_never_breaks_the_meeting(tmp_path):
    def boom(*_a):
        raise RuntimeError("memory sink exploded")

    m = meeting(tmp_path, boom)
    m.transcript_line("Ja", "ahoj")  # must not raise
    m.turn("q", "a", "assistant")
    assert (m.path / "transcript.md").read_text(encoding="utf-8").count("ahoj") == 1  # the local file is the truth


def test_blank_text_and_unknown_kinds_are_ignored(tmp_path):
    seen = []
    sink = Sink(lambda e: seen.append(e) or True)
    sink("nonsense", "acme", "s", "x")
    m = meeting(tmp_path, sink)
    m.transcript_line("Ja", "   ")
    assert seen == []


def test_the_secret_never_reaches_the_status_text_or_the_problem_text():
    link = MemoryLink(cfg(env={AM_ENV_VAR: "SUPERSECRETVALUE"}), lambda: "acme")
    assert "SUPERSECRETVALUE" not in link.status_text() and "SUPERSECRETVALUE" not in link.problem
    assert "SUPERSECRETVALUE" not in repr(link.status_text())


def test_controls_tell_the_link_when_private_changes():
    from lowass.controls import Controls

    told = []
    flow = SimpleNamespace(private=SimpleNamespace(set=lambda: None, clear=lambda: None, is_set=lambda: False),
                           idle_status=lambda: "idle")
    c = Controls(SimpleNamespace(shortcuts=list), lambda *_a: None, flow, None, told.append)
    c.set_private(True)
    c.set_private(False)
    assert told == [True, False]
    assert memlink.EXCLUDED_PROJECTS == ("private", "testing")
