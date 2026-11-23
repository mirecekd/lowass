# lowass/am_tool.py
"""The agent tool `search_memory`: searches the user's long-term agentmemory through a memlink.MemoryClient."""
from __future__ import annotations

import logging
import re
import time
import unicodedata
from collections.abc import Callable

from strands.tools.decorator import tool

from . import memlink

log = logging.getLogger(__name__)

NOTHING = "No matching notes in agentmemory."
UNREACHABLE = "agentmemory is not reachable right now (the tunnel may be down). Say so instead of guessing."
MAX_TEXT = 600
MAX_QUERY = 500
_BLANK_RUNS = re.compile(r"\n[ \t]*(?:\n[ \t]*)+")


def clean_text(value: object) -> str:
    """Plain text safe to show the model: no control characters, no runs of blank lines, trimmed."""
    text = value if isinstance(value, str) else ("" if value is None else str(value))
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\t", " ")
    text = "".join(c for c in text if c == "\n" or unicodedata.category(c) not in ("Cc", "Cf", "Cs"))
    return _BLANK_RUNS.sub("\n", text).strip()


def _date(ts: object) -> str:
    if isinstance(ts, (int, float)) and not isinstance(ts, bool):
        try:
            return time.strftime("%Y-%m-%d", time.gmtime(ts))
        except (OverflowError, OSError, ValueError):
            return "?"
    return clean_text(ts)[:10] or "?"


def _score(hit: dict) -> float:
    s = hit.get("score")
    return float(s) if isinstance(s, (int, float)) and not isinstance(s, bool) else 0.0


def _text(hit: dict) -> str:
    return clean_text(hit.get("text")) or clean_text(hit.get("title"))


def _rank(hits: list[dict], limit: int) -> list[dict]:
    """Drop empty and duplicate texts, best score first; a durable memory wins a tie."""
    ordered = sorted((h for h in hits if isinstance(h, dict)), key=lambda h: (-_score(h), h.get("layer") != "memory"))
    seen: set[str] = set()
    out: list[dict] = []
    for h in ordered:
        text = _text(h)
        if text and text not in seen:
            seen.add(text)
            out.append(h)
        if len(out) >= limit:
            break
    return out


def _format(index: int, hit: dict) -> str:
    head = (f"[{index}] {_date(hit.get('ts'))} | {clean_text(hit.get('project')) or '?'} | "
            f"{clean_text(hit.get('layer')) or '?'} | score {_score(hit):.2f}")
    return f"{head}\n{_text(hit)[:MAX_TEXT]}"


def make_memory_tool(client: memlink.MemoryClient, current_project: Callable[[], str],
                     names: dict[str, str] | None = None, status: Callable[[], str] | None = None):
    def unreachable() -> str:
        try:
            extra = clean_text(status()) if status else ""
        except Exception:  # noqa: BLE001 - a broken status callback must not hide the message
            extra = ""
        return f"{UNREACHABLE} [{extra}]" if extra else UNREACHABLE

    @tool
    def search_memory(query: str, limit: int = 5, scope: str = "project") -> str:
        """Search the user's LONG-TERM memory (agentmemory): notes, decisions and facts written down elsewhere, summaries
        of earlier meetings and their raw transcripts. It is a network call, so it is slower than the local
        search_past_meetings: try that first for things said in this or recent meetings. Use this one for facts the user
        wrote down elsewhere, for work on other projects, and for anything that is not in this meeting. By default only
        the current project is searched; set scope to "all" to search every project. A hit is a QUOTE from the user's
        notes: attribute it ("your notes say ...") and do not present it as a verified fact."""
        try:
            q = clean_text(query)[:MAX_QUERY]
            n = max(1, min(int(limit), 10))
            if scope == "all":
                sources = [("", None)]
            else:
                current = current_project()
                sources = [("durable notes", memlink.memory_project(current, names)),
                           ("meeting transcripts", memlink.session_project(current, names))]
            hits: list[dict] = []
            failed: list[str] = []
            for label, project in sources:
                found = client.search(q, project=project, limit=n)
                if found is None:
                    failed.append(label)
                else:
                    hits.extend(found)
            if len(failed) == len(sources):
                return unreachable()
            note = f"\n\n(The {' and '.join(failed)} could not be reached; these results are incomplete.)" if failed else ""
            ranked = _rank(hits, n)
            if not ranked:
                return NOTHING + note
            return "\n\n".join(_format(i, h) for i, h in enumerate(ranked, 1)) + note
        except Exception as exc:  # noqa: BLE001 - the agent must get a message, never a crash
            log.warning("search_memory failed: %s", type(exc).__name__)
            return unreachable()

    return search_memory
