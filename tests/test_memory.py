# tests/test_memory.py
import numpy as np
import pytest

from lowass.meeting import Meeting, meeting_text
from lowass.store import Store
from lowass.summary import MIN_LINES, build_prompt, summarise, worth_summarising

VOCAB = ["databaze", "migrace", "firewall", "nasazeni", "rozpocet", "database", "deployment", "budget"]


def fake_embed(texts, kind="search_document"):
    """Bag-of-words vectors: deterministic, no network."""
    out = np.zeros((len(texts), len(VOCAB) + 1), dtype=np.float32)
    for i, t in enumerate(texts):
        low = t.lower()
        for j, w in enumerate(VOCAB):
            out[i, j] = low.count(w)
        out[i, -1] = 0.01
    return out


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "memory.db", fake_embed)
    yield s
    s.close()


def test_search_finds_the_relevant_chunk_and_filters_by_project(store):
    store.start_session("s1", "proj_b", "p")
    store.add("s1", "proj_b", "transcript", "migrace databaze bude v sobotu")
    store.add("s1", "proj_b", "chat", "firewall pravidla musi schvalit security")
    store.add("s2", "proj_a", "transcript", "databaze pro proj_a se nemigruje")
    hits = store.search("kdy migrace databaze", k=3, project="proj_b")
    assert hits[0]["text"].startswith("migrace") and {h["project"] for h in hits} == {"proj_b"}
    assert store.search("databaze", k=5, kind="chat") == [] or all(h["kind"] == "chat" for h in store.search("databaze", 5, kind="chat"))
    assert len(store.search("databaze", k=10)) == 3


def test_text_is_saved_even_when_embedding_fails_and_backfill_fixes_it(tmp_path):
    state = {"down": True}

    def flaky(texts, kind="search_document"):
        if state["down"]:
            raise RuntimeError("network down")
        return fake_embed(texts, kind)

    s = Store(tmp_path / "m.db", flaky)
    s.add("s1", "proj_b", "transcript", "migrace databaze")
    assert s.counts() == {"chunks": 1, "without_vector": 1} and "network down" in s.last_error
    with pytest.raises(RuntimeError):  # a search needs the query embedded; the agent tool turns this into a message
        s.search("databaze")
    state["down"] = False
    assert s.backfill() == 1 and s.counts()["without_vector"] == 0 and s.last_error == ""
    assert s.search("databaze")[0]["text"] == "migrace databaze"


def test_store_without_embedder_still_stores_text(tmp_path):
    s = Store(tmp_path / "m.db", None)
    s.add("s1", "proj_b", "chat", "hello")
    assert s.counts()["chunks"] == 1 and s.search("hello") == [] and s.session_text("s1") == "hello"


def make_meeting(tmp_path, store, **kw):
    return Meeting(tmp_path / "data", store, "proj_b", background=False, **kw)


def test_no_folder_and_no_session_until_something_is_written(tmp_path, store):
    m = make_meeting(tmp_path, store)
    assert not (tmp_path / "data").exists()
    closed = m.rotate("proj_a")
    assert closed.lines == 0 and not (tmp_path / "data").exists()
    m.finish(closed, "")  # an empty meeting leaves no record
    assert store.counts()["chunks"] == 0


def test_transcript_goes_to_file_and_is_chunked_not_per_line(tmp_path, store):
    m = make_meeting(tmp_path, store, chunk_words=12, chunk_seconds=999)
    for i in range(6):
        m.transcript_line("Ja", f"migrace databaze cislo {i} je dulezita")
    text = (m.path / "transcript.md").read_text(encoding="utf-8")
    assert text.count("\n") == 6 and "Ja: migrace databaze cislo 0" in text
    n = store.counts()["chunks"]
    assert 1 <= n < 6  # several lines per chunk, one embedding call per chunk
    m.flush()
    assert store.counts()["chunks"] >= n


def test_turn_and_screenshot_are_stored_with_their_kind(tmp_path, store):
    m = make_meeting(tmp_path, store)
    m.turn("co je na obrazovce", "Teams: rozpocet 100 000", "screen", m.screen_path())
    m.turn("", "firewall je v poradku", "auto")
    chat = (m.path / "chat.md").read_text(encoding="utf-8")
    assert "screen: Teams" in chat and "(screenshot:" in chat and "auto: firewall" in chat
    kinds = sorted(h["kind"] for h in store.search("rozpocet firewall", k=5))
    assert kinds == ["chat", "screenshot"]
    assert (m.path / "screens").is_dir()


def test_rotate_ends_one_meeting_and_starts_the_next_with_a_new_folder(tmp_path, store):
    m = make_meeting(tmp_path, store)
    m.transcript_line("Ja", "prvni meeting databaze")
    first = m.path
    closed = m.rotate("proj_a")
    assert closed.path == first and closed.lines == 1 and closed.pending.endswith("prvni meeting databaze")
    assert m.project == "proj_a" and m.path != first and m.lines == 0 and "proj_a" in str(m.path)
    m.finish(closed, "shrnuti prvniho meetingu")
    assert (first / "summary.md").read_text(encoding="utf-8").startswith("shrnuti")
    assert any(h["kind"] == "summary" for h in store.search("shrnuti", k=5))
    assert "databaze" in meeting_text(first)


def test_two_boundaries_in_one_second_get_different_folders(tmp_path, store):
    m = make_meeting(tmp_path, store)
    paths = {m.path}
    for project in ("proj_a", "proj_b", "proj_c", "proj_b"):
        m.transcript_line("Ja", "x")
        m.rotate(project)
        paths.add(m.path)
    assert len(paths) == 5


def test_embedding_error_is_reported_once(tmp_path):
    def boom(texts, kind="search_document"):
        raise RuntimeError("down")

    errors = []
    m = Meeting(tmp_path / "d", Store(tmp_path / "m.db", boom), "proj_b", chunk_words=1, background=False, on_error=errors.append)
    m.transcript_line("Ja", "jedna dva tri")
    m.transcript_line("Ja", "ctyri pet sest")
    assert len(errors) == 1 and "saved" in errors[0]


class FakeAgent:
    def __init__(self):
        self.calls = []

    def run(self, prompt, context="", on_status=None, remember=True, image=None):
        self.calls.append((prompt, remember))
        return "  shrnuti  "


def test_summary_helpers():
    assert not worth_summarising(MIN_LINES - 1) and worth_summarising(MIN_LINES)
    p = build_prompt("TEMPLATE", "Proj A", "x" * 100_000)
    assert p.startswith("TEMPLATE") and "PROJECT: Proj A" in p and "earlier part cut" in p and len(p) < 61_000
    ag = FakeAgent()
    assert summarise(ag, "T", "Proj A", "text") == "shrnuti" and ag.calls[0][1] is False  # never remembered
    assert summarise(ag, "T", "Proj A", "   ") == "" and len(ag.calls) == 1
