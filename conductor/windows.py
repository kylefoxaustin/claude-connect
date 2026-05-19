"""WindowMapper — wmctrl-based PID→window resolution and `claude:<name>` focus.

Best-effort; if wmctrl isn't installed the focus action returns False and the
frontend just dims the focus button.
"""

from __future__ import annotations

import logging
import shutil
import subprocess

log = logging.getLogger(__name__)


def wmctrl_available() -> bool:
    return shutil.which("wmctrl") is not None


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


def focus_session(
    *,
    terminal_pid: int | None,
    title: str | None = None,
    window_title: str | None = None,
) -> bool:
    """Focus a session's terminal window. Returns True on success.

    A single terminal server (tilix, gnome-terminal-server) owns *all* its
    windows, so they share one PID — PID matching alone can't tell them apart.
    We match on the window title instead, scoped to that terminal's windows:

      1. ``claude:<name>`` exact-ish title (the `claude-tracked` wrapper).
      2. ``window_title`` (the session's customTitle, which Claude Code writes
         to the X11 window title) — the reliable key.
      3. ``title`` (summary / project basename) as a looser fallback.
      4. Any window owned by ``terminal_pid`` (ambiguous last resort).
    """
    if not wmctrl_available():
        return False

    windows = list_windows()
    # Scope title matching to this terminal's own windows when we can identify
    # them — disambiguates among sibling terminal windows and avoids matching
    # unrelated app windows that happen to share a project name in their title.
    term_windows = [w for w in windows if terminal_pid is not None and w[1] == terminal_pid]
    search = term_windows or windows

    for hint in (window_title, title):
        if hint:
            wid = _best_title_match(windows, f"claude:{hint}")
            if wid is not None and _raise_window(wid):
                return True

    for hint in (window_title, title):
        wid = _best_title_match(search, hint)
        if wid is not None and _raise_window(wid):
            return True

    if terminal_pid is not None:
        for wid, pid, _title in windows:
            if pid == terminal_pid and _raise_window(wid):
                return True
    return False
