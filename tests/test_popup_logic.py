# tests/test_popup_logic.py
from lowass.popup_logic import CardQueue, Rect, place_card, slide_positions

SCREEN_W = 1920
SCREEN_H = 1080


def test_place_card_prefers_left_of_main_window():
    main = Rect(800, 100, 400, 300)
    assert place_card(main, 340, 200, SCREEN_W, SCREEN_H) == (452, 100, "left")


def test_place_card_left_blocked_goes_below():
    main = Rect(100, 100, 400, 300)
    assert place_card(main, 340, 200, SCREEN_W, SCREEN_H) == (100, 408, "below")


def test_place_card_below_blocked_goes_inside():
    main = Rect(100, 700, 400, 300)
    assert place_card(main, 340, 200, SCREEN_W, SCREEN_H) == (100, 700, "inside")


def test_place_card_below_wider_than_screen_goes_inside():
    main = Rect(100, 100, 400, 300)
    assert place_card(main, 340, 200, 300, SCREEN_H)[2] == "inside"


def test_place_card_clamps_y_for_left_side():
    main = Rect(800, 1000, 400, 60)
    x, y, side = place_card(main, 340, 200, SCREEN_W, SCREEN_H)
    assert side == "left"
    assert (x, y) == (452, SCREEN_H - 48 - 200)


def test_place_card_clamps_negative_y_for_left_side():
    main = Rect(800, -20, 400, 300)
    assert place_card(main, 340, 200, SCREEN_W, SCREEN_H) == (452, 0, "left")


def test_slide_positions_left_ends_exactly_at_x():
    positions = slide_positions(452, "left")
    assert positions[0] == 476
    assert positions[-1] == 452
    assert len(positions) == 7
    assert positions == sorted(positions, reverse=True)


def test_slide_positions_other_sides_do_not_slide():
    assert slide_positions(100, "below") == [100]
    assert slide_positions(100, "inside") == [100]


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_card_queue_is_empty_at_start():
    queue = CardQueue(clock=FakeClock())
    assert queue.current() is None
    assert queue.remaining() == 0.0
    assert queue.extra() == 0


def test_card_queue_shows_card_until_ttl():
    clock = FakeClock()
    queue = CardQueue(ttl_sec=10.0, clock=clock)
    queue.show("Alice", 3.0, "Say yes")
    card = queue.current()
    assert card is not None
    assert (card.who, card.waited_sec, card.text) == ("Alice", 3.0, "Say yes")
    clock.now += 9.9
    assert queue.current() is not None
    clock.now += 0.2
    assert queue.current() is None


def test_card_queue_newer_hint_replaces_and_counts_extra():
    queue = CardQueue(clock=FakeClock())
    queue.show("Alice", 1.0, "first")
    queue.show("Bob", 2.0, "second")
    queue.show("Carol", 3.0, "third")
    card = queue.current()
    assert card is not None
    assert card.text == "third"
    assert queue.extra() == 2


def test_card_queue_extra_resets_after_expiry():
    clock = FakeClock()
    queue = CardQueue(ttl_sec=10.0, clock=clock)
    queue.show("Alice", 1.0, "first")
    queue.show("Bob", 2.0, "second")
    clock.now += 11.0
    queue.show("Carol", 3.0, "third")
    assert queue.extra() == 0


def test_card_queue_remaining_goes_from_one_to_zero():
    clock = FakeClock()
    queue = CardQueue(ttl_sec=10.0, clock=clock)
    queue.show("Alice", 1.0, "text")
    assert queue.remaining() == 1.0
    clock.now += 2.5
    assert queue.remaining() == 0.75
    clock.now += 20.0
    assert queue.remaining() == 0.0


def test_card_queue_dismiss_clears_card_and_extra():
    queue = CardQueue(clock=FakeClock())
    queue.show("Alice", 1.0, "first")
    queue.show("Bob", 2.0, "second")
    queue.dismiss()
    assert queue.current() is None
    assert queue.extra() == 0
