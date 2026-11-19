# tests/test_tooltip.py
"""Tooltip placement (pure) and where the shortcut tooltips get their text."""
from lowass.config import Config
from lowass.tooltip import tip_position


def test_tooltip_goes_above_the_button_and_below_when_there_is_no_room():
    assert tip_position(100, 700, 60, 24, 300, 80, 1920, 1080) == (100, 700 - 80 - 6)
    x, y = tip_position(100, 30, 60, 24, 300, 80, 1920, 1080)  # no room above
    assert y == 30 + 24 + 6 and x == 100


def test_tooltip_stays_on_the_screen_at_the_right_and_bottom_edge():
    x, y = tip_position(1900, 1070, 60, 24, 300, 80, 1920, 1080)
    assert x == 1920 - 300 and 0 <= y <= 1080 - 80


def test_shortcut_tip_is_the_hint_else_the_prompt_else_the_check_prompt():
    cfg = Config({"prompts": {"check": "CHECK PROMPT"}, "ui": {"shortcuts": [
        {"label": "A", "prompt": "full prompt of A"},
        {"label": "B", "prompt": "full prompt of B", "hint": "short hint of B"},
        {"label": "Fact-check", "action": "check"},
    ]}})
    assert [s["tip"] for s in cfg.shortcuts()] == ["full prompt of A", "short hint of B", "CHECK PROMPT"]
