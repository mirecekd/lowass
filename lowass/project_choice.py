# lowass/project_choice.py
"""The 'which project is starting?' decision: when to ask and what the answer does (no tkinter; the dialog is project_picker.py).

Private stays ON while the question is open, so nothing is heard before the choice. A project button switches the project
(this rotates the meeting) and then leaves Private. Closing the dialog keeps Private on."""
from __future__ import annotations

import logging
import threading
from collections.abc import Callable

from .project_picker_logic import should_ask

log = logging.getLogger("lowass.project")
CANCELLED = "PRIVATE: choose a project to start listening"


class ProjectChoice:
    def __init__(self, enabled: bool, project_count: int, post: Callable[[str, str], None], current: Callable[[], str],
                 meeting_empty: Callable[[], bool], switch: Callable[[str], None], release: Callable[[], None]):
        """`switch(key)` returns when the project is connected (it may fail: then `current()` is not the key);
        `release()` leaves Private."""
        self.enabled, self.project_count, self.post = enabled, project_count, post
        self.current, self.meeting_empty, self.switch, self.release = current, meeting_empty, switch, release

    def wanted(self) -> bool:
        return should_ask(self.enabled, self.project_count, self.meeting_empty())

    def request(self) -> None:
        """The window shows the dialog (a message, because this may be called from any thread)."""
        self.post("ask_project", self.current())

    def ask_if_wanted(self) -> bool:
        if not self.wanted():
            return False
        self.request()
        return True

    def chosen(self, key: str) -> None:
        """A project button was pressed (Tk thread): the switch is slow, so it runs in a thread."""
        threading.Thread(target=self.apply, args=(key,), daemon=True, name="project-choice").start()

    def apply(self, key: str) -> None:
        if key != self.current():
            self.switch(key)
            if self.current() != key:  # the switch failed (the window already says why): do not listen into the wrong project
                self.post("status", CANCELLED)
                return
            self.post("project", key)
        log.info("meeting starts in project %s", key)
        self.release()

    def cancelled(self) -> None:
        self.post("status", CANCELLED)
