# lowass/listener.py
"""Owns PyAudio streams and threads; pushes recognised text to a callback."""
from __future__ import annotations

import logging
import queue
import threading
from collections.abc import Callable

from .audio import Segmenter, capture_worker, find_wasapi_devices, open_input_stream
from .audio_live import capture_live
from .debug import save_wav
from .gate import Gate
from .stt import stt_worker

log = logging.getLogger("lowass.listener")


class Listener:
    def __init__(self, cfg, on_text: Callable[[str, str], None], stats=None,
                 on_error: Callable[[str], None] | None = None, login: Callable[[], bool] | None = None,
                 voice=None, paused: Callable[[], bool] | None = None):
        self.cfg, self.on_text, self.stats, self.on_error, self.login = cfg, on_text, stats, on_error, login
        self.voice, self.paused = voice, paused  # voice: lowass.voice.Voice (live mode); paused: Private mode
        self.live = None
        self.stop = threading.Event()
        self.audio_q: queue.Queue[tuple[str, bytes]] = queue.Queue()
        self._p = None
        self._streams: list = []

    def start(self) -> list[str]:
        import pyaudiowpatch as pyaudio  # type: ignore[import-not-found]  # pyright: ignore[reportMissingImports]  # Windows only, lazy

        a = self.cfg.section("audio")
        dbg = self.cfg.section("debug")
        self._p = p = pyaudio.PyAudio()
        mic, loop = find_wasapi_devices(p, pyaudio)
        log.info("me=%s other=%s", mic["name"], loop["name"])
        if dbg.get("enabled"):
            for i in range(p.get_device_count()):  # full device list helps when the default is wrong
                d = p.get_device_info_by_index(i)
                log.debug("device %d: %s | in=%s out=%s loopback=%s rate=%s", i, d["name"], d["maxInputChannels"],
                          d["maxOutputChannels"], d.get("isLoopbackDevice"), d["defaultSampleRate"])
        out_q = self.audio_q
        if dbg.get("enabled") and dbg.get("save_wav_dir"):
            out_q = self._tap(dbg["save_wav_dir"])
        use_live = self._start_live()
        specs = [(a["my_label"], mic, a["mic_threshold"]), (a["other_label"], loop, a["loopback_threshold"])]
        for label, info, thr in specs:
            stream, rate, ch, chunk = open_input_stream(p, pyaudio, info)
            self._streams.append(stream)
            if self.stats:
                self.stats.register(label, thr)
            if use_live:
                gate = Gate(thr, a["silence_duration"], a["max_segment_sec"], a["min_speech_sec"])
                threading.Thread(target=capture_live, daemon=True, name=f"cap-{label}",
                                 args=(label, stream, rate, ch, chunk, gate, self.live, self.stop, self.stats,
                                       self.paused)).start()
                continue
            seg = Segmenter(thr, a["silence_duration"], a["max_segment_sec"], a["min_speech_sec"])
            threading.Thread(target=capture_worker, daemon=True, name=f"cap-{label}",
                             args=(label, stream, rate, ch, chunk, seg, out_q, self.stop, self.stats)).start()
        if not use_live:
            self._start_stt()
        return [mic["name"], loop["name"]]

    def _start_live(self) -> bool:
        """Live streaming (words appear while you speak) needs Amazon Transcribe and the Voice handler."""
        if (self.cfg.section("stt").get("provider", "transcribe") != "transcribe" or self.voice is None
                or self.cfg.section("transcribe").get("mode", "live") != "live"):
            return False
        from .live import LiveTranscriber
        from .transcribe import LOGIN_ERRORS, Transcriber, friendly_error
        voice = self.voice
        if voice is None:
            return False
        tr = Transcriber(self.cfg.section("transcribe"))

        def failed(exc: BaseException) -> None:
            if isinstance(exc, LOGIN_ERRORS) and self.login is not None:
                self.login()  # the browser opens; the utterance spoken meanwhile is lost
            elif self.on_error:
                self.on_error(friendly_error(exc, tr.profile))
            if self.stats:
                self.stats.stt_result("err", friendly_error(exc, tr.profile))

        def final(speaker: str, text: str, lang: str | None) -> None:
            if self.stats:
                self.stats.stt_result("ok" if text.strip() else "empty")
            voice.final(speaker, text, lang)

        self.live = LiveTranscriber(tr, voice.partial, final, failed)
        return True

    def _start_stt(self) -> None:
        provider = self.cfg.section("stt").get("provider", "transcribe")
        if provider == "transcribe":
            from .transcribe import Transcriber, transcribe_worker
            tr = Transcriber(self.cfg.section("transcribe"))
            threading.Thread(target=transcribe_worker, daemon=True, name="stt",
                             args=(self.audio_q, self.stop, tr, self.on_text, self.stats, self.on_error, self.login)).start()
        elif provider == "groq":
            threading.Thread(target=stt_worker, daemon=True, name="stt",
                             args=(self.audio_q, self.stop, self.cfg.env("GROQ_API_KEY"), self.cfg.section("groq"),
                                   self.on_text, self.stats)).start()
        else:
            raise ValueError(f"stt.provider must be 'transcribe' or 'groq', got {provider!r}")

    def _tap(self, directory: str):
        """Queue-like object that also saves every segment as a WAV for listening back."""
        real = self.audio_q

        class Tap:
            @staticmethod
            def put(item):
                save_wav(directory, item[0], item[1])
                real.put(item)

        return Tap()

    def close(self) -> None:
        self.stop.set()
        if self.live is not None:
            self.live.close()
        for s in self._streams:
            try:
                s.stop_stream()
                s.close()
            except OSError:
                pass
        if self._p is not None:
            self._p.terminate()
