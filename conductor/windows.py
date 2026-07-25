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
# tilix's activate-terminal (D-Bus) is ASYNC. We watch getactivewindow only to detect that
# focus MOVED off the previous window (measured live: ~0.5–0.75s), then settle before typing.
_FOCUS_POLL_TIMEOUT_S = 2.0
_FOCUS_POLL_STEP_S = 0.1
_TILE_SETTLE_S = 0.4

# A human actively at the keyboard/mouse within this long ⇒ DEFER injection. Conductor types into
# terminals, and doing so while a person is driving the same X session races their live focus — the
# keystrokes can split into whatever tile they just clicked (Kyle, 2026-07-25: a "push approved"
# notice split across two Tilix panes, half landing on his shell prompt). No window-level guard can
# catch this: panes share one X11 window, so the mis-delivery check is blind to which pane is focused.
_HUMAN_ACTIVE_MS = 4000


def _mutter_idle_ms() -> int | None:
    """Milliseconds since the last human keyboard/mouse input, via GNOME Mutter's IdleMonitor over
    D-Bus (no new dependency — dbus-send ships with the desktop). Returns None if it can't be read
    (no Mutter, no session bus) — the caller treats that as 'can't tell, proceed', so this is a guard
    that helps where it can and never blocks the fleet on a box it can't measure."""
    try:
        r = subprocess.run(
            ["dbus-send", "--session", "--print-reply", "--dest=org.gnome.Mutter.IdleMonitor",
             "/org/gnome/Mutter/IdleMonitor/Core", "org.gnome.Mutter.IdleMonitor.GetIdletime"],
            capture_output=True, text=True, timeout=2.0)
        if r.returncode != 0:
            return None
        m = re.search(r"uint64\s+(\d+)", r.stdout)
        return int(m.group(1)) if m else None
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def human_recently_active(threshold_ms: int = _HUMAN_ACTIVE_MS) -> bool:
    """True iff a human used the machine within ``threshold_ms``. Best-effort: unknown ⇒ False
    (proceed), so this never wedges injection on a host where idle time can't be read."""
    idle = _mutter_idle_ms()
    return idle is not None and idle < threshold_ms


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


def _active_window_name() -> str | None:
    """Title of the currently-focused window (``getactivewindow getwindowname``). May be empty
    for a tilix tile CLIENT window that carries no title of its own — that's why callers treat a
    MISSING name as 'can't verify' (accept) but a MISMATCHING name as 'wrong window' (reject)."""
    try:
        out = subprocess.run(
            ["xdotool", "getactivewindow", "getwindowname"],
            capture_output=True, text=True, timeout=2.0,
        )
        return out.stdout.strip() if out.returncode == 0 else None
    except (subprocess.TimeoutExpired, OSError):
        return None


def _active_is_not_target(title: str | None, window_title: str | None) -> bool:
    """True only when the active window is CONFIRMED to be a DIFFERENT session than the target.

    The tilix-path counterpart to ``_window_belongs_to_target`` — the guard that path was missing
    (Kyle, 2026-07-23: a push notice for 95emulator was typed into qualcomm's active terminal).

    We compare ONLY against the target's ``window_title`` — the field that, by construction,
    *matches the X11 window title* (the ``/rename`` custom title, e.g. ``Project 95Qemu``). We do
    NOT match the general ``title``/tag: window titles are inconsistent (a session with no custom
    title shows its cwd, e.g. ``kyle@skippy: ~/…/qualcomm/results``), so tag-matching would
    false-refuse and break the common /msg-check path. So: if the target has a window_title and
    the active window has a title that does NOT contain it, it's a different window — refuse. If
    either is missing/unmatchable, we can't confirm a mismatch, so we DON'T block (the focus-moved
    check is the guard there). Note this still catches the reported bug: the TARGET's title
    (95Qemu) is absent from the WRONG window's name (qualcomm's cwd), so it correctly refuses."""
    wt = (window_title or "").strip()
    if not wt:
        return False                      # no reliable X11 title for the target -> can't confirm
    name = _active_window_name()
    if not name:
        return False                      # no active-window title -> can't confirm a mismatch
    return wt.lower() not in name.lower()  # target's title absent from active window -> different


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


def _window_belongs_to_target(
    wid: int, title: str | None, window_title: str | None,
) -> bool:
    """Does window ``wid`` actually belong to the target session?

    The guard against MIS-DELIVERY. ``send_keys_to_session`` used to activate a tilix tile
    (an async D-Bus call) and then trust ``getactivewindow`` — but when the activate hasn't
    landed within the settle sleep, ``getactivewindow`` returns the PREVIOUSLY focused window,
    and we typed there. That is how mcxn's push verdict was typed into 91emulator's terminal.

    So before typing a single key we confirm the window we're about to type into carries the
    target's own title, using the SAME matchers ``_resolve_window`` trusts. If ``wid`` can't be
    found or matches no hint, we FAIL CLOSED (return False) — a keystroke in the wrong terminal
    is unrecoverable, so "don't type, retry later" is always the safe answer.
    """
    titles = [t for w, _pid, t in list_windows() if w == wid]
    if not titles:
        return False                      # can't see the window -> can't verify -> don't type
    tl = titles[0].lower()
    # FULL-HINT substring ONLY. A partial/token match is unsafe here: two sessions can share a
    # token ("simtest-a"/"simtest-b" both contain "simtest"; "keyhole"/"keyhole-sizer" both
    # contain "keyhole"), and a shared token would confirm the WRONG window — which the live
    # smoke test caught doing exactly that (a stale-focused simtest-b verified as simtest-a).
    # For a safety verify, a false negative just means "refuse and retry"; a false positive
    # means a keystroke in the wrong terminal. So require the whole hint to appear. Conductor's
    # stored window_title IS the real X11 title, so the full hint matches in the normal case.
    for hint in (window_title, title):
        if hint and hint.lower() in tl:
            return True
    return False


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


def _focus_session_input(
    *,
    pid: int | None,
    terminal_pid: int | None,
    title: str | None,
    window_title: str | None,
) -> bool:
    """Place keyboard focus on a session's terminal INPUT — correctly, for BOTH the text sender
    and the AskUserQuestion picker. Returns True if focus was placed; False if it could not be
    confirmed (the caller must NOT type on a False).

    Shared by ``send_keys_to_session`` and ``send_key_sequence`` so the picker-answer path can
    never drift from the fixed text path again — that drift is exactly the bug that made a phone
    answer to an AskUserQuestion vanish (Conductor logged it as sent, it never reached the tile).

    TILIX: activate the tile by its UUID (read from the target's own ``/proc/<pid>/environ``, so it
    is the RIGHT tile by construction — no title ambiguity, no mis-delivery), then wait out the
    async focus change and settle. We do NOT read ``getactivewindow`` to identify the window (it
    returns unmatchable client ids) and we do NOT ``windowactivate`` (it raises the window but does
    not give a tilix TILE keyboard focus — keys vanish). NON-TILIX: resolve by title, verify it is
    the target's window, and ``windowactivate``."""
    # A human actively driving the machine will race us for keyboard focus — and if they steal it
    # mid-type (e.g. clicking another Tilix pane over RustDesk), our keystrokes split into their
    # window. No window-level check can see that (panes share one X11 window), so we refuse UP FRONT:
    # don't type while a person is active; the caller retries once they go idle (same as the busy
    # guard). This is the only guard that catches pane-level mis-delivery, because it never competes.
    if human_recently_active():
        log.debug("a human is active at the machine — deferring injection to avoid a focus race")
        return False
    tilix_id = tilix_id_for_pid(pid)
    if tilix_id:
        before = _active_window_id()
        if not tilix_activate_terminal(tilix_id):
            return False
        deadline = time.monotonic() + _FOCUS_POLL_TIMEOUT_S
        moved = False
        while time.monotonic() < deadline:
            if _active_window_id() != before:
                moved = True
                break                       # focus has moved off the previous window
            time.sleep(_FOCUS_POLL_STEP_S)
        # THE FIX (Kyle, 2026-07-23). This path used to `return True` here unconditionally — so if
        # the async activate never actually moved focus (target window minimised, or the user had
        # switched to ANOTHER session's terminal in the meantime), we'd fall through and type into
        # whatever window WAS focused. That is exactly how a push notice for 95emulator landed in
        # qualcomm's active terminal. Two guards now, both fail CLOSED (don't type, retry later):
        #   1. focus must actually MOVE off the previously-active window, and
        #   2. the now-active window must not be CONFIRMED to be a different session.
        if not moved:
            log.warning("tilix activate did not move focus to the target — refusing to type "
                        "(it would land in the currently-active window)")
            return False
        time.sleep(_TILE_SETTLE_S)          # let the tile's widget start accepting input
        if _active_is_not_target(title, window_title):
            log.warning("active window is a DIFFERENT session than the target (%s / %s) — "
                        "refusing to type", window_title, title)
            return False
        return True

    if not wmctrl_available():
        return False
    wid = _resolve_window(terminal_pid=terminal_pid, title=title, window_title=window_title)
    if wid is None or not _raise_window(wid):
        return False
    if not _window_belongs_to_target(wid, title, window_title):
        log.warning("refusing to focus window 0x%x — its title does not match the target "
                    "session (%s / %s)", wid, window_title, title)
        return False
    try:
        subprocess.run(["xdotool", "windowactivate", "--sync", str(wid)],
                       check=True, capture_output=True, timeout=3.0)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as e:
        log.debug("windowactivate failed: %s", e)
        return False
    time.sleep(_FOCUS_SETTLE_S)
    return True


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
    # Focus the tile via the SHARED helper — the old path used getactivewindow + windowactivate,
    # which does not give a tilix tile keyboard focus, so a phone answer to an AskUserQuestion was
    # logged as sent and never landed in the picker.
    if not _focus_session_input(
        pid=pid, terminal_pid=terminal_pid, title=title, window_title=window_title,
    ):
        return False
    try:
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
    if not _focus_session_input(
        pid=pid, terminal_pid=terminal_pid, title=title, window_title=window_title,
    ):
        return False
    return _type_into_focused_window(text, title=title, window_title=window_title)


def _type_into_focused_window(
    text: str, *, title: str | None = None, window_title: str | None = None,
) -> bool:
    """Ctrl-U (clear the line), type ``text``, then Return — into whatever window currently has
    keyboard focus. The caller focuses the RIGHT tile first; as a LAST line of defence (the focus
    settle leaves a small window in which the user could switch terminals) we re-confirm the
    active window isn't a confirmed-different session immediately before the first keystroke."""
    try:
        time.sleep(_FOCUS_SETTLE_S)  # let the widget start accepting input (no dropped leaders)
        if _active_is_not_target(title, window_title):
            log.warning("focus moved to a different session before typing — aborting (would "
                        "mis-deliver to %s / %s)", window_title, title)
            return False
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
        log.debug("type-into-focused failed: %s", e)
        return False
