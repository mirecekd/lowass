# lowass/cli.py
"""Command line entry: argument parsing, config + environment checks, then App.run()."""
from __future__ import annotations

import argparse
import logging
import sys

from . import deps
from .app import App
from .config import ROOT, ConfigError, load
from .debug import setup_logging
from .sso_login import LoginManager

log = logging.getLogger("lowass.cli")


def login_only(profile: str) -> int:
    """`run.bat --login`: sign in to AWS without starting the window. Exit code 0 = a valid login exists afterwards."""

    def notify(kind: str, text: str) -> None:
        if kind != "status":
            print(text, file=sys.stderr if kind == "err" else sys.stdout, flush=True)

    mgr = LoginManager(profile, notify)
    if mgr.begin(force=True):
        mgr.wait_idle()
    return 0 if mgr.ok() else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="lowass", description="LOcal Windows ASSistant")
    ap.add_argument("--no-audio", action="store_true", help="UI + chat + tools only (no capture, no STT)")
    ap.add_argument("--debug", action="store_true", help="force debug mode (same as [debug] enabled = true)")
    ap.add_argument("--login", action="store_true", help="only sign in to AWS (device code in the browser), then exit")
    args = ap.parse_args(argv)
    try:
        cfg = load()
    except ConfigError as exc:
        print(exc, file=sys.stderr)
        return 2
    if args.login:
        return login_only(cfg.section("transcribe")["profile"])
    if args.debug:
        cfg.section("debug")["enabled"] = True
    log_path = setup_logging(ROOT, cfg.section("debug"))
    log.warning("LOWASS starting (debug=%s, log=%s)", bool(cfg.section("debug").get("enabled")), log_path)
    need = ["LITELLM_BASE_URL", "LITELLM_API_KEY", "MCPHUB_TOKEN"]  # mcphub URLs live in lowass.toml [projects]
    if not args.no_audio and cfg.section("stt").get("provider") == "groq":
        need.append("GROQ_API_KEY")
    missing = cfg.missing_env(tuple(need))
    if missing:
        env_file = ROOT / ".env"
        hint = "" if env_file.exists() else f"\nThe file {env_file} does not exist: copy .env.example to .env and fill it in."
        print("Missing in .env: " + ", ".join(missing) + hint, file=sys.stderr)
        return 2
    packages = deps.missing(str(cfg.section("stt").get("provider", "transcribe")), audio=not args.no_audio and sys.platform == "win32")
    if packages:
        print(deps.install_hint(packages), file=sys.stderr)
        return 2
    App(cfg, audio=not args.no_audio).run()
    return 0
