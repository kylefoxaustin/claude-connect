"""X11 reachability — the meta-check.

The bug these guard (Kyle, 2026-08-05, found by a reboot): the systemd service came up with NO
DISPLAY/XAUTHORITY — `systemctl --user import-environment` does not retroactively patch a running
unit — and **wmctrl and xdotool print "Cannot open display" to stderr and EXIT 0**. So every
window call succeeded as far as Conductor could tell and did nothing: a relaunch logged
"2/2 launched" while no window spawned, and the wind-down before it reached ~2 of 25 sessions.

The tests deliberately drive the REAL failure shape — a fake tool that exits 0 while complaining
to stderr — rather than asserting our description of it. A test that only checks a non-zero exit
code would have passed against the broken code, which is the whole reason this file exists.
"""

from __future__ import annotations


import subprocess
import sys
from pathlib import Path

import pytest

from conductor import x11 as w


@pytest.fixture(autouse=True)
def _clear_env_cache():
    """The resolved-display cache is module state; a leak between tests would make one test's
    discovery satisfy the next one's assertion."""
    w._x11_env_cache = (0.0, None)
    yield
    w._x11_env_cache = (0.0, None)


def _fake_tool(tmp_path: Path, name: str, *, body: str) -> Path:
    """Write an executable stub onto a PATH dir."""
    p = tmp_path / name
    p.write_text("#!/bin/sh\n" + body + "\n")
    p.chmod(0o755)
    return p


# ⚠️ WINDOWS, and the reason is in the process loader rather than in anything this file tests.
#
# `_fake_tool` writes a `#!/bin/sh` stub with no extension. `CreateProcess` does not read a
# shebang and — unlike a shell — does not consult PATHEXT: given "wmctrl" it appends `.exe` and
# nothing else. So a stub named `wmctrl`, `wmctrl.sh` or `wmctrl.cmd` is equally unreachable
# through `subprocess.run(["wmctrl", ...])`, and every test below died with FileNotFoundError
# from inside subprocess BEFORE reaching its assertion. That read as "the X11 code fails on
# Windows" while none of it was being exercised.
#
# A `.cmd` shim delegating to Git Bash was tried first and does not work, for the PATHEXT reason
# above. Making it work would mean changing `_run_x` to resolve tools through `shutil.which()`
# — which WOULD find a `.cmd` — but that is skippy's production file, the change buys Linux
# nothing, and on Windows `x11.py` is not the backend at all any more (`desktop_win.py` is), so
# it would be product code edited solely to move a test from red to green. Declined.
#
# What is NOT skipped, and it is the part that matters: `_display_failed` — the actual stderr
# sniffing these tests exist to guard — is covered by the four parametrized unit tests above,
# which pass on Windows. What is skipped is only the subprocess PLUMBING around it.
_needs_a_path_executable = pytest.mark.skipif(
    sys.platform == "win32",
    reason="fixture needs a shebang stub resolvable by name; CreateProcess only appends .exe, "
           "so the sh stub is unreachable — _display_failed itself is still covered here",
)


# The exact observed behaviour of wmctrl/xdotool with no reachable display.
_LIES_ABOUT_SUCCESS = 'echo "Cannot open display." >&2\nexit 0'


# ── the failure is on stderr, not in the exit code ────────────────────────────────────────

@pytest.mark.parametrize("msg", [
    "Cannot open display.",
    "Error: Can't open display: (null)",
    "xdotool: unable to open display",
    "No protocol specified",
])
def test_display_failure_detected_from_stderr(msg):
    r = subprocess.CompletedProcess(args=["x"], returncode=0, stdout="", stderr=msg)
    assert w._display_failed(r) is True


def test_healthy_output_is_not_a_display_failure():
    r = subprocess.CompletedProcess(args=["x"], returncode=0, stdout="0x1 0 skippy Conductor", stderr="")
    assert w._display_failed(r) is False


def test_unrelated_stderr_is_not_a_display_failure():
    """Don't cry display-down over an ordinary tool error — that would be a false alarm on the
    loudest banner we ship, which is how an alarm gets ignored."""
    r = subprocess.CompletedProcess(args=["x"], returncode=1, stdout="", stderr="wmctrl: no such window")
    assert w._display_failed(r) is False


# ── _run_x turns the lie into a real failure ──────────────────────────────────────────────

@_needs_a_path_executable
def test_run_x_forces_nonzero_when_the_tool_exits_zero_on_a_dead_display(tmp_path, monkeypatch):
    """THE REGRESSION. `wmctrl -i -a` exiting 0 against no display is what made `_raise_window`
    return True for a raise that never happened."""
    _fake_tool(tmp_path, "wmctrl", body=_LIES_ABOUT_SUCCESS)
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.setattr(w, "_discover_display_env", lambda: None)

    r = w._run_x(["wmctrl", "-l"])
    assert r.returncode != 0, "a call that could not open a display must not look successful"


@_needs_a_path_executable
def test_run_x_raises_for_check_true_callers(tmp_path, monkeypatch):
    """Callers that use check=True must see the failure through their existing except clause."""
    _fake_tool(tmp_path, "xdotool", body=_LIES_ABOUT_SUCCESS)
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.setattr(w, "_discover_display_env", lambda: None)

    with pytest.raises(subprocess.CalledProcessError):
        w._run_x(["xdotool", "key", "Return"], check=True)


@_needs_a_path_executable
def test_run_x_leaves_a_healthy_call_alone(tmp_path, monkeypatch):
    _fake_tool(tmp_path, "wmctrl", body='echo "0x04e00007  0 skippy Project claude connect"')
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setenv("DISPLAY", ":0")

    r = w._run_x(["wmctrl", "-lp"])
    assert r.returncode == 0
    assert "claude connect" in r.stdout


@_needs_a_path_executable
def test_raise_window_reports_failure_on_a_dead_display(tmp_path, monkeypatch):
    """End-to-end on the function whose True return was the lie."""
    _fake_tool(tmp_path, "wmctrl", body=_LIES_ABOUT_SUCCESS)
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.setattr(w, "_discover_display_env", lambda: None)

    assert w._raise_window(0x04E00007) is False


@_needs_a_path_executable
def test_list_windows_is_empty_but_the_call_is_not_silent(tmp_path, monkeypatch, caplog):
    """An empty window list reads to every caller as 'this session has no window'. When the real
    cause is an unreachable display that must be logged at WARNING, not swallowed at debug."""
    _fake_tool(tmp_path, "wmctrl", body=_LIES_ABOUT_SUCCESS)
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.setattr(w, "_discover_display_env", lambda: None)

    with caplog.at_level("WARNING"):
        assert w.list_windows() == []
    assert any(r.levelname == "WARNING" for r in caplog.records)


# ── the display is resolved at CALL TIME, and it self-heals ───────────────────────────────

def test_display_is_borrowed_when_our_process_has_none(monkeypatch):
    """The systemd-service case: the unit inherited no DISPLAY, so we take one from a live X
    client instead of being permanently blind."""
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.setattr(w, "_discover_display_env",
                        lambda: {"DISPLAY": ":0", "XAUTHORITY": "/run/user/1000/gdm/Xauthority"})

    env = w.x11_env(force=True)
    assert env["DISPLAY"] == ":0"
    assert env["XAUTHORITY"] == "/run/user/1000/gdm/Xauthority"


def test_our_own_display_wins_over_discovery(monkeypatch):
    """Interactive / native-app case: if we HAVE a display it is authoritative — never let a
    stray donor process move us onto a different X session than the one we were started on."""
    monkeypatch.setenv("DISPLAY", ":1")
    monkeypatch.setattr(w, "_discover_display_env", lambda: {"DISPLAY": ":9"})

    assert w.x11_env(force=True)["DISPLAY"] == ":1"


@_needs_a_path_executable
def test_a_moved_display_self_heals_without_a_restart(tmp_path, monkeypatch):
    """THE DRIFT CASE. skippy's display has been both :1 and :0 across reboots. A cached value
    that has gone stale must be re-discovered on the failing call, not held until someone
    restarts the service — inheriting once is the original bug."""
    # Succeeds only for DISPLAY=:0; the cache is primed with the stale :1.
    _fake_tool(tmp_path, "xdotool", body=(
        'if [ "$DISPLAY" = ":0" ]; then echo 81825405; exit 0; fi\n'
        'echo "Cannot open display." >&2\nexit 0'
    ))
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.delenv("DISPLAY", raising=False)
    w._x11_env_cache = (float("inf"), {"DISPLAY": ":1"})     # stale, and "fresh" by TTL
    monkeypatch.setattr(w, "_discover_display_env", lambda: {"DISPLAY": ":0"})

    r = w._run_x(["xdotool", "getactivewindow"])
    assert r.returncode == 0, "the retry must re-discover the moved display"
    assert r.stdout.strip() == "81825405"


# ── the alarm itself ──────────────────────────────────────────────────────────────────────

@_needs_a_path_executable
def test_health_reports_unreachable(tmp_path, monkeypatch):
    _fake_tool(tmp_path, "xdotool", body=_LIES_ABOUT_SUCCESS)
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.setattr(w, "_discover_display_env", lambda: None)

    h = w.x11_health()
    assert h["ok"] is False
    assert h["reason"] == "no_display"
    assert h["detail"], "an alarm with no explanation is a red dot nobody can act on"


@_needs_a_path_executable
def test_health_reports_ok(tmp_path, monkeypatch):
    _fake_tool(tmp_path, "xdotool", body="echo 81825405")
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setenv("DISPLAY", ":0")

    h = w.x11_health()
    assert h["ok"] is True
    assert h["display"] == ":0"


def test_health_reports_missing_xdotool(monkeypatch):
    monkeypatch.setattr(w, "xdotool_available", lambda: False)
    h = w.x11_health()
    assert h["ok"] is False
    assert h["reason"] == "no_xdotool"
