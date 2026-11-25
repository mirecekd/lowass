# lowass/move_report.py
"""Runs the agentmemory part of a move and tells the user what happened, including what was NOT done."""
from __future__ import annotations

from collections.abc import Callable

from .memlink import MemoryClient
from .move_am import apply_agentmemory
from .move_plan import AM_MOVE, Plan

REDO = "A re-run is safe as far as the server de-duplicates identical observations (UNVERIFIED): "


def print_am_report(plan: Plan, client: MemoryClient, names: dict[str, str], out: Callable[[str], None]) -> int:
    """Returns 0 when everything was accepted, 4 when the agentmemory part is INCOMPLETE."""
    rep = apply_agentmemory(plan, client, names, out)
    if plan.deletes or rep.old_memories:
        out(f"Old summary/facts memories under project '{plan.old_memory_project}' ({len(rep.old_memories)}):")
        for h in rep.old_memories:
            out(f"  - {h.get('title') or '(no title)'} | {str(h.get('text', ''))[:80]!r}")
        if rep.old_memories:
            out("  Delete them by hand (MCP tool memory_governance_delete); this tool has no verified REST delete.")
    out(f"agentmemory: {rep.memories_sent} memories and {rep.observations_sent}/{rep.observations_total} transcript lines sent")
    if plan.am_mode == AM_MOVE:
        out(f"NOTE: the OLD observations stay under project '{plan.old_session_project}' in agentmemory (the API cannot delete them).")
    if rep.incomplete:
        out("agentmemory part INCOMPLETE:")
        for p in rep.problems:
            out(f"  - {p}")
        out(f"{REDO}python -m lowass.move_meeting --resend --to {plan.new_key} --sid {plan.sid}")
        return 4
    return 0
