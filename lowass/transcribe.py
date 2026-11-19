# lowass/transcribe.py
"""Amazon Transcribe streaming: one short streaming session per speech segment.

Credentials come from a NAMED AWS PROFILE in ~/.aws/config (boto3), never from role ARNs or keys in the project.
When the SSO login is missing or expired the worker starts the app's own device-code sign-in (sso_login.py).
"""
from __future__ import annotations

import asyncio
import io
import logging
import queue
import re
import threading
import time
import wave
from collections.abc import Callable
from typing import Any

import boto3
from amazon_transcribe.auth import StaticCredentialResolver
from amazon_transcribe.client import TranscribeStreamingClient
from amazon_transcribe.handlers import TranscriptResultStreamHandler
from botocore.exceptions import (
    NoCredentialsError,
    ProfileNotFound,
    SSOTokenLoadError,
    TokenRetrievalError,
    UnauthorizedSSOTokenError,
)

from . import crt_patch
from .languages import DEFAULT, order_for

log = logging.getLogger("lowass.transcribe")

LANG_RE = re.compile(r"^[a-z]{2,3}-[A-Z]{2}$")
LOGIN_ERRORS = (NoCredentialsError, TokenRetrievalError, UnauthorizedSSOTokenError, SSOTokenLoadError)


def check_languages(langs: list[str]) -> list[str]:
    """Transcribe allows one dialect per language (no en-US together with en-GB) and codes like cs-CZ."""
    if not langs:
        raise ValueError("transcribe.languages is empty")
    seen: set[str] = set()
    for code in langs:
        if not LANG_RE.match(code):
            raise ValueError(f"bad language code {code!r}, expected something like cs-CZ")
        base = code.split("-")[0]
        if base in seen:
            raise ValueError(f"only one dialect per language is allowed, got two {base}-* codes")
        seen.add(base)
    return langs


def stream_kwargs(langs: list[str]) -> dict[str, Any]:
    """One language = fixed; several = Transcribe identifies the language (also mid-segment switches)."""
    if len(langs) == 1:
        return {"language_code": langs[0]}
    return {"language_code": None, "identify_multiple_languages": True, "language_options": langs}


def wav_to_pcm(wav: bytes) -> bytes:
    with wave.open(io.BytesIO(wav), "rb") as wf:
        if wf.getframerate() != 16000 or wf.getnchannels() != 1 or wf.getsampwidth() != 2:
            raise ValueError("expected 16 kHz mono 16-bit WAV")
        return wf.readframes(wf.getnframes())


def friendly_error(exc: BaseException, profile: str) -> str:
    if isinstance(exc, ProfileNotFound):
        return f"AWS profile '{profile}' not found in ~/.aws/config (on Windows: %USERPROFILE%\\.aws\\config)."
    if isinstance(exc, LOGIN_ERRORS):
        return "AWS login missing or expired."
    text = str(exc)
    if "AccessDenied" in text or "not authorized" in text:
        return f"Profile '{profile}' may not call transcribe:StartStreamTranscription. Pick another profile in lowass.toml."
    return f"{type(exc).__name__}: {text[:160]}"


class _Collect(TranscriptResultStreamHandler):
    def __init__(self, stream: Any):
        super().__init__(stream)
        self.final: list[str] = []
        self.langs: set[str] = set()

    async def handle_transcript_event(self, transcript_event: Any) -> None:
        for r in transcript_event.transcript.results:
            if not r.is_partial and r.alternatives:
                self.final.append(r.alternatives[0].transcript)
                if r.language_code:
                    self.langs.add(r.language_code)


class Transcriber:
    def __init__(self, cfg: dict):
        self.profile = cfg["profile"]
        self.region = cfg["region"]
        self.configured = check_languages(list(cfg["languages"]))  # the order of lowass.toml = the meaning of "default"
        self.choice = DEFAULT  # the language dropdown: 'default' or one configured code that goes to the FRONT of the list
        self.timeout = float(cfg.get("timeout_sec", 30))
        crt_patch.apply()  # harmless CANCELLED tracebacks of the library are silenced (see crt_patch.py)
        self._session = boto3.Session(profile_name=self.profile, region_name=self.region)

    @property
    def langs(self) -> list[str]:
        """The language list for the NEXT stream. Read at every open, so a change of the dropdown takes effect with the
        next sentence (a running sentence keeps the list it started with)."""
        return order_for(self.choice, self.configured)

    def credentials(self) -> Any:
        """Frozen credentials of the profile (botocore refreshes SSO ones itself)."""
        try:
            creds = self._session.get_credentials()
            if creds is None:
                raise NoCredentialsError()
            return creds.get_frozen_credentials()
        except LOGIN_ERRORS:
            # a new sign-in writes a new token file; a fresh session picks it up instead of a cached failure
            self._session = boto3.Session(profile_name=self.profile, region_name=self.region)
            raise

    async def _stream(self, pcm: bytes) -> tuple[str, list[str]]:
        c = self.credentials()
        client = TranscribeStreamingClient(region=self.region,
                                           credential_resolver=StaticCredentialResolver(c.access_key, c.secret_key, c.token))
        stream = await client.start_stream_transcription(media_sample_rate_hz=16000, media_encoding="pcm",
                                                         **stream_kwargs(self.langs))
        handler = _Collect(stream.output_stream)

        async def send() -> None:
            for i in range(0, len(pcm), 3200):  # 100 ms chunks
                await stream.input_stream.send_audio_event(audio_chunk=pcm[i:i + 3200])
            await stream.input_stream.end_stream()

        await asyncio.gather(send(), handler.handle_events())
        return " ".join(handler.final).strip(), sorted(handler.langs)

    def run(self, pcm: bytes) -> tuple[str, list[str]]:
        return asyncio.run(asyncio.wait_for(self._stream(pcm), self.timeout))


def transcribe_worker(audio_q: queue.Queue[tuple[str, bytes]], stop: threading.Event, tr: Any,
                      on_text: Callable[[str, str], None], stats: Any = None,
                      on_error: Callable[[str], None] | None = None,
                      login: Callable[[], bool] | None = None) -> None:
    """login(): starts the device-code sign-in; returns True when one is now running (or just finished)."""
    log.info("transcribe worker started: profile=%s languages=%s", getattr(tr, "profile", "?"), getattr(tr, "langs", "?"))
    last_error = ""
    while not stop.is_set() or not audio_q.empty():
        try:
            speaker, wav = audio_q.get(timeout=0.2)
        except queue.Empty:
            continue
        started = time.time()
        try:
            text, langs = tr.run(wav_to_pcm(wav))
        except Exception as exc:  # noqa: BLE001 - any failure must surface in the window and must not kill the thread
            if isinstance(exc, LOGIN_ERRORS) and login is not None:
                login()  # the browser opens; segments spoken meanwhile are dropped, the next ones work after the approval
                if stats:
                    stats.stt_result("err", "waiting for the AWS sign-in")
                continue
            msg = friendly_error(exc, tr.profile)
            log.error("Transcribe error: %s", msg)
            if stats:
                stats.stt_result("err", msg)
            if on_error and msg != last_error:  # the same message is shown once, not for every segment
                on_error(msg)
            last_error = msg
            continue
        last_error = ""
        log.debug("Transcribe %s %.1fs %.0fKB langs=%s -> %r", speaker, time.time() - started, len(wav) / 1024, langs, text)
        if stats:
            stats.stt_result("ok" if text else "empty")
        if text:
            on_text(speaker, text)
