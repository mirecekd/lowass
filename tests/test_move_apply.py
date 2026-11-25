# tests/test_move_apply.py
import hashlib
import sqlite3
from pathlib import Path

import pytest

from lowass import move_apply
from lowass.move_apply import MoveLocalError, apply_local
from lowass.move_plan import plan_move
from lowass.store import SCHEMA
from lowass.view import Meet

SID = "20261123-110225397"
PROJECTS = {"acme": "ACME", "globex": "Globex"}


def make_data(tmp_path: Path) -> Meet:
    folder = tmp_path / "acme" / SID
    (folder / "screens").mkdir(parents=True)
    (folder / "transcript.md").write_text("[10:00:00] Ann: hello\n", encoding="utf-8")
    (folder / "screens" / "100000.png").write_bytes(b"png")
    db = sqlite3.connect(tmp_path / "memory.db")
    db.executescript(SCHEMA)
    db.execute("INSERT INTO sessions(id, project, path) VALUES(?,?,?)", (SID, "acme", str(folder)))
    db.execute("INSERT INTO sessions(id, project, path) VALUES(?,?,?)", ("other", "acme", "x"))
    for kind, p in (("transcript", folder / "transcript.md"), ("screenshot", folder / "screens" / "100000.png")):
        db.execute("INSERT INTO chunks(session_id, project, kind, text, path) VALUES(?,?,?,?,?)", (SID, "acme", kind, "t", str(p)))
    db.execute("INSERT INTO chunks(session_id, project, kind, text, path) VALUES(?,?,?,?,?)", ("other", "acme", "chat", "t", "x"))
    db.commit()
    db.close()
    return Meet("acme", SID, folder, 1)


def rows(tmp_path: Path) -> list[tuple]:
    db = sqlite3.connect(tmp_path / "memory.db")
    try:
        return db.execute("SELECT 's', id, project, path FROM sessions UNION ALL "
                          "SELECT 'c', session_id, project, path FROM chunks ORDER BY 1, 2, 4").fetchall()
    finally:
        db.close()


def snapshot(tmp_path: Path) -> dict[str, str]:
    return {str(p.relative_to(tmp_path)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(tmp_path.rglob("*")) if p.is_file()}


def test_local_move_updates_sqlite_and_folder(tmp_path: Path) -> None:
    meeting = make_data(tmp_path)
    plan = plan_move(meeting, "globex", PROJECTS, {}, ())
    res = apply_local(plan)
    new = tmp_path / "globex" / SID
    assert (res.sessions, res.chunks, res.db_found) == (1, 2, True)
    assert (new / "transcript.md").read_text(encoding="utf-8").startswith("[10:00:00] Ann")
    assert (new / "screens" / "100000.png").read_bytes() == b"png"
    assert not (tmp_path / "acme" / SID).exists()
    got = rows(tmp_path)
    assert ("s", SID, "globex", str(new)) in got
    assert ("c", SID, "globex", str(new / "transcript.md")) in got
    assert ("c", SID, "globex", str(new / "screens" / "100000.png")) in got
    assert ("s", "other", "acme", "x") in got and ("c", "other", "acme", "x") in got  # other meetings untouched


def test_rename_failure_rolls_back_the_database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    meeting = make_data(tmp_path)
    plan = plan_move(meeting, "globex", PROJECTS, {}, ())
    before_rows, before_files = rows(tmp_path), snapshot(tmp_path)

    def broken_rename(self: Path, target: Path) -> Path:
        raise PermissionError("locked")

    monkeypatch.setattr(Path, "rename", broken_rename)
    with pytest.raises(MoveLocalError, match="nothing was changed"):
        apply_local(plan)
    monkeypatch.undo()
    assert rows(tmp_path) == before_rows
    assert snapshot(tmp_path) == before_files
    assert meeting.path.is_dir()


def test_target_folder_collision_changes_nothing(tmp_path: Path) -> None:
    meeting = make_data(tmp_path)
    plan = plan_move(meeting, "globex", PROJECTS, {}, ())
    plan.new_dir.mkdir(parents=True)
    before = rows(tmp_path)
    with pytest.raises(MoveLocalError, match="already exists"):
        apply_local(plan)
    assert rows(tmp_path) == before and meeting.path.is_dir()


def test_locked_database_changes_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    meeting = make_data(tmp_path)
    plan = plan_move(meeting, "globex", PROJECTS, {}, ())
    monkeypatch.setattr(move_apply, "LOCK_WAIT_SEC", 0.05)
    other = sqlite3.connect(tmp_path / "memory.db", isolation_level=None)
    other.execute("BEGIN IMMEDIATE")
    try:
        with pytest.raises(MoveLocalError, match="memory.db cannot be updated"):
            apply_local(plan)
    finally:
        other.execute("ROLLBACK")
        other.close()
    assert meeting.path.is_dir() and not plan.new_dir.exists()


def test_without_database_only_the_folder_moves(tmp_path: Path) -> None:
    folder = tmp_path / "acme" / SID
    folder.mkdir(parents=True)
    plan = plan_move(Meet("acme", SID, folder, 0), "globex", PROJECTS, {}, ())
    res = apply_local(plan)
    assert res.db_found is False and (tmp_path / "globex" / SID).is_dir()
    assert not (tmp_path / "memory.db").exists()
