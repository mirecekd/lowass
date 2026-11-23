# lowass/am_sync.py
"""The background sender: memlink Events from any thread go to an Outbox and to agentmemory from ONE daemon thread.
add() never blocks on the network and nothing here raises into LOWASS."""
from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable

from lowass import memlink
from lowass.memlink import Event, MemoryClient

log = logging.getLogger("lowass.am_sync")
MAX_BACKOFF = 30.0


class MemorySync:
    def __init__(self, client: MemoryClient, names: dict[str, str] | None = None, enabled: bool = True,
                 excluded: tuple[str, ...] = memlink.EXCLUDED_PROJECTS, limit: int = 2000, batch: int = 20,
                 interval: float = 1.0, clock: Callable[[], float] = time.time,
                 wait: Callable[[float], object] | None = None):
        self._client, self._names, self._enabled, self._excluded = client, names, enabled, excluded
        self._batch, self._interval, self._clock = max(1, batch), interval, clock
        self._stopping = threading.Event()
        self._wait = wait or self._stopping.wait
        self._outbox = memlink.Outbox(limit)
        self._lock = threading.Lock()  # guards the outbox and the state below; never held during a client call
        self._round_lock = threading.Lock()
        self._private = False
        self._started: set[str] = set()  # sessions already started on the server
        self._ends: dict[str, str] = {}  # sessions whose meeting is over -> LOWASS project
        self._sent = self._failed = 0
        self._delay = 0.0
        self._up = False
        self._thread: threading.Thread | None = None
        self._closed = False

    def add(self, e: Event) -> bool:
        if not self._enabled or not memlink.allowed(e.project, self._excluded) or not e.text.strip():
            return False
        with self._lock:
            if self._private:
                return False
            self._outbox.put(e)
        return True

    def set_private(self, on: bool) -> None:
        with self._lock:
            self._private = on
            if on:
                self._outbox.clear()

    def end_meeting(self, session: str, project: str) -> None:
        if self._enabled and memlink.allowed(project, self._excluded):
            with self._lock:
                self._ends[session] = project

    def reset(self, session: str | None = None) -> None:
        with self._lock:
            self._outbox.clear(session)
            if session is None:
                self._ends.clear()
            else:
                self._ends.pop(session, None)

    @property
    def status(self) -> dict:
        with self._lock:
            return {"enabled": self._enabled, "up": self._up, "waiting": len(self._outbox), "sent": self._sent,
                    "dropped": self._outbox.dropped, "failed": self._failed, "private": self._private}

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stopping.clear()
        self._closed = False
        self._thread = threading.Thread(target=self._run, name="am-sync", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        if self._closed:
            return
        self._closed = True
        deadline = self._clock() + timeout
        self._stopping.set()
        thread = self._thread
        if thread is not None:
            thread.join(max(0.0, timeout))
            if thread.is_alive():
                return  # stuck in a network call; it is a daemon
        self.flush(wait_on_failure=False, deadline=deadline)

    def flush(self, max_rounds: int = 1000, wait_on_failure: bool = True, deadline: float | None = None) -> bool:
        """Send until nothing waits; True when all went out. A failed round waits the backoff, unless wait_on_failure
        is False (then the first failure ends the flush)."""
        for _ in range(max_rounds):
            if self._idle():
                return True
            if deadline is not None and self._clock() >= deadline:
                return False
            if not self._send_round():
                if not wait_on_failure:
                    return False
                self._wait(self._delay)
        return self._idle()

    def _idle(self) -> bool:
        with self._lock:
            return not len(self._outbox) and not self._ends

    def _run(self) -> None:
        while not self._stopping.is_set():
            try:
                ok = self._send_round()
            except Exception as exc:  # noqa: BLE001 - thread must survive
                log.warning("am_sync round crashed: %s", type(exc).__name__)
                ok = False
            if not ok:
                self._wait(self._delay)
            elif self._idle():
                self._wait(self._interval)

    def _send_round(self) -> bool:
        """One pass over up to `batch` events. True when it ended without a failure."""
        with self._round_lock:
            with self._lock:
                self._drop_old_facts()
                batch = self._outbox.take(self._batch)
            for e in batch:
                with self._lock:
                    if self._private:
                        return True
                if not self._deliver(e):
                    return self._failure()
                with self._lock:
                    self._outbox.done([e])
                    self._sent += 1
                self._succeeded()
            return self._finish_ends() or self._failure()

    def _drop_old_facts(self) -> None:
        """FACTS are an overwritten sheet: keep only the newest per session (caller holds the lock)."""
        items = self._outbox.take(len(self._outbox))
        newest = {e.session: i for i, e in enumerate(items) if e.kind == memlink.FACTS}
        self._outbox.done([e for i, e in enumerate(items) if e.kind == memlink.FACTS and newest[e.session] != i])

    def _deliver(self, e: Event) -> bool:
        try:
            if e.session not in self._started:
                if not self._client.start_session(memlink.session_id(e.session),
                                                  memlink.session_project(e.project, self._names)):
                    return False
                self._started.add(e.session)
            if memlink.is_memory(e):
                return bool(self._client.remember(memlink.remember_payload(e, self._names)))
            return bool(self._client.observe(memlink.observe_payload(e, self._names)))
        except Exception as exc:  # noqa: BLE001
            log.warning("am_sync send failed: %s", type(exc).__name__)
            return False

    def _finish_ends(self) -> bool:
        """End the sessions that are over and fully sent; one never started is just forgotten."""
        with self._lock:
            waiting = {e.session for e in self._outbox.take(len(self._outbox))}
            ready = [s for s in self._ends if s not in waiting]
        for session in ready:
            if session in self._started:
                try:
                    if not self._client.end_session(memlink.session_id(session)):
                        return False
                except Exception as exc:  # noqa: BLE001
                    log.warning("am_sync end_session failed: %s", type(exc).__name__)
                    return False
                self._started.discard(session)
                self._succeeded()
            with self._lock:
                self._ends.pop(session, None)
        return True

    def _succeeded(self) -> None:
        self._delay = 0.0
        self._up = True

    def _failure(self) -> bool:
        self._delay = 1.0 if not self._delay else min(MAX_BACKOFF, self._delay * 2)
        try:
            up = bool(self._client.health())
        except Exception:  # noqa: BLE001
            up = False
        with self._lock:
            self._failed += 1
            self._up = up
        return False
