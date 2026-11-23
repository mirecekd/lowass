# tests/test_closing.py
"""Close meeting: Private first, let the running work finish, close the meeting, end in Private with a status-line confirmation."""
import threading
from types import SimpleNamespace

from lowass import closing
from lowass.freeze import PrivateGate


class Fake:
    def __init__(self, lines=5, flush_ok=True, boom=False, drain=0.0):
        self.events, self.posts = [], []
        self.gate = PrivateGate(drain_sec=drain)
        self.closed = SimpleNamespace(sid="s1", project="acme", lines=lines, pending="")
        self.flush_ok, self.boom = flush_ok, boom
        self.link = SimpleNamespace(set_private=lambda on: self.events.append(("link_private", on)),
                                    end_meeting=lambda s, p: self.events.append(("end", s, p)),
                                    flush=self._flush, sync=SimpleNamespace(status={"waiting": 7}))
        self.app = SimpleNamespace(
            ui=SimpleNamespace(post=lambda k, t: self.posts.append((k, t))), project="acme",
            flow=SimpleNamespace(private=self.gate, finish=self._finish),
            session=SimpleNamespace(agent=SimpleNamespace(clear=lambda: self.events.append(("agent_clear",)))),
            meeting=SimpleNamespace(rotate=self._rotate), transcript=SimpleNamespace(clear=lambda: self.events.append(("tr_clear",))),
            assist=SimpleNamespace(reset=lambda: self.events.append(("assist_reset",))), link=self.link)

    def _rotate(self, project):
        self.events.append(("rotate", self.gate.is_set()))  # was Private already on when the meeting was closed?
        return self.closed

    def _finish(self, closed, agent):
        if self.boom:
            raise RuntimeError("summary exploded")
        self.events.append(("finish", closed.sid))

    def _flush(self, timeout):
        self.events.append(("flush",))
        return self.flush_ok

    def run(self):
        closing.close_meeting(self.app)
        for t in threading.enumerate():
            if t.name == "close-meeting":
                t.join(10)


def test_private_is_on_before_the_meeting_is_closed_and_the_button_goes_red():
    f = Fake()
    f.run()
    assert ("rotate", True) in f.events and ("private", "1") in f.posts
    assert f.gate.is_set()  # and it stays on: the user presses Play when the next call starts


def test_the_order_is_rotate_clear_finish_end_flush_and_status_confirms():
    f = Fake()
    f.run()
    names = [e[0] for e in f.events]
    assert names == ["rotate", "agent_clear", "tr_clear", "assist_reset", "finish", "end", "flush"]
    status = [t for k, t in f.posts if k == "status"][-1]
    assert status.startswith("Meeting closed") and "Private" in status and "not reachable" not in status


def test_agentmemory_is_not_told_private_so_the_end_of_the_meeting_still_goes_out():
    f = Fake()
    f.run()
    assert not any(e[0] == "link_private" for e in f.events)


def test_an_unreachable_agentmemory_is_said_plainly_and_the_events_wait():
    f = Fake(flush_ok=False)
    f.run()
    assert "not reachable" in [t for k, t in f.posts if k == "status"][-1] and "7 events" in f.posts[-1][1]


def test_an_empty_meeting_says_so_and_sends_nothing():
    f = Fake(lines=0)
    f.run()
    assert "end" not in [e[0] for e in f.events] and "flush" not in [e[0] for e in f.events]
    assert "empty" in [t for k, t in f.posts if k == "status"][-1]


def test_a_failure_is_shown_the_status_returns_to_private_and_a_second_close_works():
    f = Fake(boom=True)
    f.run()
    assert any(k == "err" and "summary exploded" in t for k, t in f.posts)
    assert "press Private" in [t for k, t in f.posts if k == "status"][-1]
    f.boom, f.posts = False, []
    f.run()  # the lock was released
    assert [t for k, t in f.posts if k == "status"][-1].startswith("Meeting closed")


def test_a_second_click_while_closing_is_refused():
    f = Fake()
    assert closing._RUNNING.acquire(blocking=False)
    try:
        closing.close_meeting(f.app)
        assert f.posts == [("err", "A meeting is already being closed.")]
    finally:
        closing._RUNNING.release()


def test_it_waits_for_the_drain_so_the_last_sentence_is_not_lost():
    f = Fake(drain=0.4)
    f.run()
    assert f.gate.muted()  # closing only went on after the gate had drained
