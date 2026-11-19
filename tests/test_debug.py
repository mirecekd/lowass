# tests/test_debug.py
import logging
import threading
import time

import numpy as np

from lowass import debug
from lowass.audio import Segmenter, capture_worker


def test_stats_line_counts_and_resets_peak():
    s = debug.Stats()
    s.register("Ja", 0.0025)
    s.chunk("Ja", 0.01)
    s.chunk("Ja", 0.03)
    s.segment("Ja", True)
    s.segment("Ja", False)
    s.stt_result("ok")
    s.stt_result("err", "boom")
    s.agent_result("quiet")
    line = s.line()
    assert "rms 0.0300/0.0025" in line and "seg 1  drop 1" in line and "err 1" in line and "last err: boom" in line
    assert "rms 0.0000" in s.line()  # per-interval peak resets
    assert s.maxpeak["Ja"] == 0.03


def test_rows_are_one_per_stage_with_levels():
    s = debug.Stats()
    s.register("Ja", 0.0025)
    s.register("Protistrana", 0.012)
    s.chunk("Ja", 0.01)
    s.chunk("Protistrana", 0.0)
    rows = s.rows("7")
    assert [t.split()[0] for _lvl, t in rows] == ["Ja", "Pro", "STT", "Ag"]
    assert [lvl for lvl, _t in rows] == ["hot", "dim", "dim", "dim"]
    assert "new words 7" in rows[3][1]
    s.stt_result("ok")
    s.stt_result("err", "boom")
    rows = s.rows()
    assert len(rows) == 5 and rows[2][0] == "err" and rows[-1] == ("err", "last err: boom")


def test_an_old_error_fades_from_the_panel_but_the_counter_keeps_the_total(monkeypatch):
    """A red row that never goes away hides whether the app recovered: after ERR_TTL it is back to normal."""
    s = debug.Stats()
    s.register("Ja", 0.0025)
    s.stt_result("ok")
    s.stt_result("err", "AwsCrtError: AWS_IO_SOCKET_TIMEOUT")
    fresh = s.rows()
    assert fresh[-1] == ("err", "last err: AwsCrtError: AWS_IO_SOCKET_TIMEOUT") and fresh[1][0] == "err"  # fresh: shown
    later = time.monotonic() + debug.ERR_TTL + 1
    monkeypatch.setattr(debug.time, "monotonic", lambda: later)
    rows = s.rows()
    assert not any(t.startswith("last err") for _l, t in rows)  # the red row is gone
    assert rows[1][0] == "ok" and "err 1" in rows[1][1]  # the STT row is back to normal, the total is still counted


def test_level_bar_and_row_parsing():
    assert debug.level_bar(0.0, 0.01) == "[-----|-----]"
    assert debug.level_bar(0.01, 0.01) == "[#####|-----]"  # exactly at the threshold: left half full
    assert debug.level_bar(0.02, 0.01) == "[#####|#####]"
    assert debug.level_bar(9.0, 0.01) == "[#####|#####]"  # capped
    assert debug.parse_rows("hot|Ja x\nerr|boom|with bar\nplain\nJa  [##|---] rms") == [
        ("hot", "Ja x"), ("err", "boom|with bar"), ("dim", "plain"), ("dim", "Ja  [##|---] rms")]


def test_heartbeat_warns_when_no_audio_arrives():
    s = debug.Stats()
    s.register("Ja", 0.0025)
    posted, stop = [], threading.Event()
    t = threading.Thread(target=s.heartbeat, args=(lambda k, v: posted.append((k, v)), 0.05, stop, "Ja", lambda: "0", 0.2))
    t.start()
    time.sleep(0.6)
    stop.set()
    t.join(2)
    errs = [v for k, v in posted if k == "err"]
    assert len(errs) == 1 and "No audio" in errs[0]
    assert any(k == "stats" for k, _ in posted)


def test_no_audio_warning_counts_from_the_moment_the_capture_opens():
    """The device opens late (a sign-in or a slow start): no warning while nothing is registered, then the usual delay."""
    s = debug.Stats()
    posted, stop = [], threading.Event()
    t = threading.Thread(target=s.heartbeat, args=(lambda k, v: posted.append((k, v)), 0.05, stop, "Ja", lambda: "0", 0.3))
    t.start()
    time.sleep(0.6)  # twice the warn time, but no capture is open yet
    assert [v for k, v in posted if k == "err"] == []
    s.register("Ja", 0.0025)  # the device opens now
    time.sleep(0.15)
    assert [v for k, v in posted if k == "err"] == []  # armed, but the 0.3 s have not passed
    time.sleep(0.5)
    stop.set()
    t.join(2)
    errs = [v for k, v in posted if k == "err"]
    assert len(errs) == 1 and "No audio" in errs[0]


def test_heartbeat_warns_on_digital_silence_only_once():
    s = debug.Stats()
    s.register("Ja", 0.0025)
    s.chunk("Ja", 0.0)
    posted, stop = [], threading.Event()
    t = threading.Thread(target=s.heartbeat, args=(lambda k, v: posted.append((k, v)), 0.05, stop, "Ja", lambda: "0", 0.2))
    t.start()
    time.sleep(0.8)
    stop.set()
    t.join(2)
    errs = [v for k, v in posted if k == "err"]
    assert len(errs) == 1 and "digital silence" in errs[0]


def test_save_wav_writes_file(tmp_path):
    debug.save_wav(str(tmp_path / "w"), "Ja", b"RIFFxxxx")
    files = list((tmp_path / "w").glob("*-Ja-*.wav"))
    assert len(files) == 1 and files[0].read_bytes() == b"RIFFxxxx"


def test_excepthook_reports_crashed_thread():
    posted = []
    old = threading.excepthook
    try:
        debug.install_excepthook(lambda k, v: posted.append((k, v)))
        t = threading.Thread(target=lambda: 1 / 0, name="boom-thread")
        t.start()
        t.join()
    finally:
        threading.excepthook = old
    assert posted and posted[0][0] == "err" and "boom-thread" in posted[0][1]


def test_setup_logging_creates_file_and_levels(tmp_path):
    path = debug.setup_logging(tmp_path, {"enabled": True, "log_file": "x.log"})
    logging.getLogger("lowass.t").debug("hello-debug")
    for h in logging.getLogger().handlers:
        h.flush()
    assert path is not None and "hello-debug" in path.read_text(encoding="utf-8")
    logging.basicConfig(force=True)  # restore a neutral root for other tests


class FakeStream:
    """Delivers a loud then a silent block, then asks the worker to stop."""

    def __init__(self, stop, frames):
        self.stop, self.frames, self.i = stop, frames, 0

    def read(self, n, exception_on_overflow=False):
        if self.i >= len(self.frames):
            self.stop.set()
            return np.zeros(n, dtype=np.int16).tobytes()
        amp = self.frames[self.i]
        self.i += 1
        return np.full(n, int(amp * 32767), dtype=np.int16).tobytes()


def test_capture_worker_feeds_stats_and_queue():
    import queue

    stop, q, s = threading.Event(), queue.Queue(), debug.Stats()
    s.register("Ja", 0.01)
    seg = Segmenter(0.01, 0.1, 15, 0.1)
    rate, chunk = 16000, 800
    frames = [0.3] * 6 + [0.0] * 4
    capture_worker("Ja", FakeStream(stop, frames), rate, 1, chunk, seg, q, stop, s)
    assert s.chunks["Ja"] >= 10 and s.segs["Ja"] == 1 and q.qsize() == 1
    assert s.maxpeak["Ja"] > 0.2


def test_capture_worker_counts_short_blip_as_dropped():
    import queue

    stop, q, s = threading.Event(), queue.Queue(), debug.Stats()
    seg = Segmenter(0.01, 0.1, 15, 0.35)
    capture_worker("Ja", FakeStream(stop, [0.3] + [0.0] * 4), 16000, 1, 800, seg, q, stop, s)
    assert s.dropped["Ja"] == 1 and s.segs["Ja"] == 0 and q.empty()
