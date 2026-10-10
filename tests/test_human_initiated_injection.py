"""An explicit click is not a focus race.

The focus-race guard refuses to type while a human has been active in the last 4 s — a
real protection, because Tilix panes share one X11 window and a racing focus splits
keystrokes across tiles. It is correct for an AUTONOMOUS wake.

⚠️ But clicking the 📬 bubble IS human activity inside that window, by construction. So
the manual ping could never succeed: it failed 100% of the time and surfaced as
"Couldn't reach the session's window (not found)" — a message about the wrong thing
entirely. MEASURED 2026-10-10: mutter idle 280 ms against a 4000 ms threshold, while Kyle
was clicking the button that asks for exactly this.

These tests pin the distinction, and the signature agreement that makes it safe to thread.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _params(path: Path, name: str) -> set[str] | None:
    for fn in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(fn, ast.FunctionDef) and fn.name == name:
            return {a.arg for a in fn.args.args} | {a.arg for a in fn.args.kwonlyargs}
    return None


def _body(path: Path, name: str) -> str:
    src = path.read_text(encoding="utf-8")
    for fn in ast.walk(ast.parse(src)):
        if isinstance(fn, ast.FunctionDef) and fn.name == name:
            return ast.get_source_segment(src, fn) or ""
    return ""


def test_the_guard_is_conditional_not_unconditional():
    """`human_recently_active()` alone would refuse every click forever."""
    body = _body(ROOT / "conductor/x11.py", "_focus_session_input")
    assert "human_recently_active() and not human_initiated" in body, (
        "the focus-race guard must yield to an explicit human action, or the manual "
        "ping can never fire"
    )


def test_every_function_passing_the_flag_also_declares_it():
    """Threading a new kwarg is a NameError waiting to happen: two functions passed
    `human_initiated=human_initiated` before declaring it, which parses fine and raises
    at request time."""
    src = (ROOT / "conductor/x11.py").read_text(encoding="utf-8")
    missing = []
    for fn in ast.walk(ast.parse(src)):
        if not isinstance(fn, ast.FunctionDef):
            continue
        seg = ast.get_source_segment(src, fn) or ""
        if "human_initiated=human_initiated" not in seg:
            continue
        params = {a.arg for a in fn.args.args} | {a.arg for a in fn.args.kwonlyargs}
        if "human_initiated" not in params:
            missing.append(fn.name)
    assert not missing, f"pass the flag without declaring it -> NameError: {missing}"


def test_both_backends_keep_one_signature():
    """desktop.py picks a backend at import. A caller that works on Linux must not
    TypeError on Windows, so the Windows build accepts (and ignores) the flag."""
    win = ROOT / "conductor/desktop_win.py"
    for name in ("send_keys_to_session", "send_key_to_session", "send_key_sequence"):
        w = _params(win, name)
        if w is None:
            continue                     # not implemented there at all: fine
        x = _params(ROOT / "conductor/x11.py", name) or set()
        assert not (x - w), f"{name}: linux-only params {sorted(x - w)}"


def test_the_manual_ping_sets_it_and_autonomous_wakes_do_not():
    """The flag must be opt-IN. If an autonomous wake set it, Conductor would type over
    Kyle mid-keystroke — which is the defect the guard exists for."""
    main = (ROOT / "conductor/main.py").read_text(encoding="utf-8")
    assert 'human_initiated=True' in main, "the manual ping must opt in"
    # exactly one opt-in site today: the 📬 bubble. A second one is a decision, not a typo.
    assert main.count("human_initiated=True") == 1, (
        "more than one path now bypasses the focus-race guard — that is a deliberate "
        "choice and should be reviewed, not inherited"
    )
