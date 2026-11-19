# lowass/sso_login.py
"""Device-code sign-in to AWS IAM Identity Center without the AWS CLI (like `aws sso login --use-device-code`).

The user approves in the browser: the password and MFA are typed THERE, never in this app. The token is stored in the
CLI's cache (see sso.py), so boto3 picks it up and refreshes it. The flow itself lives in sso_device.py; this module
runs one sign-in at a time for the app (LoginManager).
"""
from __future__ import annotations

import logging
import threading
import time
import webbrowser
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .sso import (
    SsoError,
    epoch,
    load_token,
    sso_session_of,
    token_valid,
    usable,
)
from .sso_device import DeviceLogin, _oidc

__all__ = ["FRESH_SECONDS", "DeviceLogin", "LoginManager"]

FRESH_SECONDS = 300.0

log = logging.getLogger("lowass.sso")


def _fresh(tok: dict[str, Any]) -> bool:
    """The access token itself still has more than FRESH_SECONDS to live (no refresh needed)."""
    try:
        return epoch(tok["expiresAt"]) - time.time() > FRESH_SECONDS
    except (KeyError, ValueError, OverflowError):
        return False


class LoginManager:
    """The app's entry point: one sign-in at a time; progress goes to the window through `notify(kind, text)`."""

    def __init__(self, profile: str, notify: Callable[[str, str], None],
                 open_browser: Callable[[str], bool] = webbrowser.open, directory: Path | None = None,
                 make_client: Callable[[str], Any] = _oidc, pause: Callable[[float], bool] | None = None):
        self.profile, self.notify, self.open_browser = profile, notify, open_browser
        self.directory, self.make_client, self.pause = directory, make_client, pause
        self._lock = threading.Lock()
        self.current: DeviceLogin | None = None

    def ok(self) -> bool:
        """Fresh token on disk is trusted without a network call; an expired one is proven by asking boto3, because
        its refresh token may be revoked even though the dates look fine (seen on a real expired login)."""
        try:
            session = sso_session_of(self.profile)
        except SsoError:
            return False
        if self.directory is not None:  # tests use a private cache folder and have no real AWS to ask
            return token_valid(session, directory=self.directory)
        tok = load_token(session)
        if tok and _fresh(tok):
            return True
        return usable(self.profile)

    def begin(self, on_done: Callable[[], None] | None = None, force: bool = False) -> bool:
        """Starts a sign-in in a thread unless one is running or the token is fine. True = a sign-in started."""
        if not self._lock.acquire(blocking=False):
            return False
        if not force and self.ok():
            self._lock.release()
            return False
        threading.Thread(target=self._run, args=(on_done,), daemon=True, name="aws-login").start()
        return True

    def _run(self, on_done: Callable[[], None] | None) -> None:
        try:
            self.current = login = DeviceLogin(sso_session_of(self.profile), self.make_client, self.directory, self.pause)
            shown = login.start()
            try:
                opened = self.open_browser(shown["url"])
            except Exception:
                log.debug("cannot open the browser", exc_info=True)
                opened = False
            self.notify("bot", f"AWS sign-in: approve in the browser (code {shown['user_code']}). "
                               + ("The page was opened for you." if opened else f"Open this address: {shown['url']}"))
            self.notify("status", "waiting for the AWS sign-in in the browser...")
            login.wait()
            self.notify("bot", "AWS sign-in done.")
            if on_done:
                on_done()
        except SsoError as exc:
            self.notify("err", str(exc))
        except Exception as exc:
            log.exception("AWS sign-in failed")
            self.notify("err", f"AWS sign-in failed: {type(exc).__name__}: {exc}")
        finally:
            self.current = None
            self._lock.release()

    def cancel(self) -> None:
        if self.current:
            self.current.cancelled.set()

    def wait_idle(self, poll: float = 0.2) -> None:
        """Blocks until no sign-in is running (used by the command line)."""
        while self._lock.locked():
            time.sleep(poll)
