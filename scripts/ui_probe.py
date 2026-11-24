# scripts/ui_probe.py
"""Can the active speaker / live captions of a running app (Microsoft Teams) be read through UI Automation? Explores the
window of that app. Run it on Windows (pip install pywinauto), the app already running, from the project folder:

  python -m scripts.ui_probe --list-windows                         title, class, pid and process of the top-level windows
  python -m scripts.ui_probe --window Teams --dump --out tree.txt   the control tree as indented text (--depth 12, --max-elements 5000)
  python -m scripts.ui_probe --window Teams --find caption          path and properties of elements matching name/id/class
  python -m scripts.ui_probe --window Teams --watch 60              ONLY the changes of the tree, with a time (talk, let others talk)
  python -m scripts.ui_probe --pid 1234 --dump                      choose the window by process id instead of the title regex

Chromium / WebView2 (new Teams) and Electron (classic Teams) build a rich UIA tree only when they see an assistive tool. If the
dump is almost empty: run with --enable-accessibility (walks the tree once first and waits, which usually wakes it), start
Narrator (Win+Ctrl+Enter, it forces it), or start the app / browser with --force-renderer-accessibility (msedge, chrome).
Read-only: nothing is clicked or typed. Needs the call window open; captions on (... > Language and speech > Show live captions)."""
from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

from scripts.ui_probe_tree import Node, collect, diff, find, format_node, pick_windows
from scripts.ui_probe_uia import children_of, read_element, top_windows

WARM_UP_SECONDS = 2.0
MANY_CHANGES = 40
SMALL_TREE = 30
ACCESSIBILITY_NOTE = ("note: the tree is small. Chromium/WebView2 exposes its content only to an assistive tool: try "
                      "--enable-accessibility, Narrator running, or --force-renderer-accessibility on the app.")


def parse(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(prog="ui_probe", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--list-windows", action="store_true", help="list the top-level windows and exit")
    ap.add_argument("--window", metavar="REGEX", help="choose the window whose title matches (case-insensitive)")
    ap.add_argument("--pid", type=int, help="choose the window of this process id")
    ap.add_argument("--dump", action="store_true", help="print the control tree")
    ap.add_argument("--find", metavar="TEXT", help="print elements whose name / automation id / class contains TEXT")
    ap.add_argument("--watch", type=float, metavar="SECONDS", help="print only the tree changes for this long")
    ap.add_argument("--interval", type=float, default=0.5, help="seconds between snapshots for --watch")
    ap.add_argument("--depth", type=int, default=12, help="deepest level to read")
    ap.add_argument("--max-elements", type=int, default=5000, help="stop after this many elements (WebView2 trees are huge)")
    ap.add_argument("--out", metavar="FILE", help="write the --dump or --watch text to this UTF-8 file")
    ap.add_argument("--fields", default="name,flags", help="--watch: which properties to compare (name,class_name,rect,flags)")
    ap.add_argument("--ignore", default="call-duration|^\\[[^]]*\\] ~ .*Text\\[0\\]  name: '\\d\\d:\\d\\d'",
                    help="--watch: regex of change lines to hide (default: the call clock); empty = hide nothing")
    ap.add_argument("--enable-accessibility", action="store_true", help="walk the tree once and wait first, to wake Chromium")
    args = ap.parse_args(argv)
    if not (args.list_windows or args.dump or args.find is not None or args.watch is not None):
        ap.error("say what to do: --list-windows, --dump, --find TEXT or --watch SECONDS")
    if not args.list_windows and args.window is None and args.pid is None:
        ap.error("choose the window with --window REGEX or --pid N (see --list-windows)")
    return args


def snapshot(root, args) -> tuple[list[Node], bool]:
    return collect(root, read_element, children_of, args.depth, args.max_elements)


def choose(args):
    windows = top_windows()
    if args.list_windows:
        for w, _ in windows:
            print(f"pid={w.pid:<6} {w.process:24} class={w.class_name:28} title={w.title!r}")
        return None
    chosen = pick_windows([w for w, _ in windows], args.window, args.pid)
    if not chosen:
        raise SystemExit("no window matches; see --list-windows")
    if len(chosen) > 1:
        print(f"{len(chosen)} windows match, using the first; the others:")
        for w in chosen[1:]:
            print(f"  pid={w.pid} class={w.class_name} title={w.title!r}")
    handle = chosen[0].handle
    print(f"window: pid={chosen[0].pid} {chosen[0].process} title={chosen[0].title!r}")
    return next(info for w, info in windows if w.handle == handle)


def settled_snapshot(root, args) -> tuple[list[Node], bool]:
    if args.enable_accessibility:
        print("--enable-accessibility: walking the tree once and waiting to wake Chromium/WebView2 ...")
        snapshot(root, args)
        time.sleep(WARM_UP_SECONDS)
    nodes, truncated = snapshot(root, args)
    if len(nodes) < SMALL_TREE and not args.enable_accessibility:
        print(ACCESSIBILITY_NOTE)
    return nodes, truncated


def count_line(nodes: list[Node], truncated: bool, cap: int) -> str:
    return f"{len(nodes)} elements" + (f" (cut at --max-elements {cap}; raise it or lower --depth)" if truncated else "")


def watch(root, args) -> None:
    """Prints only changes of --fields (default name and flags: the rectangles move all the time), minus lines matching --ignore."""
    previous, _ = settled_snapshot(root, args)
    fields = tuple(args.fields.split(","))
    ignore = re.compile(args.ignore) if args.ignore else None
    try:
        log = open(args.out, "w", encoding="utf-8") if args.out else None  # noqa: SIM115 - closed in finally
    except OSError as exc:
        raise SystemExit(f"cannot write {args.out}: {exc}") from exc
    print(f"watching {args.watch:.0f} s every {args.interval} s, baseline {len(previous)} elements; only changes follow (Ctrl+C ends)")
    end = time.monotonic() + args.watch
    try:
        while time.monotonic() < end:
            time.sleep(args.interval)
            current, _ = snapshot(root, args)
            stamp = time.strftime("%H:%M:%S") + f".{int(time.time() * 1000) % 1000:03}"
            lines = [x for x in diff(previous, current, fields) if not (ignore and ignore.search(x))]
            previous = current
            if len(lines) > MANY_CHANGES:  # minimised / restored window: the whole tree is added or removed
                lines = [f"{len(lines)} changes at once (window minimised, restored or the page changed): not listed"]
            for line in lines:
                text = f"[{stamp}] {line}"
                print(text)
                if log:
                    log.write(text + "\n")
                    log.flush()
    except KeyboardInterrupt:
        print("stopped")
    finally:
        if log:
            log.close()


def main(argv: list[str] | None = None) -> int:
    args = parse(argv)
    root = choose(args)
    if root is None:
        return 0
    if args.watch is not None:
        watch(root, args)
        return 0
    nodes, truncated = settled_snapshot(root, args)
    if args.find is not None:
        hits = find(nodes, args.find)
        for node in hits:
            print(format_node(node, with_path=True))
        print(f"{len(hits)} match(es) in {count_line(nodes, truncated, args.max_elements)}")
    if args.dump:
        text = "\n".join(format_node(n) for n in nodes)
        if args.out:
            Path(args.out).write_text(text + "\n", encoding="utf-8")
        else:
            print(text)
        print(count_line(nodes, truncated, args.max_elements) + (f"; written to {args.out}" if args.out else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
