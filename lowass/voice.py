# lowass/voice.py
"""What happens to a recognised sentence: captions, wake phrase, transcript + memory, instant translation.

The audio threads call partial() / final(); nothing here blocks them (translation runs in a small pool)."""
from __future__ import annotations

import logging
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

log = logging.getLogger("lowass.voice")
Post = Callable[[str, str], None]


class Voice:
    def __init__(self, post: Post, transcript: Any, meeting: Any, my_label: str, paused: Callable[[], bool],
                 ask: Callable[[str], None], translator: Any = None, wake: Any = None, armed_sec: float = 10.0):
        self.post, self.transcript, self.meeting, self.my_label = post, transcript, meeting, my_label
        self.paused, self.ask, self.translator, self.wake, self.armed_sec = paused, ask, translator, wake, armed_sec
        self.translate_on = False  # the Translate button: foreign speech is only transcribed until it is switched on
        self.tap: Callable[[str, str], None] | None = None  # sees every stored sentence (hints, facts sheet)
        self._armed_until = 0.0
        self._pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="translate")

    def partial(self, speaker: str, text: str, lang: str | None = None) -> None:
        if not self.paused():
            self.post("caption", f"{speaker}\tpartial\t{text}")

    def final(self, speaker: str, text: str, lang: str | None = None) -> None:
        if self.paused() or not text.strip():
            return
        self.post("caption", f"{speaker}\tfinal\t{text}")
        log.debug("heard %s [%s]: %s", speaker, lang, text)
        if speaker == self.my_label and self.wake is not None and self._wake(text):
            return  # a question for the assistant is not part of the conversation
        self.transcript.add(speaker, text)
        self.meeting.transcript_line(speaker, text)
        if self.tap is not None:
            self.tap(speaker, text)
        if self.translate_on and self.translator is not None and self.translator.needed(lang):
            self._pool.submit(self._translate, speaker, text, lang)

    def _wake(self, text: str) -> bool:
        """True when `text` was addressed to the assistant (and was handed over to it)."""
        rest = self.wake.strip(text)
        if rest is None:
            if time.time() < self._armed_until:  # the sentence after a bare wake phrase is the question
                self._armed_until = 0.0
                self.ask(text)
                return True
            return False
        if rest:
            self.ask(rest)
        else:
            self._armed_until = time.time() + self.armed_sec
            self.post("status", "wake phrase heard: ask now")
        return True

    def _translate(self, speaker: str, text: str, lang: str | None) -> None:
        out = self.translator.translate(text, lang) if lang else None
        if out and self.translate_on and not self.paused():  # switched off while the request ran: show nothing
            self.post("caption_tr", f"{speaker}\t{out}\t{text}")  # the source sentence pins the translation to its line
            self.post("tr", f"{speaker}: {out}")  # also into the scrolling log: the caption panel only holds a few lines

    def close(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)


def build_voice(cfg: Any, post: Post, transcript: Any, meeting: Any, paused: Callable[[], bool],
                ask: Callable[[str], None]) -> Voice:
    """Voice from lowass.toml: [translate] (translator only when enabled; the button decides when it is used),
    [wake] phrases, and the start state of the Translate button (`on_start`)."""
    from .translate import Translator
    from .wake import LEAD_INS, WakeWords

    tc, tr, w = cfg.section("transcribe"), cfg.section("translate"), cfg.section("wake")
    translator = None
    if tr.get("enabled", True):
        translator = Translator(tc["profile"], tc["region"], tr.get("target", "cs"),
                                tuple(tr.get("understood", ("cs", "sk", "en"))))
    wake = WakeWords(list(w["phrases"]), lead_ins=list(w.get("lead_ins", LEAD_INS)),
                     start_only=list(w.get("start_only", []))) if w.get("phrases") else None
    voice = Voice(post, transcript, meeting, cfg.section("audio")["my_label"], paused, ask, translator, wake,
                  float(w.get("armed_sec", 10)))
    voice.translate_on = bool(tr.get("on_start", False)) and translator is not None
    return voice
