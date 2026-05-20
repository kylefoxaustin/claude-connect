"""WindowMapper — wmctrl-based PID→window resolution and `claude:<name>` focus.

Best-effort; if wmctrl isn't installed the focus action returns False and the
frontend just dims the focus button.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import time

log = logging.getLogger(__name__)

# After windowactivate --sync the WM reports the window focused, but a terminal
# widget (VTE/Tilix) that's been unfocused a while needs a moment more before it
# accepts keystrokes — otherwise leading characters are dropped and a partial
# slash command (e.g. "/msg-check" → "/mc…") can fuzzy-match the wrong command.
_FOCUS_SETTLE_S = 0.25
# Per-keystroke delay (ms) for `xdotool type` — slow enough that Claude Code's
# slash-command menu keeps up with each character.
_TYPE_DELAY_MS = "28"
# Pause after typing so the slash menu settles on the full match before Enter.
_PRE_RETURN_S = 0.15


def wmctrl_available() -> bool:
    return shutil.which("wmctrl") is not None


def xdotool_available() -> bool:
    return shutil.which("xdotool") is not None


def list_windows() -> list[tuple[int, int, str]]:
    """Return [(window_id_int, pid, title)] from `wmctrl -lp`. Empty list if unavailable."""
    if not wmctrl_available():
        return []
    try:
        out = subprocess.run(
            ["wmctrl", "-lp"], check=True, capture_output=True, text=True, timeout=2.0,
        ).stdout
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as e:
        log.debug("wmctrl -lp failed: %s", e)
        return []
    rows: list[tuple[int, int, str]] = []
    for line in out.splitlines():
        # Format: <wid> <desktop> <pid> <host> <title...>
        parts = line.split(None, 4)
        if len(parts) < 5:
            continue
        try:
            wid = int(parts[0], 16)
            pid = int(parts[2])
        except ValueError:
            continue
        rows.append((wid, pid, parts[4]))
    return rows


def _raise_window(wid: int) -> bool:
    try:
        r = subprocess.run(
            ["wmctrl", "-i", "-a", f"0x{wid:08x}"], capture_output=True, timeout=2.0,
        )
        return r.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def _best_title_match(windows: list[tuple[int, int, str]], hint: str | None) -> int | None:
    """Window id whose title contains ``hint`` (case-insensitive). When several
    match, prefer the shortest title — the least extra text around the hint, i.e.
    the most specific match (so "keyhole" picks "Project: Keyhole" over
    "Project keyhole-sizer")."""
    if not hint:
        return None
    h = hint.lower()
    matches = [(wid, title) for wid, _pid, title in windows if h in title.lower()]
    if not matches:
        return None
    matches.sort(key=lambda wt: len(wt[1]))
    return matches[0][0]


def _resolve_window(
    *,
    terminal_pid: int | None,
    title: str | None = None,
    window_title: str | None = None,
) -> int | None:
    """Resolve a session's terminal window id (without raising it).

    A single terminal server (tilix, gnome-terminal-server) owns *all* its
    windows, so they share one PID — PID matching alone can't tell them apart.
    We match on the window title instead, scoped to that terminal's windows:

      1. ``claude:<name>`` exact-ish title (the `claude-tracked` wrapper).
      2. ``window_title`` (the session's customTitle, which Claude Code writes
         to the X11 window title) — the reliable key.
      3. ``title`` (summary / project basename) as a looser fallback.
      4. Any window owned by ``terminal_pid`` (ambiguous last resort).
    """
    windows = list_windows()
    # Scope title matching to this terminal's own windows when we can identify
    # them — disambiguates among sibling terminal windows and avoids matching
    # unrelated app windows that happen to share a project name in their title.
    term_windows = [w for w in windows if terminal_pid is not None and w[1] == terminal_pid]
    search = term_windows or windows

    for hint in (window_title, title):
        if hint:
            wid = _best_title_match(windows, f"claude:{hint}")
            if wid is not None:
                return wid

    for hint in (window_title, title):
        wid = _best_title_match(search, hint)
        if wid is not None:
            return wid

    if terminal_pid is not None:
        for wid, pid, _title in windows:
            if pid == terminal_pid:
                return wid
    return None


def focus_session(
    *,
    terminal_pid: int | None,
    title: str | None = None,
    window_title: str | None = None,
) -> bool:
    """Focus a session's terminal window. Returns True on success."""
    if not wmctrl_available():
        return False
    wid = _resolve_window(
        terminal_pid=terminal_pid, title=title, window_title=window_title,
    )
    return wid is not None and _raise_window(wid)


def send_keys_to_session(
    *,
    text: str,
    terminal_pid: int | None,
    title: str | None = None,
    window_title: str | None = None,
) -> bool:
    """Activate a session's window and type ``text`` followed by Enter.

    Used to drive the live Claude session — e.g. inject ``/msg-check`` so the
    real Claude (not a side subprocess) reads the bus. Requires both wmctrl (to
    find/raise the window) and xdotool (to type). VTE/GTK terminals reject
    synthetic keystrokes sent to an unfocused window, so we activate first and
    type via XTEST against the focused window — this steals focus by design.

    Returns True if the keystrokes were dispatched. Best-effort: a False return
    means we couldn't locate/activate the window or a tool was missing.
    """
    if not (wmctrl_available() and xdotool_available()):
        return False
    wid = _resolve_window(
        terminal_pid=terminal_pid, title=title, window_title=window_title,
    )
    if wid is None or not _raise_window(wid):
        return False
    try:
        # windowactivate --sync blocks until the WM reports the window focused;
        # the settle pause then lets the terminal widget actually start accepting
        # input, so no leading characters of `text` are dropped.
        subprocess.run(
            ["xdotool", "windowactivate", "--sync", str(wid)],
            check=True, capture_output=True, timeout=3.0,
        )
        time.sleep(_FOCUS_SETTLE_S)
        # Clear any stray text on the input line first (Ctrl-U = kill-line), so a
        # partial/garbled command can't be assembled from leftover characters.
        subprocess.run(
            ["xdotool", "key", "--clearmodifiers", "ctrl+u"],
            check=True, capture_output=True, timeout=3.0,
        )
        subprocess.run(
            ["xdotool", "type", "--clearmodifiers", "--delay", _TYPE_DELAY_MS, "--", text],
            check=True, capture_output=True, timeout=8.0,
        )
        time.sleep(_PRE_RETURN_S)
        subprocess.run(
            ["xdotool", "key", "Return"],
            check=True, capture_output=True, timeout=3.0,
        )
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as e:
        log.debug("send_keys_to_session failed: %s", e)
        return False
