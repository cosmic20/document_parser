"""Persistent Vaultify terminal sessions — Claude Code in a PTY, decoupled from the browser tab.

A session outlives its WebSocket: navigating away just *detaches* the bridge while the ``claude``
process keeps running, so document processing and a vault build can proceed at the same time.
Reconnecting *re-attaches* and replays recent output from a ring buffer. A session ends only when
``claude`` exits or is explicitly stopped.
"""

from __future__ import annotations

import asyncio
import fcntl
import os
import pty
import signal
import struct
import termios
from dataclasses import dataclass, field
from pathlib import Path

_BUFFER_CAP = 256 * 1024  # bytes of recent output replayed to a (re)attaching terminal


@dataclass
class TermSession:
    class_id: str
    pid: int
    fd: int
    buffer: bytearray = field(default_factory=bytearray)
    alive: bool = True
    ws: object | None = None  # the currently-attached WebSocket (at most one)


def _read(fd: int) -> bytes:
    try:
        return os.read(fd, 4096)
    except OSError:  # raised when the PTY closes (child exited)
        return b""


class TerminalManager:
    """Registry of live ``claude`` PTY sessions, keyed by class id."""

    def __init__(self) -> None:
        self._sessions: dict[str, TermSession] = {}

    def get(self, class_id: str) -> TermSession | None:
        s = self._sessions.get(class_id)
        return s if (s and s.alive) else None

    def active_class_ids(self) -> list[str]:
        return [cid for cid, s in self._sessions.items() if s.alive]

    def ensure(self, class_id: str, cwd: Path, argv: list[str]) -> TermSession:
        """Return the live session for a class, spawning ``claude`` if there isn't one."""
        existing = self.get(class_id)
        if existing:
            return existing
        pid, fd = pty.fork()
        if pid == 0:  # child becomes claude
            os.chdir(str(cwd))
            os.execvp(argv[0], argv)
            os._exit(1)  # only reached if exec fails
        s = TermSession(class_id=class_id, pid=pid, fd=fd)
        self._sessions[class_id] = s
        asyncio.create_task(self._pump(s))
        return s

    async def _pump(self, s: TermSession) -> None:
        """Drain the PTY into the ring buffer + the attached WS, for the session's lifetime."""
        loop = asyncio.get_running_loop()
        try:
            while True:
                data = await loop.run_in_executor(None, _read, s.fd)
                if not data:
                    break
                s.buffer.extend(data)
                if len(s.buffer) > _BUFFER_CAP:
                    del s.buffer[: len(s.buffer) - _BUFFER_CAP]
                if s.ws is not None:
                    try:
                        await s.ws.send_bytes(data)
                    except Exception:
                        s.ws = None
        finally:
            s.alive = False
            if s.ws is not None:
                try:
                    await s.ws.close()
                except Exception:
                    pass
            for fn in (lambda: os.close(s.fd), lambda: os.waitpid(s.pid, 0)):
                try:
                    fn()
                except OSError:
                    pass

    def write(self, s: TermSession, data: bytes) -> None:
        try:
            os.write(s.fd, data)
        except OSError:
            pass

    def resize(self, s: TermSession, rows: int, cols: int) -> None:
        try:
            fcntl.ioctl(s.fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
        except OSError:
            pass

    def stop(self, class_id: str) -> None:
        s = self._sessions.get(class_id)
        if s and s.alive:
            try:
                os.kill(s.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass

    def shutdown(self) -> None:
        for s in self._sessions.values():
            if s.alive:
                try:
                    os.kill(s.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass


manager = TerminalManager()
