"""Focus/typing mis-delivery guards (conductor/windows.py).

Regression for 2026-07-23: a push notice for 95emulator was typed into qualcomm's ACTIVE
terminal, because the tilix focus path returned success even when the async activate never
actually moved focus to the target — then typed into whatever window was focused. X11 itself
can't run in CI, so we mock the xdotool/tilix primitives and test the DECISION logic.
"""

from __future__ import annotations

import conductor.windows as w


def _fast(monkeypatch):
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
    monkeypatch.setattr(w.subprocess, "run",
                        lambda *a, **k: type("R", (), {"returncode": 0, "stdout": ""})())
    assert w._type_into_focused_window("x", title="t", window_title="Project X") is True


def test_active_not_target_accepts_when_no_window_title(monkeypatch):
    """A session with no custom title (cwd-titled window) can't be confirmed a mismatch — so we
    must NOT block on it (else the common /msg-check path breaks for those sessions)."""
    monkeypatch.setattr(w, "_active_window_name", lambda: "kyle@skippy: ~/GitHub/qualcomm/results")
    assert w._active_is_not_target("[other:qualcomm]", None) is False    # window_title None -> accept
    assert w._active_is_not_target("[other:qualcomm]", "") is False
