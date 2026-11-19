# lowass/config.py
"""Load lowass.toml (behaviour) and .env (secrets, endpoints)."""
from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import tomllib
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
REQUIRED_ENV = ("LITELLM_BASE_URL", "LITELLM_API_KEY", "MCPHUB_TOKEN")  # GROQ_API_KEY only for stt.provider = groq
STATE_FILE = ".lowass-state.json"


class Config:
    """Thin wrapper: cfg.section("agent")["quiet_sec"], cfg.env("GROQ_API_KEY")."""

    def __init__(self, data: dict[str, Any]):
        self.data = data

    def section(self, name: str) -> dict[str, Any]:
        return self.data.get(name, {})

    @staticmethod
    def env(name: str) -> str:
        return os.environ.get(name, "").strip()

    def deny_regex(self) -> re.Pattern[str]:
        return re.compile(self.section("guard").get("write_deny_regex", r"(?!)"))

    @staticmethod
    def _state() -> dict[str, Any]:
        """Remembered UI choices (model, project) from .lowass-state.json; {} when missing or broken."""
        try:
            data = json.loads((ROOT / STATE_FILE).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    @staticmethod
    def save_state(**choices: str) -> None:
        with contextlib.suppress(OSError):
            (ROOT / STATE_FILE).write_text(json.dumps({**Config._state(), **choices}), encoding="utf-8")

    def models(self) -> tuple[list[str], str]:
        """(available model ids, selected id). Selection = saved choice if still listed, else models.default."""
        m = self.section("models")
        available = list(m.get("available", [])) or [m["default"]]
        saved = self._state().get("model")
        return available, saved if isinstance(saved, str) and saved in available else str(m["default"])

    def save_model(self, model: str) -> None:
        self.save_state(model=model)

    def projects(self) -> dict[str, dict[str, Any]]:
        """[projects.<key>] tables: name, mcphub_url, prompt."""
        return {k: v for k, v in self.section("projects").items() if isinstance(v, dict)}

    def project(self) -> tuple[dict[str, str], str]:
        """({key: display name}, selected key). Selection = saved choice, else projects.default, else the first."""
        projs = self.projects()
        if not projs:
            raise ConfigError("lowass.toml has no [projects.<key>] section")
        chosen = self.section("projects").get("default")
        if chosen not in projs:
            chosen = next(iter(projs))
        saved = self._state().get("project")
        return {k: v.get("name", k) for k, v in projs.items()}, saved if isinstance(saved, str) and saved in projs else str(chosen)

    def system_prompt(self, project_key: str) -> str:
        """Common system prompt + the project's own part. Built once per session (keeps the prompt cache stable)."""
        proj = self.projects()[project_key]
        base = self.section("prompts")["system"]
        extra = str(proj.get("prompt", "")).strip()
        return f"{base}\nPROJECT: {proj.get('name', project_key)}\n{extra}\n" if extra else base

    def shortcuts(self) -> list[dict[str, str]]:
        """[[ui.shortcuts]] buttons as {label, prompt, action}. A button needs a label and either a prompt or
        action = "check"; a broken entry is skipped (it must never stop the app from starting)."""
        out = []
        for s in self.section("ui").get("shortcuts", []):
            label = str(s.get("label", "")).strip()
            action, prompt = str(s.get("action", "")), str(s.get("prompt", "")).strip()
            if label and (prompt or action == "check"):
                out.append({"label": label, "prompt": prompt, "action": action})
        return out

    def missing_env(self, names: tuple[str, ...] = REQUIRED_ENV) -> list[str]:
        return [n for n in names if not self.env(n)]


class ConfigError(RuntimeError):
    """lowass.toml is missing or not valid TOML."""


def _with_defaults(user: dict[str, Any], sample: dict[str, Any]) -> dict[str, Any]:
    """An older lowass.toml lacks sections and keys added later (it crashed the start with a KeyError): whatever the
    user's file does not say comes from the sample. [projects] is the user's own list and is never mixed."""
    merged = dict(sample)
    for key, value in user.items():
        base = sample.get(key)
        merged[key] = {**base, **value} if isinstance(value, dict) and isinstance(base, dict) and key != "projects" else value
    return merged


def load(root: Path | None = None, name: str = "lowass.toml") -> Config:
    """Read lowass.toml. When it is missing, the first start copies lowass.toml.sample (the only config file in git)."""
    root = (root or ROOT).resolve()
    load_dotenv(root / ".env")
    path = root / name
    sample = root / f"{name}.sample"
    if not path.exists() and sample.exists():
        with contextlib.suppress(OSError):  # read-only folder: the sample is read directly below
            shutil.copyfile(sample, path)
    try:
        with (path if path.exists() else sample).open("rb") as fh:
            data = tomllib.load(fh)
        if sample.exists() and path.exists() and path != sample:
            with sample.open("rb") as fh:
                data = _with_defaults(data, tomllib.load(fh))
        return Config(data)
    except FileNotFoundError as exc:
        raise ConfigError(f"Config file not found: {path}") from exc
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError(f"Cannot read {path}: {exc}") from exc
