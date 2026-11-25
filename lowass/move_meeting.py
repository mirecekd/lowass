# lowass/move_meeting.py
"""CLI: move one meeting to another project (local files, local RAG, agentmemory).

    python -m lowass.move_meeting [--config lowass.toml] [--sid SID] [--to KEY] [--limit 30] [--dry-run] [--yes] [--resend]

Close the meeting in LOWASS first (Close meeting) and exit the app, then run this."""
from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from pathlib import Path

from . import config as cfgmod
from .memlink import EXCLUDED_PROJECTS
from .memory import data_dir
from .move_apply import MoveLocalError, apply_local
from .move_link import AmLink, am_problem
from .move_plan import MoveError, Plan, plan_move
from .move_report import print_am_report
from .view import Meet, describe, recent

Ask = Callable[[str], str]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="python -m lowass.move_meeting", description=(__doc__ or "").split("\n\n")[0])
    p.add_argument("--config", default="lowass.toml", help="config file name inside the LOWASS folder")
    p.add_argument("--sid", help="meeting id (or its start); skips the question")
    p.add_argument("--to", help="target project key; skips the question")
    p.add_argument("--limit", type=int, default=30, help="how many meetings to list")
    p.add_argument("--dry-run", action="store_true", help="print the plan and exit without asking")
    p.add_argument("--yes", action="store_true", help="do not ask 'Apply?'")
    p.add_argument("--resend", action="store_true", help="redo only the agentmemory part of a meeting already moved (--to = its project)")
    return p.parse_args(argv)


def _pick(ask: Ask, prompt: str, count: int) -> int | None:
    answer = ask(prompt).strip()
    return int(answer) - 1 if answer.isdecimal() and 1 <= int(answer) <= count else None


def choose_meeting(root: Path, args: argparse.Namespace, ask: Ask, out: Callable[[str], None]) -> Meet | None:
    items = recent(root, None, limit=args.limit if not args.sid else 100000)
    if args.sid:
        hits = [m for m in items if m.sid.startswith(args.sid)]
        if len(hits) != 1:
            out(f"--sid {args.sid}: {len(hits)} meetings match")
            return None
        return hits[0]
    if not items:
        out(f"No meetings found in {root}")
        return None
    for n, m in enumerate(items, 1):
        out(describe(m, n))
    i = _pick(ask, "Which meeting? [number] ", len(items))
    return items[i] if i is not None else None


def choose_target(meeting: Meet, projects: dict[str, str], args: argparse.Namespace, ask: Ask,
                  out: Callable[[str], None]) -> str | None:
    if args.to:
        return args.to
    keys = list(projects)
    for n, k in enumerate(keys, 1):
        out(f"{n:>2}. {k}  ({projects[k]})" + ("   <- now" if k == meeting.project else ""))
    i = _pick(ask, "Move to? [number] ", len(keys))
    return keys[i] if i is not None else None


def run(args: argparse.Namespace, ask: Ask = input, out: Callable[[str], None] = print) -> int:
    cfg = cfgmod.load(name=args.config)
    root = data_dir(cfg)
    projects, _ = cfg.project()
    meeting = choose_meeting(root, args, ask, out)
    if meeting is None:
        out("No meeting chosen, nothing changed.")
        return 2
    target = choose_target(meeting, projects, args, ask, out)
    if target is None:
        out("No target chosen, nothing changed.")
        return 2
    problem = am_problem(cfg)
    a = cfg.section("agentmemory")
    names = {str(k): str(v) for k, v in dict(a.get("projects", {})).items()}
    try:
        plan = plan_move(meeting, target, projects, names, tuple(a.get("exclude", EXCLUDED_PROJECTS)),
                         am_enabled=not problem, resend=args.resend)
    except MoveError as exc:
        out(f"Refused: {exc}")
        return 2
    out("\nPLAN (nothing has been changed yet):")
    out("\n".join(plan.lines()))
    if problem:
        out(f"agentmemory is skipped: {problem}")
    if args.dry_run:
        out("Dry run: nothing changed.")
        return 0
    if not args.yes and ask("Apply? [y/N] ").strip().lower() != "y":
        out("Cancelled, nothing changed.")
        return 1
    return apply(plan, cfg, names, out)


def apply(plan: Plan, cfg: cfgmod.Config, names: dict[str, str], out: Callable[[str], None]) -> int:
    if plan.local:
        try:
            res = apply_local(plan)
        except MoveLocalError as exc:
            out(f"FAILED, nothing was changed: {exc}")
            return 3
        out(f"Local move done: folder renamed, {res.sessions} session row(s) and {res.chunks} chunk(s) updated"
            + ("" if res.db_found else " (memory.db not found)"))
    code = 0
    if plan.sends:
        with AmLink(cfg) as link:
            if link.client is None:
                out(f"agentmemory part INCOMPLETE: {link.error}\nRe-run with --resend --to {plan.new_key} --sid {plan.sid}")
                return 4
            code = print_am_report(plan, link.client, link.names or names, out)
    elif plan.am_note:
        out(f"agentmemory: {plan.am_note}")
    return code


def main(argv: list[str] | None = None) -> int:
    try:
        return run(parse_args(argv))
    except (cfgmod.ConfigError, KeyboardInterrupt, EOFError) as exc:
        print(f"Stopped: {exc or 'interrupted'}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
