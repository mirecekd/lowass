# tests/test_hints.py
from lowass.hints import HintWatcher, Pending

ME = "Ja"
THEM = "Protistrana"


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def make(clock: FakeClock) -> HintWatcher:
    return HintWatcher(ME, ["Miroslav", "Miro"], clock=clock)


def test_question_mark_is_candidate() -> None:
    clock = FakeClock()
    watcher = make(clock)
    watcher.heard(THEM, "Kdy to bude hotove?")
    clock.now += 13
    pending = watcher.due()
    assert pending == Pending(THEM, "Kdy to bude hotove?", 1000.0)


def test_name_with_diacritics_is_candidate() -> None:
    clock = FakeClock()
    watcher = HintWatcher(ME, ["Miroslavě"], clock=clock)
    watcher.heard(THEM, "Řekni nám něco, Miroslave.")
    clock.now += 13
    assert watcher.due() is not None


def test_short_name_as_whole_word() -> None:
    clock = FakeClock()
    watcher = make(clock)
    watcher.heard(THEM, "Miro, ty to znáš.")
    clock.now += 13
    assert watcher.due() is not None


def test_name_inside_other_word_is_not_candidate() -> None:
    clock = FakeClock()
    watcher = make(clock)
    watcher.heard(THEM, "Mirone je jiny clovek.")
    clock.now += 13
    assert watcher.due() is None


def test_opener_is_candidate() -> None:
    clock = FakeClock()
    watcher = make(clock)
    watcher.heard(THEM, "Mohl bys to poslat zitra.")
    clock.now += 13
    assert watcher.due() is not None


def test_english_opener_is_candidate() -> None:
    clock = FakeClock()
    watcher = make(clock)
    watcher.heard(THEM, "Could you send it tomorrow.")
    clock.now += 13
    assert watcher.due() is not None


def test_plain_statement_is_not_candidate() -> None:
    clock = FakeClock()
    watcher = make(clock)
    watcher.heard(THEM, "Dnes je pekne pocasi.")
    clock.now += 13
    assert watcher.due() is None


def test_user_sentences_never_create_pending() -> None:
    clock = FakeClock()
    watcher = make(clock)
    watcher.heard(ME, "Co to je za vec?")
    clock.now += 13
    assert watcher.due() is None


def test_short_user_reply_does_not_clear() -> None:
    clock = FakeClock()
    watcher = make(clock)
    watcher.heard(THEM, "Kdy to bude?")
    watcher.heard(ME, "moment")
    watcher.heard(ME, "ano ano")
    clock.now += 13
    assert watcher.due() is not None


def test_real_user_answer_clears() -> None:
    clock = FakeClock()
    watcher = make(clock)
    watcher.heard(THEM, "Kdy to bude?")
    watcher.heard(ME, "bude to hotove zitra")
    clock.now += 13
    assert watcher.due() is None


def test_wait_boundary() -> None:
    clock = FakeClock()
    watcher = make(clock)
    watcher.heard(THEM, "Kdy to bude?")
    clock.now += 12
    assert watcher.due() is None
    clock.now += 0.1
    assert watcher.due() is not None


def test_max_age_drops_stale_question() -> None:
    clock = FakeClock()
    watcher = make(clock)
    watcher.heard(THEM, "Kdy to bude?")
    clock.now += 89.9
    assert watcher.due() is not None
    watcher.heard(THEM, "Kdy to bude opravdu?")
    clock.now += 90
    assert watcher.due() is None
    clock.now += 1
    assert watcher.due() is None


def test_newer_question_replaces_older() -> None:
    clock = FakeClock()
    watcher = make(clock)
    watcher.heard(THEM, "Prvni otazka?")
    clock.now += 5
    watcher.heard(THEM, "Druha otazka?")
    clock.now += 10
    assert watcher.due() is None  # newer one is only 10 s old
    clock.now += 3
    pending = watcher.due()
    assert pending is not None
    assert pending.text == "Druha otazka?"


def test_statement_does_not_clear_pending() -> None:
    clock = FakeClock()
    watcher = make(clock)
    watcher.heard(THEM, "Kdy to bude?")
    watcher.heard(THEM, "Dnes je pekne pocasi.")
    clock.now += 13
    pending = watcher.due()
    assert pending is not None
    assert pending.text == "Kdy to bude?"


def test_no_double_delivery_until_new_candidate() -> None:
    clock = FakeClock()
    watcher = make(clock)
    watcher.heard(THEM, "Kdy to bude?")
    clock.now += 13
    assert watcher.due() is not None
    assert watcher.due() is None
    clock.now += 5
    watcher.heard(THEM, "A co dalsi?")
    clock.now += 13
    pending = watcher.due()
    assert pending is not None
    assert pending.text == "A co dalsi?"


def test_handled_starts_cooldown() -> None:
    clock = FakeClock()
    watcher = make(clock)
    watcher.heard(THEM, "Kdy to bude?")
    clock.now += 13
    assert watcher.due() is not None
    watcher.handled()
    watcher.heard(THEM, "A co dalsi?")
    clock.now += 13
    assert watcher.due() is None  # within 45 s cooldown
    clock.now += 33
    assert watcher.due() is not None  # more than 45 s since handled()


def test_cooldown_boundary() -> None:
    clock = FakeClock()
    watcher = make(clock)
    watcher.handled()
    watcher.heard(THEM, "A co dalsi?")
    clock.now += 45
    assert watcher.due() is None
    clock.now += 0.1
    assert watcher.due() is not None


def test_empty_and_whitespace_ignored() -> None:
    clock = FakeClock()
    watcher = make(clock)
    watcher.heard(THEM, "Kdy to bude?")
    watcher.heard(THEM, "   ")
    watcher.heard(THEM, "")
    watcher.heard(ME, "  ")
    clock.now += 13
    pending = watcher.due()
    assert pending is not None
    assert pending.text == "Kdy to bude?"


def test_czech_case_forms_of_the_users_names_match_but_surnames_do_not():
    """People call him 'Miroslave', 'Mirku', 'Mirovi'; a surname that merely starts the same must not wake the assistant."""
    from lowass.hints import name_pattern

    cases = {
        "miroslav": (["miroslave", "miroslavu", "miroslavovi", "miroslava"], ["miroslavsky", "miros"]),
        "mirek": (["mirek", "mirku", "mirka", "mirkovi", "mirkem"], ["mirkov", "mirecek"]),
        "miro": (["miro", "mira", "mirovi", "mirem"], ["mironov", "mir", "miroslavsky"]),
    }
    for name, (yes, no) in cases.items():
        pattern = name_pattern(name)
        assert all(pattern.search(w) for w in yes), (name, [w for w in yes if not pattern.search(w)])
        assert not any(pattern.search(w) for w in no), (name, [w for w in no if pattern.search(w)])
