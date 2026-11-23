# lowass/view.py
"""Read-only look at an OLDER meeting (`/load`). Only reads `data/<project>/<session>/`; never writes anything."""
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path

SID = re.compile(r"^\d{8}-\d{9}(-\d+)?$")  # what new_session_id() makes: 20261123-110225397
VIEW_MAX_CHARS = 300_000  # the whole meeting goes to the model (Claude takes far more); only a monster is cut at the front


@dataclass(frozen=True)
class Meet:
    project: str
    sid: str
    path: Path
    lines: int


def _lines(path: Path) -> int:
    n = 0
    for name in ("transcript.md", "chat.md"):
        f = path / name
        if f.is_file():
            n += f.read_text(encoding="utf-8", errors="replace").count("\n")
    return n


def recent(root: Path, project: str | None = None, limit: int = 10) -> list[Meet]:
    """Newest first. `project` = the folder name (the project key); None = every project."""
    if project:
        projects = [root / project]
    else:
        projects = [p for p in sorted(root.iterdir()) if p.is_dir()] if root.is_dir() else []
    found = [Meet(p.name, s.name, s, 0) for p in projects if p.is_dir() for s in p.iterdir() if s.is_dir() and SID.match(s.name)]
    found.sort(key=lambda m: m.sid, reverse=True)
    return [Meet(m.project, m.sid, m.path, _lines(m.path)) for m in found[:limit]]


def resolve(items: list[Meet], ref: str) -> Meet | None:
    """`3` = the third line of the last list; otherwise an id or the start of it (must be unique)."""
    ref = ref.strip()
    if ref.isdecimal() and 1 <= int(ref) <= len(items):
        return items[int(ref) - 1]
    hits = [m for m in items if ref and m.sid.startswith(ref)]
    return hits[0] if len(hits) == 1 else None


def describe(m: Meet, n: int = 0) -> str:
    when = f"{m.sid[:4]}-{m.sid[4:6]}-{m.sid[6:8]} {m.sid[9:11]}:{m.sid[11:13]}"
    summary = "summary" if (m.path / "summary.md").is_file() else "no summary"
    return f"{n:>2}. {when}  {m.project}  {m.lines} lines, {summary}  [{m.sid}]"


def text(m: Meet) -> str:
    """Transcript, chat and the last facts sheet of that meeting, as one text for the model."""
    parts = []
    for name, title in (("transcript.md", "TRANSCRIPT"), ("chat.md", "ASSISTANT CHAT"), ("facts.md", "FACTS SHEET (last)")):
        f = m.path / name
        content = f.read_text(encoding="utf-8", errors="replace") if f.is_file() else ""
        if content.strip():  # an empty file is no text: a meeting of empty files must not look like one with content
            parts.append(f"{title}:\n{content}")
    body = "\n".join(parts)
    return body if len(body) <= VIEW_MAX_CHARS else "...[earlier part cut]\n" + body[-VIEW_MAX_CHARS:]


class Viewer:
    """What is loaded (None = the live meeting is the subject) and the last list, so `/load 3` knows what 3 is."""

    def __init__(self) -> None:
        self.loaded: Meet | None = None
        self.listing: list[Meet] = []
        self.stamp = ""

    def load(self, m: Meet) -> None:
        self.loaded, self.stamp = m, time.strftime("%H:%M:%S")

    def unload(self) -> None:
        self.loaded = None
