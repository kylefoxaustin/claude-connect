"""Focus must never raise another session's terminal.

Kyle, 2026-08-31: "when I click on the 95emulator cards play button on conductor on Skippy it
opens qualcomms tilix."

95emulator is daemon-hosted and has NO terminal window at all, so nothing could legitimately
match. But every tilix window on that box is titled "✳ Project <name>", so the token `project`
scored 1 against all nineteen of them and `_token_match` kept the first — qualcomm's live
session. The hint shared exactly one word with the window it chose, and that word was in every
other window too.

⭐ THE CLASS: a token present in every candidate discriminates nothing, however true it is of
each one. Same shape as the fleet-health alarm that fired on 36 of 36 cursors — a signal that
matches everything is not a signal, it is a constant, and ranking by it returns whatever came
first.

Blast radius was smaller than it looks, and only by luck of a second control:
`send_keys_to_session` verifies with FULL-HINT substring before typing, so keystrokes were
refused rather than delivered to qualcomm. `focus_session` had no such check and simply raised
whatever came back — so the wrong window was yanked to the front, which is what Kyle saw.

Window titles below are copied from the live `wmctrl` list, not invented.
"""
from __future__ import annotations

import pytest

from conductor import x11 as w

# The real desktop: nineteen tilix windows all sharing the word "Project", plus unrelated apps.
LIVE = [
    (1, 1996087, "✳ Project Qualcomm"),
    (2, 1996087, "✳ Project Kitchen_Margin"),
    (3, 1996087, "✳ Project campmatch"),
    (4, 1996087, "✳ Project PAI"),
    (5, 1996087, "✳ Project PAI-sizer"),
    (6, 1996087, "✳ Project tipometer"),
    (7, 1996087, "◑ Project claude connect"),
    (8, 1996087, "✳ Project 91qemu"),
    (9, 1996087, "✳ Project 93Qemu"),
    (10, 1996087, "✳ Project Holobench"),
    (11, 3382494, "Qualcomm® Visual Studio Code Extension - Visual Studio Code"),
    (12, 79741, "Qualcomm Package Manager 3"),
]


def test_a_session_with_no_window_matches_NOTHING():
    """The bug, exactly as Kyle hit it. 'Project 95Qemu' is on no window anywhere."""
    got = w._token_match(LIVE, "Project 95Qemu", "95emulator")
    assert got is None, (
        f"matched window {got} for a session that has no window — with the live titles above "
        "that is qualcomm's live terminal"
    )


def test_the_universal_token_alone_never_wins():
    """Even for a name that shares nothing else, 'Project' must not carry the decision."""
    assert w._token_match(LIVE, "Project Nonexistent") is None
    assert w._token_match(LIVE, "Project") is None


def test_a_genuinely_distinctive_hint_still_matches():
    """The regression guard. Discarding noise tokens must not discard the signal."""
    assert w._token_match(LIVE, "Project Holobench", "holobench") == 10
    assert w._token_match(LIVE, "Project campmatch") == 3


def test_the_reworded_auto_topic_case_the_matcher_exists_for():
    """From the original docstring: a window whose title is a REWORDING of the session name.

    This is the whole reason token matching exists, so the fix has to keep it working.
    """
    windows = [
        (1, 100, "Build Rockchip RK182X EVK setup guide"),
        (2, 100, "Project unrelated"),
        (3, 100, "Project something else"),
    ]
    assert w._token_match(windows, "rk182x-evk-setup-guide") == 1


def test_a_single_window_search_still_works():
    """df<=1 keeps a token that is technically 'in every candidate' when there is only one.

    Without that clause the noise filter eats the only evidence available and the matcher
    refuses every single-window desktop.
    """
    assert w._token_match([(7, 100, "Project Holobench")], "holobench") == 7


def test_a_tie_refuses_rather_than_guessing():
    """⚠️ Ambiguity is when guessing does the most damage — the wrong window is another
    Claude's live terminal. The caller's next strategy already declines rather than pick a
    sibling, so refusing here loses nothing and risks nothing."""
    windows = [(1, 100, "simtest-a run"), (2, 100, "simtest-b run"), (3, 100, "other")]
    assert w._token_match(windows, "simtest") is None


def test_focus_refuses_to_RAISE_a_window_it_cannot_confirm(monkeypatch):
    """⭐ The second half. send_keys already refused to TYPE; focus still raised the window.

    Raising the wrong window is not harmless when nothing is typed: it steals the screen from
    whatever Kyle was doing and dumps him in a colleague's session.
    """
    raised: list[int] = []
    monkeypatch.setattr(w, "wmctrl_available", lambda: True)
    monkeypatch.setattr(w, "tilix_id_for_pid", lambda pid: None)
    monkeypatch.setattr(w, "list_windows", lambda: LIVE)
    monkeypatch.setattr(w, "_raise_window", lambda wid: raised.append(wid) or True)
    monkeypatch.setattr(w, "_resolve_window", lambda **kw: 1)   # force the mis-resolution

    ok = w.focus_session(pid=135180, terminal_pid=None,
                         title="95emulator", window_title="Project 95Qemu")
    assert ok is False, "reported success after focusing the wrong session"
    assert raised == [], f"raised window {raised} despite being unable to confirm it"


def test_focus_still_raises_a_confirmed_window(monkeypatch):
    """The other direction, or 'refuses to raise' would just mean 'focus is broken'."""
    raised: list[int] = []
    monkeypatch.setattr(w, "wmctrl_available", lambda: True)
    monkeypatch.setattr(w, "tilix_id_for_pid", lambda pid: None)
    monkeypatch.setattr(w, "list_windows", lambda: LIVE)
    monkeypatch.setattr(w, "_raise_window", lambda wid: raised.append(wid) or True)

    ok = w.focus_session(pid=1, terminal_pid=1996087,
                         title="holobench", window_title="Project Holobench")
    assert ok is True and raised == [10]
