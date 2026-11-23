# tests/test_review.py
"""/load is READ-ONLY: it lists, opens and summarises an older meeting and writes nothing anywhere."""
import threading
from pathlib import Path
from types import SimpleNamespace

from lowass import view
from lowass.review import Review

SID_A, SID_B = "20261120-090000000", "20261123-110225397"


def make_meeting(root: Path, project: str, sid: str, transcript="[10:00:00] Protistrana: ahoj\n", summary=False) -> Path:
    d = root / project / sid
    d.mkdir(parents=True)
    (d / "transcript.md").write_text(transcript, encoding="utf-8")
    (d / "chat.md").write_text("[10:01:00] user: q\nassistant: a\n", encoding="utf-8")
    (d / "facts.md").write_text("NUMBERS\n- 500\n", encoding="utf-8")
    if summary:
        (d / "summary.md").write_text("S\n", encoding="utf-8")
    return d


def snapshot(root: Path) -> dict[str, bytes]:
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


class FakeAgent:
    def __init__(self):
        self.calls = []

    def run(self, prompt, context="", on_status=None, remember=True, image=None):
        self.calls.append((prompt, context, remember))
        return "SUMMARY OF THE OLD ONE"


def build(tmp_path, project="acme"):
    posts, agent = [], FakeAgent()
    flow = SimpleNamespace(busy=threading.Lock(), session=SimpleNamespace(agent=agent, project=project),
                           idle_status=lambda: "idle")
    cfg = SimpleNamespace(section=lambda n: {"data_dir": str(tmp_path), "queue_wait_sec": 1}, projects=lambda: {"acme": {"name": "ACME"}})
    return Review(cfg, lambda k, t: posts.append((k, t)), flow), agent, posts


def wait(review: Review) -> None:
    for t in threading.enumerate():
        if t.name == "review":
            t.join(5)


def test_list_is_newest_first_and_limited_to_the_project(tmp_path):
    make_meeting(tmp_path, "acme", SID_A)
    make_meeting(tmp_path, "acme", SID_B, summary=True)
    make_meeting(tmp_path, "globex", "20261122-080000000")
    r, _, posts = build(tmp_path)
    assert r.command("/load") is True
    text = posts[-1][1]
    assert text.index(SID_B) < text.index(SID_A) and "globex" not in text and "no summary" in text
    r.command("/load all")
    assert "globex" in posts[-1][1]


def test_open_by_number_by_id_and_by_a_prefix(tmp_path):
    make_meeting(tmp_path, "acme", SID_A)
    make_meeting(tmp_path, "acme", SID_B)
    r, _, _ = build(tmp_path)
    r.command("/load")
    r.command("/load 2")
    assert r.viewer.loaded and r.viewer.loaded.sid == SID_A
    r.command("/load 20261123")
    assert r.viewer.loaded and r.viewer.loaded.sid == SID_B
    r.command("/unload")
    assert not r.active


def test_an_unknown_or_ambiguous_reference_loads_nothing(tmp_path):
    make_meeting(tmp_path, "acme", SID_A)
    make_meeting(tmp_path, "acme", "20261120-090000001")
    r, _, posts = build(tmp_path)
    r.command("/load")
    r.command("/load 2026112")  # matches both
    r.command("/load 99")
    assert not r.active and [k for k, _ in posts if k == "err"] == ["err", "err"]


def test_the_summary_of_a_loaded_meeting_is_stateless_and_writes_nothing(tmp_path):
    make_meeting(tmp_path, "acme", SID_B)
    before = snapshot(tmp_path)
    r, agent, posts = build(tmp_path)
    r.command("/load")
    r.command("/load 1")
    r.run("Summarise", "Summary")
    wait(r)
    assert ("bot", "SUMMARY OF THE OLD ONE") in posts
    prompt, context, remember = agent.calls[0]
    assert "ahoj" in prompt and "NUMBERS" in prompt and "OLDER" in prompt  # transcript, chat/facts and the rule
    assert remember is False and context == ""  # the agent's own memory is untouched
    assert snapshot(tmp_path) == before  # not one file changed, added or removed


def test_commands_are_not_mistaken_for_questions_and_plain_text_passes(tmp_path):
    r, _, _ = build(tmp_path)
    assert r.command("/hint") is False and r.command("what is the budget?") is False and r.command("") is False


def test_a_loaded_meeting_with_no_text_says_so(tmp_path):
    d = make_meeting(tmp_path, "acme", SID_A, transcript="")
    for name in ("chat.md", "facts.md"):
        (d / name).unlink()
    r, agent, posts = build(tmp_path)
    r.command("/load")
    r.command("/load 1")
    r.run("Summarise", "Summary")
    assert agent.calls == [] and posts[-1][0] == "err"


def test_a_monster_meeting_is_cut_at_the_front_not_refused(tmp_path):
    d = make_meeting(tmp_path, "acme", SID_A, transcript="x" * (view.VIEW_MAX_CHARS + 5000) + "THE-END\n")
    out = view.text(view.recent(tmp_path, "acme")[0])
    assert out.startswith("...[earlier part cut]") and "THE-END" in out and d.exists()


def test_folders_that_are_not_meetings_are_ignored(tmp_path):
    make_meeting(tmp_path, "acme", SID_A)
    (tmp_path / "acme" / "screens").mkdir()
    (tmp_path / "memory.db").write_text("x")
    assert [m.sid for m in view.recent(tmp_path)] == [SID_A]
    assert view.recent(tmp_path / "nope") == []


def test_controls_route_buttons_and_questions_to_the_loaded_meeting_only():
    from lowass.controls import Controls

    asked, ran = [], []
    flow = SimpleNamespace(ask=asked.append, shortcut=lambda p, label: ran.append(label), check_now=lambda: ran.append("check"),
                           idle_status=lambda: "idle", busy=threading.Lock(), session=SimpleNamespace(agent=None, project="p"))
    cfg = SimpleNamespace(shortcuts=lambda: [{"label": "Check", "action": "check"}], section=lambda n: {}, projects=dict)
    posts = []
    c = Controls(cfg, lambda k, t: posts.append((k, t)), flow, None)
    c.ask_or_command("normal question")
    assert asked == ["normal question"]  # not loaded: the old path
    c.review.viewer.loaded = view.Meet("p", SID_A, Path("/nonexistent"), 0)
    c.ask_or_command("question about the old one")
    c.on_shortcut("p", "Check")
    assert asked == ["normal question"] and ran == []  # the running meeting's agent path was not used
    assert posts[-1][0] == "err"  # fact-check refuses while viewing
