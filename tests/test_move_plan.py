# tests/test_move_plan.py
from pathlib import Path

import pytest

from lowass import move_plan
from lowass.move_plan import MoveError, plan_move
from lowass.view import Meet

PROJECTS = {"acme": "ACME", "globex": "Globex", "private": "Private", "testing": "Testing"}
NAMES = {"acme": "Acme Corp"}
EXCLUDED = ("private", "testing")
SID = "20261123-110225397"


def meet(tmp_path: Path, project: str = "acme") -> Meet:
    path = tmp_path / project / SID
    path.mkdir(parents=True)
    return Meet(project, SID, path, 3)


def test_move_between_sent_projects(tmp_path: Path) -> None:
    plan = plan_move(meet(tmp_path), "globex", PROJECTS, NAMES, EXCLUDED)
    assert plan.am_mode == move_plan.AM_MOVE
    assert plan.new_dir == tmp_path / "globex" / SID
    assert plan.db_path == tmp_path / "memory.db"
    assert (plan.old_memory_project, plan.new_memory_project) == ("Acme Corp", "globex")
    assert (plan.old_session_project, plan.new_session_project) == ("lowass-Acme Corp", "lowass-globex")
    assert plan.sends and plan.deletes
    text = "\n".join(plan.lines())
    assert f"lowass-meeting-{SID}" in text and "STAY under project 'lowass-Acme Corp'" in text


def test_move_from_excluded_project_is_new_upload(tmp_path: Path) -> None:
    plan = plan_move(meet(tmp_path, "private"), "acme", PROJECTS, NAMES, EXCLUDED)
    assert plan.am_mode == move_plan.AM_UPLOAD
    assert plan.sends and not plan.deletes


def test_move_to_excluded_project_stays_local(tmp_path: Path) -> None:
    plan = plan_move(meet(tmp_path), "private", PROJECTS, NAMES, EXCLUDED)
    assert plan.am_mode == move_plan.AM_LOCAL_ONLY
    assert not plan.sends and not plan.deletes
    assert "NOT removed" in "\n".join(plan.lines())


def test_move_between_excluded_projects_is_local(tmp_path: Path) -> None:
    plan = plan_move(meet(tmp_path, "private"), "testing", PROJECTS, NAMES, EXCLUDED)
    assert plan.am_mode == move_plan.AM_OFF and not plan.sends


def test_agentmemory_disabled(tmp_path: Path) -> None:
    plan = plan_move(meet(tmp_path), "globex", PROJECTS, NAMES, EXCLUDED, am_enabled=False)
    assert plan.am_mode == move_plan.AM_OFF and not plan.sends


def test_same_agentmemory_project_changes_nothing_there(tmp_path: Path) -> None:
    plan = plan_move(meet(tmp_path), "globex", PROJECTS, {"acme": "shared", "globex": "shared"}, EXCLUDED)
    assert plan.am_mode == move_plan.AM_SAME and not plan.sends


def test_refuses_same_project(tmp_path: Path) -> None:
    with pytest.raises(MoveError, match="already in project"):
        plan_move(meet(tmp_path), "acme", PROJECTS, NAMES, EXCLUDED)


def test_refuses_unknown_target(tmp_path: Path) -> None:
    with pytest.raises(MoveError, match="unknown target"):
        plan_move(meet(tmp_path), "initech", PROJECTS, NAMES, EXCLUDED)


def test_refuses_existing_target_folder(tmp_path: Path) -> None:
    m = meet(tmp_path)
    (tmp_path / "globex" / SID).mkdir(parents=True)
    with pytest.raises(MoveError, match="already exists"):
        plan_move(m, "globex", PROJECTS, NAMES, EXCLUDED)


def test_refuses_missing_meeting(tmp_path: Path) -> None:
    with pytest.raises(MoveError, match="does not exist"):
        plan_move(Meet("acme", SID, tmp_path / "acme" / SID, 0), "globex", PROJECTS, NAMES, EXCLUDED)


def test_resend_redoes_only_agentmemory(tmp_path: Path) -> None:
    plan = plan_move(meet(tmp_path, "globex"), "globex", PROJECTS, NAMES, EXCLUDED, resend=True)
    assert plan.am_mode == move_plan.AM_RESEND and not plan.local and plan.sends and not plan.deletes
    assert "Folder: rename" not in "\n".join(plan.lines())


def test_resend_refuses_other_project(tmp_path: Path) -> None:
    with pytest.raises(MoveError, match="--resend"):
        plan_move(meet(tmp_path), "globex", PROJECTS, NAMES, EXCLUDED, resend=True)
