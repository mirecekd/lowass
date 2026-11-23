# lowass/memlink.py
"""The contract between LOWASS and agentmemory: what an event is, what the server is sent, and a bounded outbox.

Pure logic, no network and no threads, so everything here is tested with plain data. The pieces that talk to the
network (am_client, am_tunnel, am_sync) are written against these types."""
from __future__ import annotations

import contextlib
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Protocol

# Projects that never go to agentmemory (the user's decision): Private is private, Testing is noise.
EXCLUDED_PROJECTS = ("private", "testing")

SENTENCE, TURN, SUMMARY, FACTS = "sentence", "turn", "summary", "facts"
KINDS = (SENTENCE, TURN, SUMMARY, FACTS)


@dataclass(frozen=True)
class Event:
    """One thing LOWASS wants to remember. `kind` is one of KINDS; `project` is the LOWASS project key ('acme'), NOT yet the
    agentmemory name; `session` is the id of the meeting (Meeting.sid); `ts` is a unix time in seconds."""

    kind: str
    project: str
    session: str
    text: str
    ts: float = field(default_factory=time.time)
    speaker: str = ""  # SENTENCE: the speaker label; TURN: 'you' or 'assistant' or 'auto'
    seq: int = 0  # position inside the meeting; makes two identical sentences two different observations


def iso(ts: float) -> str:
    """A UTC timestamp the server accepts: 2026-11-23T07:00:00Z."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))


def allowed(project: str, excluded: tuple[str, ...] = EXCLUDED_PROJECTS) -> bool:
    """Is a meeting of this project sent at all? The comparison ignores the case."""
    return project.strip().lower() not in {e.lower() for e in excluded}


def memory_project(key: str, names: dict[str, str] | None = None) -> str:
    """The agentmemory project of the SUMMARY and the FACTS (a durable memory): the user's own project name, so a meeting
    about ACME is found next to the other notes about ACME. `names` maps a LOWASS key to that name; an unknown key is used
    as it is."""
    return (names or {}).get(key, key)


def session_project(key: str, names: dict[str, str] | None = None) -> str:
    """The agentmemory project of the raw TRANSCRIPT and the chat (observations of a session): `lowass-<name>`, kept apart
    from the durable notes because it is large and noisy."""
    return f"lowass-{memory_project(key, names)}"


def session_id(sid: str) -> str:
    """A session id that cannot collide with the ones of other agents (Pi, Hermes use their own)."""
    return f"lowass-{sid}"


def observe_payload(e: Event, names: dict[str, str] | None = None, cwd: str = "/lowass") -> dict:
    """POST /agentmemory/observe. hookType, sessionId, project, cwd and timestamp are required strings. The text carries
    '[#seq hh:mm:ss] Speaker:' because the server treats identical text in one second as a duplicate."""
    stamp = time.strftime("%H:%M:%S", time.gmtime(e.ts))
    who = f"{e.speaker}: " if e.speaker else ""
    return {"hookType": "prompt_submit", "sessionId": session_id(e.session), "project": session_project(e.project, names),
            "cwd": cwd, "timestamp": iso(e.ts), "data": {"prompt": f"[#{e.seq} {stamp}] {who}{e.text}"}}


def remember_payload(e: Event, names: dict[str, str] | None = None, meeting_title: str = "") -> dict:
    """POST /agentmemory/remember for a SUMMARY or the FACTS of a meeting."""
    label = "summary" if e.kind == SUMMARY else "facts"
    head = f"LOWASS meeting {label} ({e.session})" + (f" {meeting_title}" if meeting_title else "")
    return {"content": f"{head}\n{e.text}", "project": memory_project(e.project, names),
            "concepts": ["lowass", f"lowass-{label}", f"lowass-meeting-{e.session}"]}


def is_memory(e: Event) -> bool:
    """SUMMARY and FACTS are durable memories, the rest are observations of the session."""
    return e.kind in (SUMMARY, FACTS)


class MemoryClient(Protocol):
    """What the rest of LOWASS needs from agentmemory. am_client.AgentMemoryClient implements it over REST; tests use fakes.
    Every method returns instead of raising: False / [] / None mean 'did not work', the caller keeps the event and retries."""

    def health(self) -> bool: ...

    def start_session(self, session: str, project: str, cwd: str = "/lowass") -> bool: ...

    def end_session(self, session: str) -> bool: ...

    def observe(self, payload: dict) -> bool: ...

    def remember(self, payload: dict) -> bool: ...

    def search(self, query: str, project: str | None = None, limit: int = 5) -> list[dict] | None:
        """Hits as {'layer': 'memory'|'observation', 'title': str, 'text': str, 'project': str, 'ts': str, 'score': float};
        None = the server could not be reached (an empty list means 'nothing found')."""
        ...


class Outbox:
    """Events waiting to be sent. Bounded: when the server is unreachable for a long time the OLDEST sentences are dropped
    first (a summary or the facts are never dropped before a sentence), so memory cannot grow without limit."""

    def __init__(self, limit: int = 2000):
        self.limit = max(1, limit)
        self._items: deque[Event] = deque()
        self.dropped = 0

    def __len__(self) -> int:
        return len(self._items)

    def put(self, e: Event) -> None:
        self._items.append(e)
        while len(self._items) > self.limit:
            victim = next((x for x in self._items if x.kind in (SENTENCE, TURN)), None)
            if victim is None:  # nothing but summaries and facts: drop the oldest of them, never refuse a new one
                self._items.popleft()
            else:
                self._items.remove(victim)
            self.dropped += 1

    def take(self, n: int) -> list[Event]:
        """Up to n events from the front WITHOUT removing them: they are removed by `done` after a successful send."""
        return list(self._items)[:max(0, n)]

    def done(self, sent: list[Event]) -> None:
        for e in sent:
            if self._items and self._items[0] is e:
                self._items.popleft()
            else:
                with contextlib.suppress(ValueError):  # already removed by an earlier send
                    self._items.remove(e)

    def clear(self, session: str | None = None) -> int:
        """Forget everything (Private) or only one meeting. Returns how many events were thrown away."""
        keep = deque(e for e in self._items if session is not None and e.session != session)
        gone = len(self._items) - len(keep)
        self._items = keep
        return gone
