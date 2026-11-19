# lowass/store.py
"""Local vector store: plain SQLite + float32 BLOBs + numpy cosine search.

No native SQLite extension (Windows Python builds often cannot load them). Meeting data is small, brute force is fine.
A chunk is saved FIRST (text never gets lost); its vector is added right after and retried later if embedding failed.
"""
from __future__ import annotations

import sqlite3
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions(
  id TEXT PRIMARY KEY, project TEXT, started REAL, ended REAL, summary TEXT, path TEXT);
CREATE TABLE IF NOT EXISTS chunks(
  id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, project TEXT, kind TEXT, ts REAL,
  text TEXT, path TEXT, embedding BLOB);
CREATE INDEX IF NOT EXISTS chunks_session ON chunks(session_id);
"""


class Store:
    def __init__(self, db_path: Path, embed: Callable[[list[str], str], np.ndarray] | None):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(db_path), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(SCHEMA)
        self._lock = threading.Lock()
        self._embed = embed
        self.last_error = ""

    def start_session(self, sid: str, project: str, path: str) -> None:
        with self._lock:
            self._db.execute("INSERT OR IGNORE INTO sessions(id, project, started, path) VALUES(?,?,?,?)",
                             (sid, project, time.time(), path))
            self._db.commit()

    def end_session(self, sid: str, summary: str = "") -> None:
        with self._lock:
            self._db.execute("UPDATE sessions SET ended=?, summary=? WHERE id=?", (time.time(), summary, sid))
            self._db.commit()

    def add(self, sid: str, project: str, kind: str, text: str, path: str = "", ts: float | None = None) -> int:
        """Saves the text, then tries to embed it. Returns the chunk id; an embedding failure is kept in last_error."""
        with self._lock:
            cur = self._db.execute("INSERT INTO chunks(session_id, project, kind, ts, text, path) VALUES(?,?,?,?,?,?)",
                                   (sid, project, kind, ts or time.time(), text, path))
            self._db.commit()
            cid = int(cur.lastrowid or 0)
        self._embed_missing([cid])
        return cid

    def _embed_missing(self, ids: list[int]) -> int:
        if not self._embed or not ids:
            return 0
        with self._lock:
            rows = self._db.execute("SELECT id, text FROM chunks WHERE embedding IS NULL").fetchall()
        wanted = set(ids)
        rows = [r for r in rows if r["id"] in wanted]
        if not rows:
            return 0
        try:
            vecs = self._embed([r["text"] for r in rows], "search_document")
        except Exception as exc:  # noqa: BLE001 - text is already saved; the vector is retried by backfill()
            self.last_error = f"{type(exc).__name__}: {exc}"[:200]
            return 0
        with self._lock:
            self._db.executemany("UPDATE chunks SET embedding=? WHERE id=?",
                                 [(v.astype(np.float32).tobytes(), r["id"]) for v, r in zip(vecs, rows, strict=True)])
            self._db.commit()
        self.last_error = ""
        return len(rows)

    def backfill(self, limit: int = 96) -> int:
        """Embeds chunks that were saved without a vector (network was down). Returns how many got one."""
        with self._lock:
            ids = [r["id"] for r in self._db.execute("SELECT id FROM chunks WHERE embedding IS NULL LIMIT ?", (limit,))]
        return self._embed_missing(ids)

    def search(self, query: str, k: int = 5, project: str | None = None, kind: str | None = None) -> list[dict[str, Any]]:
        if not self._embed:
            return []
        qv = self._embed([query], "search_query")[0].astype(np.float32)
        with self._lock:
            rows = self._db.execute(
                "SELECT id, session_id, project, kind, ts, text, path, embedding FROM chunks "
                "WHERE embedding IS NOT NULL AND (? IS NULL OR project=?) AND (? IS NULL OR kind=?)",
                (project, project, kind, kind)).fetchall()
        if not rows:
            return []
        mat = np.vstack([np.frombuffer(r["embedding"], dtype=np.float32) for r in rows])
        denom = np.linalg.norm(mat, axis=1) * (np.linalg.norm(qv) or 1.0)
        score = (mat @ qv) / np.where(denom == 0, 1.0, denom)
        top = np.argsort(-score)[:k]
        return [{**{c: rows[i][c] for c in ("session_id", "project", "kind", "ts", "text", "path")}, "score": float(score[i])}
                for i in top]

    def session_text(self, sid: str, kinds: tuple[str, ...] = ("transcript", "chat")) -> str:
        with self._lock:
            rows = self._db.execute("SELECT kind, text FROM chunks WHERE session_id=? ORDER BY ts, id", (sid,)).fetchall()
        return "\n".join(r["text"] for r in rows if r["kind"] in kinds)

    def counts(self) -> dict[str, int]:
        with self._lock:
            r = self._db.execute("SELECT COUNT(*) n, SUM(embedding IS NULL) m FROM chunks").fetchone()
        return {"chunks": int(r["n"] or 0), "without_vector": int(r["m"] or 0)}

    def close(self) -> None:
        with self._lock:
            self._db.close()
