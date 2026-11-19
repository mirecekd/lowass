# lowass/screen.py
"""Screenshot of the PRIMARY monitor (Teams window), downscaled PNG bytes. The window hides itself while grabbing."""
from __future__ import annotations

import io

import mss
from PIL import Image


def grab_primary(max_side: int = 1568) -> bytes:
    """Primary monitor only (never the virtual all-monitors desktop). max_side keeps the vision request small
    while text stays readable; 0 = no downscale."""
    with mss.MSS() as sct:
        mon = sct.primary_monitor
        shot = sct.grab(mon)
    img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
    if max_side and max(img.size) > max_side:
        img.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
