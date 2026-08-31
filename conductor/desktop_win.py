"""The Windows backend for the six-function desktop contract (see ``desktop.py``).

Implements the surface ``main.py`` consumes, against the Win32 API through ``ctypes`` — no new
dependency, matching the reason the msgbox is Python: any machine that can run Conductor can
already run this.

─────────────────────────────────────────────────────────────────────────────────────────────
⚠️ THE RULE THAT OUTRANKS EVERYTHING ELSE IN THIS FILE
─────────────────────────────────────────────────────────────────────────────────────────────
    A backend that cannot act MUST return False. It must never return True having done nothing.

skippy's 2026-08-05 outage is the reason: ``wmctrl`` and ``xdotool`` exit 0 while printing
"Cannot open display", so a 25-session wind-down reported success and did nothing, and fleet
health read green throughout. Windows has its own version of that trap and it is *worse*, because
the API is not a CLI whose exit code you can distrust — it is a function that returns a BOOL you
did not check:

    SetForegroundWindow() RETURNS FALSE ROUTINELY AND IT IS NOT AN ERROR PATH.

Windows refuses foreground changes from a process that does not currently own the foreground
(the foreground-lock rules), and it signals that refusal in a return value that is easy not to
look at. A backend that calls it and returns True has re-created 2026-08-05 exactly.

So every function here ends by **observing the world**, not by trusting a call:

    focus       -> GetForegroundWindow() must actually equal the target HWND afterwards
    typing      -> SendInput() must report the number of events it accepted
    health      -> an EnumWindows call that must really enumerate

`_focus_hwnd` re-reads the foreground window after every attempt and returns what it FOUND, never
what it asked for.

─────────────────────────────────────────────────────────────────────────────────────────────
WHAT THIS BACKEND CANNOT DO, stated here rather than discovered later
─────────────────────────────────────────────────────────────────────────────────────────────
**Tabs are not windows.** Windows Terminal hosts many sessions as TABS inside ONE top-level
window, exactly like the tilix case the X11 backend solves with ``TILIX_ID``. There is no
supported public API to select a specific WT tab from outside the process, so where two sessions
share a Windows Terminal window this backend can raise the window but cannot guarantee the right
TAB is in front. `x11_health()` reports that condition rather than hiding it, and
`_windows_for_session` refuses a match it cannot make uniquely rather than guessing at one — a
keystroke typed into the WRONG live Claude session is worse than a keystroke not typed at all.

A session in its own window (conhost, a dedicated WT window, VS Code's terminal host) is matched
exactly and driven normally.
"""
from __future__ import annotations

import ctypes
import logging
import sys
import time
from ctypes import wintypes

log = logging.getLogger(__name__)

# Importing this module off Windows is a programming error (desktop.py only reaches it on win32),
# but it must not be an *explosion* — a backend that dies at import takes the whole app down on a
# platform where the correct outcome is merely "focus does not work here".
_WIN = sys.platform == "win32"

if _WIN:                                                    # pragma: no cover - platform-gated
    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
else:                                                       # pragma: no cover
    _user32 = _kernel32 = None

# ---- key names -------------------------------------------------------------------------------
# main.py speaks xdotool keysym names ("Return", "Escape", "Right", "1") because that is the
# vocabulary the X11 backend established and the callers were written against. Translating here
# rather than renaming at the call sites keeps the contract identical on both platforms — the same
# reason wmctrl_available keeps its Linux name.
_VK = {
    "Return": 0x0D, "Enter": 0x0D, "KP_Enter": 0x0D,
    "Escape": 0x1B, "Esc": 0x1B,
    "Tab": 0x09, "BackSpace": 0x08, "Delete": 0x2E, "space": 0x20,
    "Up": 0x26, "Down": 0x28, "Left": 0x25, "Right": 0x27,
    "Home": 0x24, "End": 0x23, "Prior": 0x21, "Next": 0x22,
}
_VK.update({str(d): 0x30 + d for d in range(10)})           # "0".."9" -> VK_0..VK_9

_KEYEVENTF_KEYUP = 0x0002
_KEYEVENTF_UNICODE = 0x0004
_INPUT_KEYBOARD = 1
_SW_RESTORE = 9


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]


class _INPUTunion(ctypes.Union):
    _fields_ = [("ki", _KEYBDINPUT), ("_pad", ctypes.c_byte * 32)]


class _INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTunion)]


def _send(events: list[_INPUT]) -> bool:
    """Dispatch keyboard events, and report what the OS ACCEPTED rather than what we sent.

    ``SendInput`` returns the number of events actually inserted into the input stream. A short
    count means something blocked it (UIPI across an integrity level, a low-level hook, a session
    lock). Returning True on a short count would be the 2026-08-05 lie in miniature.
    """
    if not events:
        return False
    n = len(events)
    arr = (_INPUT * n)(*events)
    sent = _user32.SendInput(n, arr, ctypes.sizeof(_INPUT))
    if sent != n:
        log.warning("SendInput accepted %d of %d events (err=%d) — keystrokes were NOT delivered",
                    sent, n, ctypes.get_last_error())
        return False
    return True


def _vk_events(vk: int) -> list[_INPUT]:
    down = _INPUT(type=_INPUT_KEYBOARD, u=_INPUTunion(ki=_KEYBDINPUT(wVk=vk, wScan=0, dwFlags=0,
                                                                     time=0, dwExtraInfo=None)))
    up = _INPUT(type=_INPUT_KEYBOARD, u=_INPUTunion(ki=_KEYBDINPUT(wVk=vk, wScan=0,
                                                                   dwFlags=_KEYEVENTF_KEYUP,
                                                                   time=0, dwExtraInfo=None)))
    return [down, up]


def _char_events(ch: str) -> list[_INPUT]:
    """Type one character as a UNICODE event rather than a virtual-key.

    ⚠️ Deliberate, and it is the fix for a failure this project has already paid for on the other
    platform: v2.41.0 traced stuck-key repeats (``waits for youuuuu`` ×130) to xdotool keysym
    remapping. Virtual-key codes are keyboard-LAYOUT dependent — the same VK is a different
    character on a German or Dvorak layout, so a path built on them types different text on
    different machines and there is no error anywhere. KEYEVENTF_UNICODE bypasses the layout
    entirely and delivers the codepoint. Text goes through here; only NAMED keys use VKs.
    """
    out: list[_INPUT] = []
    for unit in ch.encode("utf-16-le").decode("utf-16-le"):     # normalise to UTF-16 code units
        code = ord(unit)
        for flags in (_KEYEVENTF_UNICODE, _KEYEVENTF_UNICODE | _KEYEVENTF_KEYUP):
            out.append(_INPUT(type=_INPUT_KEYBOARD,
                              u=_INPUTunion(ki=_KEYBDINPUT(wVk=0, wScan=code, dwFlags=flags,
                                                           time=0, dwExtraInfo=None))))
    return out


# ---- window discovery ------------------------------------------------------------------------
_ENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


def _enumerate() -> list[tuple[int, int, str]]:
    """Every visible top-level window as (hwnd, owning pid, title). [] if enumeration failed."""
    found: list[tuple[int, int, str]] = []

    def cb(hwnd, _lparam):
        if not _user32.IsWindowVisible(hwnd):
            return True
        pid = wintypes.DWORD()
        _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        length = _user32.GetWindowTextLengthW(hwnd)
        title = ""
        if length:
            buf = ctypes.create_unicode_buffer(length + 1)
            _user32.GetWindowTextW(hwnd, buf, length + 1)
            title = buf.value
        found.append((hwnd, int(pid.value), title))
        return True

    try:
        _user32.EnumWindows(_ENUMPROC(cb), 0)
    except OSError:
        log.warning("EnumWindows failed (err=%d)", ctypes.get_last_error())
        return []
    return found


# Processes that own a window but are NEVER a session's terminal. `explorer.exe` is the one that
# matters: it is the desktop shell, so it owns Program Manager, every File Explorer window, and the
# desktop itself — and it is an ancestor of literally every interactive process on the machine.
_NEVER_A_TERMINAL = {"explorer.exe", "dwm.exe", "sihost.exe", "shellexperiencehost.exe",
                     "searchhost.exe", "startmenuexperiencehost.exe", "textinputhost.exe"}

# Terminal hosts that own the HWND on behalf of the program running inside them. The ancestor walk
# is allowed to reach one of these and MUST STOP there.
_TERMINAL_HOSTS = {"windowsterminal.exe", "conhost.exe", "openconsole.exe", "cmd.exe",
                   "powershell.exe", "pwsh.exe", "mintty.exe", "alacritty.exe", "wezterm-gui.exe",
                   "code.exe"}

# Hosts that put MANY sessions in ONE window as tabs. For these, owning-pid is not enough to
# identify a session and the window title (which tracks the ACTIVE tab) has to agree as well.
_MULTIPLEXERS = {"windowsterminal.exe", "code.exe"}


def _proc_name(pid: int) -> str:
    try:
        import psutil
        return psutil.Process(pid).name().lower()
    except Exception:
        return ""


def _pid_family(pid: int | None) -> set[int]:
    """``pid``, its descendants, and its ancestors ONLY as far as the terminal host.

    ⚠️ THIS FUNCTION IS WHY THE END-TO-END TEST EXISTS. The first version walked `p.parents()`
    unbounded, which is correct-sounding and catastrophic: on Windows every interactive process
    descends from `explorer.exe`, so the "family" of any session included the desktop shell — and
    therefore Program Manager, every File Explorer window, and (via the shared Windows Terminal
    ancestor) OTHER LIVE CLAUDE SESSIONS' windows. Measured 2026-08-30: the matcher returned an
    explorer window first, `focus` reported success because that window really did come to the
    foreground, and the text was typed into the desktop. Both functions returned True. That is the
    2026-08-05 outage reproduced on a new platform inside an hour of writing the backend.

    A console session's window IS legitimately owned by an ancestor — `conhost.exe` or
    `WindowsTerminal.exe` hosts it — so the walk upward is necessary. It just has to stop at the
    host instead of continuing to the shell.
    """
    if not pid:
        return set()
    fam = {int(pid)}
    try:
        import psutil
        try:
            p = psutil.Process(pid)
        except psutil.Error:
            return fam
        for child in p.children(recursive=True):
            fam.add(child.pid)
        for anc in p.parents():                       # parents() is ordered nearest-first
            name = ""
            try:
                name = anc.name().lower()
            except psutil.Error:
                pass
            if name in _NEVER_A_TERMINAL:
                break                                  # reached the shell — everything above is noise
            fam.add(anc.pid)
            if name in _TERMINAL_HOSTS:
                break                                  # the host owns the window; go no further
    except Exception:                                  # psutil absent or a race — degrade, never raise
        log.debug("could not walk the process family for pid=%s", pid, exc_info=True)
    return fam


def _windows_for_session(*, pid: int | None, terminal_pid: int | None,
                         title: str | None, window_title: str | None) -> list[int]:
    """Candidate HWNDs for one session, best evidence first, and EMPTY when it cannot tell.

    Returning [] is a real answer. Every caller turns it into False, which is the honest outcome:
    we could not find the window, so we did not type into one. The alternative — falling back to
    "the first terminal-looking window" — types a live Claude session's answer into a DIFFERENT
    live Claude session, which is unrecoverable and silent.
    """
    wins = [(h, p, t) for h, p, t in _enumerate()
            if t and _proc_name(p) not in _NEVER_A_TERMINAL]
    if not wins:
        return []

    family = _pid_family(terminal_pid) | _pid_family(pid)
    by_pid = [(h, p, t) for h, p, t in wins if p in family]

    # A multiplexer window is shared by every tab in it, so owning-pid identifies the WINDOW and
    # not the SESSION. The window title tracks the ACTIVE tab, which is the only evidence Windows
    # offers about which session is actually in front — so it has to agree before we type.
    if by_pid:
        muxed = [(h, p, t) for h, p, t in by_pid if _proc_name(p) in _MULTIPLEXERS]
        direct = [(h, p, t) for h, p, t in by_pid if _proc_name(p) not in _MULTIPLEXERS]
        if direct:
            return [h for h, _p, _t in direct]
        for wanted in (window_title, title):
            if not wanted:
                continue
            agree = [h for h, _p, t in muxed if wanted in t]
            if len(agree) == 1:
                return agree
        if muxed:
            log.warning(
                "session (terminal_pid=%s title=%r) is inside a tabbed terminal host and no window "
                "title matches — the right TAB is not in front and cannot be selected from outside, "
                "so refusing rather than typing into whichever tab is", terminal_pid, title)
            return []

    # Title matching, and ONLY when it identifies exactly one window. A terminal title is set by
    # the shell and is not unique by construction — two sessions in the same project can carry the
    # same title — so an ambiguous match is treated as no match.
    for wanted in (window_title, title):
        if not wanted:
            continue
        hits = [h for h, _p, t in wins if wanted in t]
        if len(hits) == 1:
            return hits
        if len(hits) > 1:
            log.warning("title %r matches %d windows — refusing to guess which session it is",
                        wanted, len(hits))
            return []
    return []


def _focus_hwnd(hwnd: int) -> bool:
    """Raise a window and RETURN WHAT ACTUALLY HAPPENED.

    ``SetForegroundWindow`` returns FALSE whenever Windows' foreground lock says a background
    process may not steal focus, which is the normal case for a service-like app. The documented
    way through it is to attach our input queue to the current foreground thread's for the
    duration of the call, which makes us "the foreground process" for the check.

    Whether that worked is decided by ``GetForegroundWindow()``, never by the return value.
    """
    if _user32.IsIconic(hwnd):
        _user32.ShowWindow(hwnd, _SW_RESTORE)

    _user32.SetForegroundWindow(hwnd)
    if _user32.GetForegroundWindow() == hwnd:
        return True

    fg = _user32.GetForegroundWindow()
    ours = _kernel32.GetCurrentThreadId()
    theirs = _user32.GetWindowThreadProcessId(fg, None) if fg else 0
    attached = bool(_user32.AttachThreadInput(ours, theirs, True)) if theirs and theirs != ours else False
    try:
        _user32.BringWindowToTop(hwnd)
        _user32.SetForegroundWindow(hwnd)
    finally:
        if attached:
            _user32.AttachThreadInput(ours, theirs, False)

    # The foreground change is asynchronous; give it a moment, then BELIEVE THE OBSERVATION.
    for _ in range(10):
        if _user32.GetForegroundWindow() == hwnd:
            return True
        time.sleep(0.02)

    log.warning("could not bring hwnd=%s to the foreground — refusing to report success", hwnd)
    return False


def _focus_and_then(send: list[_INPUT], **kw) -> bool:
    """Shared spine: locate, focus, verify focus, then type. Any step failing means False.

    Typing is only attempted once the window is CONFIRMED foreground. Synthetic input goes to
    whatever holds focus, so typing without that check does not merely fail — it delivers the
    keystrokes somewhere else, which is how an answer meant for one session lands in another.
    """
    if not wmctrl_available():
        return False
    hwnds = _windows_for_session(**kw)
    if not hwnds:
        log.warning("no window found for session (terminal_pid=%s title=%r) — not typing",
                    kw.get("terminal_pid"), kw.get("title"))
        return False
    if not _focus_hwnd(hwnds[0]):
        return False
    return _send(send) if send else True


# ---- the six -----------------------------------------------------------------------------------
def wmctrl_available() -> bool:
    """Can this backend enumerate and raise windows at all? (the portable meaning of the name)

    Answered by ENUMERATING, not by checking that a DLL loaded. `user32` is present on every
    Windows install, so "did the import work" is not evidence of anything — the same
    resolution-is-not-usability trap as the zero-byte `python3.exe` App Execution Alias, which
    satisfies `command -v` and exits 49. A session with no desktop attached (a service, an SSH
    session with no interactive window station) loads user32 fine and enumerates nothing.
    """
    if not _WIN:
        return False
    return bool(_enumerate())


def x11_health() -> dict:
    """Can Conductor reach a desktop right now? Same dict shape as the X11 backend.

    ``reason`` and ``detail`` are what the fleet-health banner shows, so they say what is broken
    in the reader's terms. The keys stay identical across backends because `/api/health` and the
    frontend read them by name.
    """
    if not _WIN:
        return {"ok": False, "reason": "wrong_platform", "display": None,
                "detail": "The Windows backend was loaded on a non-Windows host."}
    wins = _enumerate()
    if not wins:
        return {"ok": False, "reason": "no_desktop", "display": None,
                "detail": "No interactive desktop — Conductor cannot enumerate or raise any "
                          "window, so focus, wake, /msg-check and wind-down close are all dead."}

    # Report the tab limitation as part of health rather than leaving it to be discovered by a
    # keystroke going somewhere unexpected. ok=True: the backend CAN act; this is a caveat on
    # precision, not an inability, and downgrading it to ok=False would silence the whole fleet.
    hosts = sum(1 for _h, _p, t in wins if "Windows Terminal" in (t or ""))
    detail = ""
    if hosts:
        detail = (f"{hosts} Windows Terminal window(s) present: sessions sharing one window are "
                  f"raised as a window, but the specific TAB cannot be selected from outside.")
    return {"ok": True, "reason": "", "display": f"{len(wins)} windows", "detail": detail}


def focus_session(*, pid: int | None = None, terminal_pid: int | None,
                  title: str | None = None, window_title: str | None = None) -> bool:
    """Focus a session's terminal window. True only if it is genuinely in the foreground after."""
    return _focus_and_then([], pid=pid, terminal_pid=terminal_pid,
                           title=title, window_title=window_title)


def send_keys_to_session(*, text: str, pid: int | None = None, terminal_pid: int | None,
                         title: str | None = None, window_title: str | None = None) -> bool:
    """Activate a session's window and type ``text`` followed by Enter. Steals focus by design."""
    events: list[_INPUT] = []
    for ch in text:
        events.extend(_char_events(ch))
    events.extend(_vk_events(_VK["Return"]))
    return _focus_and_then(events, pid=pid, terminal_pid=terminal_pid,
                           title=title, window_title=window_title)


def send_key_to_session(*, key: str, pid: int | None = None, terminal_pid: int | None,
                        title: str | None = None, window_title: str | None = None) -> bool:
    """Press ONE named key — no text, no Return. Exists so a modal can be dismissed with Escape.

    An unknown key name returns False instead of typing something approximate. The caller that
    needs this is dismissing the `/rc` modal, where the neighbouring option is "Disconnect this
    session" — a wrong keystroke there is destructive, so guessing is not available.
    """
    vk = _VK.get(key)
    if vk is None:
        log.warning("unknown key name %r — refusing to send an approximation", key)
        return False
    return _focus_and_then(_vk_events(vk), pid=pid, terminal_pid=terminal_pid,
                           title=title, window_title=window_title)


def send_key_sequence(*, keys: list[str], pid: int | None = None, terminal_pid: int | None,
                      title: str | None = None, window_title: str | None = None) -> bool:
    """Send raw key NAMES to drive the AskUserQuestion picker (digits, Right, Return).

    Deliberately no leading ctrl+u, matching the X11 backend: there is no input line in a picker,
    and the whole sequence is rejected if ANY name is unknown — a picker half-driven is a picker
    left in an arbitrary state on a live session.
    """
    events: list[_INPUT] = []
    for k in keys:
        vk = _VK.get(k)
        if vk is None:
            log.warning("unknown key name %r in sequence %r — sending none of it", k, keys)
            return False
        events.extend(_vk_events(vk))
    return _focus_and_then(events, pid=pid, terminal_pid=terminal_pid,
                           title=title, window_title=window_title)
