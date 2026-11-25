# tests/test_move_am.py
from pathlib import Path

from lowass import memlink
from lowass.move_am import apply_agentmemory, transcript_events
from lowass.move_plan import plan_move
from lowass.view import Meet

SID = "20261123-110225397"
PROJECTS = {"acme": "ACME", "globex": "Globex"}
NAMES = {"acme": "Acme Corp"}


class FakeClient:
    def __init__(self, hits=None, fail_observe_from: int = 0, fail_remember: bool = False, fail_start: bool = False):
        self.hits = hits if hits is not None else []
        self.fail_from, self.fail_remember, self.fail_start = fail_observe_from, fail_remember, fail_start
        self.calls: list[tuple] = []

    def health(self) -> bool:
        return True

    def search(self, query, project=None, limit=5):
        self.calls.append(("search", query, project))
        return self.hits

    def remember(self, payload):
        self.calls.append(("remember", payload))
        return not self.fail_remember

    def start_session(self, session, project, cwd="/lowass"):
        self.calls.append(("start", session, project))
        return not self.fail_start

    def observe(self, payload):
        self.calls.append(("observe", payload))
        n = sum(1 for c in self.calls if c[0] == "observe")
        return not (self.fail_from and n >= self.fail_from)

    def end_session(self, session):
        self.calls.append(("end", session))
        return True


def meeting_in(tmp_path: Path, project: str = "globex", lines: int = 3) -> Meet:
    folder = tmp_path / project / SID
    folder.mkdir(parents=True)
    body = "".join(f"[10:00:{i:02d}] Ann: sentence {i}\n" for i in range(lines)) + "\nplain line\n"
    (folder / "transcript.md").write_text(body, encoding="utf-8")
    (folder / "summary.md").write_text("the summary\n", encoding="utf-8")
    (folder / "facts.md").write_text("the facts\n", encoding="utf-8")
    return Meet(project, SID, folder, lines)


def resend_plan(tmp_path: Path, project: str = "globex"):
    return plan_move(meeting_in(tmp_path, project), project, PROJECTS, NAMES, ("private",), resend=True)


def kinds(client: FakeClient) -> list[str]:
    return [c[0] for c in client.calls]


def test_transcript_events_parse_lines_and_numbers(tmp_path: Path) -> None:
    plan = resend_plan(tmp_path)
    events = transcript_events(plan, plan.old_dir)
    assert [e.seq for e in events] == [1, 2, 3, 4]
    assert (events[0].speaker, events[0].text, events[0].project) == ("Ann", "sentence 0", "globex")
    assert events[3].speaker == "" and events[3].text == "plain line"
    assert events[0].ts < events[1].ts  # parsed from the [hh:mm:ss] stamps


def test_full_send_goes_under_the_new_project(tmp_path: Path) -> None:
    plan = resend_plan(tmp_path)
    old = {"layer": "memory", "title": "LOWASS meeting summary", "text": f"head ({SID}) old", "project": ""}
    client = FakeClient(hits=[old, {"layer": "observation", "text": SID}, {"layer": "memory", "text": "other meeting"}])
    said: list[str] = []
    rep = apply_agentmemory(plan, client, NAMES, said.append, plan.old_dir)
    assert not rep.incomplete and (rep.memories_sent, rep.observations_sent, rep.observations_total) == (2, 4, 4)
    assert kinds(client) == ["remember", "remember", "start", "observe", "observe", "observe", "observe", "end"]
    remembers = [c[1] for c in client.calls if c[0] == "remember"]
    assert {r["project"] for r in remembers} == {"globex"}
    assert all(f"lowass-meeting-{SID}" in r["concepts"] for r in remembers)
    assert [r["content"].split("\n", 1)[1] for r in remembers] == ["the summary", "the facts"]
    assert ("start", f"lowass-{SID}", "lowass-globex") in client.calls
    observes = [c[1] for c in client.calls if c[0] == "observe"]
    assert all(o["project"] == "lowass-globex" for o in observes)
    assert "[#1 10:00:00" in observes[0]["data"]["prompt"] and "Ann: sentence 0" in observes[0]["data"]["prompt"]
    assert rep.old_memories == []  # resend does not search


def test_move_looks_up_old_memories_first_by_concept_and_project(tmp_path: Path) -> None:
    meeting = meeting_in(tmp_path, "acme")
    plan = plan_move(meeting, "globex", PROJECTS, NAMES, ("private",))
    plan.new_dir.parent.mkdir()
    plan.old_dir.rename(plan.new_dir)
    old = {"layer": "memory", "title": "summary", "text": f"LOWASS meeting summary ({SID})", "project": ""}
    client = FakeClient(hits=[old, {"layer": "memory", "text": "unrelated"}])
    rep = apply_agentmemory(plan, client, NAMES, lambda s: None)
    assert client.calls[0] == ("search", f"lowass-meeting-{SID}", "Acme Corp")
    assert rep.old_memories == [old]
    assert kinds(client)[1] == "remember"  # lookup happens before anything new is sent


def test_progress_every_50_lines(tmp_path: Path) -> None:
    plan = resend_plan(tmp_path)
    (plan.old_dir / "transcript.md").write_text("".join(f"[10:00:00] Bob: line {i}\n" for i in range(120)), encoding="utf-8")
    said: list[str] = []
    apply_agentmemory(plan, FakeClient(), NAMES, said.append, plan.old_dir)
    assert [s for s in said if "lines" in s and "/" in s] == ["  transcript: 50/120 lines", "  transcript: 100/120 lines"]


def test_failures_are_reported_as_incomplete(tmp_path: Path) -> None:
    plan = resend_plan(tmp_path)
    rep = apply_agentmemory(plan, FakeClient(fail_observe_from=3, fail_remember=True), NAMES, lambda s: None, plan.old_dir)
    assert rep.incomplete
    text = " | ".join(rep.problems)
    assert "summary.md was NOT accepted" in text and "facts.md was NOT accepted" in text and "2 of 4" in text


def test_refused_session_start_sends_no_observation(tmp_path: Path) -> None:
    plan = resend_plan(tmp_path)
    client = FakeClient(fail_start=True)
    rep = apply_agentmemory(plan, client, NAMES, lambda s: None, plan.old_dir)
    assert rep.incomplete and "observe" not in kinds(client)


def test_unreachable_server_stops_after_five_failed_lines(tmp_path: Path) -> None:
    plan = resend_plan(tmp_path)
    (plan.old_dir / "transcript.md").write_text("".join(f"[10:00:00] Bob: l{i}\n" for i in range(30)), encoding="utf-8")
    client = FakeClient(fail_observe_from=1)
    rep = apply_agentmemory(plan, client, NAMES, lambda s: None, plan.old_dir)
    assert kinds(client).count("observe") == 5 and rep.incomplete


def test_failed_search_is_reported(tmp_path: Path) -> None:
    meeting = meeting_in(tmp_path, "acme")
    plan = plan_move(meeting, "globex", PROJECTS, NAMES, ("private",))
    plan.new_dir.parent.mkdir()
    plan.old_dir.rename(plan.new_dir)

    class NoAnswer(FakeClient):
        def search(self, query, project=None, limit=5):
            return None

    rep = apply_agentmemory(plan, NoAnswer(), NAMES, lambda s: None)
    assert rep.incomplete and "by hand" in rep.problems[0]
    assert memlink.session_id(SID) == f"lowass-{SID}"
