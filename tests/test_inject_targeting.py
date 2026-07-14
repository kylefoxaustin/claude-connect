"""Keystroke MIS-DELIVERY — Conductor typed mcxn's push verdict into 91's terminal.

CONFIRMED from the transcripts, not theorized: the verdict "✅ Kyle says PUSH — the approval
is already armed for mcxn947qemu" was ENQUEUED into 91emulator's session (a `queue-operation`
record, sessionId d6e5aa65 = 91) two seconds after Conductor attested typing it into mcxn
(pid 54912). The ledger recorded the INTENT (mcxn); the keys landed in 91.

MECHANISM (from the code + the ledger timeline):
  send_keys_to_session() calls tilix_activate_terminal() — an ASYNC D-Bus activate with no
  sync — then sleeps a fixed 0.25s and reads xdotool getactivewindow, trusting whatever window
  is focused. When the activate hasn't landed within the sleep, getactivewindow returns the
  PREVIOUSLY focused window and it types THERE. Conductor had focused 91's window 20s earlier
  (to answer 91's picker), so 91 was the stale-active window. mcxn got the verdict 12x, 91 got
  it 2x — the split IS the race.

  For tilix, every window shares one PID (one terminal server), so PID can't distinguish them.
  The reliable distinguisher is the per-session WINDOW TITLE. The fix: after focusing, VERIFY
  the window we're about to type into actually belongs to the target session, and if it does
  not, DO NOT TYPE — retry later. A keystroke typed into the wrong terminal is unrecoverable.

This test encodes the exact race and asserts the fixed behaviour. It is RED against the
pre-fix code (which types into the stale window) and GREEN after.
"""

from __future__ import annotations

import types

import pytest

import conductor.windows as W


@pytest.fixture
def stub(monkeypatch):
    """Simulate the environment: tilix present, the target's tile activates 'successfully'
    (the async D-Bus call returns 0), but the ACTIVE window is still the previously-focused
    one — the stale-focus race. Records every xdotool 'type'/'key' so the test can see whether
    (and where) we typed."""
    typed: list[str] = []
    activated: list[int] = []

    monkeypatch.setattr(W, "xdotool_available", lambda: True)
    monkeypatch.setattr(W, "wmctrl_available", lambda: True)
    monkeypatch.setattr(W, "tilix_id_for_pid", lambda pid: "TILE-MCXN")
    monkeypatch.setattr(W, "tilix_activate_terminal", lambda uuid: True)  # D-Bus call "succeeds"

    # THE RACE: getactivewindow returns 91's window (0x5B = 91), not mcxn's tile.
    WRONG_WID = 0x5B          # 91emulator's window (stale focus)
    RIGHT_WID = 0xAC          # mcxn's window
    monkeypatch.setattr(W, "_active_window_id", lambda: WRONG_WID)

    # Title map so a verifier can tell whose window each id is.
    titles = {WRONG_WID: "Project 91qemu", RIGHT_WID: "Project mcxqemu"}
    monkeypatch.setattr(W, "list_windows",
                        lambda: [(wid, 4321, t) for wid, t in titles.items()])

    def fake_run(cmd, *a, **k):
        # cmd like ["xdotool","windowactivate","--sync","91"] / ["xdotool","type",...,text]
        if len(cmd) >= 2 and cmd[0] == "xdotool":
            if cmd[1] == "windowactivate":
                activated.append(int(cmd[-1]))
            elif cmd[1] == "type":
                typed.append(cmd[-1])
            elif cmd[1] == "key" and cmd[-1] not in ("ctrl+u", "Return"):
                typed.append(cmd[-1])
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(W.subprocess, "run", fake_run)
    monkeypatch.setattr(W.time, "sleep", lambda *_: None)
    return types.SimpleNamespace(typed=typed, activated=activated,
                                 WRONG_WID=WRONG_WID, RIGHT_WID=RIGHT_WID)


def test_never_types_into_the_wrong_window_when_focus_is_stale(stub):
    """THE INVARIANT the incident violated: mcxn's keystrokes must NEVER land in 91's window.

    The active window is 91's (stale focus), but the target is mcxn. The fix rejects the
    unverified active window and recovers via reliable title-resolution, so it delivers to
    mcxn's window — but the load-bearing assertion is the harm one: 91 is never typed into."""
    ok = W.send_keys_to_session(
        text="✅ Kyle says PUSH — armed for mcxn947qemu",
        pid=54912, terminal_pid=4321,
        title="mcxqemu", window_title="Project mcxqemu",
    )
    assert stub.WRONG_WID not in stub.activated, "typed into 91's window — the exact bug"
    # Recovery is the good outcome: it found mcxn's window by title instead of the stale one.
    assert ok is True
    assert stub.activated and stub.activated[-1] == stub.RIGHT_WID


def test_aborts_rather_than_type_when_it_cannot_confirm_any_window(monkeypatch, stub):
    """When the stale-focus window is wrong AND title-resolution can't find the target either
    (no window matches), we must ABORT — not fall back to typing into the stale window."""
    # Only 91's window exists in the world; mcxn's is gone. Nothing matches the mcxn hints.
    monkeypatch.setattr(W, "list_windows",
                        lambda: [(stub.WRONG_WID, 4321, "Project 91qemu")])
    ok = W.send_keys_to_session(
        text="/msg-check",
        pid=54912, terminal_pid=4321,
        title="mcxqemu", window_title="Project mcxqemu",
    )
    assert ok is False
    assert stub.typed == [], f"typed into an unconfirmed window: {stub.typed}"


def test_DOES_type_when_the_focused_window_is_the_right_one(monkeypatch, stub):
    """Control: when the activate lands and getactivewindow returns mcxn's own window, we type
    normally — the guard must not break the happy path."""
    monkeypatch.setattr(W, "_active_window_id", lambda: stub.RIGHT_WID)
    ok = W.send_keys_to_session(
        text="/msg-check",
        pid=54912, terminal_pid=4321,
        title="mcxqemu", window_title="Project mcxqemu",
    )
    assert ok is True
    assert "/msg-check" in stub.typed
    assert stub.activated and stub.activated[-1] == stub.RIGHT_WID
