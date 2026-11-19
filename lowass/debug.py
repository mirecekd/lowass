# lowass/debug.py
"""Debug support: log file, live stats line, thread-crash reporting, optional WAV dump."""
from __future__ import annotations

import contextlib
import logging
import logging.handlers
import sys
import threading
import time
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path

log = logging.getLogger("lowass.debug")
ERR_TTL = 60.0  # seconds an error stays red in the debug panel (the counters keep the total)


def setup_logging(root: Path, dcfg: dict) -> Path | None:
    """File log (DEBUG when debug is on, WARNING otherwise) + console. Returns the log path."""
    enabled = bool(dcfg.get("enabled"))
    handlers: list[logging.Handler] = []
    path: Path | None = None
    with contextlib.suppress(OSError):  # unwritable folder: console only
        candidate = root / dcfg.get("log_file", "lowass.log")
        fh = logging.handlers.RotatingFileHandler(candidate, maxBytes=1_000_000, backupCount=2, encoding="utf-8")
        fh.setLevel(logging.DEBUG if enabled else logging.WARNING)
        handlers.append(fh)
        path = candidate
    if sys.stderr is not None:  # pythonw has no console
        sh = logging.StreamHandler()
        sh.setLevel(logging.INFO)
        handlers.append(sh)
    fmt = logging.Formatter("%(asctime)s %(levelname)s [%(threadName)s] %(name)s: %(message)s")
    for h in handlers:
        h.setFormatter(fmt)
    logging.basicConfig(level=logging.WARNING, handlers=handlers, force=True)
    logging.getLogger("lowass").setLevel(logging.DEBUG if enabled else logging.INFO)  # libraries stay at WARNING
    return path


def install_excepthook(post: Callable[[str, str], None]) -> None:
    """A crashed thread must never die silently (pythonw has no console)."""
    def hook(args: threading.ExceptHookArgs) -> None:
        name = args.thread.name if args.thread else "?"
        log.error("thread %s crashed", name, exc_info=args.exc_value)
        post("err", f"thread '{name}' crashed: {args.exc_value!r} (see the log file)")
    threading.excepthook = hook


def save_wav(directory: str, label: str, wav: bytes) -> None:
    try:
        d = Path(directory)
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{time.strftime('%Y%m%d-%H%M%S')}-{label}-{int(time.time() * 1000) % 1000:03d}.wav").write_bytes(wav)
    except OSError as exc:
        log.warning("cannot save wav: %s", exc)


LEVELS = ("hot", "ok", "dim", "err")


def parse_rows(text: str) -> list[tuple[str, str]]:
    """Inverse of the 'level|text' lines the heartbeat posts. A line without a known level prefix is shown dimmed."""
    out: list[tuple[str, str]] = []
    for line in text.split("\n"):
        level, sep, rest = line.partition("|")
        out.append((level, rest) if sep and level in LEVELS else ("dim", line))
    return out


def level_bar(peak: float, threshold: float, cells: int = 10) -> str:
    """ASCII level meter: `[###--|-----]`. The `|` in the middle is the threshold; '#' to the right of it = voice."""
    half = cells // 2
    filled = min(cells, round(peak / threshold * half)) if threshold > 0 else 0
    body = ["#" if i < filled else "-" for i in range(cells)]
    return "[" + "".join(body[:half]) + "|" + "".join(body[half:]) + "]"


class Stats:
    """Counters for every stage of the pipeline; line() renders them for the window."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.thr: dict[str, float] = {}
        self.chunks: defaultdict[str, int] = defaultdict(int)
        self.peak: defaultdict[str, float] = defaultdict(float)
        self.maxpeak: defaultdict[str, float] = defaultdict(float)
        self.segs: defaultdict[str, int] = defaultdict(int)
        self.dropped: defaultdict[str, int] = defaultdict(int)
        self.stt: defaultdict[str, int] = defaultdict(int)
        self.agent: defaultdict[str, int] = defaultdict(int)
        self._last_err = ""
        self._err_at = 0.0

    @property
    def last_err(self) -> str:
        return self._last_err

    @last_err.setter
    def last_err(self, text: str) -> None:
        self._last_err, self._err_at = text, time.monotonic()

    def _recent_err(self) -> bool:
        """An error is shown for ERR_TTL seconds only: a red row that never goes away hides whether it recovered."""
        return bool(self._last_err) and time.monotonic() - self._err_at < ERR_TTL

    def register(self, label: str, threshold: float) -> None:
        with self._lock:
            self.thr[label] = threshold

    def chunk(self, label: str, rms: float) -> None:
        with self._lock:
            self.chunks[label] += 1
            self.peak[label] = max(self.peak[label], rms)
            self.maxpeak[label] = max(self.maxpeak[label], rms)

    def segment(self, label: str, sent: bool) -> None:
        with self._lock:
            (self.segs if sent else self.dropped)[label] += 1

    def stt_result(self, kind: str, err: str = "") -> None:
        """kind: ok | empty | filtered | rate | err"""
        with self._lock:
            self.stt[kind] += 1
            if err:
                self.last_err = err

    def agent_result(self, kind: str) -> None:
        """kind: quiet | answer | err"""
        with self._lock:
            self.agent[kind] += 1

    def rows(self, new_words: str = "0") -> list[tuple[str, str]]:
        """[(level, text)] for the window: one row per input (Ja, Pro), then STT and Ag.
        level: hot (voice above the threshold) | ok | dim | err. A fifth row appears only while there is an error.
        Reading the rows resets the per-interval peak (the rms shown is the loudest chunk of the last interval)."""
        out: list[tuple[str, str]] = []
        with self._lock:
            for label, thr in self.thr.items():
                peak = self.peak[label]
                text = (f"{label[:3]:<3} {level_bar(peak, thr)} rms {peak:.4f}/{thr:.4f}  chunks {self.chunks[label]}"
                        f"  seg {self.segs[label]}  drop {self.dropped[label]}")
                out.append(("hot" if peak > thr else "dim", text))
                self.peak[label] = 0.0
            s, a = self.stt, self.agent
            stt_bad = self._recent_err() and (s["err"] > 0 or s["rate"] > 0)
            out.append(("err" if stt_bad else ("ok" if s["ok"] else "dim"),
                        f"STT ok {s['ok']}  empty {s['empty']}  filtered {s['filtered']}  429 {s['rate']}  err {s['err']}"))
            out.append(("err" if a["err"] and self._recent_err() else ("ok" if a["answer"] else "dim"),
                        f"Ag  quiet {a['quiet']}  answer {a['answer']}  err {a['err']}  new words {new_words}"))
            if self._recent_err():
                out.append(("err", "last err: " + self._last_err[:90]))
        return out

    def line(self) -> str:
        """The same numbers as one plain line (for the log file)."""
        return " | ".join(text for _level, text in self.rows())

    def mic_state(self, label: str) -> tuple[bool, int, float]:
        """(is the capture of `label` registered, chunks seen, loudest chunk ever)."""
        with self._lock:
            return label in self.thr, self.chunks[label], self.maxpeak[label]

    def heartbeat(self, post: Callable[[str, str], None] | None, interval: float, stop: threading.Event,
                  my_label: str, extra: Callable[[], str], warn_after: float = 10.0) -> None:
        """Runs lowass.heartbeat.run_heartbeat (kept here so existing callers and tests keep working)."""
        from .heartbeat import run_heartbeat
        run_heartbeat(self, post, interval, stop, my_label, extra, warn_after)
