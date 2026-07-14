"""Keystroke targeting — Conductor must type into the RIGHT tilix tile, or none.

CONFIRMED live: Conductor typed mcxn's push verdict into 91's terminal. The cause, pinned by
the simtest X11 smoke test (Kyle's simulator): the code activated the target's tilix tile, then
read `xdotool getactivewindow` and `windowactivate`-d whatever it returned — but getactivewindow
was stale (the previous window) AND returns a CLIENT window id that never matches wmctrl's frame
ids, and `windowactivate` on a tilix window doesn't focus the tile's input at all. So that layer
caused BOTH the mis-delivery (typed into the stale window) and, once guarded, silent non-delivery
(typed into an unfocused tile).

The fix, verified live (inject for A while B is force-focused -> lands in A, never B): trust
tilix's own activate-terminal addressed by the tile UUID — the UUID comes from the target's
/proc/<pid>/environ, so it is the RIGHT tile by construction. Wait for focus to move (async),
settle, type. No getactivewindow identity-matching, no windowactivate.

The title verify (_window_belongs_to_target) remains for the NON-tilix fallback, where we do
resolve by title — and it must not false-positive on a token two sessions share.
"""

from __future__ import annotations

import types

import pytest

import conductor.windows as W


@pytest.fixture
def env(monkeypatch):
    calls = {"activated_uuid": None, "typed": [], "windowactivated": []}
    seq = {"vals": [0x1, 0x1, 0x2]}      # active window: before=0x1, moves to 0x2 on 3rd read
    state = {"i": 0}
    clock = {"t": 0.0}

    def active():
        v = seq["vals"][min(state["i"], len(seq["vals"]) - 1)]
        state["i"] += 1
        return v

    def activate(uuid):
        calls["activated_uuid"] = uuid
        return calls.get("_activate_ok", True)

    def run(cmd, *a, **k):
        if len(cmd) >= 2 and cmd[0] == "xdotool":
            if cmd[1] == "type":
                calls["typed"].append(cmd[-1])
            elif cmd[1] == "windowactivate":
                calls["windowactivated"].append(cmd[-1])
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(W, "xdotool_available", lambda: True)
    monkeypatch.setattr(W, "wmctrl_available", lambda: True)
    monkeypatch.setattr(W, "tilix_id_for_pid", lambda pid: "TILE-A")
    monkeypatch.setattr(W, "tilix_activate_terminal", activate)
    monkeypatch.setattr(W, "_active_window_id", active)
    monkeypatch.setattr(W.subprocess, "run", run)
    monkeypatch.setattr(W.time, "sleep", lambda s: clock.__setitem__("t", clock["t"] + s))
    monkeypatch.setattr(W.time, "monotonic", lambda: clock["t"])
    return calls


def _send(**over):
    kw = dict(text="/msg-check", pid=54912, terminal_pid=4321,
              title="mcxqemu", window_title="Project mcxqemu")
    kw.update(over)
    return W.send_keys_to_session(**kw)


def test_tilix_activates_the_right_tile_by_uuid_and_types(env):
    """The UUID from the target's own /proc environ IS the identity — activate it, wait for
    focus to move, type. Never windowactivate (which doesn't focus a tilix tile's input)."""
    ok = _send()
    assert ok is True
    assert env["activated_uuid"] == "TILE-A", "did not activate the target's own tile"
    assert env["typed"] == ["/msg-check"]
    assert env["windowactivated"] == [], "used windowactivate on a tilix tile (breaks input)"


def test_tilix_refuses_when_the_tile_activate_fails(env):
    """If tilix can't activate the tile, we must not type into whatever happens to be focused."""
    env["_activate_ok"] = False
    ok = _send()
    assert ok is False
    assert env["typed"] == []


def test_non_tilix_path_verifies_title_before_typing(monkeypatch, env):
    """Non-tilix terminal: no tile UUID, so resolve by title, windowactivate, and verify the
    window really is the target's before typing."""
    monkeypatch.setattr(W, "tilix_id_for_pid", lambda pid: None)     # not a tilix session
    monkeypatch.setattr(W, "_resolve_window", lambda **k: 0xAC)
    monkeypatch.setattr(W, "_raise_window", lambda wid: True)
    monkeypatch.setattr(W, "list_windows", lambda: [(0xAC, 4321, "Project mcxqemu")])
    ok = _send()
    assert ok is True
    assert env["windowactivated"] == ["172"]    # 0xAC == 172: raised the resolved window
    assert env["typed"] == ["/msg-check"]


def test_non_tilix_refuses_a_title_mismatch(monkeypatch, env):
    monkeypatch.setattr(W, "tilix_id_for_pid", lambda pid: None)
    monkeypatch.setattr(W, "_resolve_window", lambda **k: 0xBAD)
    monkeypatch.setattr(W, "_raise_window", lambda wid: True)
    monkeypatch.setattr(W, "list_windows", lambda: [(0xBAD, 4321, "Project 91qemu")])  # wrong window
    assert _send() is False
    assert env["typed"] == []


def test_verify_guard_does_not_false_positive_on_a_SHARED_token(monkeypatch):
    """Found live: two sessions whose titles share a token ("simtest-a"/"simtest-b" both contain
    "simtest"; "keyhole"/"keyhole-sizer" both contain "keyhole") must not verify as each other."""
    windows = [(0xA, 4321, "kyle@skippy: ~/Documents/GitHub/simtest-a"),
               (0xB, 4321, "kyle@skippy: ~/Documents/GitHub/simtest-b")]
    monkeypatch.setattr(W, "list_windows", lambda: windows)
    assert W._window_belongs_to_target(0xB, "simtest-a",
                                       "kyle@skippy: ~/Documents/GitHub/simtest-a") is False
    assert W._window_belongs_to_target(0xA, "simtest-a",
                                       "kyle@skippy: ~/Documents/GitHub/simtest-a") is True
