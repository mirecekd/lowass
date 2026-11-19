# lowass/memory.py
"""Builds the local memory (Store + Embedder + Meeting) from lowass.toml and exposes search to the agent."""
from __future__ import annotations

import threading
import time
from collections.abc import Callable
from pathlib import Path

from strands.tools.decorator import tool

from .config import ROOT, Config
from .embed import Embedder
from .meeting import Meeting
from .store import Store


def data_dir(cfg: Config) -> Path:
    p = Path(cfg.section("memory").get("data_dir", "data"))
    return p if p.is_absolute() else ROOT / p


def open_meeting(cfg: Config, project: str, on_error: Callable[[str], None] | None = None) -> Meeting:
    m, e = cfg.section("memory"), cfg.section("embeddings")
    embed = None
    if e.get("enabled") and cfg.env("LITELLM_API_KEY"):
        embed = Embedder(cfg.env("LITELLM_BASE_URL"), cfg.env("LITELLM_API_KEY"), e["model"],
                         int(e.get("dimensions", 1536)), float(e.get("timeout_sec", 60))).embed
    d = data_dir(cfg)
    store = Store(d / "memory.db", embed)
    threading.Thread(target=_backfill, args=(store,), daemon=True, name="embed-backfill").start()
    return Meeting(d, store, project, int(m.get("chunk_words", 180)), float(m.get("chunk_seconds", 90)), on_error)


def _backfill(store: Store) -> None:
    for _ in range(20):  # text saved while the network was down gets its vector later
        if not store.backfill():
            return


def make_search_tool(store: Store, current_project: Callable[[], str]):
    @tool
    def search_past_meetings(query: str, limit: int = 5, all_projects: bool = False) -> str:
        """Search the user's EARLIER meetings stored locally: transcripts, the chat with this assistant, descriptions
        of screenshots and meeting summaries. Use it when someone refers to something said or decided before, or to check
        what was agreed earlier. By default only the current project is searched; set all_projects only when asked."""
        try:
            hits = store.search(query, k=max(1, min(limit, 10)), project=None if all_projects else current_project())
        except Exception as exc:  # noqa: BLE001 - the agent must get a message, not a crash, when embedding is down
            return f"Meeting search is unavailable right now ({type(exc).__name__}). Say so instead of guessing."
        if not hits:
            return "No stored meetings match."
        return "\n\n".join(f"[{time.strftime('%Y-%m-%d %H:%M', time.localtime(h['ts']))} | {h['project']} | {h['kind']} | "
                           f"score {h['score']:.2f}]\n{h['text'][:700]}" for h in hits)

    return search_past_meetings
