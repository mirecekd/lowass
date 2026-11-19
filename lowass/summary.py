# lowass/summary.py
"""Meeting summary: pure text helpers + one agent call. The prompt lives in lowass.toml [prompts].summary."""
from __future__ import annotations

from typing import Any

MIN_LINES = 3  # fewer transcript lines + chat turns than this: no summary (an accidental Clear)
MAX_CHARS = 60_000  # keeps the request small; the tail of a very long meeting is the most recent part


def build_prompt(template: str, project_name: str, meeting_text: str) -> str:
    body = meeting_text if len(meeting_text) <= MAX_CHARS else "...[earlier part cut]\n" + meeting_text[-MAX_CHARS:]
    return f"{template}\n\nPROJECT: {project_name}\n\nMEETING:\n{body}"


def worth_summarising(lines: int) -> bool:
    return lines >= MIN_LINES


def summarise(agent: Any, template: str, project_name: str, meeting_text: str) -> str:
    """One stateless agent call (nothing remembered). Returns '' when there is nothing to summarise."""
    if not meeting_text.strip():
        return ""
    return agent.run(build_prompt(template, project_name, meeting_text), "", remember=False).strip()
