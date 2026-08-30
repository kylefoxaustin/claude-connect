"""The one import site for everything that drives a terminal.

Conductor is read-only toward Claude with a handful of deliberate exceptions, and every one of
them ends up here: raising a window, typing a `/msg-check`, sending a bare `Escape` to a picker,
answering a decision. All of it is desktop automation, all of it is platform-specific, and until
now all of it was `from .x11 import ...` in `main.py` — which named the Linux mechanism in the
one file that should not care what the mechanism is.

win_conductor (2026-08-27) needs that seam to put a Windows backend behind, and could not make it
itself: the extraction touches `main.py`'s import site, which was one of the two files this side
was holding unpushed commits in.

─────────────────────────────────────────────────────────────────────────────────────────────
WHY THE SPLIT IS HERE AND NOT ELSEWHERE: whoever can PROVE a half owns that half.
─────────────────────────────────────────────────────────────────────────────────────────────
Neither side can test the other's platform, so the seam goes where verification changes hands.
This extraction is a refactor of an existing, working Linux path — the only thing that can show
it did not regress is running it against a real X server, which only skippy has. The Windows
backend is new code whose only possible evidence is a real Windows desktop. So: this side
extracts and keeps Linux green; that side implements `desktop_win.py` behind the contract below.

─────────────────────────────────────────────────────────────────────────────────────────────
⚠️ THE CONTRACT A BACKEND MUST HONOUR — and the one rule that matters more than the rest
─────────────────────────────────────────────────────────────────────────────────────────────
    A backend that cannot act MUST return False. It must never return True having done nothing.

This is not a style note. On 2026-08-05 Conductor ran a 25-session wind-down against a display it
could not reach: `wmctrl` and `xdotool` exit 0 while printing "Cannot open display" to stderr, so
every focus, wake and close reported success and none of them happened, and the dashboard read as
healthy throughout. An unimplemented backend that returns True reproduces that outage exactly,
and it is worse on a fresh platform because there is no history to be suspicious of.

`x11_health()` is the honest way to say "I cannot act": return ``ok=False`` with a ``detail``
naming the reason. The fleet-health banner surfaces that, and a Windows build with no backend
SHOULD show it — "Conductor cannot type at any session" is a true statement there today.
"""
from __future__ import annotations

import sys

# The Linux backend is the reference implementation and, right now, the only one. It imports
# nothing Linux-only at module scope (it reads /proc at call time), so this import is safe to
# evaluate anywhere — a backend that exploded on import would take down the whole app on a
# platform where the right outcome is merely "focus does not work yet".
from . import x11 as _linux

if sys.platform == "win32":
    try:
        from . import desktop_win as _backend      # type: ignore[attr-defined]
    except ImportError:
        # No Windows backend yet. Fall through to the X11 one, whose probes return False and
        # whose x11_health() reports why. That is the honest failure: every action refuses and
        # says so, rather than silently succeeding.
        _backend = _linux
else:
    _backend = _linux

backend_name: str = getattr(_backend, "__name__", "?").rsplit(".", 1)[-1]

# The surface main.py actually consumes. Deliberately NOT a re-export of everything x11.py
# happens to expose: a backend should have to implement six functions, not thirty, and anything
# outside this list is a Linux implementation detail that Windows must not be asked to mimic.
focus_session = _backend.focus_session
send_key_sequence = _backend.send_key_sequence
send_key_to_session = _backend.send_key_to_session
send_keys_to_session = _backend.send_keys_to_session
wmctrl_available = _backend.wmctrl_available
x11_health = _backend.x11_health

__all__ = [
    "backend_name",
    "focus_session",
    "send_key_sequence",
    "send_key_to_session",
    "send_keys_to_session",
    "wmctrl_available",
    "x11_health",
]
