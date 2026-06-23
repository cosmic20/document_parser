"""Tests for the persistent terminal session manager (PTY decoupled from any WebSocket).

Uses a harmless ``cat`` process (echoes input) instead of ``claude`` to exercise spawn → buffer →
survive-without-a-socket → stop, driving the async pump via ``asyncio.run``.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from document_parser.terminals import TerminalManager, _pid_alive


def test_session_buffers_survives_detach_and_stops():
    async def scenario():
        mgr = TerminalManager()
        s = mgr.ensure("c1", Path("/tmp"), ["cat"])  # cat echoes stdin; stays alive

        mgr.write(s, b"hello world\n")
        await asyncio.sleep(0.3)
        # Output is captured in the ring buffer even with NO socket attached (s.ws is None).
        assert s.ws is None
        assert b"hello world" in bytes(s.buffer)

        # The session is discoverable for re-attach (still alive after a "detach").
        assert mgr.get("c1") is s
        assert "c1" in mgr.active_class_ids()

        # Stopping ends the session.
        mgr.stop("c1")
        for _ in range(60):
            if not s.alive:
                break
            await asyncio.sleep(0.05)
        assert not s.alive
        assert mgr.get("c1") is None

    asyncio.run(scenario())


def test_ensure_never_double_spawns_for_one_class():
    """Two Vaultify clicks for the same class must share one process, never run two concurrently.

    Two live ``claude`` sessions would edit the same vault notes at once and corrupt them, so
    ``ensure`` returns the existing live session rather than spawning a second.
    """

    async def scenario():
        mgr = TerminalManager()
        a = mgr.ensure("c1", Path("/tmp"), ["cat"])
        b = mgr.ensure("c1", Path("/tmp"), ["cat"])  # "clicked Vaultify again"
        assert a is b and a.pid == b.pid  # same process, not a second one

        # A lingering process from a prior session is terminated before a fresh spawn, so we never
        # end up with two live processes for the class even if the old one wasn't cleanly stopped.
        a.alive = False  # simulate a stale flag while the process is still running
        old_pid = a.pid
        c = mgr.ensure("c1", Path("/tmp"), ["cat"])
        assert c.pid != old_pid  # spawned fresh
        for _ in range(60):  # the orphaned old process gets reaped
            if not _pid_alive(old_pid):
                break
            await asyncio.sleep(0.05)
        assert not _pid_alive(old_pid)

        mgr.stop("c1")

    asyncio.run(scenario())
