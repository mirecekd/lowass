# tests/test_resolutions.py
"""The window must start in the same relative place on EVERY resolution and monitor arrangement.

Tk reads a geometry string `WxH+X+Y` / `WxH-X-Y`; the helper below reproduces that rule, so the test would have caught
the field bug where a negative coordinate was written as `-N` (which Tk reads as 'N px from the right / bottom edge')."""
import re

import pytest

from lowass.layout import GAP, column_slots, geometry_string, start_rect
from lowass.monitors import Monitor, pick_monitor
from lowass.popup_logic import Rect, place_card

TASKBAR = 48
CFG = {"width": 560, "height": 860, "x": -20, "y": 60}  # the values of the real lowass.toml


def tk_reads(geometry: str, virtual: Rect) -> Rect:
    """What Tk does with a geometry string `WxH+X+Y`. CERTAIN (Tk manual): `+X` / `+Y` are absolute coordinates of the left /
    top edge in the screen coordinate system whose origin is the top-left corner of the PRIMARY monitor, so `+-1920` is a
    real negative coordinate. `-X` / `-Y` mean the distance from the RIGHT / BOTTOM edge of the screen to the window edge;
    which screen edge that is with several monitors is an ASSUMPTION here (the primary one), and it does not matter for
    what the test proves: it is NOT the negative coordinate that was asked for."""
    m = re.fullmatch(r"(\d+)x(\d+)([+-])(-?\d+)([+-])(-?\d+)", geometry)
    assert m, geometry
    w, h, sx, x, sy, y = int(m[1]), int(m[2]), m[3], int(m[4]), m[5], int(m[6])
    left = x if sx == "+" else virtual.x + virtual.w - w - abs(x)
    top = y if sy == "+" else virtual.y + virtual.h - h - abs(y)
    return Rect(left, top, w, h)


def virtual_screen(monitors: list[Monitor]) -> Rect:
    left = min(m.work.x for m in monitors)
    top = min(m.work.y for m in monitors)
    right = max(m.work.x + m.work.w for m in monitors)
    bottom = max(m.work.y + m.work.h for m in monitors)
    return Rect(left, top, right - left, bottom - top)


def work(w: int, h: int, x: int = 0, y: int = 0) -> Rect:
    return Rect(x, y, w, h - TASKBAR)  # a work area: the screen minus the taskbar


# name -> (the arrangement of monitors)
ARRANGEMENTS = {
    "one 1366x768": [Monitor(1, work(1366, 768), True)],
    "one 1920x1080": [Monitor(1, work(1920, 1080), True)],
    "one 4k": [Monitor(1, work(3840, 2160), True)],
    "right of primary": [Monitor(1, work(1920, 1080), True), Monitor(2, work(2560, 1440, 1920, 0), False)],
    "left of primary": [Monitor(1, work(1920, 1080), True), Monitor(2, work(1920, 1080, -1920, 0), False)],
    "above primary": [Monitor(1, work(1920, 1080), True), Monitor(2, work(1920, 1080, 0, -1080), False)],
    "below primary": [Monitor(1, work(1920, 1080), True), Monitor(2, work(1920, 1080, 0, 1080), False)],
    "left and offset up": [Monitor(1, work(1920, 1080), True), Monitor(2, work(2560, 1440, -2560, -360), False)],
    "three in a row": [Monitor(1, work(1920, 1080), True), Monitor(2, work(1920, 1080, 1920, 0), False),
                       Monitor(3, work(1920, 1080, 3840, 0), False)],
    "portrait second": [Monitor(1, work(1920, 1080), True), Monitor(2, work(1080, 1920, 1920, -400), False)],
    "primary on the right": [Monitor(2, work(1920, 1080, -1920, 0), False), Monitor(1, work(1920, 1080), True)],
}


@pytest.mark.parametrize("name", list(ARRANGEMENTS))
def test_main_window_lands_where_it_was_meant_to_on_every_arrangement(name):
    monitors = ARRANGEMENTS[name]
    area = pick_monitor(monitors, "last").work
    rect = start_rect(area, CFG["width"], CFG["height"], CFG["x"], CFG["y"])
    seen = tk_reads(geometry_string(rect), virtual_screen(monitors))  # what Tk would really do with the string
    assert seen == rect, f"{name}: asked for {rect}, Tk would put it at {seen}"
    assert area.x <= seen.x and seen.x + seen.w <= area.x + area.w, "inside the monitor horizontally"
    assert area.y <= seen.y and seen.y + seen.h <= area.y + area.h, "inside the work area vertically (no taskbar)"


@pytest.mark.parametrize("name", list(ARRANGEMENTS))
def test_the_offsets_are_the_same_on_every_monitor_20_from_the_right_60_from_the_top(name):
    area = pick_monitor(ARRANGEMENTS[name], "last").work
    r = start_rect(area, CFG["width"], CFG["height"], CFG["x"], CFG["y"])
    if r.h == CFG["height"]:  # a window that had to shrink is moved up instead: only check the ones that fit
        assert r.y - area.y == 60
    assert area.x + area.w - (r.x + r.w) == 20 or r.w < CFG["width"]


@pytest.mark.parametrize("name", list(ARRANGEMENTS))
def test_the_old_string_would_have_been_wrong_where_a_coordinate_is_negative(name):
    """The bug: f'{x:+d}{y:+d}' wrote `-1920` for a monitor left of the primary, and Tk read it as 'from the right edge'."""
    monitors = ARRANGEMENTS[name]
    rect = start_rect(pick_monitor(monitors, "last").work, CFG["width"], CFG["height"], CFG["x"], CFG["y"])
    old = f"{rect.w}x{rect.h}{rect.x:+d}{rect.y:+d}"
    wrong = tk_reads(old, virtual_screen(monitors)) != rect
    assert wrong == (rect.x < 0 or rect.y < 0), f"{name}: only a negative coordinate may break the old string"


@pytest.mark.parametrize("name", list(ARRANGEMENTS))
def test_side_windows_and_card_stay_on_the_main_windows_monitor(name):
    monitors = ARRANGEMENTS[name]
    area = pick_monitor(monitors, "last").work
    main = start_rect(area, CFG["width"], CFG["height"], CFG["x"], CFG["y"])
    top, bottom = column_slots(main, area)
    for slot in (top, bottom):
        assert area.x <= slot.x and slot.x + slot.w <= area.x + area.w, name
        assert area.y <= slot.y and slot.y + slot.h <= area.y + area.h, name
        assert slot.x + slot.w <= main.x or slot.x >= main.x + main.w, f"{name}: a side window must not cover the main window"
    assert top.y + top.h + GAP == bottom.y and bottom.y + bottom.h == area.y + area.h  # halves fill the monitor
    x, y, side = place_card(main, 340, 200, area)
    assert area.x <= x and x + 340 <= area.x + area.w or side == "inside"
    assert area.y <= y <= area.y + area.h


def test_a_small_screen_shrinks_the_window_instead_of_pushing_it_off():
    monitors = ARRANGEMENTS["one 1366x768"]  # the work area is only 720 px high, the window wants 860
    area = monitors[0].work
    r = start_rect(area, CFG["width"], CFG["height"], CFG["x"], CFG["y"])
    assert r.h == area.h and r.y == area.y and r.x + r.w == area.x + area.w - 20


def test_geometry_string_is_always_plus_signed():
    assert geometry_string(Rect(-1920, -400, 560, 860)) == "560x860+-1920+-400"
    assert geometry_string(Rect(1360, 60, 560, 860)) == "560x860+1360+60"


def test_a_window_that_is_where_it_was_asked_to_be_is_not_reported_but_a_far_one_is():
    from lowass.layout import moved

    wanted = Rect(1360, 60, 560, 860)
    assert not moved(wanted, Rect(1362, 63, 560, 860))  # a few pixels of border and shadow
    assert moved(wanted, Rect(1360, 700, 560, 860))  # "oddly at the bottom"
    assert moved(wanted, Rect(-2500, 60, 560, 860))  # on the wrong monitor


def test_height_full_fills_the_work_area_from_the_top_to_the_taskbar_on_every_arrangement():
    from lowass.layout import frame_height, full_client_height

    for name, monitors in ARRANGEMENTS.items():
        area = pick_monitor(monitors, "last").work
        r = start_rect(area, 560, "full", -20, 60)
        assert r.y == area.y and r.h == area.h and r.x + r.w == area.x + area.w - 20, name  # y is ignored, 20 px from the right
        frame = frame_height(31, 8)  # a typical 100 % Windows title bar and border
        client = full_client_height(area, frame)
        assert client + frame == area.h, name  # the OUTER window ends exactly at the taskbar, not below it


def test_a_guessed_frame_keeps_the_first_frame_inside_the_area_and_a_failed_measurement_is_harmless():
    from lowass.layout import frame_height, full_client_height

    area = Rect(0, 0, 1920, 1152)
    assert start_rect(area, 560, "full", -20, 60, chrome=40).h == 1112
    assert frame_height(-5, -3) == 0 and frame_height(31, 8) == 39
    assert full_client_height(Rect(0, 0, 800, 150), 39) == 200  # a tiny area never gives a negative or useless height
    assert start_rect(area, 560, "FULL", -20, 60).h == 1152  # case does not matter
    assert start_rect(area, 560, 860, -20, 60).h == 860 and start_rect(area, 560, "860", -20, 60).h == 860  # numbers as before
