# scripts/meeting_log.py
"""Writes a JSONL timeline of who has the microphone muted / unmuted in a running Microsoft Teams meeting (new Teams,
WebView2) by reading the participant tiles through UI Automation. Run it on Windows (pip install pywinauto):

  python -m scripts.meeting_log [--pid 1234] [--interval 0.5] [--out data/meeting-YYYYmmdd-HHMMSS.jsonl] [--print]

One JSON object per line: {"t": epoch, "event": "start", "pid": N or null} first, then {"t": epoch, "name": "...", "muted": bool,
"present": bool}: one line per participant at the start, afterwards only changes (mute flips, a participant appears or leaves
the gallery; a participant who left keeps the last muted value). Keep the meeting window visible (a minimised window freezes
the tree) and in gallery view (speaker / focus view hides tiles). Read-only; Ctrl+C ends. The Teams process (ms-teams.exe) is
found by itself; --pid overrides it (python -m scripts.ui_probe --list-windows lists the pids)."""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import TextIO

from scripts.meeting_log_core import diff_states, read_states
from scripts.ui_probe_tree import Node, collect, pick_windows, teams_pids
from scripts.ui_probe_uia import children_of, read_element, top_windows

WARM_UP_SECONDS = 2.0
MINIMISED_LEFT = -30000  # Windows parks a minimised window around -32000


def parse(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(prog="meeting_log", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pid", type=int, help="process id of the Teams window (default: found by itself, ms-teams.exe)")
    ap.add_argument("--interval", type=float, default=0.5, help="seconds between snapshots")
    ap.add_argument("--out", metavar="FILE", help="JSONL file (default data/meeting-YYYYmmdd-HHMMSS.jsonl)")
    ap.add_argument("--depth", type=int, default=40, help="deepest level to read")
    ap.add_argument("--max-elements", type=int, default=20000, help="stop a snapshot after this many elements")
    ap.add_argument("--print", action="store_true", help="also echo every line to the console")
    return ap.parse_args(argv)


def snapshot(root, args) -> list[Node]:
    return collect(root, read_element, children_of, args.depth, args.max_elements)[0]


def choose_window(args):
    """The window that shows the most participant tiles (a process may own several top-level windows). Without --pid every
    window of the Teams client is tried, so a running call is found by itself."""
    windows = top_windows()
    if args.pid is None:
        pids = teams_pids([w for w, _ in windows])
        if not pids:
            raise SystemExit("Teams is not running (no ms-teams.exe window); start it or give --pid")
        handles = {w.handle for w, _ in windows if w.pid in pids}
    else:
        handles = {w.handle for w in pick_windows([w for w, _ in windows], pid=args.pid)}
    roots = [info for w, info in windows if w.handle in handles]
    if not roots:
        raise SystemExit(f"no window of process {args.pid}; see python -m scripts.ui_probe --list-windows")
    for root in roots:
        snapshot(root, args)  # wake Chromium accessibility, then give it time to build the tree
    time.sleep(WARM_UP_SECONDS)
    best = max(roots, key=lambda root: len(read_states(snapshot(root, args))))
    if not read_states(snapshot(best, args)):
        raise SystemExit("no meeting window with participant tiles found: join the call, keep Teams visible (not minimised)")
    return best


def is_minimised(root) -> bool:
    return read_element(root)["rect"][0] <= MINIMISED_LEFT


def emit(events: list[dict], log: TextIO, echo: bool) -> None:
    for event in events:
        line = json.dumps(event, ensure_ascii=False)
        log.write(line + "\n")
        log.flush()
        if echo:
            print(line)


def run(root, args, log: TextIO) -> None:
    emit([{"t": time.time(), "event": "start", "pid": args.pid}], log, args.print)
    state: dict[str, bool] = {}
    warned = False
    while True:
        if is_minimised(root):
            if not warned:
                print("warning: the Teams window is minimised, its tree is frozen; restore it", file=sys.stderr)
                warned = True
        else:
            current = read_states(snapshot(root, args))
            emit(diff_states(state, current, time.time()), log, args.print)
            state = current
        time.sleep(args.interval)


def main(argv: list[str] | None = None) -> int:
    args = parse(argv)
    out = Path(args.out) if args.out else Path("data") / time.strftime("meeting-%Y%m%d-%H%M%S.jsonl")
    try:
        root = choose_window(args)
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", encoding="utf-8") as log:
            print(f"writing {out}; Ctrl+C ends", file=sys.stderr)
            run(root, args, log)
    except KeyboardInterrupt:
        print("stopped", file=sys.stderr)
    except OSError as exc:
        raise SystemExit(f"cannot write {out}: {exc}") from exc
    return 0


if __name__ == "__main__":
    sys.exit(main())
