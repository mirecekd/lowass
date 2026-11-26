# tests/test_speaker_watch.py
"""lowass/speaker_watch.py on Linux: the Windows backend (UIA + mss) is replaced by fakes; fake names only."""
import logging
import threading
import time
from types import SimpleNamespace
from typing import ClassVar

import pytest

from lowass import speaker_watch
from lowass.speaker_watch import SpeakerWatch

SIZE = 100


class FakeScreen:
    monitors: ClassVar[list[dict]] = [{"left": 0, "top": 0, "width": SIZE, "height": SIZE}]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def grab(self, box):
        return SimpleNamespace(bgra=bytes(box["width"] * box["height"] * 4), width=box["width"], height=box["height"])


class FakeBackend:
    def __init__(self, minimised: bool = False):
        self.minimised = minimised

    def find_window(self):
        return "root"

    def is_minimised(self, root) -> bool:
        return self.minimised

    def window_rect(self, root):
        return (0, 0, SIZE, SIZE)

    def tile_rects(self, root):
        return {"Anna": (0, 0, 50, 50), "Boris": (50, 50, 100, 100)}

    def screen(self):
        return FakeScreen()


class FakeTracker:
    """Reports one event per frame, so the test does not depend on pixel statistics."""

    def feed(self, t, stats):
        assert set(stats) == {"Anna", "Boris"}
        return [{"t": t, "name": "Anna", "speaking": True}]


@pytest.fixture(autouse=True)
def fast(monkeypatch):
    monkeypatch.setattr(speaker_watch, "RETRY_SECONDS", 0.01)
    monkeypatch.setattr(speaker_watch, "SpeakerTracker", FakeTracker)


def wait_for(condition, seconds: float = 3.0) -> bool:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if condition():
            return True
        time.sleep(0.005)
    return condition()


def thread_alive() -> bool:
    return any(t.name == "speaker-watch" and t.is_alive() for t in threading.enumerate())


def test_events_reach_the_callback_and_stop_ends_the_thread(monkeypatch):
    monkeypatch.setattr(speaker_watch, "_make_backend", FakeBackend)
    events: list[dict] = []
    watch = SpeakerWatch(events.append, fps=100.0)
    watch.start()
    assert wait_for(lambda: len(events) >= 2)
    assert events[0]["name"] == "Anna" and events[0]["speaking"] is True and "t" in events[0]
    begin = time.monotonic()
    watch.stop()
    assert time.monotonic() - begin < 1.0
    assert not thread_alive()


def test_a_failing_find_window_retries_and_logs_the_state_once(monkeypatch, caplog):
    calls = {"n": 0}

    class Flaky(FakeBackend):
        def find_window(self):
            calls["n"] += 1
            if calls["n"] <= 3:
                raise SystemExit("Teams is not running")
            if calls["n"] == 4:
                raise RuntimeError("boom")
            return "root"

    monkeypatch.setattr(speaker_watch, "_make_backend", Flaky)
    events: list[dict] = []
    watch = SpeakerWatch(events.append, fps=100.0)
    with caplog.at_level(logging.INFO, logger="lowass.speaker_watch"):
        watch.start()
        assert wait_for(lambda: len(events) >= 1)
        watch.stop()
    assert calls["n"] >= 5
    assert [r.getMessage() for r in caplog.records].count(speaker_watch.WAITING_TEXT) == 1
    assert sum("boom" in r.getMessage() for r in caplog.records) == 1
    assert not thread_alive()


def test_an_exception_in_the_frame_loop_finds_the_window_again(monkeypatch):
    made = []

    def make():
        backend = FakeBackend()
        made.append(backend)
        if len(made) == 1:
            backend.tile_rects = lambda root: (_ for _ in ()).throw(RuntimeError("uia gone"))
        return backend

    monkeypatch.setattr(speaker_watch, "_make_backend", make)
    events: list[dict] = []
    watch = SpeakerWatch(events.append, fps=100.0)
    watch.start()
    assert wait_for(lambda: len(events) >= 1)
    watch.stop()
    assert len(made) >= 2


def test_an_exception_in_on_event_does_not_kill_the_loop(monkeypatch, caplog):
    monkeypatch.setattr(speaker_watch, "_make_backend", FakeBackend)
    calls = {"n": 0}

    def bad(event):
        calls["n"] += 1
        raise ValueError("callback broke")

    watch = SpeakerWatch(bad, fps=100.0)
    with caplog.at_level(logging.WARNING, logger="lowass.speaker_watch"):
        watch.start()
        assert wait_for(lambda: calls["n"] >= 3)
        watch.stop()
    assert sum("callback broke" in r.getMessage() for r in caplog.records) == 1
    assert not thread_alive()


def test_a_minimised_window_is_skipped(monkeypatch):
    monkeypatch.setattr(speaker_watch, "_make_backend", lambda: FakeBackend(minimised=True))
    events: list[dict] = []
    watch = SpeakerWatch(events.append, fps=100.0)
    watch.start()
    time.sleep(0.2)
    watch.stop()
    assert events == []
    assert not thread_alive()


def test_no_tiles_closes_the_lit_names(monkeypatch):
    fed = []

    class Tracker:
        def feed(self, t, stats):
            fed.append(stats)
            return [{"t": t, "name": "Anna", "speaking": False}]

    backend = FakeBackend()
    backend.tile_rects = lambda root: {}
    monkeypatch.setattr(speaker_watch, "_make_backend", lambda: backend)
    monkeypatch.setattr(speaker_watch, "SpeakerTracker", Tracker)
    events: list[dict] = []
    watch = SpeakerWatch(events.append, fps=100.0)
    watch.start()
    assert wait_for(lambda: len(events) >= 1)
    watch.stop()
    assert fed[0] == {}
    assert events[0] == {"t": events[0]["t"], "name": "Anna", "speaking": False}
