# scripts/speaker_probe.py
"""SPIKE: can we see WHO IS SPEAKING in a Microsoft Teams gallery from the coloured border Teams draws around the active
speaker's tile? Run it on Windows (pip install pywinauto mss numpy) while a meeting window is visible, gallery view:

  python -m scripts.speaker_probe [--pid 1234] [--seconds 60] [--fps 5] [--out data/speaker-YYYYmmdd-HHMMSS.jsonl] [--stats]

UI Automation gives the screen rectangle of every participant tile, mss grabs the meeting window, and for each tile a ring of
pixels just inside the edge is measured (mean colour, uniformity, saturation); a solid saturated uniform ring that stands out
from the tile's own baseline and from the other tiles means 'speaking'. Only CHANGES are printed:
[hh:mm:ss.mmm] speaking: <name> / stopped: <name>. --out gets {"t": epoch, "name": str, "speaking": bool} per change.
--stats also writes EVERY frame per tile (next to --out, *.stats.jsonl) as {"t","name","rgb","std","sat","score"}: aggregate
numbers only, so they can be sent back for analysis. Pixels or images are NEVER saved, printed or logged.
Limits: a minimised window is not visible (warning); a tile partly off the window / screen gives a warning (a tile covered by
another window cannot be detected and measures that window's pixels); speaker / focus view hides tiles. Read-only; Ctrl+C ends."""
from __future__ import annotations

import argparse
import contextlib
import json
import sys
import time
from pathlib import Path
from typing import TextIO

from scripts.speaker_probe_core import (
    SpeakerTracker,
    read_rects,
    ring_pixels,
    ring_stats,
    score,
)

RECT_REFRESH_SECONDS = 2.0
MINIMISED_LEFT = -30000  # Windows parks a minimised window around -32000


def parse(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(prog="speaker_probe", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pid", type=int, help="process id of the Teams window (default: found by itself, ms-teams.exe)")
    ap.add_argument("--seconds", type=float, default=60.0, help="how long to watch (default 60)")
    ap.add_argument("--fps", type=float, default=5.0, help="screen grabs per second (default 5)")
    ap.add_argument("--out", metavar="FILE", help="JSONL file of speaking events (default data/speaker-YYYYmmdd-HHMMSS.jsonl)")
    ap.add_argument("--stats", action="store_true", help="also write every frame per tile (numbers only) to <out>.stats.jsonl")
    ap.add_argument("--depth", type=int, default=40, help="deepest UIA level to read")
    ap.add_argument("--max-elements", type=int, default=20000, help="stop a UIA snapshot after this many elements")
    return ap.parse_args(argv)


def make_dpi_aware() -> None:
    """UIA rectangles and screenshot pixels must share one coordinate system (physical pixels)."""
    import ctypes

    with contextlib.suppress(Exception):  # not Windows, or already set
        ctypes.windll.user32.SetProcessDPIAware()  # type: ignore[attr-defined]  # Windows only


def stamp(t: float) -> str:
    return time.strftime("%H:%M:%S", time.localtime(t)) + f".{int(t % 1 * 1000):03d}"


def grab_box(sct, window: tuple[int, int, int, int]):
    """Window rectangle clipped to the virtual desktop as an mss monitor dict (None when nothing of it is on screen)."""
    desk = sct.monitors[0]
    left, top = max(window[0], desk["left"]), max(window[1], desk["top"])
    right, bottom = min(window[2], desk["left"] + desk["width"]), min(window[3], desk["top"] + desk["height"])
    if right <= left or bottom <= top:
        return None
    return {"left": left, "top": top, "width": right - left, "height": bottom - top}


def grab_rgb(sct, box):
    import numpy as np

    shot = sct.grab(box)
    return np.frombuffer(shot.bgra, np.uint8).reshape(shot.height, shot.width, 4)[:, :, [2, 1, 0]]


def run(root, args, log: TextIO, stats_log: TextIO | None) -> None:
    import mss

    from scripts.meeting_log import is_minimised, snapshot
    from scripts.ui_probe_uia import read_element

    tracker = SpeakerTracker()
    rects: dict[str, tuple[int, int, int, int]] = {}
    window = (0, 0, 0, 0)
    next_rects, warned = 0.0, set()
    end = time.monotonic() + args.seconds
    with mss.MSS() as sct:
        desk = sct.monitors[0]
        print(f"screen {desk['width']}x{desk['height']} at ({desk['left']},{desk['top']})", file=sys.stderr)
        while time.monotonic() < end:
            started = time.monotonic()
            if is_minimised(root):
                if "minimised" not in warned:
                    warned.add("minimised")
                    print("warning: the Teams window is minimised; restore it", file=sys.stderr)
                time.sleep(0.5)
                continue
            if started >= next_rects:
                next_rects = started + RECT_REFRESH_SECONDS
                window = read_element(root)["rect"]
                fresh = read_rects(snapshot(root, args))
                if not rects:
                    print(f"{len(fresh)} participant tiles", file=sys.stderr)
                rects = fresh
            box = grab_box(sct, window)
            if box and rects:
                process_frame(sct, box, rects, tracker, log, stats_log, warned)
            time.sleep(max(0.0, 1.0 / args.fps - (time.monotonic() - started)))


def process_frame(sct, box, rects, tracker, log: TextIO, stats_log: TextIO | None, warned: set) -> None:
    """Grab one frame, measure the ring of every tile, feed the tracker, print and write what changed."""
    img = grab_rgb(sct, box)
    now = time.time()
    stats = {}
    for name, (left, top, right, bottom) in rects.items():
        rel = (left - box["left"], top - box["top"], right - box["left"], bottom - box["top"])
        if (rel[0] < 0 or rel[1] < 0 or rel[2] > box["width"] or rel[3] > box["height"]) and name not in warned:
            warned.add(name)
            print(f"warning: tile '{name}' is partly outside the visible window / screen; its ring is cut", file=sys.stderr)
        stats[name] = ring_stats(ring_pixels(img, rel))
    for name, (rgb, std, sat) in stats.items():
        if stats_log:
            stats_log.write(json.dumps({"t": now, "name": name, "rgb": list(rgb), "std": round(std, 2), "sat": round(sat, 3),
                                        "score": round(score(std, sat), 3)}, ensure_ascii=False) + "\n")
    for event in tracker.feed(now, stats):
        print(f"[{stamp(now)}] {'speaking' if event['speaking'] else 'stopped'}: {event['name']}")
        log.write(json.dumps(event, ensure_ascii=False) + "\n")
        log.flush()


def main(argv: list[str] | None = None) -> int:
    args = parse(argv)
    make_dpi_aware()
    from scripts.meeting_log import choose_window  # lazy: pulls in the Windows glue

    out = Path(args.out) if args.out else Path("data") / time.strftime("speaker-%Y%m%d-%H%M%S.jsonl")
    try:
        root = choose_window(args)
        out.parent.mkdir(parents=True, exist_ok=True)
        stats_path = out.with_suffix(".stats.jsonl")
        with out.open("w", encoding="utf-8") as log, (stats_path.open("w", encoding="utf-8") if args.stats
                                                       else contextlib.nullcontext()) as sl:
            print(f"writing {out}" + (f" and {stats_path}" if args.stats else "") + "; Ctrl+C ends", file=sys.stderr)
            run(root, args, log, sl)
    except KeyboardInterrupt:
        print("stopped", file=sys.stderr)
    except OSError as exc:
        raise SystemExit(f"cannot write {out}: {exc}") from exc
    return 0


if __name__ == "__main__":
    sys.exit(main())
