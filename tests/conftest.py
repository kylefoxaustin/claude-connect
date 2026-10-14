"""Shared test isolation: the suite must never read the LIVE fleet's bus state.

⚠️ WHY THIS EXISTS. Eleven test modules build an `AppState(load_settings())`, and
`load_settings()` points at the real `~/.claude/bus-state` — coordination state being
written by ~27 live sessions while the suite runs.

That was harmless only while nothing in the tested paths read that directory. On
2026-10-08 the wake path started reading `<member>.delivered`, so it would not wake a
session for mail it was mid-reply to. Fifteen tests failed immediately — correctly
suppressing wakes, inside unit tests, because a real session happened to hold a staged
record at that second. The harness uses live tag names like `[other:qualcomm]`, so the
collision was certain the moment anything consulted that state.

The sharp part: the suite had been reporting PASS throughout. Not because it was isolated
— because no `.delivered` file happened to exist during those runs. A green suite that
depends on what another process is doing is not evidence, and it would have failed for
whoever ran it next with no way to connect the failure to the change that caused it.

WHY A PROPERTY PATCH rather than patching `load_settings`: modules import the symbol into
their own namespace (`from conductor.main import load_settings`), so patching it at the
source does not reach them — measured, test_coord kept failing. Patching the resolved-path
property catches every construction and import style at once.

WHY IT DEFERS TO AN EXPLICIT OVERRIDE: tests that deliberately point at a `tmp_path` must
keep working. Only the DEFAULT live path is redirected.

A test that wants real state should set `settings.bus.state_dir` itself; that is honoured.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

_LIVE_DEFAULT = os.path.expanduser("~/.claude/bus-state")


@pytest.fixture(autouse=True)
def _never_read_live_bus_state(monkeypatch, tmp_path_factory):
    from conductor.settings import BusSettings

    # Deliberately NOT under the test's own tmp_path: at least one test asserts that a
    # code path leaves no trace on disk by inspecting its working directory, and creating
    # a directory there made that test fail. Isolation must not become a side effect that
    # other tests can observe.
    scratch = tmp_path_factory.mktemp("isolated-bus-state")

    original = BusSettings.state_dir_resolved.fget

    def _resolved(self):
        p = original(self)
        # Only redirect the LIVE default. A test that chose a path keeps it.
        return Path(scratch) if str(p) == _LIVE_DEFAULT else p

    monkeypatch.setattr(BusSettings, "state_dir_resolved", property(_resolved))
    yield


_LIVE_BUS_SCRIPT = os.path.expanduser("~/.claude/bin/bus.sh")


@pytest.fixture(autouse=True)
def _never_run_the_live_bus_script(monkeypatch, tmp_path_factory):
    """The same leak, one door over, and a worse one: it WRITES. `answer_proposal` shells out
    to `settings.bus.script_path` — `bus.sh push approve <repo>` — so on a box with the bus
    installed, test_proposal_verdict_doorbell approved a real pending push for a repo named
    `pai` every time the suite ran; on a box without it (a fresh clone) the same tests
    failed with FileNotFoundError (README review, 2026-10-14). Redirect the live default to a
    stub that refuses, which is what the real script does when nothing is pending. A test that
    sets `settings.bus.script_path` itself keeps its own."""
    from conductor.settings import BusSettings

    stub = tmp_path_factory.mktemp("isolated-bus-script") / "bus.sh"
    stub.write_text("#!/bin/sh\necho 'test stub: the live bus is never run from tests' >&2\nexit 1\n")
    stub.chmod(0o755)
    original = BusSettings.script_path_resolved.fget

    def _resolved(self):
        p = original(self)
        return stub if str(p) == _LIVE_BUS_SCRIPT else p

    monkeypatch.setattr(BusSettings, "script_path_resolved", property(_resolved))
    yield
