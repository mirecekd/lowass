# tests/test_core.py
import re
import time

import numpy as np
import pytest

from lowass import config, hotkeys
from lowass.audio import Segmenter
from lowass.dsp import prepare_audio_chunk, to_wav_bytes
from lowass.guard import blocked, check_call
from lowass.stt import clean
from lowass.transcript import Transcript

CFG = config.load(config.ROOT, "lowass.toml.sample")  # the sample is the tested config, not a local lowass.toml
DENY = CFG.deny_regex()


@pytest.mark.parametrize("name", [
    "corp-jira-jira_search", "wiki-confluence_get_page", "tavily-tavily_search",
    "github-personal-get_file_contents", "context7-query-docs", "aws-knowledge-aws___search_documentation",
    "corp-gitlab-list_merge_requests", "customer-jira-jira_get_issue", "notion-notion-fetch"])
def test_read_tools_allowed(name):
    assert not blocked(name, DENY)


@pytest.mark.parametrize("name", [
    "corp-jira-jira_create_issue", "wiki-confluence_update_page", "customer-jira-jira_add_comment",
    "corp-jira-jira_transition_issue", "github-personal-delete_file", "github-personal-push_files",
    "corp-gitlab-create_merge_request", "customer-jira-jira_batch_create_issues", "notion-notion-create-pages"])
def test_write_tools_blocked(name):
    assert blocked(name, DENY)


def test_check_call_blocks_write_and_passes_read():
    assert (check_call({"toolName": "customer-jira-jira_add_comment", "arguments": {}}, DENY) or "").startswith("BLOCKED")
    assert check_call({"toolName": "tavily-tavily_search", "arguments": {"query": "x"}}, DENY) is None
    assert check_call({"toolName": "corp-gitlab-list_merge_requests"}, DENY) is None
    assert (check_call({}, DENY) or "").startswith("ERROR")


def test_transcript_new_words_and_take():
    t = Transcript(window_minutes=5)
    t.add("Ja", "jedna dva tri")
    t.add("Protistrana", "styri pet")
    assert t.new_words() == 5
    new, window = t.take_new()
    assert "Ja: jedna" in new and window.count("\n") == 1
    assert t.new_words() == 0
    t.add("Ja", "sest")
    assert t.take_new()[0].endswith("Ja: sest")


def test_transcript_window_trims_and_mark_survives():
    t = Transcript(window_minutes=1)
    t.add("Ja", "stare vety", ts=time.time() - 3600)
    t.add("Ja", "nova veta")
    assert "stare" not in t.window_text()
    assert t.new_words() == 2


def _chunk(amp, n=800):
    return (np.ones(n, dtype=np.float32) * amp), amp


def test_segmenter_emits_on_silence_and_drops_blips():
    seg = Segmenter(threshold=0.01, silence_sec=0.2, max_sec=15, min_speech=0.35)
    out = [seg.feed(*_chunk(0.1), 0.05) for _ in range(10)]
    assert all(o is None for o in out)
    wav = None
    for _ in range(6):
        wav = seg.feed(*_chunk(0.0), 0.05) or wav
    assert wav and wav[:4] == b"RIFF"
    seg2 = Segmenter(0.01, 0.2, 15, 0.35)
    seg2.feed(*_chunk(0.1), 0.05)
    res = [seg2.feed(*_chunk(0.0), 0.05) for _ in range(6)]
    assert all(r is None for r in res) and not seg2.speaking


def test_segmenter_max_length_cut():
    seg = Segmenter(0.01, 0.65, 1.0, 0.35)
    outs = [seg.feed(*_chunk(0.1), 0.05) for _ in range(25)]
    assert any(o for o in outs)


def test_prepare_audio_resamples_and_picks_loud_channel():
    stereo = np.zeros((4800, 2), dtype=np.int16)
    stereo[:, 1] = 8000
    audio, rms = prepare_audio_chunk(stereo.tobytes(), 2, 48000)
    assert len(audio) == 1600 and rms > 0.2
    assert to_wav_bytes(audio)[:4] == b"RIFF"


def test_stt_clean_filters_hallucinations():
    assert clean(" Konec. ", {"konec."}) == ""
    assert clean("Ahoj", {"konec."}) == "Ahoj"


def test_hotkey_parse():
    mods, vk = hotkeys.parse("ctrl+alt+space")
    assert mods & 0x2 and mods & 0x1 and vk == 0x20
    assert hotkeys.parse("ctrl+shift+L")[1] == ord("L")
    assert hotkeys.parse("alt+f9")[1] == 0x78
    with pytest.raises(ValueError):
        hotkeys.parse("hyper+x")


def test_config_prompts_and_env_check(monkeypatch):
    assert "NOTHING" in CFG.section("prompts")["auto"]
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    assert "GROQ_API_KEY" in CFG.missing_env(("GROQ_API_KEY",))
    assert isinstance(DENY, re.Pattern)


def test_models_default_and_saved_choice(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ROOT", tmp_path)
    avail, chosen = CFG.models()
    assert chosen == "global.anthropic.claude-haiku-5-5" and chosen in avail
    assert any(not m.startswith("eu.") for m in avail)
    CFG.save_model("global.anthropic.claude-sonnet-5-5")
    assert CFG.models()[1] == "global.anthropic.claude-sonnet-5-5"
    CFG.save_model("not-listed")
    assert CFG.models()[1] == "global.anthropic.claude-haiku-5-5"


def test_language_rule_in_prompt_and_auto_stt_language():
    s = CFG.section("prompts")["system"]
    assert "English" in s and "Czech" in s and "translate" in s
    assert CFG.section("groq")["language"] == ""


def test_transcript_clear_resets_window_and_mark():
    t = Transcript(window_minutes=5)
    t.add("Ja", "jedna dva tri")
    t.take_new()
    t.clear()
    assert t.window_text() == "" and t.new_words() == 0
    t.add("Ja", "ctyri pet")
    assert t.new_words() == 2 and "ctyri" in t.take_new()[0]
