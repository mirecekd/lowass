# lowass/meeting.py
"""One meeting = everything between two boundaries (start, Clear, project switch, exit).

Local files per meeting: transcript.md, chat.md, summary.md, screens/*.png. The same text feeds the vector store.
Transcript lines are stored in chunks (words or seconds), never one embedding call per line.
rotate() is fast and has no network call, so it is safe on the UI thread; finish() does the slow part.
"""
from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .session_id import new_session_id
from .store import Store

log = logging.getLogger("lowass.meeting")


@dataclass
class Closed:
    sid: str
    project: str
    path: Path
    lines: int  # transcript lines + agent turns: an (almost) empty meeting gets no summary
    pending: str  # transcript lines not stored in the vector store yet


def meeting_text(path: Path) -> str:
    """Transcript + agent chat of a meeting, read from the local files (works even if embedding never worked)."""
    parts = []
    for name, title in (("transcript.md", "TRANSCRIPT"), ("chat.md", "ASSISTANT CHAT")):
        f = path / name
        if f.exists():
            parts.append(f"{title}:\n{f.read_text(encoding='utf-8')}")
    return "\n".join(parts)


class Meeting:
    def __init__(self, data_dir: Path, store: Store, project: str, chunk_words: int = 180, chunk_seconds: float = 90.0,
                 on_error: Callable[[str], None] | None = None, background: bool = True,
                 sink: Callable[[str, str, str, str, str], None] | None = None):
        self.dir, self.store = data_dir, store
        # sink(kind, project, session, text, speaker): a copy of what is stored (agentmemory)
        self.sink = sink
        self.chunk_words, self.chunk_seconds = chunk_words, chunk_seconds
        self.on_error, self.background = on_error, background
        self._lock = threading.Lock()
        self._last_error = ""
        self.sid, self.project, self.path = "", project, data_dir
        self._pending: list[str] = []
        self._pending_since = 0.0
        self.lines = 0
        self._created = False
        self.begin(project)

    def begin(self, project: str) -> str:
        with self._lock:
            self.project, self.sid = project, new_session_id()
            self.path = self.dir / project / self.sid
            self._pending, self._pending_since, self.lines = [], 0.0, 0
            self._created = False  # folder + session record appear with the first write: no empty meetings
            sid = self.sid
        log.info("meeting %s started", sid)
        return sid

    def _ensure(self) -> None:
        """Called with the lock held before every write."""
        if not self._created:
            (self.path / "screens").mkdir(parents=True, exist_ok=True)
            self.store.start_session(self.sid, self.project, str(self.path))
            self._created = True

    def _append(self, name: str, text: str) -> None:
        self._ensure()
        with (self.path / name).open("a", encoding="utf-8") as fh:
            fh.write(text + "\n")

    def _after_add(self) -> None:
        err = self.store.last_error
        if err and err != self._last_error and self.on_error:
            self.on_error(f"Memory: embedding failed, the text is saved and will be embedded later ({err[:120]})")
        self._last_error = err

    def _emit(self, kind: str, text: str, speaker: str = "", closed: Closed | None = None) -> None:
        """A copy for `sink` (agentmemory). Never raises: the local files are the truth."""
        if self.sink is None or not text.strip():
            return
        project, sid = (closed.project, closed.sid) if closed is not None else (self.project, self.sid)
        try:
            self.sink(kind, project, sid, text, speaker)
        except Exception:
            log.warning("the memory sink failed", exc_info=True)

    def transcript_line(self, speaker: str, text: str) -> None:
        stamp = time.strftime("%H:%M:%S")
        line = f"[{stamp}] {speaker}: {text}"
        self._emit("sentence", text, speaker)
        with self._lock:
            self._append("transcript.md", line)
            self.lines += 1
            if not self._pending:
                self._pending_since = time.time()
            self._pending.append(line)
            due = (sum(len(p.split()) for p in self._pending) >= self.chunk_words
                   or time.time() - self._pending_since >= self.chunk_seconds)
        if due:
            if self.background:
                threading.Thread(target=self.flush, daemon=True, name="embed-flush").start()
            else:
                self.flush()

    def flush(self) -> None:
        """Stores the pending transcript lines as one chunk (one embedding call)."""
        with self._lock:
            if not self._pending:
                return
            text, self._pending = "\n".join(self._pending), []
            sid, project, path = self.sid, self.project, str(self.path / "transcript.md")
        self.store.add(sid, project, "transcript", text, path)
        self._after_add()

    def turn(self, user_text: str, answer: str, role: str = "assistant", image: Path | None = None) -> None:
        """One agent turn = one chunk. role: assistant | auto | screen (screen = the answer about a screenshot)."""
        stamp = time.strftime("%H:%M:%S")
        head = f"[{stamp}] user: {user_text}\n" if user_text else f"[{stamp}] "
        label = f"{head}{role}: {answer}" + (f"\n(screenshot: {image.name})" if image else "")
        with self._lock:
            self._append("chat.md", label)
            self.lines += 1
            sid, project, path = self.sid, self.project, str(image or self.path / "chat.md")
        self.store.add(sid, project, "screenshot" if image else "chat", label, path)
        self._after_add()
        self._emit("turn", f"user: {user_text}\n{role}: {answer}" if user_text else f"{role}: {answer}", role)

    def save_facts(self, text: str) -> None:
        """The rolling facts sheet of this meeting (overwritten on every update)."""
        with self._lock:
            self._ensure()
            (self.path / "facts.md").write_text(text + "\n", encoding="utf-8")
        # not sent now (each update would be one more memory): finish() sends the last sheet

    def screen_path(self) -> Path:
        with self._lock:
            self._ensure()
            return self.path / "screens" / f"{time.strftime('%H%M%S')}.png"

    def rotate(self, project: str | None = None) -> Closed:
        """Closes the current meeting and (when project is given) starts the next one at once. No network here."""
        with self._lock:
            closed = Closed(self.sid, self.project, self.path, self.lines, "\n".join(self._pending))
            self._pending = []
        if project is not None:
            self.begin(project)
        return closed

    def finish(self, closed: Closed, summary: str = "") -> None:
        """The slow part: store the leftover transcript and the summary, close the session record."""
        if closed.lines == 0 and not closed.pending:
            return  # nothing was written: no folder, no record
        if closed.pending:
            self.store.add(closed.sid, closed.project, "transcript", closed.pending, str(closed.path / "transcript.md"))
        if summary:
            (closed.path / "summary.md").write_text(summary + "\n", encoding="utf-8")
            self.store.add(closed.sid, closed.project, "summary", summary, str(closed.path / "summary.md"))
        self.store.end_session(closed.sid, summary)
        self._after_add()
        self._emit("summary", summary, closed=closed)
        facts = closed.path / "facts.md"
        if facts.exists():  # the FINAL sheet of the meeting, once
            self._emit("facts", facts.read_text(encoding="utf-8").strip(), closed=closed)
