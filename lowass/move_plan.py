# lowass/move_plan.py
"""Pure plan for moving one meeting to another project: what changes locally, in SQLite and in agentmemory.

Nothing here writes anything. `plan_move` validates and returns a `Plan`; `Plan.lines()` is what the user reads before
saying yes; lowass/move_apply.py executes it."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from . import memlink
from .view import Meet

# What happens in agentmemory (Plan.am_mode)
AM_MOVE = "move"  # old and new project are sent: replace the durable memories, re-send the observations
AM_UPLOAD = "upload"  # the old project was never sent (private/testing): everything is a NEW upload
AM_RESEND = "resend"  # --resend: the folder is already moved, only agentmemory is redone (old memories deleted first)
AM_LOCAL_ONLY = "local-only"  # the target project is never sent: only the local move
AM_SAME = "same"  # both LOWASS projects map to the same agentmemory project: nothing to change there
AM_OFF = "off"  # [agentmemory] is disabled or has no secret, or neither project is sent


class MoveError(ValueError):
    """The move is refused; the message says why."""


@dataclass(frozen=True)
class Plan:
    meeting: Meet
    new_key: str
    new_dir: Path
    db_path: Path
    am_mode: str
    old_memory_project: str
    new_memory_project: str
    old_session_project: str
    new_session_project: str
    am_note: str = ""

    @property
    def sid(self) -> str:
        return self.meeting.sid

    @property
    def old_key(self) -> str:
        return self.meeting.project

    @property
    def old_dir(self) -> Path:
        return self.meeting.path

    @property
    def local(self) -> bool:
        """False for --resend: the files and SQLite are not touched."""
        return self.am_mode != AM_RESEND

    @property
    def sends(self) -> bool:
        """True when summary, facts and transcript go to agentmemory (so a tunnel is needed)."""
        return self.am_mode in (AM_MOVE, AM_UPLOAD, AM_RESEND)

    @property
    def deletes(self) -> bool:
        """True when old summary/facts memories are looked up (to be listed for deletion by hand)."""
        return self.am_mode == AM_MOVE

    def lines(self) -> list[str]:
        """The exact list of changes, in the order they are done."""
        out = [f"Meeting {self.sid}: project '{self.old_key}' -> '{self.new_key}'"]
        if self.local:
            sql = "" if self.db_path.is_file() else "  [memory.db not found: skipped]"
            out += [(f"1. SQLite {self.db_path}: sessions and chunks of this meeting get project '{self.new_key}' and the "
                     f"folder prefix '{self.old_dir}' -> '{self.new_dir}' (one transaction){sql}"),
                    f"2. Folder: rename {self.old_dir} -> {self.new_dir} (transcript, chat, summary, facts, screens)"]
        if self.deletes:
            where = self.old_memory_project
            out.append(f"3. agentmemory: find the old summary/facts memories (concept lowass-meeting-{self.sid}, project "
                       f"'{where}') and list their ids. The REST delete call is NOT available in this tool: delete them "
                       f"by hand (MCP tool memory_governance_delete, memoryIds)")
        if self.sends:
            out.append(f"4. agentmemory: send summary and facts under project '{self.new_memory_project}' and every "
                       f"transcript line as an observation under project '{self.new_session_project}'")
        if self.am_mode == AM_MOVE:
            out.append(f"   LIMIT: the old observations cannot be deleted through the API: they STAY under project "
                       f"'{self.old_session_project}' in agentmemory")
        elif self.am_mode == AM_UPLOAD:
            out.append(f"   (project '{self.old_key}' was never sent: nothing to delete)")
        elif not self.sends:
            out.append(f"3. agentmemory: nothing is sent or deleted. {self.am_note}")
        return out


def plan_move(meeting: Meet, target_key: str, projects: Mapping[str, str], am_names: Mapping[str, str],
              excluded: tuple[str, ...], am_enabled: bool = True, resend: bool = False) -> Plan:
    """`projects` = the keys of [projects] (key -> display name); `am_names` = [agentmemory.projects]; `excluded` =
    [agentmemory].exclude. `resend` = redo only the agentmemory part of a meeting that is already in `target_key`.
    Raises MoveError when the move must not happen."""
    if not meeting.path.is_dir():
        raise MoveError(f"meeting folder does not exist: {meeting.path}")
    if target_key not in projects:
        raise MoveError(f"unknown target project '{target_key}' (known: {', '.join(projects)})")
    if resend != (target_key == meeting.project):
        raise MoveError(f"the meeting is already in project '{target_key}' (use --resend to redo only agentmemory)"
                        if not resend else "--resend needs the project the meeting is in now")
    root = meeting.path.parent.parent
    new_dir = root / target_key / meeting.sid
    if new_dir.exists() and not resend:
        raise MoveError(f"target folder already exists, refusing to touch it: {new_dir}")
    names = dict(am_names)
    old_sent, new_sent = memlink.allowed(meeting.project, excluded), memlink.allowed(target_key, excluded)
    old_mem, new_mem = memlink.memory_project(meeting.project, names), memlink.memory_project(target_key, names)
    if not am_enabled or not (old_sent or new_sent):
        mode, note = AM_OFF, "[agentmemory] is disabled or has no secret in .env, or neither project is sent."
    elif not new_sent:
        mode, note = AM_LOCAL_ONLY, (f"Project '{target_key}' is never sent. "
                                     f"Memories already sent under '{meeting.project}' are NOT removed.")
    elif resend:
        mode, note = AM_RESEND, ""
    elif not old_sent:
        mode, note = AM_UPLOAD, ""
    elif old_mem == new_mem:
        mode, note = AM_SAME, f"Both projects use the agentmemory project '{old_mem}': nothing to change there."
    else:
        mode, note = AM_MOVE, ""
    return Plan(meeting, target_key, new_dir, root / "memory.db", mode, old_mem, new_mem,
                memlink.session_project(meeting.project, names), memlink.session_project(target_key, names), note)
