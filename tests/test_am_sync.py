# tests/test_am_sync.py
from __future__ import annotations

import threading

from lowass.am_sync import MemorySync
from lowass.memlink import FACTS, SENTENCE, SUMMARY, TURN, Event


class FakeClient:
    def __init__(self, fail: int = 0, always_fail: bool = False):
        self.calls: list[tuple[str, str]] = []
        self.fail, self.always_fail, self.healthy, self.fail_start = fail, always_fail, True, False

    def _ok(self, call: tuple[str, str]) -> bool:
        if self.fail > 0:
            self.fail -= 1
            return False
        if self.always_fail:
            return False
        self.calls.append(call)
        return True

    def health(self) -> bool:
        return self.healthy

    def start_session(self, session: str, project: str, cwd: str = "/lowass") -> bool:
        return not self.fail_start and self._ok(("start", session))

    def end_session(self, session: str) -> bool:
        return self._ok(("end", session))

    def observe(self, payload: dict) -> bool:
        return self._ok(("observe", payload["data"]["prompt"]))

    def remember(self, payload: dict) -> bool:
        return self._ok(("remember", payload["content"]))

    def search(self, query: str, project: str | None = None, limit: int = 5) -> list | None:
        return []

    def kinds(self) -> list[str]:
        return [k for k, _ in self.calls]


def ev(text: str = "hi", kind: str = SENTENCE, project: str = "acme", session: str = "s1", seq: int = 0) -> Event:
    return Event(kind, project, session, text, 1000.0, seq=seq)


def make(client: FakeClient, **kw) -> tuple[MemorySync, list[float]]:
    delays: list[float] = []
    return MemorySync(client, wait=delays.append, **kw), delays


def test_add_filters():
    sync, _ = make(FakeClient())
    assert sync.add(ev()) is True
    for project in ("Private", "private", "TESTING", "Testing"):
        assert sync.add(ev(project=project)) is False
    assert sync.add(ev("  ")) is False and sync.status["waiting"] == 1
    assert make(FakeClient(), enabled=False)[0].add(ev()) is False


def test_private_drops_waiting_and_off_accepts_again():
    sync, _ = make(FakeClient())
    sync.add(ev())
    sync.set_private(True)
    assert sync.status["private"] is True and sync.status["waiting"] == 0
    assert sync.add(ev()) is False
    sync.set_private(False)
    assert sync.status["waiting"] == 0 and sync.add(ev()) is True


def test_start_session_once_and_before_first_observe():
    c = FakeClient()
    sync, _ = make(c)
    for i, sid in enumerate(("s1", "s1", "s2")):
        sync.add(ev(f"x{i}", session=sid))
    assert sync.flush() is True and sync.status["sent"] == 3
    assert c.kinds() == ["start", "observe", "observe", "start", "observe"] and c.calls[0][1] == "lowass-s1"


def test_start_failure_sends_nothing_and_loses_nothing():
    c = FakeClient()
    c.fail_start = True
    sync, _ = make(c)
    sync.add(ev())
    assert sync._send_round() is False and c.calls == []
    assert (sync.status["waiting"], sync.status["failed"]) == (1, 1)
    c.fail_start = False
    assert sync._send_round() is True and c.kinds() == ["start", "observe"]


def test_first_failure_stops_round_and_keeps_order():
    c = FakeClient()
    sync, _ = make(c)
    for i in range(6):
        sync.add(ev(f"t{i}", seq=i))
    original = c.observe
    c.observe = lambda p: not p["data"]["prompt"].endswith("t2") and original(p)  # type: ignore[method-assign]
    assert sync._send_round() is False and sync.status["waiting"] == 4
    del c.observe
    assert sync._send_round() is True
    assert [p.split("] ")[1] for k, p in c.calls if k == "observe"] == [f"t{i}" for i in range(6)]


def test_backoff_doubles_caps_and_resets():
    c = FakeClient(always_fail=True)
    sync, delays = make(c)
    sync.add(ev())
    assert sync.flush(max_rounds=8) is False
    assert delays == [1.0, 2.0, 4.0, 8.0, 16.0, 30.0, 30.0, 30.0]
    c.always_fail = False
    assert sync.flush() is True and len(delays) == 8
    sync.add(ev())
    c.always_fail = True
    sync.flush(max_rounds=1)
    assert delays[-1] == 1.0  # the success reset the backoff


def test_facts_coalesce_to_the_newest():
    c = FakeClient()
    sync, _ = make(c)
    for text in ("sheet 0", "sheet 1", "sheet 2"):
        sync.add(ev(text, FACTS))
    sync.add(ev("other sheet", FACTS, session="s2"))
    assert sync.flush() is True and sync.status["failed"] == 0
    sent = [t.split("\n")[1] for k, t in c.calls if k == "remember"]
    assert sent == ["sheet 2", "other sheet"]
    sync.add(ev("chat", TURN, session="s3"))
    sync.add(ev("sum", SUMMARY, session="s3"))
    sync.flush()
    assert c.kinds()[-3:] == ["start", "observe", "remember"]


def test_end_meeting_waits_for_the_events_and_ends_once():
    c = FakeClient()
    sync, _ = make(c)
    sync.add(ev())
    sync.end_meeting("s1", "acme")
    sync.flush()
    assert c.kinds() == ["start", "observe", "end"]
    assert c.calls[-1] == ("end", "lowass-s1")
    sync.flush()
    assert c.kinds().count("end") == 1
    sync.add(ev(session="s3"))
    sync.flush()
    sync.end_meeting("s3", "acme")
    sync.flush()
    assert c.calls[-1] == ("end", "lowass-s3")


def test_end_meeting_of_a_session_never_started_does_not_call_the_client():
    c = FakeClient()
    sync, _ = make(c)
    sync.end_meeting("never", "acme")
    assert sync.flush() is True and c.calls == []


def test_end_failure_is_retried():
    c = FakeClient()
    sync, delays = make(c)
    sync.add(ev())
    sync.flush()
    sync.end_meeting("s1", "acme")
    c.fail = 1
    assert sync.flush() is True and (c.kinds()[-1], delays) == ("end", [1.0])


def test_reset_session_leaves_other_sessions():
    sync, _ = make(FakeClient())
    sync.add(ev(session="s1"))
    sync.add(ev(session="s2"))
    sync.reset("s1")
    assert sync.status["waiting"] == 1
    sync.reset()
    assert sync.status["waiting"] == 0


def test_stop_flushes_once_and_does_not_hang_on_a_failing_client():
    sync, delays = make(FakeClient(always_fail=True))
    sync.add(ev())
    sync.stop(0.2)
    sync.stop(0.2)
    assert delays == []
    assert (sync.status["waiting"], sync.status["failed"]) == (1, 1)


def test_thread_sends_and_start_stop_are_idempotent():
    c = FakeClient()
    sync = MemorySync(c, interval=0.01)
    sync.start()
    sync.start()
    sync.add(ev())
    sync.stop(0.3)
    sync.stop(0.3)
    assert c.kinds() == ["start", "observe"] and sync.status["waiting"] == 0
    block = threading.Event()  # a thread stuck in a network call must not hang stop()
    c.observe = lambda payload: block.wait(2)  # type: ignore[method-assign]
    sync = MemorySync(c, interval=0.01)
    sync.add(ev())
    sync.start()
    sync.stop(0.1)
    block.set()


def test_outbox_limit_with_long_outage_counts_dropped():
    sync, _ = make(FakeClient(always_fail=True), limit=5)
    for _ in range(12):
        sync.add(ev())
    sync.flush(max_rounds=3)
    assert (sync.status["waiting"], sync.status["dropped"]) == (5, 7)


def test_client_exception_never_escapes():
    c = FakeClient()

    def boom(*_a):
        raise RuntimeError("down")

    c.observe = c.health = boom  # type: ignore[method-assign]
    sync, _ = make(c)
    sync.add(ev())
    assert sync._send_round() is False
    assert sync.status["waiting"] == 1 and sync.status["up"] is False


def test_add_from_many_threads_loses_nothing():
    c = FakeClient()
    sync, _ = make(c, limit=5000)

    def work(t: int) -> None:
        for i in range(50):
            sync.add(ev(f"t{t}-{i}", session=f"s{t}", seq=i))

    threads = [threading.Thread(target=work, args=(t,)) for t in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sync.status["waiting"] == 1000 and sync.flush() is True
    assert (c.kinds().count("observe"), c.kinds().count("start")) == (1000, 20)
