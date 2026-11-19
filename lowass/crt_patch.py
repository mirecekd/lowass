# lowass/crt_patch.py
"""Silences a harmless crash in amazon-transcribe: data that arrives after a stream was cancelled.

When live_stream.py cancels a receiver (a discarded or replaced stream), the pending chunk Future is cancelled. The CRT
thread then calls `set_result` on it and the library raises InvalidStateError, which awscrt prints as a traceback.
Nothing breaks, but the console fills with errors. The patched callbacks skip cancelled futures."""
from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger("lowass.crt_patch")


def _on_body(self: Any, chunk: bytes, **_kwargs: Any) -> None:
    with self._chunk_lock:
        while self._chunk_futures:
            future = self._chunk_futures.pop(0)
            if future.set_running_or_notify_cancel():  # False = it was cancelled: try the next waiter
                future.set_result(chunk)
                return
        self._received_chunks.append(chunk)


def _on_complete(self: Any, completion_future: Any) -> None:  # the name matches the library's own signature
    with self._chunk_lock:
        while self._chunk_futures:
            future = self._chunk_futures.pop(0)
            if future.set_running_or_notify_cancel():
                future.set_result(b"")
                return


def apply() -> bool:
    """Patch once; returns False (and changes nothing) when the library looks different from what was tested."""
    try:
        import amazon_transcribe.httpsession as http
        cls: Any = http.AwsCrtHttpResponse
        if not (hasattr(cls, "_on_body") and hasattr(cls, "_on_complete")):
            return False
        if getattr(cls, "_lowass_patched", False):
            return True
        setattr(cls, "_on_body", _on_body)  # noqa: B010 - the class is third-party and typed without these attributes
        setattr(cls, "_on_complete", _on_complete)  # noqa: B010
        setattr(cls, "_lowass_patched", True)  # noqa: B010
        return True
    except Exception:  # a missing or changed library must never stop the app: the traceback is only noise
        log.warning("could not patch amazon-transcribe (harmless)", exc_info=True)
        return False
