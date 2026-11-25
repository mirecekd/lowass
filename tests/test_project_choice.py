# tests/test_project_choice.py
"""Which project is starting? When the question is asked, and what each answer does (no tkinter)."""
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock

from lowass.controls import Controls
from lowass.freeze import PrivateGate
from lowass.project_choice import CANCELLED, ProjectChoice
from lowass.project_picker_logic import should_ask
from lowass.ui_poll import make_handlers


class World:
    """A fake app: the meeting, the Private gate, the current project and everything that was posted or switched."""

    def __init__(self, enabled=True, count=3, lines=0, private=True, fail_switch=False):
        self.posts, self.calls = [], []
        self.lines, self.project, self.fail_switch = lines, "acme", fail_switch
        self.gate = PrivateGate()
        if private:
            self.gate.set()
        self.choice = ProjectChoice(enabled, count, lambda k, t: self.posts.append((k, t)), lambda: self.project,
                                    lambda: self.lines == 0, self.switch, self.release)
        flow = SimpleNamespace(private=self.gate, idle_status=lambda: "listening")
        self.controls = Controls(SimpleNamespace(shortcuts=list), lambda k, t: self.posts.append((k, t)), flow, None,
                                 choice=self.choice)

    def switch(self, key):
        self.calls.append(("switch", key))
        if not self.fail_switch:
            self.project = key

    def release(self):
        self.calls.append(("release",))
        self.controls.set_private(False, sync_button=True, ask=False)

    def asked(self):
        return [t for k, t in self.posts if k == "ask_project"]


def test_should_ask_needs_enabled_two_projects_and_an_empty_meeting():
    assert should_ask(True, 2, True)
    assert not should_ask(False, 2, True)
    assert not should_ask(True, 1, True)
    assert not should_ask(True, 2, False)


def test_play_after_close_meeting_asks_and_stays_private():
    w = World()
    w.controls.set_private(False, sync_button=True)
    assert w.asked() == ["acme"] and w.gate.is_set()
    assert ("private", "1") in w.posts and ("status", CANCELLED) in w.posts
    assert ("private", "0") not in w.posts


def test_play_in_the_middle_of_a_meeting_does_not_ask():
    w = World(lines=4)
    w.controls.set_private(False, sync_button=True)
    assert w.asked() == [] and not w.gate.is_set()


def test_one_project_or_switched_off_does_not_ask():
    for w in (World(count=1), World(enabled=False)):
        w.controls.set_private(False, sync_button=True)
        assert w.asked() == [] and not w.gate.is_set()


def test_turning_private_on_never_asks():
    w = World(private=False)
    w.controls.set_private(True, sync_button=True)
    assert w.asked() == [] and w.gate.is_set()


def test_the_same_project_continues_without_a_switch():
    w = World()
    w.choice.apply("acme")
    assert w.calls == [("release",)] and not w.gate.is_set() and ("private", "0") in w.posts


def test_another_project_switches_first_then_leaves_private():
    w = World()
    w.choice.apply("globex")
    assert w.calls == [("switch", "globex"), ("release",)] and not w.gate.is_set()
    assert ("project", "globex") in w.posts


def test_a_failed_switch_keeps_private():
    w = World(fail_switch=True)
    w.choice.apply("globex")
    assert w.calls == [("switch", "globex")] and w.gate.is_set() and ("status", CANCELLED) in w.posts


def test_cancel_keeps_private():
    w = World()
    w.choice.cancelled()
    assert w.gate.is_set() and w.calls == [] and ("status", CANCELLED) in w.posts


def test_chosen_runs_the_work_in_a_thread():
    w = World()
    done = threading.Event()
    w.choice.release = done.set
    w.choice.chosen("acme")
    assert done.wait(2)


def test_ask_project_message_opens_the_picker_with_the_window_callbacks():
    seen = []
    picker = SimpleNamespace(ask=lambda *a: seen.append(a))
    cb = SimpleNamespace(on_project_chosen=print, on_project_cancelled=repr)
    win = MagicMock(picker=picker, _project_keys={"acme": "Acme", "globex": "Globex"}, cb=cb)
    make_handlers(win)["ask_project"]("acme")
    assert seen == [({"acme": "Acme", "globex": "Globex"}, "acme", print, repr)]
