# lowass/closing.py
"""The Close meeting button: stop listening (Private), let what is running finish, close the meeting (summary, store,
copy to agentmemory) and stay in Private until the user presses Play.

The Private GATE is set directly and NOT through Controls.set_private: that also tells agentmemory, which throws the
waiting events away, and here exactly those events (the end of this meeting) have to go out."""
from __future__ import annotations

import logging
import threading
import time
from typing import Any

log = logging.getLogger("lowass.closing")
_RUNNING = threading.Lock()
PRIVATE_HINT = "PRIVATE: press Private to listen again"


def close_meeting(app: Any) -> None:
    """Called from the UI thread: everything slow runs in a thread."""
    if not _RUNNING.acquire(blocking=False):
        app.ui.post("err", "A meeting is already being closed.")
        return
    threading.Thread(target=_run, args=(app,), daemon=True, name="close-meeting").start()


def _run(app: Any) -> None:
    post = app.ui.post
    try:
        gate = app.flow.private
        gate.set()
        post("private", "1")  # the red button, without calling on_private
        post("status", "closing the meeting: the last sentence finishes...")
        end = time.monotonic() + float(getattr(gate, "drain_sec", 0.0)) + 2.0
        while not gate.muted() and time.monotonic() < end:
            time.sleep(0.2)
        agent = app.session.agent
        closed = app.meeting.rotate(app.project)  # the next, empty meeting starts at once; it is not heard (Private)
        if agent:
            agent.clear()
        app.transcript.clear()
        app.assist.reset()
        app.flow.finish(closed, agent)  # summary (shown in the window), local store, copy to agentmemory
        post("status", _result(app, closed))
    except Exception as exc:
        log.exception("closing the meeting failed")
        post("err", f"Closing the meeting failed: {type(exc).__name__}: {exc}")
        post("status", PRIVATE_HINT)
    finally:
        _RUNNING.release()


def _result(app: Any, closed: Any) -> str:
    if closed.lines == 0 and not closed.pending:
        return f"Nothing to close (the meeting was empty). {PRIVATE_HINT}"
    app.link.end_meeting(closed.sid, closed.project)
    sent = app.link.flush(30.0)
    waiting = app.link.sync.status["waiting"] if app.link.sync is not None else 0
    note = "" if sent else f", agentmemory not reachable ({waiting} events wait and will be retried)"
    return f"Meeting closed: summary and memory done{note}. {PRIVATE_HINT}"
