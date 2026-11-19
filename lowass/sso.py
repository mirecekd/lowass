# lowass/sso.py
"""AWS IAM Identity Center helpers: which SSO session a profile signs in with, and the token cache shared with the CLI.

The token is read and written through botocore's own SSOTokenLoader + JSONFileCache, so the file name, the format and
the permissions are exactly what the AWS CLI and boto3 expect (no hashing of our own). boto3 also refreshes it.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import boto3
import dateutil.parser
from botocore.exceptions import SSOTokenLoadError
from botocore.utils import JSONFileCache, SSOTokenLoader


class SsoError(RuntimeError):
    """A sign-in problem with a message the user can read."""


@dataclass(frozen=True)
class SsoSession:
    name: str | None  # None = a legacy profile with sso_start_url but without an [sso-session] block
    start_url: str
    region: str


def cache_dir() -> Path:
    return Path(os.path.expanduser("~/.aws/sso/cache"))


def _loader(directory: Path | None = None) -> SSOTokenLoader:
    return SSOTokenLoader(cache=JSONFileCache(str(directory or cache_dir())))


def iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def epoch(text: str) -> float:
    dt = dateutil.parser.parse(text)
    return (dt if dt.tzinfo else dt.replace(tzinfo=UTC)).timestamp()


def sso_session_of(profile: str) -> SsoSession:
    """The SSO session a profile signs in with. A chained profile (source_profile) uses its source's session."""
    try:
        full = boto3.Session(profile_name=profile)._session.full_config  # botocore's parsed ~/.aws/config
    except Exception as exc:
        raise SsoError(f"Cannot read the AWS config for profile '{profile}': {exc}") from exc
    profiles, sessions = full.get("profiles", {}), full.get("sso_sessions", {})
    name, seen = profile, set()
    while name and name not in seen:
        seen.add(name)
        p = profiles.get(name)
        if p is None:
            break
        if "sso_session" in p:
            s = sessions.get(p["sso_session"])
            if not s or "sso_start_url" not in s or "sso_region" not in s:
                raise SsoError(f"sso-session '{p['sso_session']}' in ~/.aws/config lacks sso_start_url or sso_region.")
            return SsoSession(p["sso_session"], s["sso_start_url"], s["sso_region"])
        if "sso_start_url" in p and "sso_region" in p:
            return SsoSession(None, p["sso_start_url"], p["sso_region"])
        name = p.get("source_profile", "")
    raise SsoError(f"Profile '{profile}' has no SSO login (no sso_session / source_profile chain) in ~/.aws/config.")


def save_token(session: SsoSession, token: dict[str, Any], directory: Path | None = None) -> None:
    _loader(directory).save_token(session.start_url, token, session.name)


def load_token(session: SsoSession, directory: Path | None = None) -> dict[str, Any] | None:
    try:
        return _loader(directory)(session.start_url, session.name)
    except (SSOTokenLoadError, KeyError):
        return None


def token_valid(session: SsoSession, skew: float = 300.0, directory: Path | None = None) -> bool:
    """True when the access token lives at least `skew` more seconds. An expired one counts as valid ONLY when
    a refresh token and a live client registration exist (boto3 then renews it); `refresh_ok(session)` can confirm
    that against AWS, because a refresh token can be dead even when its dates look fine."""
    tok = load_token(session, directory)
    if not tok:
        return False
    try:
        if epoch(tok["expiresAt"]) - time.time() > skew:
            return True
        return bool(tok.get("refreshToken")) and epoch(tok["registrationExpiresAt"]) > time.time()
    except (KeyError, ValueError, OverflowError):
        return False


def usable(profile: str) -> bool:
    """The real test: can boto3 get credentials for the profile right now (this renews an expired token)?
    Used instead of reading dates, because a refresh token the server has revoked still looks valid in the file."""
    try:
        creds = boto3.Session(profile_name=profile).get_credentials()
        return creds is not None and bool(creds.get_frozen_credentials().access_key)
    except Exception:  # noqa: BLE001 - any failure to get credentials means: sign in again
        return False
