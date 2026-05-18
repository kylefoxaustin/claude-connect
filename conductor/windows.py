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


def focus_session(*, terminal_pid: int | None, title_hint: str | None) -> bool:
    """Try to focus the terminal window for a session. Returns True on success.

    Strategy:
      1. If there's a window titled `claude:<title_hint>`, focus by title (precise tab).
      2. Else, find any window whose PID matches `terminal_pid` and raise it.
    """
    if not wmctrl_available():
        return False

    if title_hint:
        target = f"claude:{title_hint}"
        try:
            r = subprocess.run(
                ["wmctrl", "-a", target], capture_output=True, timeout=2.0,
            )
            if r.returncode == 0:
                return True
        except (subprocess.TimeoutExpired, OSError):
            pass

    if terminal_pid is None:
        return False

    for wid, pid, _title in list_windows():
        if pid == terminal_pid:
            try:
                r = subprocess.run(
                    ["wmctrl", "-i", "-a", f"0x{wid:08x}"],
                    capture_output=True, timeout=2.0,
                )
                if r.returncode == 0:
                    return True
            except (subprocess.TimeoutExpired, OSError):
                continue
    return False
