"""Tests for the persistent terminal session manager (PTY decoupled from any WebSocket).

Uses a harmless ``cat`` process (echoes input) instead of ``claude`` to exercise spawn → buffer →
survive-without-a-socket → stop, driving the async pump via ``asyncio.run``.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from document_parser.terminals import TerminalManager


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
