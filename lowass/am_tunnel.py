# lowass/am_tunnel.py
"""`ssh -L` to the agentmemory server, kept alive in a daemon thread. ssh never asks (BatchMode) and binds to 127.0.0.1
only; every effect (process, waiting, health check) is injectable."""
from __future__ import annotations

import contextlib
import logging
import subprocess
import threading
import time
from collections.abc import Callable
from typing import IO

log = logging.getLogger("lowass.am_tunnel")

NO_SSH = "The OpenSSH client is missing. On Windows: Settings, Optional features, OpenSSH Client."
TICK = 0.5  # seconds between looks at ssh
CHECK_TICKS = 6  # a check every 3 s
MAX_FAILS = 5  # this many failed checks in a row restart ssh


def _port(name: str, value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 65535:
        raise ValueError(f"{name} must be 1..65535")
    return value


def build_command(host: str, local_port: int, remote_port: int, key_file: str = "", user: str = "",
                  ssh_binary: str = "ssh") -> list[str]:
    """The ssh argv. Empty key_file means no -i (ssh-agent, ~/.ssh/config); the key is never read."""
    if not host.strip():
        raise ValueError("host is empty")
    for name, value in (("host", host), ("key_file", key_file), ("user", user)):
        if value.startswith("-") or any(c in value for c in "\r\n\0"):
            raise ValueError(f"{name} must not start with '-' or hold control characters")
    local, remote = _port("local_port", local_port), _port("remote_port", remote_port)
    return [ssh_binary, "-N", "-T", "-o", "BatchMode=yes", "-o", "ExitOnForwardFailure=yes",
            "-o", "ServerAliveInterval=15", "-o", "ServerAliveCountMax=3", "-o", "ConnectTimeout=10",
            "-o", "StrictHostKeyChecking=accept-new", "-L", f"127.0.0.1:{local}:127.0.0.1:{remote}",
            *(["-i", key_file] if key_file else []), *(["-l", user] if user else []), host]


class Tunnel:
    """start() returns at once; the thread runs ssh and restarts it with a growing delay."""

    def __init__(self, host: str, local_port: int = 13111, remote_port: int = 3111, key_file: str = "",
                 user: str = "", ssh_binary: str = "ssh", popen: Callable[..., subprocess.Popen[bytes]] = subprocess.Popen,
                 sleep: Callable[[float], object] = time.sleep, check: Callable[[], bool] | None = None,
                 backoff: tuple[float, ...] = (1, 2, 5, 10, 30)) -> None:
        self._cmd = build_command(host, local_port, remote_port, key_file, user, ssh_binary)
        if not backoff:
            raise ValueError("backoff is empty")
        self._key = key_file
        self._popen, self._sleep, self._check, self._backoff = popen, sleep, check, backoff
        self._stop, self._lock = threading.Event(), threading.Lock()
        self._thread: threading.Thread | None = None
        self._proc: subprocess.Popen[bytes] | None = None
        self._state, self._last_error, self._restarts = "stopped", "", 0

    @property
    def state(self) -> str:
        return self._state

    @property
    def last_error(self) -> str:
        return self._last_error

    @property
    def restarts(self) -> int:
        return self._restarts

    def start(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear()
            self._state = "starting"
            self._thread = threading.Thread(target=self._run, name="am-tunnel", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        proc, thread = self._proc, self._thread
        if proc is not None:
            self._kill(proc)
        if thread is not None and thread is not threading.current_thread():
            thread.join(3)
        self._state = "stopped"

    def _wait(self, seconds: float) -> bool:
        """True when stop() was called; the default sleep is an Event wait, so stop() is at once."""
        if self._sleep is time.sleep:
            return self._stop.wait(seconds)
        self._sleep(seconds)
        return self._stop.is_set()

    def _run(self) -> None:
        index = 0
        while not self._stop.is_set():
            proc = self._spawn()
            if proc is None:
                self._state = "down"
                if self._wait(max(self._backoff)):
                    break
                continue
            reader = threading.Thread(target=self._read_stderr, args=(proc.stderr,), daemon=True)
            reader.start()
            healthy = self._watch(proc)
            self._kill(proc)
            reader.join(1)
            if self._stop.is_set():
                break
            self._last_error = self._last_error or f"ssh exited with code {proc.poll()}"
            self._state = "down"
            self._restarts += 1
            delay = self._backoff[min(0 if healthy else index, len(self._backoff) - 1)]
            index = 1 if healthy else index + 1
            log.warning("ssh tunnel is down (%s); restart in %ss", self._last_error, delay)
            if self._wait(delay):
                break
        self._state = "stopped"

    def _spawn(self) -> subprocess.Popen[bytes] | None:
        with self._lock:
            if self._stop.is_set():
                return None
            self._last_error = ""
            try:
                self._proc = self._popen(self._cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                         stderr=subprocess.PIPE, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            except FileNotFoundError:
                self._last_error = NO_SSH
                log.warning(NO_SSH)
                return None
            except OSError as exc:
                self._last_error = self._redact(f"Could not start ssh: {exc}")
                log.warning("%s", self._last_error)
                return None
            self._state = "starting"
            return self._proc

    def _watch(self, proc: subprocess.Popen[bytes]) -> bool:
        """Block while ssh runs; True when a check succeeded (resets the backoff)."""
        healthy, fails, ticks = False, 0, 0
        while not self._wait(TICK):
            if proc.poll() is not None:
                return healthy
            ticks += 1
            if ticks % CHECK_TICKS:
                continue
            if self._probe():
                healthy, fails = True, 0
                self._state = "up"
            else:
                fails += 1
                if fails >= MAX_FAILS:
                    self._last_error = self._last_error or "the tunnel does not answer"
                    break
        return healthy

    def _probe(self) -> bool:
        try:
            return self._check is None or bool(self._check())
        except Exception:  # noqa: BLE001 - a broken check must not kill the supervisor
            log.warning("health check raised")
            return False

    def _kill(self, proc: subprocess.Popen[bytes]) -> None:
        try:
            if proc.poll() is not None:
                return
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=2)
        except (OSError, subprocess.TimeoutExpired):
            log.warning("could not stop ssh")

    def _read_stderr(self, stream: IO[bytes] | None) -> None:
        """Keep only the last non-empty line, redacted."""
        with contextlib.suppress(OSError, ValueError):  # the pipe closes when ssh exits
            for raw in stream or ():
                line = raw.decode("utf-8", "replace").strip()
                if line:
                    self._last_error = self._redact(line)

    def _redact(self, text: str) -> str:
        for variant in (self._key, self._key.replace("\\", "/")):
            text = text.replace(variant, "<key>") if variant else text
        return text
