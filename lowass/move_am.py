# lowass/move_am.py
"""The agentmemory part of a move: re-send summary, facts and the transcript under the new project, list the old memories.

The REST delete call of agentmemory (governance/bulk-delete) has no documented request shape here, so it is NOT called:
the old summary/facts memories are listed and must be deleted by hand. Nothing here raises."""
from __future__ import annotations

import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from . import memlink
from .memlink import Event, MemoryClient
from .move_plan import Plan

PROGRESS_EVERY = 50
MAX_FAILS_IN_A_ROW = 5  # an unreachable server must not cost 10 s per remaining line
LINE = re.compile(r"^\[(\d\d:\d\d:\d\d)\] (.+?): (.*)$")  # what Meeting.transcript_line writes


@dataclass
class AmReport:
    memories_sent: int = 0
    observations_sent: int = 0
    observations_total: int = 0
    old_memories: list[dict] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    @property
    def incomplete(self) -> bool:
        return bool(self.problems)


def _stamp(sid: str, clock: str, fallback: float) -> float:
    """sid '20261123-110225397' + '14:05:09' -> unix time (local time, as the meeting wrote it); fallback when unparseable."""
    try:
        return time.mktime(time.strptime(f"{sid[:8]} {clock}", "%Y%m%d %H:%M:%S"))
    except ValueError:
        return fallback


def transcript_events(plan: Plan, directory: Path) -> list[Event]:
    """One SENTENCE event per non-empty line of transcript.md, numbered from 1 like the live meeting numbers them."""
    path = directory / "transcript.md"
    if not path.is_file():
        return []
    mtime = path.stat().st_mtime
    events: list[Event] = []
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not raw.strip():
            continue
        m = LINE.match(raw)
        seq = len(events) + 1
        if m:
            events.append(Event(memlink.SENTENCE, plan.new_key, plan.sid, m.group(3), _stamp(plan.sid, m.group(1), mtime),
                                m.group(2), seq))
        else:
            events.append(Event(memlink.SENTENCE, plan.new_key, plan.sid, raw.strip(), mtime, "", seq))
    return events


def old_memories(client: MemoryClient, plan: Plan) -> list[dict] | None:
    """Summary/facts memories of this meeting under the OLD project: hits whose text names the meeting id. None = no answer."""
    hits = client.search(f"lowass-meeting-{plan.sid}", project=plan.old_memory_project, limit=10)
    if hits is None:
        return None
    return [h for h in hits if h.get("layer") == "memory" and plan.sid in str(h.get("text", ""))]


def _send_memories(client: MemoryClient, plan: Plan, directory: Path, names: dict[str, str], rep: AmReport,
                   say: Callable[[str], None]) -> None:
    for kind, name in ((memlink.SUMMARY, "summary.md"), (memlink.FACTS, "facts.md")):
        f = directory / name
        text = f.read_text(encoding="utf-8", errors="replace").strip() if f.is_file() else ""
        if not text:
            say(f"  {name}: empty or missing, nothing to send")
            continue
        if client.remember(memlink.remember_payload(Event(kind, plan.new_key, plan.sid, text), names)):
            rep.memories_sent += 1
            say(f"  {name}: sent under project '{plan.new_memory_project}'")
        else:
            rep.problems.append(f"{name} was NOT accepted by agentmemory")


def _send_observations(client: MemoryClient, plan: Plan, directory: Path, names: dict[str, str], rep: AmReport,
                       say: Callable[[str], None]) -> None:
    events = transcript_events(plan, directory)
    rep.observations_total = len(events)
    if not events:
        return
    if not client.start_session(memlink.session_id(plan.sid), plan.new_session_project):
        rep.problems.append("session start was refused; the transcript was NOT sent")
        return
    fails = 0
    for i, e in enumerate(events, 1):
        if client.observe(memlink.observe_payload(e, names)):
            rep.observations_sent, fails = rep.observations_sent + 1, 0
        else:
            fails += 1
            if fails >= MAX_FAILS_IN_A_ROW:
                rep.problems.append(f"{MAX_FAILS_IN_A_ROW} transcript lines in a row failed, stopped at line {i}")
                break
        if i % PROGRESS_EVERY == 0:
            say(f"  transcript: {i}/{len(events)} lines")
    if not client.end_session(memlink.session_id(plan.sid)):
        rep.problems.append("end_session was not confirmed")
    if rep.observations_sent < len(events):
        rep.problems.append(f"only {rep.observations_sent} of {len(events)} transcript lines were accepted")


def apply_agentmemory(plan: Plan, client: MemoryClient, names: dict[str, str], say: Callable[[str], None],
                      directory: Path | None = None) -> AmReport:
    """`directory` = where the meeting is NOW (plan.new_dir after the local move, plan.old_dir for --resend).
    The old memories are looked up BEFORE anything is sent, so the new ones can never be listed as old."""
    rep = AmReport()
    here = directory or plan.new_dir
    if plan.deletes:
        say("agentmemory: looking for the old summary/facts memories")
        found = old_memories(client, plan)
        if found is None:
            rep.problems.append("the old memories could not be searched; find and delete them by hand")
        else:
            rep.old_memories = found
            say(f"  found {len(found)} old memories")
    say("agentmemory: sending summary and facts")
    _send_memories(client, plan, here, names, rep, say)
    say("agentmemory: sending transcript lines")
    _send_observations(client, plan, here, names, rep, say)
    return rep
