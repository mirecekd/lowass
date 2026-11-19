# tests/test_crt_patch.py
"""crt_patch: a chunk Future cancelled by live_stream.py must not make the CRT callback raise InvalidStateError."""
from concurrent.futures import Future
from threading import Lock

import pytest

from lowass import crt_patch


def bare_response():
    import amazon_transcribe.httpsession as http

    r = object.__new__(http.AwsCrtHttpResponse)  # no real connection: only the attributes the callbacks use
    r._chunk_lock, r._chunk_futures, r._received_chunks = Lock(), [], []
    return r


def test_the_unpatched_library_really_raises_on_a_cancelled_future():
    """Proves the test setup reproduces the field traceback (otherwise the patch test below proves nothing)."""
    import amazon_transcribe.httpsession as http

    original = http.AwsCrtHttpResponse
    if getattr(original, "_lowass_patched", False):
        pytest.skip("already patched in this process")
    r, f = bare_response(), Future()
    f.cancel()
    r._chunk_futures.append(f)
    with pytest.raises(Exception, match="CANCELLED"):
        r._on_body(b"x")


def test_patched_callbacks_skip_a_cancelled_waiter_and_serve_the_next_one():
    assert crt_patch.apply() is True
    r = bare_response()
    cancelled, live = Future(), Future()
    cancelled.cancel()
    r._chunk_futures += [cancelled, live]
    r._on_body(b"data")
    assert live.result(0) == b"data" and r._chunk_futures == [] and r._received_chunks == []


def test_patched_body_without_a_waiter_is_buffered_and_complete_gives_an_empty_chunk():
    crt_patch.apply()
    r = bare_response()
    r._on_body(b"early")
    assert r._received_chunks == [b"early"]
    waiter = Future()
    r._chunk_futures.append(waiter)
    r._on_complete(None)
    assert waiter.result(0) == b""


def test_apply_twice_is_harmless():
    assert crt_patch.apply() and crt_patch.apply()
