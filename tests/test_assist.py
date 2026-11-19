# tests/test_assist.py
"""Assist: hint card + facts sheet wiring (fake flow, no network)."""
from __future__ import annotations

import threading
from typing import Any

from lowass.assist import Assist


class Cfg:
    def __init__(self, env: dict[str, str] | None = None, hint: dict | None = None, facts: dict | None = None):
        self._env = {"LITELLM_API_KEY": "k", "LITELLM_BASE_URL": "http://x"} if env is None else env
        self.data = {
            "audio": {"my_label": "Ja"},
            "hint": {"enabled": True, "names": ["Miroslav"], "wait_sec": 0, "cooldown_sec": 0, "max_age_sec": 90, **(hint or {})},
            "facts": {"enabled": True, "min_new_words": 3, **(facts or {})},
            "prompts": {"hint": "HINT", "facts": "FACTS"},
        }

    def section(self, name: str) -> dict:
        return self.data.get(name, {})

    def env(self, name: str) -> str:
        return self._env.get(name, "")


class FakeFlow:
    def __init__(self, answer: str = "Say yes."):
        self.private = threading.Event()
        self.busy = threading.Lock()
        self.extra_context: Any = None
        self.calls: list[tuple] = []
        self.answer = answer

    def work(self, prompt: str, shown: Any, tag: str, remember: bool = True, image: Any = None, deliver: Any = None) -> None:
        self.calls.append((prompt, tag, remember))
        if self.answer and deliver:
            deliver(self.answer)


class FakeMeeting:
    def __init__(self) -> None:
        self.saved: list[str] = []

    def save_facts(self, text: str) -> None:
        self.saved.append(text)


def build(cfg: Cfg | None = None, flow: FakeFlow | None = None) -> tuple[Assist, FakeFlow, FakeMeeting, list[tuple[str, str]]]:
    posts: list[tuple[str, str]] = []
    flow, meeting = flow or FakeFlow(), FakeMeeting()
    assist = Assist(cfg or Cfg(), flow, meeting, lambda k, t: posts.append((k, t)), lambda: "m")
    return assist, flow, meeting, posts


def test_unanswered_question_asks_the_agent_and_posts_a_card() -> None:
    assist, flow, _meeting, posts = build()
    assist.tap("Protistrana", "Kdy to bude hotove?")
    assist._tick()
    assert flow.calls and flow.calls[0][1] == "hint" and flow.calls[0][2] is False
    assert "Kdy to bude hotove?" in flow.calls[0][0] and flow.calls[0][0].startswith("HINT")
    kind, text = posts[-1]
    assert kind == "hint" and text.split("\t")[0] == "Protistrana" and text.endswith("Say yes.")


def test_answer_from_the_user_cancels_the_hint() -> None:
    assist, flow, _meeting, _posts = build()
    assist.tap("Protistrana", "Kdy to bude hotove?")
    assist.tap("Ja", "Zitra to dodame vsechno")
    assist._tick()
    assert flow.calls == []


def test_busy_agent_keeps_the_question_for_the_next_second() -> None:
    assist, flow, _meeting, _posts = build()
    assist.tap("Protistrana", "Kdy to bude hotove?")
    flow.busy.acquire()
    assist._tick()
    assert flow.calls == []
    flow.busy.release()
    assist._tick()
    assert len(flow.calls) == 1


def test_quiet_agent_answer_posts_no_card() -> None:
    assist, flow, _meeting, posts = build(flow=FakeFlow(answer=""))
    assist.tap("Protistrana", "Kdy to bude hotove?")
    assist._tick()
    assert len(flow.calls) == 1 and not [p for p in posts if p[0] == "hint"]


def test_reset_forgets_the_pending_question_and_hides_the_card() -> None:
    assist, flow, _meeting, posts = build()
    assist.tap("Protistrana", "Kdy to bude hotove?")
    assist.reset()
    assist._tick()
    assert flow.calls == [] and ("hint_clear", "") in posts


def test_private_mode_does_nothing_in_the_loop() -> None:
    assist, flow, _meeting, _posts = build()
    assist.tap("Protistrana", "Kdy to bude hotove?")
    flow.private.set()
    ticks: list[int] = []
    assist._tick = lambda: ticks.append(1)  # type: ignore[method-assign]
    t = threading.Thread(target=assist.run, daemon=True)
    t.start()
    assert not t.join(1.5) and ticks == []  # still looping, never ticked
    assist.stop.set()
    t.join(2)
    assert flow.calls == []


def test_facts_sheet_is_saved_and_given_to_the_agent_as_context() -> None:
    assist, flow, meeting, _posts = build(cfg=Cfg(hint={"enabled": False}))
    assert assist.sheet is not None
    assist.sheet._complete = lambda _s, _u: "NUMBERS\n- budget 100"
    assist.tap("Protistrana", "rozpocet je sto tisic korun")
    assist._tick()
    assert meeting.saved == ["NUMBERS\n- budget 100"] and flow.extra_context() == "NUMBERS\n- budget 100"
    assist.reset()
    assert flow.extra_context() == ""


def test_no_llm_key_means_no_facts_sheet_but_hints_still_work() -> None:
    assist, flow, _meeting, _posts = build(cfg=Cfg(env={}))
    assert assist.sheet is None and flow.extra_context() == ""
    assist.tap("Protistrana", "Kdy to bude hotove?")
    assist._tick()
    assert len(flow.calls) == 1


def test_disabled_hint_never_asks() -> None:
    assist, flow, _meeting, _posts = build(cfg=Cfg(hint={"enabled": False}))
    assist.tap("Protistrana", "Kdy to bude hotove?")
    assist._tick()
    assert assist.watcher is None and flow.calls == []


class FakeAgent:
    def __init__(self, answer: str):
        self.answer, self.context = answer, ""

    def run(self, prompt: str, context: str = "", on_status: Any = None, remember: bool = True, image: Any = None) -> str:
        self.context = context
        return self.answer


def real_flow(answer: str, tmp_path: Any, facts: str = "") -> tuple[Any, FakeAgent, list[tuple[str, str]], Any]:
    from types import SimpleNamespace

    from lowass.debug import Stats
    from lowass.flow import Flow
    from lowass.transcript import Transcript

    agent, posts, turns = FakeAgent(answer), [], []
    cfg = SimpleNamespace(section=lambda n: {"agent": {"auto": False}, "debug": {}}.get(n, {}))
    meeting = SimpleNamespace(turn=lambda *a: turns.append(a))
    flow = Flow(cfg, lambda k, t: posts.append((k, t)), SimpleNamespace(agent=agent), Transcript(), meeting,  # type: ignore[arg-type]
                Stats(), threading.Lock(), lambda: "idle")
    flow.extra_context = lambda: facts
    return flow, agent, posts, turns


def test_flow_hint_goes_to_deliver_not_to_the_log_and_sees_the_facts(tmp_path: Any) -> None:
    flow, agent, posts, turns = real_flow("Say it is on Friday.", tmp_path, facts="DATES\n- Friday")
    got: list[str] = []
    flow.work("HINT", None, "hint", remember=False, deliver=got.append)
    assert got == ["Say it is on Friday."] and not [p for p in posts if p[0] in ("bot", "auto")]
    assert agent.context.startswith("FACTS SO FAR:\nDATES\n- Friday")
    assert turns and turns[0][2] == "hint"


def test_flow_hint_is_silent_in_private_and_never_reports_busy(tmp_path: Any) -> None:
    flow, _agent, posts, _turns = real_flow("x", tmp_path)
    got: list[str] = []
    flow.private.set()
    flow.work("HINT", None, "hint", deliver=got.append)
    flow.private.clear()
    flow.busy.acquire()
    flow.work("HINT", None, "hint", deliver=got.append)
    assert got == [] and not [p for p in posts if p[0] == "err"]


def test_flow_nothing_reply_gives_no_card(tmp_path: Any) -> None:
    flow, _agent, _posts, _turns = real_flow("NOTHING", tmp_path)
    got: list[str] = []
    flow.work("HINT", None, "hint", deliver=got.append)
    assert got == []


def test_hint_command_posts_a_test_card_without_the_agent() -> None:
    from types import SimpleNamespace

    from lowass.controls import Controls

    posts: list[tuple[str, str]] = []
    flow = SimpleNamespace(ask=lambda t: posts.append(("ask", t)))
    Controls(SimpleNamespace(shortcuts=list), lambda k, t: posts.append((k, t)), flow, None).ask_or_command("/hint")
    assert posts and posts[0][0] == "hint" and posts[0][1].count("\t") == 2 and not [p for p in posts if p[0] == "ask"]


def test_a_new_sheet_and_a_reset_are_posted_to_the_facts_window() -> None:
    assist, _flow, _meeting, posts = build(cfg=Cfg(hint={"enabled": False}))
    assert assist.sheet is not None
    assist.sheet._complete = lambda _s, _u: "NUMBERS\n- budget 100"
    assist.tap("Protistrana", "rozpocet je sto tisic korun")
    assist._tick()
    assert ("facts", "NUMBERS\n- budget 100") in posts
    assist.reset()
    assert ("facts_reset", "") in posts


def test_a_question_asked_while_an_automatic_check_runs_waits_instead_of_being_dropped(tmp_path: Any) -> None:
    """Field bug: 'Jarvis, ...' said 1.2 s after an automatic check started was answered with 'Still working' and lost."""
    import time

    flow, agent, posts, _turns = real_flow("The answer.", tmp_path)
    flow.busy.acquire()  # the automatic check is running
    worker = threading.Thread(target=flow.work, args=("what do you think?", "what do you think?", "bot"), daemon=True)
    worker.start()
    time.sleep(0.3)
    assert not [p for p in posts if p[0] == "err"], "the question must not be rejected"
    assert any(p[0] == "status" and "waiting" in p[1] for p in posts)  # the user sees that it waits
    flow.busy.release()  # the automatic check is done
    worker.join(3)
    assert ("you", "what do you think?") in posts and ("bot", "The answer.") in posts and agent.context is not None


def test_a_question_that_waits_too_long_says_so_and_automatic_work_never_waits(tmp_path: Any) -> None:
    flow, _agent, posts, _turns = real_flow("x", tmp_path)
    flow.cfg.section = lambda n: {"agent": {"auto": False, "queue_wait_sec": 0.2}, "debug": {}}.get(n, {})  # type: ignore[method-assign]
    flow.busy.acquire()
    flow.work("q", "q", "bot")
    assert [p for p in posts if p[0] == "err" and "Still working" in p[1]]
    posts.clear()
    flow.work("auto", None, "auto")  # an automatic check just skips: nobody is waiting for it
    assert posts == []
