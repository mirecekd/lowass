# tests/test_projects.py
import tomllib

import pytest

from lowass import config
from lowass.config import Config, ConfigError
from lowass.verdict import color_lines, compile_verdicts

CFG = config.load(config.ROOT, "lowass.toml.sample")  # the sample is the tested config, not a local lowass.toml


def test_projects_have_url_and_prompt():
    projs = CFG.projects()
    assert set(projs) == {"general", "customer_a", "customer_b"}
    for key, p in projs.items():
        assert p["name"] and p["mcphub_url"].startswith("https://") and len(p["prompt"]) > 100, key
    names, selected = CFG.project()
    assert names == {"general": "General", "customer_a": "Customer A", "customer_b": "Customer B"} and selected == "general"


def test_project_choice_is_saved_and_ignored_when_unknown(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ROOT", tmp_path)
    CFG.save_state(project="customer_b")
    assert CFG.project()[1] == "customer_b"
    CFG.save_state(model="global.anthropic.claude-haiku-5-5")  # saving the model must keep the project
    assert CFG.project()[1] == "customer_b" and CFG.models()[1] == "global.anthropic.claude-haiku-5-5"
    CFG.save_state(project="gone")
    assert CFG.project()[1] == "general"
    (tmp_path / config.STATE_FILE).write_text("{broken", encoding="utf-8")
    assert CFG.project()[1] == "general" and CFG.models()[1] == CFG.section("models")["default"]


def test_system_prompt_is_common_part_plus_project_part():
    base = CFG.section("prompts")["system"]
    for key, p in CFG.projects().items():
        sp = CFG.system_prompt(key)
        assert sp.startswith(base) and f"PROJECT: {p['name']}" in sp and p["prompt"].strip()[:40] in sp
    assert "NEVER invent expansions" in CFG.system_prompt("customer_a")
    assert "UNVERIFIED" in CFG.system_prompt("general")
    assert CFG.system_prompt("general") == CFG.system_prompt("general")  # no clock in it: stable for prompt caching


def test_no_projects_is_a_clear_error():
    with pytest.raises(ConfigError):
        Config({"projects": {"default": "x"}}).project()


def test_every_project_url_and_mcphub_token_env_present_in_example():
    assert "MCPHUB_URL" not in config.REQUIRED_ENV  # url lives in lowass.toml now
    assert "MCPHUB_TOKEN" in config.REQUIRED_ENV
    default = tomllib.loads((config.ROOT / "lowass.toml.sample").read_text(encoding="utf-8"))["projects"]["default"]
    assert default in CFG.projects()


RED = ["FALSE", "NEPRAVDA"]
BLUE = ["CONFIRMED", "POTVRZENO", "INFO"]


def tags(text):
    pat, colors = compile_verdicts(RED, BLUE)
    return [t for _l, t in color_lines(text, pat, colors, "bot")]


def test_verdict_colours():
    assert tags("- **FALSE:** wrong") == ["red"]
    assert tags("- NEPRAVDA: spatne") == ["red"]
    assert tags("* **INFO:** looked up") == ["blue"]
    assert tags("1. POTVRZENO: ok") == ["blue"]
    assert tags("- **UNVERIFIED:** could not check") == ["bot"]
    assert tags("plain answer") == ["bot"]
    assert tags("- FALSEHOOD of sorts") == ["bot"]  # word boundary: only the whole tag counts


def test_verdict_continuation_lines_inherit_until_next_bullet():
    text = "- **FALSE:** claim is wrong\n  because X\n- **INFO:** fact\n\ntail"
    assert tags(text) == ["red", "red", "blue", "bot", "bot"]


def test_verdict_without_config_leaves_default():
    pat, colors = compile_verdicts([], [])
    assert [t for _l, t in color_lines("- FALSE: x", pat, colors, "bot")] == ["bot"]


def test_old_lowass_toml_gets_missing_sections_from_the_sample(tmp_path):
    """An older local lowass.toml has no [hint]/[facts] and no hint/facts prompts: it must not crash the start."""
    sample = (config.ROOT / "lowass.toml.sample").read_text(encoding="utf-8")
    (tmp_path / "lowass.toml.sample").write_text(sample, encoding="utf-8")
    (tmp_path / "lowass.toml").write_text('[audio]\nmy_label = "Me"\n[prompts]\nsystem = "own"\n'
                                          '[projects]\ndefault = "mine"\n[projects.mine]\nname = "Mine"\n', encoding="utf-8")
    cfg = config.load(tmp_path)
    assert cfg.section("audio")["my_label"] == "Me" and cfg.section("audio")["mic_threshold"] > 0  # own value wins, rest filled
    assert cfg.section("prompts")["system"] == "own" and cfg.section("prompts")["hint"] and cfg.section("facts")["enabled"]
    assert list(cfg.projects()) == ["mine"]  # the user's project list is never mixed with the sample's


def test_first_start_creates_lowass_toml_from_the_sample(tmp_path):
    (tmp_path / "lowass.toml.sample").write_text((config.ROOT / "lowass.toml.sample").read_text(encoding="utf-8"), encoding="utf-8")
    config.load(tmp_path)
    assert (tmp_path / "lowass.toml").exists()


def test_version_is_yyyymmdd_dot_counter_and_next_one_counts_todays_tags():
    import re

    from lowass import __version__
    from scripts.release import next_version

    assert re.fullmatch(r"\d{8}\.\d+", __version__)
    assert next_version([], "20261119") == "20261119.1"
    assert next_version(["20261119.1", "20261119.3", "20261118.9", "v1"], "20261119") == "20261119.4"
