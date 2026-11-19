# lowass/sso_device.py
"""The device-code flow itself: register a client, ask for a code, poll until the user approves it in the browser.

The password and MFA are typed in the browser, never in this app. The token is stored in the CLI's cache (see sso.py).
Reference for the flow: machr (web/aws_sso.py).
"""
from __future__ import annotations

import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import boto3
from botocore import UNSIGNED
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from .sso import SsoError, SsoSession, iso, save_token

DEVICE_GRANT = "urn:ietf:params:oauth:grant-type:device_code"
SCOPES = ["sso:account:access"]
CLIENT_NAME = "lowass"
SLOW_DOWN_STEP = 5


def _oidc(region: str) -> Any:
    return boto3.client("sso-oidc", region_name=region, config=Config(signature_version=UNSIGNED))


def _code(exc: ClientError) -> str:
    return str(exc.response.get("Error", {}).get("Code", ""))


class DeviceLogin:
    """One sign-in. start() returns what to show the user; wait() blocks until it is approved (run it in a thread)."""

    def __init__(self, session: SsoSession, make_client: Callable[[str], Any] = _oidc, directory: Path | None = None,
                 pause: Callable[[float], bool] | None = None):
        self.session, self.directory = session, directory
        self._pause = pause  # tests pass a fake so nothing really sleeps
        self._client = make_client(session.region)
        self._reg: dict[str, Any] = {}
        self._auth: dict[str, Any] = {}
        self.cancelled = threading.Event()

    def start(self) -> dict[str, str]:
        try:
            self._reg = self._client.register_client(clientName=CLIENT_NAME, clientType="public", scopes=SCOPES)
            self._auth = self._client.start_device_authorization(
                clientId=self._reg["clientId"], clientSecret=self._reg["clientSecret"], startUrl=self.session.start_url)
        except (ClientError, BotoCoreError) as exc:
            raise SsoError(f"AWS sign-in service not reachable: {exc}") from exc
        a = self._auth
        return {"url": a.get("verificationUriComplete") or a["verificationUri"], "user_code": a["userCode"],
                "expires_in": str(a["expiresIn"])}

    def wait(self, sleep: Callable[[float], bool] | None = None) -> None:
        """Polls until approved. `sleep(seconds)` returns True when the sign-in was cancelled (tests pass a fake)."""
        pause = sleep or self._pause or self.cancelled.wait
        interval = float(self._auth.get("interval") or 5)
        deadline = time.time() + float(self._auth["expiresIn"])
        while time.time() < deadline:
            if pause(interval):
                raise SsoError("Sign-in cancelled.")
            try:
                tok = self._client.create_token(grantType=DEVICE_GRANT, deviceCode=self._auth["deviceCode"],
                                                clientId=self._reg["clientId"], clientSecret=self._reg["clientSecret"])
            except ClientError as exc:
                code = _code(exc)
                if code == "AuthorizationPendingException":
                    continue
                if code == "SlowDownException":
                    interval += SLOW_DOWN_STEP
                    continue
                if code == "ExpiredTokenException":
                    raise SsoError("The sign-in was not approved in time.") from exc
                if code == "AccessDeniedException":
                    raise SsoError("The sign-in was denied.") from exc
                raise SsoError(f"Sign-in failed: {code or exc}") from exc
            self._save(tok)
            return
        raise SsoError("The sign-in code expired before it was approved.")

    def _save(self, tok: dict[str, Any]) -> None:
        data = {
            "startUrl": self.session.start_url, "region": self.session.region, "accessToken": tok["accessToken"],
            "expiresAt": iso(time.time() + float(tok["expiresIn"])),
            "clientId": self._reg["clientId"], "clientSecret": self._reg["clientSecret"],
            "registrationExpiresAt": iso(float(self._reg["clientSecretExpiresAt"])),
        }
        if tok.get("refreshToken"):
            data["refreshToken"] = tok["refreshToken"]
        save_token(self.session, data, self.directory)
