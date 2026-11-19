# tests/test_freeze.py
"""Private as a freeze: it stops what is new at once, lets running work finish, then mutes the transcript path."""
import time
from types import SimpleNamespace

from lowass.freeze import PrivateGate, make_gate


def test_gate_is_set_at_once_but_muted_only_after_the_drain_time():
    g = PrivateGate(drain_sec=0.2)
    assert not g.is_set() and not g.muted()
    g.set()
    assert g.is_set() and not g.muted()  # capture stops now, but a sentence still being recognised may finish
    time.sleep(0.25)
    assert g.muted()
    g.clear()
    assert not g.is_set() and not g.muted()


def test_setting_twice_does_not_restart_the_drain_time():
    g = PrivateGate(drain_sec=0.3)
    g.set()
    time.sleep(0.2)
    g.set()  # the hotkey pressed again must not extend the drain
    time.sleep(0.15)
    assert g.muted()


def test_a_second_private_period_gets_its_own_drain_time():
    g = PrivateGate(drain_sec=0.2)
    g.set()
    time.sleep(0.25)
    g.clear()
    g.set()
    assert g.is_set() and not g.muted()


def cfg(provider="transcribe", mode="live", drain=None):
    sections = {"stt": {"provider": provider}, "transcribe": {"mode": mode}, "private": {} if drain is None else {"drain_sec": drain}}
    return SimpleNamespace(section=lambda name: sections.get(name, {}))


def test_make_gate_drains_only_in_live_mode():
    assert make_gate(cfg()).drain_sec == 10.0
    assert make_gate(cfg(drain=4)).drain_sec == 4.0
    assert make_gate(cfg(mode="segment")).drain_sec == 0.0  # no capture gate: muted at once
    assert make_gate(cfg(provider="groq")).drain_sec == 0.0
