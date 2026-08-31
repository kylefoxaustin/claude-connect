"""Focus/typing mis-delivery guards (conductor/x11.py).

Regression for 2026-07-23: a push notice for 95emulator was typed into qualcomm's ACTIVE
terminal, because the tilix focus path returned success even when the async activate never
actually moved focus to the target — then typed into whatever window was focused. X11 itself
can't run in CI, so we mock the xdotool/tilix primitives and test the DECISION logic.
"""

from __future__ import annotations

import conductor.x11 as w


def _fast(monkeypatch):
    # ⚠️ THE FIX FOR THE "ORDER-FLAKY" ENTRY IN CLAUDE.md, and it was never order at all.
    #
    # `_focus_session_input` refuses to steal focus while a human is at the keyboard, and that
    # guard reads mutter's REAL idle time over D-Bus. Nothing here patched it, so the outcome
    # depended on whether Kyle had touched his keyboard in the last four seconds: green when he
    # was away, red while he was working. Diagnosed 2026-08-31 with mutter reporting 2103 ms —
    # the test was measuring the operator, not the code.
    #
    # Every other suite that drives this path already patches it (test_focus_arrival.py:25);
    # this one just never did. The guard keeps its own dedicated coverage in
    # test_inject_targeting.py, so pinning it here removes the environment, not the assertion.
    monkeypatch.setattr(w, "human_recently_active", lambda *a, **k: False)
    monkeypatch.setattr(w, "_FOCUS_POLL_TIMEOUT_S", 0.02)
    monkeypatch.setattr(w, "_FOCUS_POLL_STEP_S", 0.001)
    monkeypatch.setattr(w, "_TILE_SETTLE_S", 0.0)
    monkeypatch.setattr(w, "_FOCUS_SETTLE_S", 0.0)


# --- _active_is_not_target: the tilix-path counterpart to _window_belongs_to_target ----------
def test_active_not_target_cannot_confirm_without_a_name(monkeypatch):
    monkeypatch.setattr(w, "_active_window_name", lambda: None)
    assert w._active_is_not_target("95emulator", "Project 95emulator") is False   # no title → accept


def test_active_not_target_false_when_name_matches(monkeypatch):
    monkeypatch.setattr(w, "_active_window_name", lambda: "Project 95emulator — vim")
    assert w._active_is_not_target(None, "Project 95emulator") is False            # it IS the target


def test_active_not_target_true_on_confirmed_mismatch(monkeypatch):
    monkeypatch.setattr(w, "_active_window_name", lambda: "Project Qualcomm")
    assert w._active_is_not_target(None, "Project 95emulator") is True             # a DIFFERENT session


# --- the tilix focus path -------------------------------------------------------------------
def test_focus_refuses_when_activate_never_moves_focus(monkeypatch):
    """Kyle's exact bug: activate returns ok but focus stays on the previously-active window."""
    _fast(monkeypatch)
    monkeypatch.setattr(w, "tilix_id_for_pid", lambda pid: "uuid-target")
    monkeypatch.setattr(w, "tilix_activate_terminal", lambda u: True)
    monkeypatch.setattr(w, "_active_window_id", lambda: 111)                       # never changes
    assert w._focus_session_input(pid=1, terminal_pid=2, title="t",
                                  window_title="Project 95emulator") is False


def test_focus_ok_when_focus_moves_to_target(monkeypatch):
    _fast(monkeypatch)
    ids = iter([111, 222, 222, 222, 222])
    monkeypatch.setattr(w, "tilix_id_for_pid", lambda pid: "uuid")
    monkeypatch.setattr(w, "tilix_activate_terminal", lambda u: True)
    monkeypatch.setattr(w, "_active_window_id", lambda: next(ids))
    monkeypatch.setattr(w, "_active_window_name", lambda: "Project 95emulator")
    assert w._focus_session_input(pid=1, terminal_pid=2, title=None,
                                  window_title="Project 95emulator") is True


def test_focus_refuses_when_focus_moves_to_wrong_window(monkeypatch):
    _fast(monkeypatch)
    ids = iter([111, 999, 999, 999, 999])
    monkeypatch.setattr(w, "tilix_id_for_pid", lambda pid: "uuid")
    monkeypatch.setattr(w, "tilix_activate_terminal", lambda u: True)
    monkeypatch.setattr(w, "_active_window_id", lambda: next(ids))
    monkeypatch.setattr(w, "_active_window_name", lambda: "Project Qualcomm")      # wrong session
    assert w._focus_session_input(pid=1, terminal_pid=2, title=None,
                                  window_title="Project 95emulator") is False


# --- send_keys_to_session must never type when focus couldn't be confirmed ------------------
def test_send_keys_does_not_type_when_focus_fails(monkeypatch):
    monkeypatch.setattr(w, "xdotool_available", lambda: True)
    monkeypatch.setattr(w, "_focus_session_input", lambda **k: False)
    typed = []
    monkeypatch.setattr(w, "_type_into_focused_window",
                        lambda *a, **k: typed.append(1) or True)
    ok = w.send_keys_to_session(text="hi", pid=1, terminal_pid=2, title="t", window_title="w")
    assert ok is False and typed == []


# --- last line of defence: focus drifts during the settle, before the keystroke -------------
def test_type_aborts_if_active_window_becomes_wrong(monkeypatch):
    _fast(monkeypatch)
    monkeypatch.setattr(w, "_active_is_not_target", lambda t, wt: True)            # drifted away
    ran = []
    monkeypatch.setattr(w.subprocess, "run", lambda *a, **k: ran.append(a[0]))
    assert w._type_into_focused_window("x", title="t", window_title="w") is False
    assert ran == []                                                              # no xdotool fired


def test_type_proceeds_when_active_is_target(monkeypatch):
    _fast(monkeypatch)
    monkeypatch.setattr(w, "_active_is_not_target", lambda t, wt: False)           # still on target
    # `stderr` is NOT optional padding: a real CompletedProcess always carries it, and the X11
    # display check reads it (the exit code lies — wmctrl/xdotool exit 0 on "Cannot open display").
    # A fake missing a field the real object always has is a fake that passes while production
    # crashes on the same line — the v2.26.1 lesson, which this fake reproduced verbatim.
    monkeypatch.setattr(w.subprocess, "run",
                        lambda *a, **k: type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})())
    assert w._type_into_focused_window("x", title="t", window_title="Project X") is True


def test_active_not_target_accepts_when_no_window_title(monkeypatch):
    """A session with no custom title (cwd-titled window) can't be confirmed a mismatch — so we
    must NOT block on it (else the common /msg-check path breaks for those sessions)."""
    monkeypatch.setattr(w, "_active_window_name", lambda: "kyle@skippy: ~/GitHub/qualcomm/results")
    assert w._active_is_not_target("[other:qualcomm]", None) is False    # window_title None -> accept
    assert w._active_is_not_target("[other:qualcomm]", "") is False


# --- send_key_to_session: dismissing a modal the injected command itself opened -------------
#
# Kyle, 2026-08-17: every relaunched session came up parked on the Remote Control menu that
# `/rc` ITSELF opens ("Disconnect this session / Show QR code / Continue"), blocking until a
# human answered. Dismissal must press a bare ESCAPE — never Return, which SELECTS whatever the
# cursor is on, and one of those options disconnects the session.

def _capture_x(monkeypatch):
    calls: list[list[str]] = []
    monkeypatch.setattr(w, "xdotool_available", lambda: True)
    monkeypatch.setattr(w, "_focus_session_input", lambda **kw: True)
    monkeypatch.setattr(w, "_active_is_not_target", lambda *a, **k: False)
    monkeypatch.setattr(w, "_run_x", lambda argv, **kw: calls.append(argv) or type(
        "R", (), {"returncode": 0, "stdout": "", "stderr": ""})())
    return calls


def test_send_key_presses_only_that_key(monkeypatch):
    _fast(monkeypatch)
    calls = _capture_x(monkeypatch)
    assert w.send_key_to_session(key="Escape", terminal_pid=1) is True
    assert calls == [["xdotool", "key", "--clearmodifiers", "Escape"]]


def test_send_key_never_types_text_or_presses_return(monkeypatch):
    """The whole point: this path must not be able to answer a picker."""
    _fast(monkeypatch)
    calls = _capture_x(monkeypatch)
    w.send_key_to_session(key="Escape", terminal_pid=1)
    flat = [tok for c in calls for tok in c]
    assert "type" not in flat, "must never type text"
    assert "Return" not in flat, "Return would SELECT an option — including 'Disconnect'"
    assert "ctrl+u" not in flat, "must not clear the line either"


def test_send_key_refuses_when_focus_moved(monkeypatch):
    """Same mis-delivery guard as typing: never press keys at the wrong session."""
    _fast(monkeypatch)
    calls = _capture_x(monkeypatch)
    monkeypatch.setattr(w, "_active_is_not_target", lambda *a, **k: True)
    assert w.send_key_to_session(key="Escape", terminal_pid=1) is False
    assert calls == [], "nothing may be pressed once focus is known to be wrong"


def test_send_key_false_without_xdotool(monkeypatch):
    _fast(monkeypatch)
    monkeypatch.setattr(w, "xdotool_available", lambda: False)
    assert w.send_key_to_session(key="Escape", terminal_pid=1) is False
