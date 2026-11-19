# lowass/guard.py
"""Read-only guard for tools reached through mcphub call_tool."""
from __future__ import annotations

import re

# "list_merge_requests" is a read even though "merge" is a write verb: a read verb directly before it wins
READ_BEFORE = re.compile(r"(?:^|[_\-])(?:list|get|search|read|fetch|find|query|describe|view)[_\-]$", re.IGNORECASE)


def blocked(tool_name: str, deny: re.Pattern[str]) -> bool:
    name = tool_name or ""
    m = deny.search(name)
    if not m:
        return False
    return not READ_BEFORE.search(name[:m.start() + 1])


def check_call(arguments: dict, deny: re.Pattern[str]) -> str | None:
    """Return an error text if a call_tool request must not run, else None."""
    name = str(arguments.get("toolName", ""))
    if not name:
        return "ERROR: toolName is missing."
    if blocked(name, deny):
        return f"BLOCKED: '{name}' looks like a write operation; LOWASS is read-only. Use a read/search tool instead."
    return None
