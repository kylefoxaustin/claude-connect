"""WindowMapper — wmctrl-based PID→window resolution and `claude:<name>` focus.

Best-effort; if wmctrl isn't installed the focus action returns False and the
frontend just dims the focus button.
"""

from __future__ import annotations

import logging
import re
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
# Pause between raw keystrokes driving the AskUserQuestion picker. The picker
# re-renders on every key (toggling a checkbox, switching tabs); pressing faster
# than it redraws is how you end up submitting a selection you never made.
_KEY_STEP_S = 0.35


def wmctrl_available() -> bool:
    return shutil.which("wmctrl") is not None


def xdotool_available() -> bool:
    return shutil.which("xdotool") is not None


def gdbus_available() -> bool:
    return shutil.which("gdbus") is not None


# A tilix terminal UUID, as stamped into TILIX_ID — eight-four-four-four-twelve
# lowercase hex. We validate before interpolating it into the gdbus parameter so
# a malformed environ value can't confuse the D-Bus argument parser.
_TILIX_UUID_RE = re.compile(r"\A[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\Z")


def _parse_tilix_id(environ: bytes) -> str | None:
    """Extract the ``TILIX_ID`` UUID from a process's NUL-separated environ.

    Tilix stamps every tile's child shell with ``TILIX_ID=<terminal-uuid>``, so
    a Claude process started in a tilix tile carries the exact handle of the tile
    it lives in. Returns the UUID if present and well-formed, else None."""
    for entry in environ.split(b"\0"):
        if entry.startswith(b"TILIX_ID="):
            val = entry[len(b"TILIX_ID="):].decode("utf-8", "replace")
            return val if _TILIX_UUID_RE.match(val) else None
    return None


def tilix_id_for_pid(pid: int | None) -> str | None:
    """Read ``TILIX_ID`` from ``/proc/<pid>/environ`` (the tilix tile UUID)."""
    if pid is None:
        return None
    try:
        with open(f"/proc/{pid}/environ", "rb") as f:
            return _parse_tilix_id(f.read())
    except OSError:
        return None


def tilix_activate_terminal(uuid: str) -> bool:
    """Focus a tilix tile by UUID via the ``activate-terminal`` gaction.

    Tilix raises the hosting window *and* switches to the exact tile — an exact
    PID→tile focus that sidesteps X11-title matching. Title matching is ambiguous
    for combined/tiled tilix windows (only the active tile's title is on the
    window) and lets a stray same-named terminal hijack focus; this avoids both.
    Returns True if the action dispatched."""
    if not gdbus_available() or not _TILIX_UUID_RE.match(uuid):
        return False
    try:
        r = subprocess.run(
            [
                "gdbus", "call", "--session",
                "--dest", "com.gexperts.Tilix",
                "--object-path", "/com/gexperts/Tilix",
                "--method", "org.gtk.Actions.Activate",
                "activate-terminal", f"[<'{uuid}'>]", "{}",
            ],
            capture_output=True, timeout=3.0,
        )
        return r.returncode == 0
    except (subprocess.TimeoutExpired, OSError) as e:
        log.debug("tilix activate-terminal failed: %s", e)
        return False


def _active_window_id() -> int | None:
    """X11 id of the currently-focused window, via ``xdotool getactivewindow``."""
    try:
        out = subprocess.run(
            ["xdotool", "getactivewindow"], capture_output=True, text=True, timeout=2.0,
        )
        return int(out.stdout.strip()) if out.returncode == 0 else None
    except (subprocess.TimeoutExpired, OSError, ValueError):
        return None


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


def _token_match(windows: list[tuple[int, int, str]], *hints: str | None) -> int | None:
    """Window whose title shares the most word-tokens with the hints.

    Handles auto-generated topic titles that don't substring-match the session
    name — e.g. session ``rk182x-evk-setup-guide`` vs window
    ``Build Rockchip RK182X EVK setup guide``: the tokens rk182x/evk/setup/guide
    all hit, so the right window wins over unrelated siblings. Returns None if
    nothing scores (no false positive)."""
    toks: set[str] = set()
    for h in hints:
        if not h:
            continue
        for t in re.split(r"[^a-z0-9]+", h.lower()):
            if len(t) >= 2:
                toks.add(t)
    if not toks:
        return None
    best_wid, best_score = None, 0
    for wid, _pid, title in windows:
        tl = title.lower()
        score = sum(1 for t in toks if t in tl)
        if score > best_score:
            best_wid, best_score = wid, score
    return best_wid if best_score > 0 else None


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
      4. Word-token overlap (handles reworded auto-topic titles).
      5. The terminal's sole window — only if it owns exactly one (else give up
         rather than focus the wrong sibling).
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

    # Token-overlap match (scoped to this terminal's windows) — catches reworded
    # auto-topic titles that don't substring-match the session name.
    wid = _token_match(search, window_title, title)
    if wid is not None:
        return wid

    # Last resort: only when the terminal owns exactly one window. With several
    # sibling windows and no title/token match, refuse to guess (focusing the
    # wrong session is worse than doing nothing).
    if len(term_windows) == 1:
        return term_windows[0][0]
    return None


def focus_session(
    *,
    pid: int | None = None,
    terminal_pid: int | None,
    title: str | None = None,
    window_title: str | None = None,
) -> bool:
    """Focus a session's terminal window. Returns True on success.

    Exact path first: if the session lives in a tilix tile, focus that tile by
    its ``TILIX_ID`` — this raises the right window and selects the right tile,
    even in a combined/tiled window where X11-title matching can't (the tile's
    title isn't on the window unless it's already the active one). Falls back to
    wmctrl title matching for non-tilix terminals or when tilix D-Bus is absent.
    """
    tilix_id = tilix_id_for_pid(pid)
    if tilix_id and tilix_activate_terminal(tilix_id):
        return True
    if not wmctrl_available():
        return False
    wid = _resolve_window(
        terminal_pid=terminal_pid, title=title, window_title=window_title,
    )
    return wid is not None and _raise_window(wid)


def _focus_and_get_window(
    *,
    pid: int | None,
    terminal_pid: int | None,
    title: str | None,
    window_title: str | None,
) -> int | None:
    """Raise a session's window and return its X11 id, or None.

    Exact path first (tilix tile by ``TILIX_ID``), falling back to wmctrl title
    matching. Shared by the text and raw-key senders.
    """
    tilix_id = tilix_id_for_pid(pid)
    if tilix_id and tilix_activate_terminal(tilix_id):
        time.sleep(_FOCUS_SETTLE_S)   # let the tile take focus before we read it
        wid = _active_window_id()
        if wid is not None:
            return wid
    if not wmctrl_available():
        return None
    wid = _resolve_window(
        terminal_pid=terminal_pid, title=title, window_title=window_title,
    )
    if wid is None or not _raise_window(wid):
        return None
    return wid


def send_key_sequence(
    *,
    keys: list[str],
    pid: int | None = None,
    terminal_pid: int | None,
    title: str | None = None,
    window_title: str | None = None,
) -> bool:
    """Send raw key *names* (``"1"``, ``"Right"``, ``"Return"``) to a session's window.

    This drives Claude Code's interactive ``AskUserQuestion`` picker, which is a
    keyboard widget and not a text field: digits toggle options, ``Right`` opens the
    review tab, ``Return`` confirms. Typing the answer as *text* would not work — while
    a picker is open the terminal routes typed characters into the picker's free-text
    "Other" field, silently turning an answer into a new option.

    Deliberately does NOT send the ctrl+u "clear the input line" that
    ``send_keys_to_session`` opens with: there is no input line here, and ctrl+u inside
    a picker is not a no-op we have any reason to trust.

    Returns True if every keystroke dispatched.
    """
    if not xdotool_available() or not keys:
        return False
    wid = _focus_and_get_window(
        pid=pid, terminal_pid=terminal_pid, title=title, window_title=window_title,
    )
    if wid is None:
        return False
    try:
        subprocess.run(
            ["xdotool", "windowactivate", "--sync", str(wid)],
            check=True, capture_output=True, timeout=3.0,
        )
        time.sleep(_FOCUS_SETTLE_S)
        for key in keys:
            # One key per call: the picker re-renders between keystrokes and a batched
            # `xdotool key a b c` can outrun the redraw.
            subprocess.run(
                ["xdotool", "key", "--clearmodifiers", key],
                check=True, capture_output=True, timeout=3.0,
            )
            time.sleep(_KEY_STEP_S)
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as e:
        log.debug("send_key_sequence failed: %s", e)
        return False


def send_keys_to_session(
    *,
    text: str,
    pid: int | None = None,
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
    if not xdotool_available():
        return False
    # Exact path: focus the precise tilix tile by TILIX_ID, then type into the
    # window it just raised — so the keystrokes can't land in a stray same-named
    # terminal the way title matching might. Falls back to wmctrl resolution.
    wid: int | None = None
    tilix_id = tilix_id_for_pid(pid)
    if tilix_id and tilix_activate_terminal(tilix_id):
        time.sleep(_FOCUS_SETTLE_S)  # let the tile take focus before we read it
        wid = _active_window_id()
    if wid is None:
        if not wmctrl_available():
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
