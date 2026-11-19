# lowass/verdict.py
"""Colour of an answer line from its leading verdict tag (FALSE, CONFIRMED, ...). Pure, no tkinter."""
from __future__ import annotations

import re
from collections.abc import Sequence

BULLET = re.compile(r"^\s*(?:[-*\u2022]|\d+[.)])\s")


def compile_verdicts(
    red: Sequence[str], blue: Sequence[str], green: Sequence[str] = (), info: Sequence[str] = (),
    opinion: Sequence[str] = (),
) -> tuple[re.Pattern[str] | None, dict[str, str]]:
    """tag -> colour name. Later groups win, so an older config that still lists CONFIRMED under `blue` is overridden
    by `green`. Blue is also the colour of translations, so the defaults use green (confirmed), violet (info) and
    yellow (the assistant's own opinion, not a verified fact)."""
    colors: dict[str, str] = {}
    for name, tags in (("red", red), ("blue", blue), ("green", green), ("info", info), ("opinion", opinion)):
        colors.update(dict.fromkeys(tags, name))
    if not colors:
        return None, colors
    pat = re.compile(r"^[\s\-*\u2022>#_]*(?:\d+[.)]\s*)?[\s\-*\u2022>#_]*(" + "|".join(re.escape(t) for t in colors) + r")\b")
    return pat, colors


def color_lines(text: str, pat: re.Pattern[str] | None, colors: dict[str, str], default: str) -> list[tuple[str, str]]:
    """[(line, tag)]: a line with a known tag gets its colour, wrapped continuation lines inherit it,
    the next bullet or blank line without a tag goes back to `default`."""
    out: list[tuple[str, str]] = []
    current = default
    for line in text.split("\n"):
        m = pat.match(line) if pat else None
        if m:
            current = colors[m.group(1)]
        elif BULLET.match(line) or not line.strip():
            current = default
        out.append((line, current))
    return out
