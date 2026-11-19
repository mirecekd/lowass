# lowass/assist.py
"""Suggested answers (hint card) and the rolling facts sheet: wires HintWatcher and FactsSheet to the meeting."""
from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import Any

from .facts import FactsSheet
from .hints import HintWatcher
from .llm import Completer

log = logging.getLogger("lowass.assist")


def hint_prompt(base: str, who: str, question: str) -> str:
    return f"{base}\n\nTHE OTHER SIDE ({who}) SAID:\n{question}"


class Assist:
    """tap() is called with every stored sentence; run() is a one-second loop started once by the App."""

    def __init__(self, cfg: Any, flow: Any, meeting: Any, post: Callable[[str, str], None], model: Callable[[], str]):
        hc, fc, prompts = cfg.section("hint"), cfg.section("facts"), cfg.section("prompts")
        self.flow, self.meeting, self.post, self.prompts = flow, meeting, post, prompts
        self.stop = threading.Event()
        self.watcher = (HintWatcher(cfg.section("audio")["my_label"], list(hc.get("names", [])), hc.get("wait_sec", 12),
                                    hc.get("cooldown_sec", 45), hc.get("max_age_sec", 90))
                        if hc.get("enabled", True) else None)
        self.sheet: FactsSheet | None = None
        key, base = cfg.env("LITELLM_API_KEY"), cfg.env("LITELLM_BASE_URL")
        if fc.get("enabled", True) and key and base:
            llm = Completer(base, key, fc.get("model") or model())
            self.sheet = FactsSheet(lambda system, user: llm.complete(system, user, 900), prompts["facts"],
                                    fc.get("min_new_words", 60), fc.get("max_chars", 3500))
        self.facts_model = fc.get("model") or ""
        self._model = model
        self._llm_for: str | None = None
        self.flow.extra_context = lambda: self.sheet.text if self.sheet else ""

    def tap(self, speaker: str, text: str) -> None:
        if self.watcher is not None:
            self.watcher.heard(speaker, text)
        if self.sheet is not None:
            self.sheet.feed(f"{speaker}: {text}")

    def reset(self) -> None:
        """Clear or a project switch: a new meeting starts with an empty sheet and no pending question."""
        if self.sheet is not None:
            self.sheet.reset()
        if self.watcher is not None:
            self.watcher.reset()
        self.post("hint_clear", "")
        self.post("facts_reset", "")

    def run(self) -> None:
        while not self.stop.wait(1.0):
            if self.flow.private.is_set():
                continue
            try:
                self._tick()
            except Exception:  # a helper must never stop the loop
                log.exception("assist tick failed")

    def _tick(self) -> None:
        if self.sheet is not None and self.sheet.due() and self.sheet.update():
            self.meeting.save_facts(self.sheet.text)
            self.post("facts", self.sheet.text)  # the facts window shows it (and opens by itself the first time)
        if self.flow.busy.locked():  # the agent is working: the question stays pending and is asked about next second
            return
        pending = self.watcher.due() if self.watcher is not None else None
        if pending is None or self.watcher is None:
            return
        waited = int(time.monotonic() - pending.asked_at)
        shown: list[str] = []

        def deliver(answer: str) -> None:
            shown.append(answer)
            self.post("hint", f"{pending.speaker}\t{waited}\t{answer}")

        log.info("hint: asking the agent about an unanswered question from %s (%d s): %s", pending.speaker, waited, pending.text[:100])
        self.flow.work(hint_prompt(self.prompts["hint"], pending.speaker, pending.text), None, "hint", remember=False,
                       deliver=deliver)
        log.info("hint: %s", "card shown" if shown else "no card (the agent said NOTHING, Private was on, or the request failed)")
        self.watcher.handled()
