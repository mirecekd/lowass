# tests/test_move_meeting.py
import hashlib
from pathlib import Path

import pytest
from test_move_am import FakeClient
from test_move_apply import make_data, rows

from lowass import move_meeting
from lowass.config import Config

SID = "20261123-110225397"
DATA = {
    "projects": {"acme": {"name": "ACME"}, "globex": {"name": "Globex"}, "private": {"name": "Private"}},
    "agentmemory": {"enabled": True, "projects": {"acme": "Acme Corp"}, "exclude": ["private"]},
}


def snapshot(root: Path) -> dict[str, str]:
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.rglob("*")) if p.is_file()}


class FakeLink:
    client: FakeClient | None = None
    error = ""
    names = {"acme": "Acme Corp"}  # noqa: RUF012 - a read-only test double
    opened = 0

    def __init__(self, cfg):
        pass

    def __enter__(self):
        FakeLink.opened += 1
        return self

    def __exit__(self, exc_type, exc, tb):
        return None


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    make_data(tmp_path)
    (tmp_path / "acme" / SID / "summary.md").write_text("sum\n", encoding="utf-8")
    monkeypatch.setattr(move_meeting.cfgmod, "load", lambda name="lowass.toml": Config(DATA))
    monkeypatch.setattr(move_meeting, "data_dir", lambda cfg: tmp_path)
    monkeypatch.setenv("AGENTMEMORY_SECRET", "s3cret")
    monkeypatch.setattr(move_meeting, "AmLink", FakeLink)
    FakeLink.client, FakeLink.opened = FakeClient(), 0
    return tmp_path


def run(args: list[str], answers: list[str]) -> tuple[int, str]:
    out: list[str] = []
    it = iter(answers)
    code = move_meeting.run(move_meeting.parse_args(args), lambda prompt: (out.append(prompt) or next(it)), out.append)
    return code, "\n".join(out)


def test_dry_run_prints_plan_and_changes_nothing(env: Path) -> None:
    before, db = snapshot(env), rows(env)
    code, text = run(["--dry-run", "--sid", SID, "--to", "globex"], [])
    assert code == 0 and "PLAN" in text and "Dry run" in text and "Apply?" not in text
    assert "STAY under project 'lowass-Acme Corp'" in text
    assert snapshot(env) == before and rows(env) == db and FakeLink.opened == 0


def test_interactive_numbers_then_no_changes_nothing(env: Path) -> None:
    before, db = snapshot(env), rows(env)
    code, text = run([], ["1", "2", "n"])
    assert code == 1 and "Which meeting? [number]" in text and "Move to? [number]" in text and "Apply? [y/N]" in text
    assert f"[{SID}]" in text and "<- now" in text and "Cancelled" in text
    assert snapshot(env) == before and rows(env) == db and FakeLink.opened == 0


def test_yes_applies_local_and_sends_to_agentmemory(env: Path) -> None:
    FakeLink.client = FakeClient()
    code, text = run(["--yes", "--sid", SID[:12], "--to", "globex"], [])
    assert code == 0 and (env / "globex" / SID / "transcript.md").is_file() and not (env / "acme" / SID).exists()
    assert ("c", SID, "globex", str(env / "globex" / SID / "transcript.md")) in rows(env)
    assert FakeLink.opened == 1
    assert [c[0] for c in FakeLink.client.calls][:2] == ["search", "remember"]
    assert "OLD observations stay under project 'lowass-Acme Corp'" in text and "memory_governance_delete" in text


def test_agentmemory_failure_leaves_local_data_moved_and_says_incomplete(env: Path) -> None:
    FakeLink.client = FakeClient(fail_observe_from=1, fail_remember=True)
    code, text = run(["--yes", "--sid", SID, "--to", "globex"], [])
    assert code == 4 and "agentmemory part INCOMPLETE" in text and "--resend --to globex" in text
    assert (env / "globex" / SID).is_dir()


def test_tunnel_failure_is_incomplete_but_local_move_stays(env: Path) -> None:
    FakeLink.client = None
    FakeLink.error = "no route"
    code, text = run(["--yes", "--sid", SID, "--to", "globex"], [])
    assert code == 4 and "INCOMPLETE: no route" in text and (env / "globex" / SID).is_dir()
    FakeLink.error = ""


def test_move_to_excluded_project_never_opens_tunnel(env: Path) -> None:
    code, text = run(["--yes", "--sid", SID, "--to", "private"], [])
    assert code == 0 and FakeLink.opened == 0 and "NOT removed" in text and (env / "private" / SID).is_dir()


def test_agentmemory_without_secret_is_skipped_with_message(env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AGENTMEMORY_SECRET")
    code, text = run(["--yes", "--sid", SID, "--to", "globex"], [])
    assert code == 0 and "agentmemory is skipped: AGENTMEMORY_SECRET is not in .env" in text and FakeLink.opened == 0


@pytest.mark.parametrize("args,expected", [(["--sid", SID, "--to", "acme"], "already in project"),
                                           (["--sid", SID, "--to", "initech"], "unknown target")])
def test_refusals_change_nothing(env: Path, args: list[str], expected: str) -> None:
    before = snapshot(env)
    code, text = run(args, [])
    assert code == 2 and expected in text and snapshot(env) == before


def test_bad_menu_answer_cancels(env: Path) -> None:
    code, text = run([], ["99"])
    assert code == 2 and "nothing changed" in text


def test_unknown_sid(env: Path) -> None:
    code, text = run(["--sid", "2099", "--to", "globex"], [])
    assert code == 2 and "0 meetings match" in text
