# lowass/move_apply.py
"""Executes the LOCAL part of a move plan: SQLite and the folder. The agentmemory part is in lowass/move_am.py.

Order that cannot lose data: open ONE SQLite transaction, update the rows, rename the folder, commit. When the rename
fails the transaction is rolled back; when the commit fails the folder is renamed back."""
from __future__ import annotations

import contextlib
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .move_plan import Plan

LOCK_WAIT_SEC = 5.0  # how long to wait when the app holds memory.db


class MoveLocalError(RuntimeError):
    """The local move did not happen; nothing was changed (the message says why)."""


@dataclass(frozen=True)
class LocalResult:
    sessions: int
    chunks: int
    db_found: bool


# Replace the old folder prefix of `path` by the new one, only for rows whose path starts with the old folder.


def _update_rows(db: sqlite3.Connection, plan: Plan) -> tuple[int, int]:
    old, new = str(plan.old_dir), str(plan.new_dir)
    keep = (len(old), old, new, len(old) + 1)  # substr(path, 1, n) = old -> new || the rest of the path
    sessions = db.execute("UPDATE sessions SET project=?, path=CASE WHEN substr(path, 1, ?) = ? THEN ? || substr(path, ?) "
                          "ELSE path END WHERE id=?", (plan.new_key, *keep, plan.sid)).rowcount
    chunks = db.execute("UPDATE chunks SET project=?, path=CASE WHEN substr(path, 1, ?) = ? THEN ? || substr(path, ?) "
                        "ELSE path END WHERE session_id=?", (plan.new_key, *keep, plan.sid)).rowcount
    return sessions, chunks


def apply_local(plan: Plan) -> LocalResult:
    """SQLite update + folder rename. Raises MoveLocalError and leaves everything as it was when anything fails."""
    if plan.new_dir.exists():
        raise MoveLocalError(f"target folder already exists: {plan.new_dir}")
    db_found = plan.db_path.is_file()
    db = sqlite3.connect(str(plan.db_path), timeout=LOCK_WAIT_SEC, isolation_level=None) if db_found else None
    sessions = chunks = 0
    try:
        if db is not None:
            try:
                db.execute("BEGIN IMMEDIATE")
                sessions, chunks = _update_rows(db, plan)
            except sqlite3.Error as exc:
                raise MoveLocalError(f"memory.db cannot be updated (is LOWASS still running?): {exc}") from exc
        try:
            plan.new_dir.parent.mkdir(parents=True, exist_ok=True)
            plan.old_dir.rename(plan.new_dir)
        except OSError as exc:
            _rollback(db)
            raise MoveLocalError(f"the folder cannot be renamed, nothing was changed: {exc}") from exc
        if db is not None:
            try:
                db.execute("COMMIT")
            except sqlite3.Error as exc:
                _rename_back(plan.new_dir, plan.old_dir)
                raise MoveLocalError(f"memory.db commit failed, folder renamed back: {exc}") from exc
    finally:
        if db is not None:
            db.close()
    return LocalResult(sessions, chunks, db_found)


def _rollback(db: sqlite3.Connection | None) -> None:
    if db is not None:
        with contextlib.suppress(sqlite3.Error):  # no transaction is open any more: nothing was written
            db.execute("ROLLBACK")


def _rename_back(new_dir: Path, old_dir: Path) -> None:
    try:
        new_dir.rename(old_dir)
    except OSError as exc:
        raise MoveLocalError(f"commit failed AND the folder could not be renamed back: {new_dir} -> {old_dir}: {exc}") from exc
