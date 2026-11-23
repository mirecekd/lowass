# tests/test_am_tunnel.py
"""am_tunnel: the ssh argv and the supervisor loop with fake processes and a fake sleep."""
from __future__ import annotations

import io
import subprocess
import time

import pytest

from lowass import am_tunnel
from lowass.am_tunnel import NO_SSH, TICK, Tunnel, build_command

KEY = "C:\\Users\\me\\.ssh\\id_secret"


class FakeProc:
    """Alive until `exits_at` polls; dies=False ignores terminate()."""

    def __init__(self, stderr: bytes = b"", exits_at: int | None = None, code: int = 255, dies: bool = True) -> None:
        self.stderr = io.BytesIO(stderr)
        self.exits_at, self.code, self.dies = exits_at, code, dies
        self.polls, self.terminated, self.killed, self.dead = 0, False, False, False

    def poll(self) -> int | None:
        self.polls += 1
        return self.code if self.dead or (self.exits_at is not None and self.polls > self.exits_at) else None

    def terminate(self) -> None:
        self.terminated, self.dead = True, self.dies

    def kill(self) -> None:
        self.killed, self.dead = True, True

    def wait(self, timeout: float | None = None) -> int:
        if not self.dead:
            raise subprocess.TimeoutExpired("ssh", timeout or 0)
        return self.code


class Factory:

    def __init__(self, make) -> None:
        self.make, self.calls = make, []

    def __call__(self, cmd, **kwargs):
        self.calls.append((cmd, kwargs))
        made = self.make(len(self.calls))
        if isinstance(made, Exception):
            raise made
        return made


def drive(factory, spawns: int = 1, on_sleep=None, **kwargs):
    """Run a Tunnel with a fake sleep; stop it at the first restart delay after `spawns` starts."""
    delays: list[float] = []

    def fake_sleep(seconds: float) -> None:
        if seconds != TICK:
            delays.append(seconds)
            if on_sleep:
                on_sleep(tunnel)
        if len(factory.calls) >= spawns and seconds != TICK:
            tunnel.stop()

    tunnel = Tunnel("srv", popen=factory, sleep=fake_sleep, **kwargs)
    tunnel.start()
    assert tunnel._thread is not None
    tunnel._thread.join(5)
    return tunnel, delays


def test_command_exact_argv_with_and_without_key_and_user() -> None:
    opts = ["BatchMode=yes", "ExitOnForwardFailure=yes", "ServerAliveInterval=15", "ServerAliveCountMax=3",
            "ConnectTimeout=10", "StrictHostKeyChecking=accept-new"]
    head = ["ssh", "-N", "-T", *[x for o in opts for x in ("-o", o)], "-L", "127.0.0.1:13111:127.0.0.1:3111"]
    assert build_command("srv", 13111, 3111) == [*head, "srv"]
    assert build_command("srv", 13111, 3111, key_file="/k", user="bob") == [*head, "-i", "/k", "-l", "bob", "srv"]
    assert build_command("srv", 13111, 3111, user="bob") == [*head, "-l", "bob", "srv"]


@pytest.mark.parametrize("host,key,user", [("", "", ""), ("  ", "", ""), ("-oX=y", "", ""), ("srv", "-o", ""),
                                           ("srv", "", "-x"), ("sr\nv", "", "")])
def test_command_rejects_bad_text(host: str, key: str, user: str) -> None:
    with pytest.raises(ValueError):
        build_command(host, 13111, 3111, key_file=key, user=user)


@pytest.mark.parametrize("local,remote", [(0, 1), (65536, 1), (1, 0), (-1, 1), (True, 1)])
def test_command_rejects_bad_ports(local: int, remote: int) -> None:
    with pytest.raises(ValueError):
        build_command("srv", local, remote)


def test_tunnel_constructor_validates() -> None:
    with pytest.raises(ValueError):
        Tunnel("-bad")


def test_stop_before_start_is_harmless() -> None:
    tunnel = Tunnel("srv")
    tunnel.stop()
    assert tunnel.state == "stopped" and tunnel.restarts == 0


def test_start_twice_starts_one_daemon_thread() -> None:
    tunnel = Tunnel("srv", popen=Factory(lambda n: FakeProc()))
    tunnel.start()
    first = tunnel._thread
    tunnel.start()
    assert tunnel._thread is first and first is not None and first.daemon
    tunnel.stop()


def started(proc: FakeProc) -> Tunnel:
    tunnel = Tunnel("srv", popen=Factory(lambda n: proc))
    tunnel.start()
    for _ in range(200):
        if tunnel._proc is not None:
            break
        time.sleep(0.01)
    return tunnel


def test_stop_terminates_a_live_process_at_once() -> None:
    proc = FakeProc()
    tunnel = started(proc)
    began = time.time()
    tunnel.stop()
    assert time.time() - began < 0.3
    assert proc.terminated and not proc.killed
    tunnel.stop()


def test_stop_kills_a_process_that_ignores_terminate() -> None:
    proc = FakeProc(dies=False)
    started(proc).stop()
    assert proc.terminated and proc.killed


def test_popen_arguments() -> None:
    factory = Factory(lambda n: FakeProc(exits_at=0))
    drive(factory)
    cmd, kwargs = factory.calls[0]
    assert cmd == build_command("srv", 13111, 3111) and kwargs["stdin"] == subprocess.DEVNULL
    assert kwargs["creationflags"] == getattr(subprocess, "CREATE_NO_WINDOW", 0)


def test_ssh_exiting_at_once_restarts_with_walked_backoff() -> None:
    factory = Factory(lambda n: FakeProc(exits_at=0, stderr=b"Permission denied (publickey).\n"))
    tunnel, delays = drive(factory, spawns=5)
    assert delays == [1, 2, 5, 10, 30]
    assert tunnel.last_error.startswith("Permission")


def test_backoff_stays_at_the_last_value() -> None:
    _, delays = drive(Factory(lambda n: FakeProc(exits_at=0)), spawns=6, backoff=(1, 2))
    assert delays == [1, 2, 2, 2, 2, 2]


def test_successful_check_resets_the_backoff() -> None:
    long_life = am_tunnel.CHECK_TICKS + 2  # only the 3rd process lives long enough for a check
    factory = Factory(lambda n: FakeProc(exits_at=long_life if n == 3 else 0))
    _, delays = drive(factory, spawns=5, check=lambda: True)
    assert delays == [1, 2, 1, 2, 5]


def test_failing_or_raising_check_restarts_the_process() -> None:
    procs: list[FakeProc] = []
    tunnel, delays = drive(Factory(lambda n: procs.append(FakeProc()) or procs[-1]), spawns=2, check=lambda: False)
    assert procs[0].terminated and delays[0] == 1 and tunnel.last_error

    def boom() -> bool:
        raise RuntimeError("token")

    tunnel, _ = drive(Factory(lambda n: FakeProc()), spawns=2, check=boom)
    assert tunnel.restarts >= 1


def test_state_is_up_after_a_good_check() -> None:
    seen: list[str] = []

    def fake_sleep(seconds: float) -> None:
        if len(seen) >= 2:
            tunnel.stop()

    tunnel = Tunnel("srv", popen=Factory(lambda n: FakeProc()), sleep=fake_sleep,
                    check=lambda: seen.append(tunnel.state) or True)
    tunnel.start()
    assert tunnel._thread is not None
    tunnel._thread.join(5)
    assert seen[0] == "starting" and "up" in seen[1:] and tunnel.state == "stopped"


def test_missing_ssh_is_down_with_a_hint_and_waits_the_longest_backoff() -> None:
    states: list[str] = []
    tunnel, delays = drive(Factory(lambda n: FileNotFoundError()), spawns=3, on_sleep=lambda t: states.append(t.state))
    assert delays == [30, 30, 30] and states == ["down"] * 3  # slow retries, no crash
    assert tunnel.last_error == NO_SSH and "OpenSSH Client" in NO_SSH


def test_key_path_never_appears_in_last_error() -> None:
    err = f'Warning: Identity file {KEY} not accessible\nload key "{KEY}": bad permissions\n'.encode()
    tunnel, _ = drive(Factory(lambda n: FakeProc(exits_at=0, stderr=err)), key_file=KEY)
    assert KEY not in tunnel.last_error and tunnel.last_error == 'load key "<key>": bad permissions'
    tunnel, _ = drive(Factory(lambda n: PermissionError(f"cannot run {KEY}")), key_file=KEY)
    assert "<key>" in tunnel.last_error and KEY not in tunnel.last_error


def test_only_the_last_stderr_line_is_kept_and_exit_code_is_the_fallback() -> None:
    tunnel = Tunnel("srv")
    tunnel._read_stderr(io.BytesIO(b"one\n\ntwo\nthree  \n\n"))
    assert tunnel.last_error == "three"
    tunnel, _ = drive(Factory(lambda n: FakeProc(exits_at=0, code=7)))
    assert "7" in tunnel.last_error
