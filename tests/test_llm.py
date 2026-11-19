# tests/test_llm.py
import httpx
import pytest

from lowass.llm import Completer, LlmError

KEY = "sk-secret-123"


class FakeResponse:
    def __init__(self, status: int = 200, payload: dict | None = None):
        self.status = status
        self.payload = payload if payload is not None else {"choices": [{"message": {"content": "  hello \n"}}]}

    def raise_for_status(self) -> None:
        if self.status >= 400:
            request = httpx.Request("POST", "http://x/chat/completions")
            raise httpx.HTTPStatusError("bad", request=request, response=httpx.Response(self.status, request=request))

    def json(self) -> dict:
        return self.payload


def make(response: FakeResponse | Exception):
    calls: list[dict] = []

    def post(url, headers, json, timeout):
        calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
        if isinstance(response, Exception):
            raise response
        return response

    return Completer("http://litellm:4000/", KEY, "m1", timeout=5.0, post=post), calls


def test_builds_request_and_parses_answer():
    completer, calls = make(FakeResponse())
    assert completer.complete("sys", "usr", max_tokens=100) == "hello"
    call = calls[0]
    assert call["url"] == "http://litellm:4000/chat/completions"
    assert call["headers"]["Authorization"] == f"Bearer {KEY}"
    assert call["timeout"] == 5.0
    assert call["json"] == {
        "model": "m1",
        "max_tokens": 100,
        "messages": [{"role": "system", "content": "sys"}, {"role": "user", "content": "usr"}],
    }


def test_http_error_becomes_llm_error_without_key():
    completer, _ = make(FakeResponse(status=500))
    with pytest.raises(LlmError) as info:
        completer.complete("s", "u")
    assert "500" in str(info.value)
    assert KEY not in str(info.value)


def test_network_error_hides_key():
    completer, _ = make(httpx.ConnectError(f"cannot connect with {KEY}"))
    with pytest.raises(LlmError) as info:
        completer.complete("s", "u")
    assert KEY not in str(info.value)
    assert "ConnectError" in str(info.value)


def test_unexpected_answer_shape_is_llm_error():
    completer, _ = make(FakeResponse(payload={"error": "nope"}))
    with pytest.raises(LlmError):
        completer.complete("s", "u")
