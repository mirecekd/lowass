# lowass/voice.py
"""What happens to a recognised sentence: captions, wake phrase, transcript + memory, instant translation.

The audio threads call partial() / final(); nothing here blocks them (translation runs in a small pool)."""
from __future__ import annotations

import logging
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from .ui_parts import NAMED

log = logging.getLogger("lowass.voice")
Post = Callable[[str, str], None]


class Voice:
    def __init__(self, post: Post, transcript: Any, meeting: Any, my_label: str, paused: Callable[[], bool],
                 ask: Callable[[str], None], translator: Any = None, wake: Any = None, armed_sec: float = 10.0,
                 names: Any = None, other_label: str = "", lead_seconds: float = 0.3):
        self.post, self.transcript, self.meeting, self.my_label = post, transcript, meeting, my_label
        self.names, self.other_label, self.lead_seconds = names, other_label, lead_seconds  # names: SpeakerTimeline | None
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
        who = self._who(speaker, text)  # the active Teams speaker of the other side, else None
        shown = f"{NAMED}{who}: {text}" if who else text  # the caption keeps the `speaker` key (it matches the open partial line)
        self.post("caption", f"{speaker}\tfinal\t{shown}")
        log.debug("heard %s [%s]: %s", who or speaker, lang, text)
        if speaker == self.my_label and self.wake is not None and self._wake(text):
            return  # a question for the assistant is not part of the conversation
        stored = who or speaker
        self.transcript.add(stored, text)
        self.meeting.transcript_line(stored, text)
        if self.tap is not None:
            self.tap(stored, text)
        if self.translate_on and self.translator is not None and self.translator.needed(lang):
            self._pool.submit(self._translate, speaker, text, lang, shown, stored)

    def _who(self, speaker: str, text: str) -> str | None:
        """Name of the Teams speaker who was lit while this sentence of the other side was said; None = keep the label."""
        if self.names is None or not self.other_label or speaker != self.other_label:
            return None
        t_end = time.time()
        # shortcut: estimated sentence start, upgrade by passing the real gate start time through live_stream
        t_start = t_end - max(1.0, 0.4 * len(text.split()))
        try:
            who = self.names.who(t_start - self.lead_seconds, t_end)
            log.info("speaker name: %s (window %.1f s, %d names lit in the history)", "found" if who else "none",
                     t_end - t_start + self.lead_seconds, len(self.names._intervals))
            return who
        except Exception:
            log.exception("speaker name lookup failed")
            return None

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

    def _translate(self, speaker: str, text: str, lang: str | None, shown: str = "", stored: str = "") -> None:
        out = self.translator.translate(text, lang) if lang else None  # the plain sentence is translated, never the name
        if out and self.translate_on and not self.paused():  # switched off while the request ran: show nothing
            # the line as shown in the caption (with the name) pins the translation to its line
            self.post("caption_tr", f"{speaker}\t{out}\t{shown or text}")
            self.post("tr", f"{stored or speaker}: {out}")  # also into the scrolling log: the caption panel only holds a few lines

    def close(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)


def build_voice(cfg: Any, post: Post, transcript: Any, meeting: Any, paused: Callable[[], bool],
                ask: Callable[[str], None], *, names: Any = None) -> Voice:
    """Voice from lowass.toml: [translate] (translator only when enabled; the button decides when it is used),
    [wake] phrases, and the start state of the Translate button (`on_start`). `names` (a SpeakerTimeline) is only
    given by the app when [speaker].enabled; without it nothing about the sentences changes."""
    from .lang_control import build_rule
    from .translate import Translator
    from .wake import LEAD_INS, WakeWords

    tc, tr, w = cfg.section("transcribe"), cfg.section("translate"), cfg.section("wake")
    translator = None
    if tr.get("enabled", True):
        translator = Translator(tc["profile"], tc["region"], tr.get("target", "cs"),
                                tuple(tr.get("understood", ("cs", "sk", "en"))), rule=build_rule(cfg))
    wake = WakeWords(list(w["phrases"]), lead_ins=list(w.get("lead_ins", LEAD_INS)),
                     start_only=list(w.get("start_only", []))) if w.get("phrases") else None
    audio = cfg.section("audio")
    voice = Voice(post, transcript, meeting, audio["my_label"], paused, ask, translator, wake,
                  float(w.get("armed_sec", 10)), names, audio.get("other_label", ""),
                  float(cfg.section("speaker").get("lead_seconds", 0.3)))
    voice.translate_on = bool(tr.get("on_start", False)) and translator is not None
    return voice
