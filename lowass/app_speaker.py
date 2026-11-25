# lowass/app_speaker.py
"""Optional Teams speaker names ([speaker].enabled): the timeline the Voice reads and the watcher thread that feeds it."""
from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger("lowass.app")


def start_speaker_names(cfg: Any) -> tuple[Any, Any]:
    """(SpeakerTimeline, running SpeakerWatch), or (None, None) when [speaker].enabled is off or anything fails:
    a problem here only costs the names, never the app."""
    sc = cfg.section("speaker")
    if not sc.get("enabled", False):
        return None, None
    try:
        from .speaker_names import SpeakerTimeline
        from .speaker_watch import SpeakerWatch

        timeline = SpeakerTimeline(min_overlap=float(sc.get("min_overlap", 0.4)))
        watch = SpeakerWatch(timeline.feed, float(sc.get("fps", 5)))
        watch.start()
        return timeline, watch
    except Exception:
        log.warning("speaker names are not available, continuing without them", exc_info=True)
        return None, None


def stop_speaker_watch(watch: Any) -> None:
    if watch is None:
        return
    try:
        watch.stop()
    except Exception:
        log.warning("speaker watch did not stop cleanly", exc_info=True)
