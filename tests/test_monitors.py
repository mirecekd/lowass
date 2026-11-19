# tests/test_monitors.py
"""Monitor choice and window placement: one monitor, two, three, gaps in the numbering, negative coordinates."""
import ctypes

from lowass import monitors
from lowass.layout import GAP, column_slots, fit, start_rect
from lowass.monitors import (
    Monitor,
    display_number,
    list_monitors,
    monitor_for_rect,
    pick_monitor,
)
from lowass.popup_logic import Rect

M1 = Monitor(1, Rect(0, 0, 1920, 1032), True)
M2 = Monitor(2, Rect(1920, 0, 2560, 1400), False)
M3 = Monitor(3, Rect(-1280, 100, 1280, 924), False)  # left of the primary: negative x


def test_display_number_reads_the_windows_device_name():
    assert display_number("\\\\.\\DISPLAY2", 9) == 2
    assert display_number("\\\\.\\display11", 9) == 11
    assert display_number("", 4) == 4 and display_number("monitor", 4) == 4


def test_default_is_the_highest_numbered_monitor_and_one_monitor_is_always_that_monitor():
    assert pick_monitor([M1, M2, M3]) is M3
    assert pick_monitor([M2, M1]) is M2  # the order of the list does not matter
    assert pick_monitor([M1]) is M1
    for which in ("last", "primary", 1, 2, "7", "nonsense", None):
        assert pick_monitor([M1], which) is M1


def test_primary_a_number_and_a_missing_number():
    assert pick_monitor([M1, M2], "primary") is M1
    assert pick_monitor([M1, M2], 1) is M1 and pick_monitor([M1, M2], "2") is M2
    assert pick_monitor([M1, M2], 5) is M2  # no such monitor: the highest one
    gaps = [Monitor(1, M1.work, True), Monitor(3, M2.work, False)]  # monitor 2 was unplugged: numbering has a gap
    assert pick_monitor(gaps).number == 3 and pick_monitor(gaps, 2).number == 3


def test_primary_choice_without_a_primary_flag_falls_back_to_the_lowest_number():
    assert pick_monitor([Monitor(2, M2.work, False), Monitor(1, M1.work, False)], "primary").number == 1


def test_window_is_assigned_to_the_monitor_it_overlaps_most():
    assert monitor_for_rect([M1, M2, M3], Rect(2000, 50, 460, 760)) is M2
    assert monitor_for_rect([M1, M2, M3], Rect(-1000, 200, 460, 760)) is M3
    assert monitor_for_rect([M1, M2], Rect(1800, 50, 400, 300)) is M2  # 120 px on M1, 280 px on M2
    assert monitor_for_rect([M1, M2], Rect(5000, 5000, 100, 100)) is M2  # outside everything: the nearest one


def test_enumeration_failure_or_nothing_found_gives_the_tk_screen_as_the_single_monitor():
    screen = Rect(0, 0, 1366, 768)

    def boom():
        raise OSError("no display")

    assert list_monitors(screen, boom) == [Monitor(1, screen, True)]
    assert list_monitors(screen, list) == [Monitor(1, screen, True)]
    assert list_monitors(screen, lambda: [M1, M2]) == [M1, M2]


def test_this_platform_without_windows_api_still_gives_one_monitor():
    screen = Rect(0, 0, 1280, 800)
    assert len(list_monitors(screen)) >= 1  # on Linux there is no enumeration: the Tk screen


def test_windows_structure_has_the_size_the_api_expects():
    """MONITORINFOEXW is 104 bytes: 4 + 16 + 16 + 4 + 64. The fields are fixed-size, so this holds on every platform."""
    assert ctypes.sizeof(monitors._Info) == 104 and ctypes.sizeof(monitors._Rect32) == 16


def test_start_rect_counts_a_negative_x_from_the_right_edge_of_the_chosen_monitor():
    r = start_rect(M2.work, 460, 760, -20, 60)
    assert r == Rect(1920 + 2560 - 460 - 20, 60, 460, 760)
    assert start_rect(M1.work, 460, 760, 100, 60) == Rect(100, 60, 460, 760)


def test_start_rect_shrinks_and_moves_up_on_a_small_screen():
    small = Rect(0, 0, 1366, 728)  # a laptop: the work area is lower than the 760 px window
    r = start_rect(small, 460, 760, -20, 60)
    assert r.h == 728 and r.y == 0 and r.x == 1366 - 460 - 20


def test_start_rect_on_a_monitor_to_the_left_has_negative_coordinates():
    r = start_rect(M3.work, 460, 760, -20, 60)
    assert r.x == -1280 + 1280 - 460 - 20 and r.y == 160


def test_fit_keeps_a_window_inside_the_area():
    assert fit(Rect(0, 0, 1000, 800), Rect(900, 700, 300, 300)) == Rect(700, 500, 300, 300)
    assert fit(Rect(0, 0, 1000, 800), Rect(-50, -50, 200, 200)) == Rect(0, 0, 200, 200)


def test_two_windows_stack_in_halves_right_next_to_the_main_window():
    main = Rect(1440, 60, 460, 760)
    top, bottom = column_slots(main, Rect(0, 0, 1920, 1032))
    assert top.x == bottom.x == 1440 - GAP - 420 and top.w == bottom.w == 420  # touching the main window, no gap for the card
    assert top.y == 0 and bottom.y == top.h + GAP and bottom.y + bottom.h == 1032  # together exactly the area
    assert abs(top.h - bottom.h) <= 1  # each one half of the height


def test_stacked_windows_follow_the_main_window_to_the_second_monitor():
    main = start_rect(M2.work, 460, 760, -20, 60)
    top, bottom = column_slots(main, M2.work)
    assert M2.work.x <= top.x and top.x + top.w <= M2.work.x + M2.work.w  # still on monitor 2
    assert top.y == M2.work.y and bottom.y + bottom.h == M2.work.y + M2.work.h


def test_stacked_windows_stay_on_a_narrow_screen():
    top, bottom = column_slots(Rect(300, 20, 460, 700), Rect(0, 0, 760, 728))
    assert top.x >= 0 and top.x + top.w <= 760 and bottom.y + bottom.h <= 728
