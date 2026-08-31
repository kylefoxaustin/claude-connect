"""The Windows desktop backend (conductor/desktop_win.py).

The half of the seam win_conductor owes. skippy extracted `desktop.py` and kept Linux green;
these pin the behaviour that only a real Windows desktop can establish.

⚠️ MOST OF THIS FILE IS ABOUT ONE RULE: never return True having done nothing — and its Windows
corollary, never act on a window you cannot prove is the right one. The regression test below
exists because the first version of this backend violated both within an hour of being written,
and the end-to-end run caught it rather than the code review.
"""
from __future__ import annotations

import os
import sys

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform != "win32",
    reason="the Windows backend needs a Windows desktop — on Linux desktop.py never imports it",
)

if sys.platform == "win32":
    from conductor import desktop, desktop_win
else:                                                   # pragma: no cover - import guard for Linux
    desktop = desktop_win = None

CONTRACT = ("focus_session", "send_key_sequence", "send_key_to_session",
            "send_keys_to_session", "wmctrl_available", "x11_health")


def test_the_selector_picks_this_backend_on_windows():
    assert desktop.backend_name == "desktop_win"
    for name in CONTRACT:
        assert getattr(desktop, name) is getattr(desktop_win, name), \
            f"{name} is not the Windows implementation — the selector did not re-point"


def test_the_backend_implements_exactly_the_contract():
    """Six functions, not thirty. A seventh here means the contract grew without a decision."""
    for name in CONTRACT:
        assert callable(getattr(desktop_win, name, None)), f"{name} is missing from the backend"


def test_health_has_the_same_keys_as_the_x11_backend():
    """`/api/health` and the frontend read these by name, so the shape is part of the contract."""
    h = desktop_win.x11_health()
    assert set(h) == {"ok", "reason", "display", "detail"}
    assert isinstance(h["ok"], bool)
    if not h["ok"]:
        assert h["detail"], "an unhealthy backend must say WHY — that is what the banner shows"


# ─────────────────────────────────────────────────────────────────────────────────────────────
# The regression that matters
# ─────────────────────────────────────────────────────────────────────────────────────────────
def test_the_process_family_never_reaches_the_desktop_shell():
    """⚠️ THE BUG THIS BACKEND SHIPPED WITH FOR ONE HOUR, PINNED SO IT CANNOT COME BACK.

    `_pid_family` originally walked `psutil.Process.parents()` unbounded to find the terminal host
    that owns a console's HWND — which is a real requirement. But on Windows EVERY interactive
    process descends from `explorer.exe`, so the family of any session included the desktop shell,
    and therefore Program Manager, every File Explorer window, and — through the shared Windows
    Terminal ancestor — other live Claude sessions' windows.

    MEASURED 2026-08-30: the matcher returned an explorer window first, `focus_session` returned
    True because that window genuinely came to the foreground, and `send_keys_to_session` typed a
    line into the desktop and returned True. Both were honest about what they did and wrong about
    what it was.
    """
    fam = desktop_win._pid_family(os.getpid())
    assert os.getpid() in fam, "the family must at least contain the process itself"
    names = {desktop_win._proc_name(p) for p in fam}
    assert not (names & desktop_win._NEVER_A_TERMINAL), (
        f"the ancestor walk reached the desktop shell: {names & desktop_win._NEVER_A_TERMINAL}. "
        "Every window explorer.exe owns is now a candidate for typing into."
    )


def test_a_tabbed_host_with_a_disagreeing_title_refuses(monkeypatch):
    """Windows Terminal puts many sessions in ONE window, so owning-pid identifies the window and
    not the session. The window title tracks the ACTIVE tab — the only evidence available from
    outside the process — so when it disagrees the honest answer is "I cannot reach that tab"."""
    monkeypatch.setattr(desktop_win, "_enumerate",
                        lambda: [(4242, 999, "some other session")])
    monkeypatch.setattr(desktop_win, "_pid_family", lambda pid: {999} if pid else set())
    monkeypatch.setattr(desktop_win, "_proc_name", lambda pid: "windowsterminal.exe")

    hw = desktop_win._windows_for_session(pid=None, terminal_pid=999,
                                          title="the session I actually want", window_title=None)
    assert hw == [], "typed into whichever tab happened to be in front"


def test_a_tabbed_host_whose_title_agrees_is_accepted(monkeypatch):
    """The other half — the guard must not be so strict that it refuses the correct window."""
    monkeypatch.setattr(desktop_win, "_enumerate",
                        lambda: [(4242, 999, "claude — my-project")])
    monkeypatch.setattr(desktop_win, "_pid_family", lambda pid: {999} if pid else set())
    monkeypatch.setattr(desktop_win, "_proc_name", lambda pid: "windowsterminal.exe")

    hw = desktop_win._windows_for_session(pid=None, terminal_pid=999,
                                          title="my-project", window_title=None)
    assert hw == [4242]


def test_an_ambiguous_title_is_not_a_match(monkeypatch):
    """Two windows with the same title is not 'probably the first one'."""
    monkeypatch.setattr(desktop_win, "_enumerate",
                        lambda: [(1, 111, "claude — proj"), (2, 222, "claude — proj")])
    monkeypatch.setattr(desktop_win, "_pid_family", lambda pid: set())
    monkeypatch.setattr(desktop_win, "_proc_name", lambda pid: "conhost.exe")

    assert desktop_win._windows_for_session(pid=None, terminal_pid=None,
                                            title="claude — proj", window_title=None) == []


# ─────────────────────────────────────────────────────────────────────────────────────────────
# Refusal paths — every one of these must be False, never an exception and never True
# ─────────────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("call", [
    lambda: desktop_win.focus_session(terminal_pid=None, title=None),
    lambda: desktop_win.send_keys_to_session(text="x", terminal_pid=None, title=None),
    lambda: desktop_win.send_key_to_session(key="Escape", terminal_pid=None, title=None),
    lambda: desktop_win.send_key_sequence(keys=["1"], terminal_pid=None, title=None),
])
def test_an_unidentifiable_session_returns_false(call):
    assert call() is False


def test_an_unknown_key_name_sends_nothing():
    """The caller for this is dismissing the /rc modal, where the neighbouring option is
    'Disconnect this session'. An approximate keystroke there is destructive."""
    assert desktop_win.send_key_to_session(key="Frobnicate", terminal_pid=None) is False


def test_one_bad_name_rejects_the_whole_sequence():
    """A picker driven halfway is a live session left in an arbitrary state."""
    assert desktop_win.send_key_sequence(keys=["1", "Frobnicate", "Return"], terminal_pid=None) is False


def test_a_short_sendinput_count_is_a_failure(monkeypatch):
    """SendInput returns how many events it ACCEPTED. UIPI, a low-level hook or a locked session
    can truncate that silently, and reporting success on a short count is the 2026-08-05 lie."""
    events = desktop_win._vk_events(0x0D)
    monkeypatch.setattr(desktop_win._user32, "SendInput", lambda n, arr, sz: n - 1)
    assert desktop_win._send(events) is False


def test_no_events_is_not_a_success():
    assert desktop_win._send([]) is False


# ─────────────────────────────────────────────────────────────────────────────────────────────
# The real thing. Opt-in: it steals focus and types.
# ─────────────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.skipif(
    os.environ.get("CONDUCTOR_DESKTOP_E2E") != "1",
    reason="steals focus and types into a real window; set CONDUCTOR_DESKTOP_E2E=1 to run it",
)
def test_end_to_end_the_keystrokes_actually_arrive(tmp_path):
    """The only test here that can prove the backend WORKS rather than that it refuses correctly.

    Everything above pins honest failure. This spawns a real console, types into it, and checks
    what the console RECEIVED on stdin — because the whole contract is that the return value has
    to match what happened in the world, and no amount of mocking can establish that.
    """
    import subprocess
    import time

    out = tmp_path / "typed.txt"
    script = tmp_path / "target.py"
    script.write_text(
        "import ctypes,sys\n"
        "from pathlib import Path\n"
        "p=Path(sys.argv[1])\n"
        "ctypes.WinDLL('kernel32').SetConsoleTitleW('conductor-e2e-target')\n"
        "p.write_text('WAITING\\n',encoding='utf-8')\n"
        "try: line=input()\n"
        "except EOFError: line='<EOF>'\n"
        "p.write_text('GOT:'+line+'\\n',encoding='utf-8')\n",
        encoding="utf-8")

    proc = subprocess.Popen([sys.executable, str(script), str(out)], creationflags=0x00000010)
    try:
        for _ in range(60):
            if out.exists() and out.read_text(encoding="utf-8").startswith("WAITING"):
                break
            time.sleep(0.1)

        # Refuse to type unless every matched window is provably the target — the same discipline
        # the backend itself applies, applied to the test so a matching bug cannot make it
        # type into the developer's own session.
        hw = desktop_win._windows_for_session(pid=None, terminal_pid=proc.pid,
                                              title="conductor-e2e-target", window_title=None)
        titles = {t for h, _p, t in desktop_win._enumerate() if h in hw}
        assert hw and all("conductor-e2e-target" in t for t in titles), \
            f"matcher resolved to windows that are not the target: {titles}"

        msg = "conductor windows backend end to end"
        sent = desktop_win.send_keys_to_session(text=msg, terminal_pid=proc.pid,
                                                title="conductor-e2e-target")
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pass
        got = out.read_text(encoding="utf-8").strip()
        landed = got == f"GOT:{msg}"
        assert sent == landed, (
            f"the return value disagreed with reality: returned {sent}, target received {got!r}")
        assert landed, "the keystrokes never arrived"
    finally:
        if proc.poll() is None:
            proc.kill()
