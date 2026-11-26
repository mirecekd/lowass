# lowass/speaker_watch.py
"""Background watcher: who is speaking in the Microsoft Teams gallery (the coloured tile border, see
scripts/speaker_probe.py), reported as {"t", "name", "speaking"} events to a callback. Windows only at run time: every
Windows / mss / pywinauto import is lazy, so the module imports everywhere. It never prints, never writes files and never
raises to the caller; problems go to the logger (each distinct message once, no participant names). Pixels are measured
and dropped, never kept."""
from __future__ import annotations

import contextlib
import logging
import threading
import time
from collections.abc import Callable
from types import SimpleNamespace

from scripts.speaker_probe_core import SpeakerTracker

from .speaker_frame import RECT_REFRESH_SECONDS, grab_box, grab_rgb, measure_tiles

RETRY_SECONDS = 5.0
MINIMISED_POLL_SECONDS = 0.5
STOP_JOIN_SECONDS = 2.0
WAITING_TEXT = "speaker watch: waiting for a Teams meeting window"
WATCHING_TEXT = "speaker watch: watching a Teams meeting window"
OUTSIDE_TEXT = "speaker watch: a participant tile is partly outside the visible window / screen; its ring is cut"


class _WindowsBackend:
    """UI Automation + screen grab (Windows). Only used inside the watch thread."""

    def __init__(self) -> None:
        self._args = SimpleNamespace(pid=None, depth=40, max_elements=20000)

    def find_window(self):
        from scripts.meeting_log import choose_window

        return choose_window(self._args)  # SystemExit when Teams or its meeting is not there

    def is_minimised(self, root) -> bool:
        from scripts.meeting_log import is_minimised

        return is_minimised(root)

    def window_rect(self, root):
        from scripts.ui_probe_uia import read_element

        return read_element(root)["rect"]

    def tile_rects(self, root):
        from scripts.meeting_log import snapshot
        from scripts.speaker_probe_core import read_rects

        return read_rects(snapshot(root, self._args))

    def screen(self):
        import mss

        return mss.MSS()


def _make_backend() -> _WindowsBackend:
    return _WindowsBackend()


def _com_init():
    """UI Automation needs COM initialised in every thread that uses it. Returns the matching uninitialise call or None."""
    with contextlib.suppress(Exception):
        import comtypes  # type: ignore[import-not-found]  # Windows only (the COM layer of pywinauto)

        comtypes.CoInitialize()
        return comtypes.CoUninitialize
    with contextlib.suppress(Exception):
        import pythoncom  # type: ignore[import-not-found]  # Windows only (pywin32)

        pythoncom.CoInitialize()
        return pythoncom.CoUninitialize
    return None


class SpeakerWatch:
    def __init__(self, on_event: Callable[[dict], None], fps: float = 5.0, log: logging.Logger | None = None) -> None:
        self._on_event = on_event
        self._fps = fps
        self._log = log or logging.getLogger("lowass.speaker_watch")
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._state = ""
        self._warned: set[str] = set()
        self._seen = ""

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="speaker-watch")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread and thread is not threading.current_thread():
            thread.join(STOP_JOIN_SECONDS)

    def _note_state(self, text: str) -> None:
        if text != self._state:
            self._state = text
            self._log.info(text)

    def _warn(self, text: str) -> None:
        if text not in self._warned:
            self._warned.add(text)
            self._log.warning(text)

    def _run(self) -> None:
        uninit = _com_init()
        try:
            while not self._stop.is_set():
                try:
                    backend = _make_backend()
                    root = backend.find_window()
                except SystemExit:  # Teams or its meeting is not there (yet)
                    self._note_state(WAITING_TEXT)
                    self._stop.wait(RETRY_SECONDS)
                    continue
                except Exception as exc:  # noqa: BLE001 - the watcher must survive any UIA failure
                    self._note_state(WAITING_TEXT)
                    self._warn(f"speaker watch: cannot look for the meeting window: {exc!r}")
                    self._stop.wait(RETRY_SECONDS)
                    continue
                self._note_state(WATCHING_TEXT)
                try:
                    self._watch(backend, root)
                except (Exception, SystemExit) as exc:  # noqa: BLE001 - any failure means: look for the window again
                    self._warn(f"speaker watch: frame loop failed, looking for the window again: {exc!r}")
                    self._stop.wait(RETRY_SECONDS)
        finally:
            if uninit:
                with contextlib.suppress(Exception):
                    uninit()

    def _watch(self, backend, root) -> None:
        tracker = SpeakerTracker()
        rects: dict = {}
        window = (0, 0, 0, 0)
        next_rects = 0.0
        outside_warned: set = set()
        with backend.screen() as sct:
            while not self._stop.is_set():
                started = time.monotonic()
                if backend.is_minimised(root):
                    self._stop.wait(MINIMISED_POLL_SECONDS)
                    continue
                if started >= next_rects:
                    next_rects = started + RECT_REFRESH_SECONDS
                    window = backend.window_rect(root)
                    rects = backend.tile_rects(root)
                    seen = f"speaker watch: {len(rects)} tiles, window {window}"
                    if seen != self._seen:  # diagnostics only, no names
                        self._seen = seen
                        self._log.info(seen)
                box = grab_box(sct, window)
                if box and rects:
                    self._frame(sct, box, rects, tracker, outside_warned)
                self._stop.wait(max(0.0, 1.0 / self._fps - (time.monotonic() - started)))

    def _frame(self, sct, box, rects, tracker, outside_warned: set) -> None:
        img = grab_rgb(sct, box)
        now = time.time()
        stats, outside = measure_tiles(img, box, rects, outside_warned)
        if outside:
            self._warn(OUTSIDE_TEXT)
        for event in tracker.feed(now, stats):
            self._log.info("speaker watch: a tile %s", "lit up" if event["speaking"] else "went dark")
            try:
                self._on_event(event)
            except Exception as exc:  # noqa: BLE001 - the callback must not kill the loop
                self._warn(f"speaker watch: the event callback failed: {exc!r}")
