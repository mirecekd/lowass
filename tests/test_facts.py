# tests/test_facts.py
import threading

from lowass.facts import FactsSheet

WORDS_5 = "one two three four five"


class FakeComplete:
    def __init__(self, answer: str | Exception = "SHEET"):
        self.answer = answer
        self.calls: list[tuple[str, str]] = []

    def __call__(self, system: str, user: str) -> str:
        self.calls.append((system, user))
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


def make(answer: str | Exception = "SHEET", **kwargs):
    fake = FakeComplete(answer)
    return FactsSheet(fake, "PROMPT", min_new_words=5, **kwargs), fake


def test_due_threshold():
    sheet, _ = make()
    assert not sheet.due()
    sheet.feed("one two three")
    assert not sheet.due()
    sheet.feed("four five")
    assert sheet.due()


def test_update_sends_only_new_text_and_previous_sheet():
    sheet, fake = make("FIRST")
    sheet.feed("alpha beta")
    assert sheet.update() is True
    assert sheet.text == "FIRST"
    fake.answer = "SECOND"
    sheet.feed("gamma delta")
    assert sheet.update() is True
    system, user = fake.calls[1]
    assert system == "PROMPT"
    assert "FIRST" in user and "gamma delta" in user
    assert "alpha" not in user
    assert not sheet.due()


def test_failure_keeps_sheet_and_buffer():
    sheet, fake = make("OLD")
    sheet.feed("alpha beta")
    sheet.update()
    fake.answer = RuntimeError("boom")
    sheet.feed(WORDS_5)
    assert sheet.update() is False
    assert sheet.text == "OLD"
    assert sheet.due()
    fake.answer = "NEW"
    assert sheet.update() is True
    assert WORDS_5 in fake.calls[-1][1]


def test_nothing_or_empty_keeps_sheet():
    sheet, fake = make("OLD")
    sheet.feed("alpha")
    sheet.update()
    for answer in ("NOTHING", "  ", ""):
        fake.answer = answer
        sheet.feed("beta")
        assert sheet.update() is False
        assert sheet.text == "OLD"


def test_unchanged_answer_returns_false():
    sheet, _ = make("SAME")
    sheet.feed("alpha")
    assert sheet.update() is True
    sheet.feed("beta")
    assert sheet.update() is False


def test_update_without_new_text_makes_no_call():
    sheet, fake = make()
    assert sheet.update() is False
    assert fake.calls == []


def test_max_chars_cut_on_line_boundary():
    sheet, _ = make("line one\nline two\nline three is long", max_chars=22)
    sheet.feed("x")
    sheet.update()
    assert sheet.text == "line one\nline two"


def test_max_chars_cut_when_line_ends_exactly_at_limit():
    sheet, _ = make("line one\nline two\nmore", max_chars=17)
    sheet.feed("x")
    sheet.update()
    assert sheet.text == "line one\nline two"


def test_max_chars_single_long_line_is_hard_cut():
    sheet, _ = make("abcdefghij", max_chars=4)
    sheet.feed("x")
    sheet.update()
    assert sheet.text == "abcd"


def test_reset_clears_sheet_and_buffer():
    sheet, _ = make("OLD")
    sheet.feed(WORDS_5)
    sheet.update()
    sheet.feed(WORDS_5)
    sheet.reset()
    assert sheet.text == ""
    assert not sheet.due()


def test_feed_during_update_is_kept_for_next_round():
    started = threading.Event()
    release = threading.Event()
    calls: list[str] = []

    def slow(system: str, user: str) -> str:
        calls.append(user)
        started.set()
        release.wait(timeout=5)
        return "SHEET"

    sheet = FactsSheet(slow, "PROMPT", min_new_words=2)
    sheet.feed("alpha beta")
    result: list[bool] = []
    worker = threading.Thread(target=lambda: result.append(sheet.update()))
    worker.start()
    assert started.wait(timeout=5)
    feeder = threading.Thread(target=lambda: sheet.feed("late words"))
    feeder.start()
    feeder.join(timeout=5)
    assert not feeder.is_alive()  # feed() does not wait for the running LLM call
    release.set()
    worker.join(timeout=5)
    assert result == [True]
    assert "late" not in calls[0]
    assert sheet.due()
    sheet.update()
    assert "late words" in calls[1]
