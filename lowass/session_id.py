# lowass/session_id.py
"""A unique id for every meeting: two meetings can never share a folder (they would be merged into one)."""
from __future__ import annotations

import threading
import time

_LOCK = threading.Lock()
_issued: set[str] = set()


def new_session_id() -> str:
    """Second + millisecond; if that id was already given out a counter is appended."""
    now = time.time()
    base = f"{time.strftime('%Y%m%d-%H%M%S', time.localtime(now))}{int(now * 1000) % 1000:03d}"
    with _LOCK:
        sid, n = base, 0
        while sid in _issued:
            n += 1
            sid = f"{base}-{n}"
        _issued.add(sid)
    return sid
