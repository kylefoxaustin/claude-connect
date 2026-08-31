"""The Linux/Windows seam for desktop automation (conductor/desktop.py).

win_conductor, 2026-08-27, listing what it is blocked on: the `desktop.py` extraction *"blocks 13
of the 25"* remaining Windows failures, and it could not do the extraction itself because it
touches `main.py`'s import site.

The seam is where VERIFICATION changes hands: this side extracts and keeps Linux green (the only
box that can run a real X server), that side implements the backend (the only box that can run a
real Windows desktop). These tests pin the half this side owes.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from conductor import desktop, main, x11

SRC = Path(__file__).resolve().parent.parent / "conductor"

# The six names main.py consumes. Adding a seventh is a real decision — it is one more function
# every future backend must implement — so it should require editing this list on purpose.
CONTRACT = (
    "focus_session",
    "send_key_sequence",
    "send_key_to_session",
    "send_keys_to_session",
    "wmctrl_available",
    "x11_health",
)


def test_main_names_the_seam_not_the_platform():
    """`main.py` must not import from `.x11` again, or the seam rots shut."""
    src = (SRC / "main.py").read_text(encoding="utf-8")
    assert "from .desktop import" in src, "main.py stopped importing the backend selector"
    assert not re.search(r"^from \.x11 import", src, re.M), \
        "main.py imports the Linux backend directly again — Windows has no seam to sit behind"


def test_the_contract_is_exactly_six_functions():
    assert set(desktop.__all__) == set(CONTRACT) | {"backend_name"}
    for name in CONTRACT:
        assert callable(getattr(desktop, name)), f"{name} is not callable on the selector"
        assert getattr(main, name) is getattr(desktop, name), \
            f"main.{name} drifted away from the selector"


def test_linux_is_wired_to_the_x11_backend():
    """The extraction must be a pure re-point: same function objects, no wrapper, no copy."""
    assert desktop.backend_name == "x11"
    for name in CONTRACT:
        assert getattr(desktop, name) is getattr(x11, name), \
            f"{name} is not the x11 implementation — the refactor changed behaviour, not just shape"


def test_a_missing_windows_backend_falls_back_to_something_that_REFUSES():
    """⚠️ The rule that matters more than portability: never return True having done nothing.

    Conductor ran a 25-session wind-down against an unreachable display on 2026-08-05 because
    `wmctrl`/`xdotool` exit 0 while printing "Cannot open display". A stub backend that returned
    True would reproduce that outage on a platform with no history to be suspicious of. So the
    fallback is the X11 backend, whose probes return False off a Linux desktop and whose health
    check explains itself — refusing loudly is the correct Windows behaviour until a real backend
    lands.
    """
    src = (SRC / "desktop.py").read_text(encoding="utf-8")
    assert "_backend = _linux" in src, "the no-backend fallback disappeared"
    # And the contract is stated where an implementer will actually read it.
    assert "MUST return False" in src, "the backend contract is no longer stated in the module"
    # ⚠️ Scan the CODE, not the prose. The first version of this assertion grepped the whole file
    # for "return True" and matched its own docstring — the sentence forbidding the thing tripped
    # the check for the thing. That is the persist-gate prefilter's false-positive class exactly
    # (v2.34.1: a pattern that reads a word in text as if it were an instruction), reproduced in
    # the test written to prevent a different silent failure.
    code = ast.parse(src)
    stub = [n for n in ast.walk(code)
            if isinstance(n, ast.Return) and isinstance(n.value, ast.Constant) and n.value.value is True]
    assert not stub, \
        "desktop.py grew a stub that reports success — that is the 2026-08-05 outage by design"


def test_patching_x11_does_not_leak_through_the_selector(monkeypatch):
    """A footgun the extraction introduces, pinned so it can never be discovered the hard way.

    `desktop.py` binds the backend's functions at import, so patching `conductor.x11.<fn>` does
    NOT change what `main` calls. A test written that way would pass green while production ran
    the real function — a mirror (FAILURE_MODES IV), and one that types into a live terminal.
    The established convention is to patch `conductor.main.<fn>`, which every existing suite uses.
    """
    sentinel = object()
    monkeypatch.setattr(x11, "send_keys_to_session", sentinel)
    assert main.send_keys_to_session is not sentinel, (
        "patching conductor.x11 leaked through — if this ever becomes true, delete this test; "
        "until then, patch 'conductor.main.send_keys_to_session' instead"
    )


@pytest.mark.parametrize("name", CONTRACT)
def test_every_contract_function_is_documented_for_an_implementer(name):
    """A backend author reads the docstring, not this test. Make sure there is one."""
    fn = getattr(x11, name)
    assert (fn.__doc__ or "").strip(), \
        f"x11.{name} has no docstring — it is now a spec another platform must implement"
