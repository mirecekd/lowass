# lowass/stt.py
"""Groq Whisper worker: WAV blocks in, transcript lines out (no UI output)."""
from __future__ import annotations

import logging
import queue
import threading
import time
from collections.abc import Callable
from typing import Any

import requests

log = logging.getLogger("lowass.stt")


def clean(text: str, hallucinations: set[str]) -> str:
    text = (text or "").strip()
    return "" if text.lower() in hallucinations else text


def stt_worker(audio_q: queue.Queue[tuple[str, bytes]], stop: threading.Event, api_key: str, cfg: dict,
               on_text: Callable[[str, str], None], stats: Any = None) -> None:
    session = requests.Session()
    headers = {"Authorization": f"Bearer {api_key}"}
    halluc = {h.lower() for h in cfg.get("hallucinations", [])}
    log.info("stt worker started: %s, language=%r", cfg["model"], cfg.get("language", ""))
    while not stop.is_set() or not audio_q.empty():
        try:
            speaker, wav = audio_q.get(timeout=0.2)
        except queue.Empty:
            continue
        data = {"model": cfg["model"], "prompt": cfg.get("prompt", ""), "response_format": "json"}
        if cfg.get("language"):  # empty = Whisper auto-detects the language
            data["language"] = cfg["language"]
        started = time.time()
        try:
            resp = session.post(cfg["url"], headers=headers, files={"file": ("speech.wav", wav, "audio/wav")},
                                data=data, timeout=15)
            if resp.status_code == 429:
                log.warning("Groq rate limit, sleeping 2 s")
                if stats:
                    stats.stt_result("rate", "Groq 429 rate limit")
                time.sleep(2)
                continue
            resp.raise_for_status()
            raw = (resp.json().get("text", "") or "").strip()
            text = clean(raw, halluc)
            log.debug("STT %s %.1fs %.0fKB -> %r%s", speaker, time.time() - started, len(wav) / 1024, raw,
                      "" if text else " (dropped)")
            if stats:
                stats.stt_result("ok" if text else ("filtered" if raw else "empty"))
            if text:
                on_text(speaker, text)
        except (requests.RequestException, ValueError) as exc:
            detail = getattr(getattr(exc, "response", None), "text", "") or ""
            log.error("STT error: %s %s", exc, detail[:200])
            if stats:
                stats.stt_result("err", f"STT {exc} {detail[:80]}")
