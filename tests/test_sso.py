# tests/test_sso.py
"""Device-code sign-in with a fake sso-oidc client; the written token is read back by the REAL botocore loader."""
import threading
import time

import pytest
from botocore.exceptions import ClientError

from lowass.sso import (
    SsoError,
    SsoSession,
    load_token,
    save_token,
    sso_session_of,
    token_valid,
)
from lowass.sso_login import DeviceLogin, LoginManager

SESSION = SsoSession("corp", "https://corp.awsapps.com/start", "eu-central-1")


def client_error(code):
    return ClientError({"Error": {"Code": code, "Message": code}}, "CreateToken")


class FakeOidc:
    """Pending N times (optionally slow-down first), then approves."""

    def __init__(self, pending=2, errors=None):
        self.script = list(errors or []) + [client_error("AuthorizationPendingException")] * pending
        self.calls = []

    def register_client(self, **kw):
        self.calls.append(("register", kw))
        return {"clientId": "cid", "clientSecret": "csecret", "clientSecretExpiresAt": time.time() + 90 * 86400}

    def start_device_authorization(self, **kw):
        self.calls.append(("start", kw))
        return {"deviceCode": "dev", "userCode": "ABCD-EFGH", "verificationUri": "https://v/u",
                "verificationUriComplete": "https://v/u?c=ABCD-EFGH", "expiresIn": 600, "interval": 1}

    def create_token(self, **kw):
        self.calls.append(("token", kw))
        if self.script:
            raise self.script.pop(0)
        return {"accessToken": "AT", "refreshToken": "RT", "expiresIn": 3600}


@pytest.fixture
def aws_config(tmp_path, monkeypatch):
    cfg = tmp_path / "config"
    cfg.write_text(
        "[sso-session corp]\nsso_start_url = https://corp.awsapps.com/start\nsso_region = eu-central-1\n"
        "[profile corp]\nsso_session = corp\nsso_account_id = 111111111111\nsso_role_name = Team\n"
        "[profile ai]\nsource_profile = corp\nrole_arn = arn:aws:iam::222222222222:role/Role\n"
        "[profile ai2]\nsource_profile = ai\nrole_arn = arn:aws:iam::333333333333:role/Role\n"
        "[profile legacy]\nsso_start_url = https://old.awsapps.com/start\nsso_region = eu-west-1\n"
        "sso_account_id = 1\nsso_role_name = R\n"
        "[profile loop-a]\nsource_profile = loop-b\n[profile loop-b]\nsource_profile = loop-a\n"
        "[profile plain]\nregion = eu-central-1\n", encoding="utf-8")
    monkeypatch.setenv("AWS_CONFIG_FILE", str(cfg))
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", str(tmp_path / "none"))
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    return cfg


def test_session_of_follows_source_profile_chains(aws_config):
    assert sso_session_of("corp") == SESSION
    assert sso_session_of("ai") == SESSION and sso_session_of("ai2") == SESSION
    assert sso_session_of("legacy") == SsoSession(None, "https://old.awsapps.com/start", "eu-west-1")


@pytest.mark.parametrize("profile", ["plain", "loop-a", "nope"])
def test_profiles_without_sso_give_a_readable_error(aws_config, profile):
    with pytest.raises(SsoError):
        sso_session_of(profile)


def run_login(tmp_path, oidc):
    login = DeviceLogin(SESSION, lambda _region: oidc, tmp_path)
    shown = login.start()
    login.wait(sleep=lambda _s: False)  # no real sleeping
    return login, shown


def test_device_flow_writes_a_token_that_botocore_reads_back(tmp_path):
    oidc = FakeOidc(pending=2)
    _login, shown = run_login(tmp_path, oidc)
    assert shown["url"] == "https://v/u?c=ABCD-EFGH" and shown["user_code"] == "ABCD-EFGH"
    kinds = [c[0] for c in oidc.calls]
    assert kinds[:2] == ["register", "start"] and kinds.count("token") == 3
    assert oidc.calls[0][1] == {"clientName": "lowass", "clientType": "public", "scopes": ["sso:account:access"]}
    assert oidc.calls[-1][1]["grantType"] == "urn:ietf:params:oauth:grant-type:device_code"
    tok = load_token(SESSION, tmp_path)  # the real botocore SSOTokenLoader + JSONFileCache
    assert tok and tok["accessToken"] == "AT" and tok["refreshToken"] == "RT"
    assert tok["startUrl"] == SESSION.start_url and tok["region"] == "eu-central-1"
    assert {"clientId", "clientSecret", "registrationExpiresAt", "expiresAt"} <= set(tok)
    assert token_valid(SESSION, directory=tmp_path)
    assert len(list(tmp_path.glob("*.json"))) == 1 and not list(tmp_path.glob("*.tmp"))


def test_slow_down_makes_the_polling_slower(tmp_path):
    waits = []
    oidc = FakeOidc(pending=0, errors=[client_error("SlowDownException")])
    login = DeviceLogin(SESSION, lambda _r: oidc, tmp_path)
    login.start()
    login.wait(sleep=lambda s: waits.append(s) or False)
    assert waits == [1.0, 6.0]


@pytest.mark.parametrize(("code", "text"), [("ExpiredTokenException", "not approved in time"),
                                              ("AccessDeniedException", "denied"), ("InvalidGrantException", "failed")])
def test_failures_become_readable_errors_and_write_nothing(tmp_path, code, text):
    login = DeviceLogin(SESSION, lambda _r: FakeOidc(pending=0, errors=[client_error(code)]), tmp_path)
    login.start()
    with pytest.raises(SsoError, match=text):
        login.wait(sleep=lambda _s: False)
    assert not list(tmp_path.glob("*.json"))


def test_cancel_stops_the_wait(tmp_path):
    login = DeviceLogin(SESSION, lambda _r: FakeOidc(pending=99), tmp_path)
    login.start()
    login.cancelled.set()
    with pytest.raises(SsoError, match="cancelled"):
        login.wait()


def test_token_valid_rules(tmp_path):
    assert not token_valid(SESSION, directory=tmp_path)  # nothing cached
    far = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 7200))
    past = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 60))
    reg_ok = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 86400))
    base = {"startUrl": SESSION.start_url, "region": "eu-central-1", "accessToken": "A", "clientId": "c", "clientSecret": "s"}
    save_token(SESSION, {**base, "expiresAt": far, "registrationExpiresAt": reg_ok}, tmp_path)
    assert token_valid(SESSION, directory=tmp_path)
    save_token(SESSION, {**base, "expiresAt": past, "registrationExpiresAt": reg_ok}, tmp_path)
    assert not token_valid(SESSION, directory=tmp_path)  # expired and no refresh token
    save_token(SESSION, {**base, "expiresAt": past, "registrationExpiresAt": reg_ok, "refreshToken": "R"}, tmp_path)
    assert token_valid(SESSION, directory=tmp_path)  # boto3 can refresh it
    save_token(SESSION, {**base, "expiresAt": past, "refreshToken": "R",
                         "registrationExpiresAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 5))}, tmp_path)
    assert not token_valid(SESSION, directory=tmp_path)  # the client registration is gone too


def test_corrupt_cache_file_means_not_logged_in(tmp_path):
    p = tmp_path / "x.json"
    save_token(SESSION, {"accessToken": "A", "expiresAt": "2099-01-01T00:00:00Z"}, tmp_path)
    for f in tmp_path.glob("*.json"):
        f.write_text("{broken", encoding="utf-8")
        p = f
    assert p.exists() and not token_valid(SESSION, directory=tmp_path)


def make_manager(tmp_path, aws_config, oidc, opened, pause=None):
    posts = []
    mgr = LoginManager("ai", lambda k, t: posts.append((k, t)), lambda u: opened.append(u) or True, tmp_path,
                       lambda _r: oidc, pause)
    return mgr, posts


def test_manager_opens_the_browser_shows_the_code_and_runs_a_callback(tmp_path, aws_config):
    opened, done = [], threading.Event()
    mgr, posts = make_manager(tmp_path, aws_config, FakeOidc(pending=1), opened, pause=lambda _s: False)
    assert not mgr.ok()
    assert mgr.begin(on_done=done.set)
    assert done.wait(10), "the on_done callback did not run"
    mgr.wait_idle(0.01)
    assert opened == ["https://v/u?c=ABCD-EFGH"]
    texts = " ".join(t for k, t in posts if k == "bot")
    assert "ABCD-EFGH" in texts and "AWS sign-in done" in texts
    assert mgr.ok()
    assert not mgr.begin()  # a valid token: nothing to do


def test_manager_runs_one_sign_in_at_a_time(tmp_path, aws_config):
    gate = threading.Event()

    class Slow(FakeOidc):
        def start_device_authorization(self, **kw):
            gate.wait(5)
            return super().start_device_authorization(**kw)

    mgr, _posts = make_manager(tmp_path, aws_config, Slow(pending=0), [])
    assert mgr.begin()
    assert not mgr.begin() and not mgr.begin(force=True)  # the second and third call do nothing
    gate.set()
    mgr.cancel()
    mgr.wait_idle(0.01)
    assert mgr.current is None  # finished and released: a new sign-in may start again


def test_manager_reports_a_profile_without_sso(tmp_path, aws_config):
    posts = []
    mgr = LoginManager("plain", lambda k, t: posts.append((k, t)), lambda _u: True, tmp_path, lambda _r: FakeOidc())
    assert mgr.begin(force=True)
    mgr.wait_idle(0.01)
    assert any(k == "err" and "no SSO login" in t for k, t in posts)
