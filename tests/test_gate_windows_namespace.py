"""The gate was open to BOTH absolute path forms on Windows. Closed here, and proven from Linux.

win_conductor MEASURED this against the armed gate on 2026-08-26 and was careful to describe it
precisely, which is why it got fixed rather than filed:

    tilde              -> DENIES
    MSYS-absolute      -> ALLOWS      (/c/Users/kyle/.claude/bin/evil.sh)
    Windows-absolute   -> ALLOWS      (C:\\Users\\kyle\\.claude\\bin\\evil.sh)

It had first been recorded as a namespace MISMATCH — CH in one spelling, the command in another —
and corrected that in writing: the Windows-form path, where BOTH sides are the same namespace, is
missed too. Two different holes wearing one description, and only the corrected version leads to
the right fix.

ROOT CAUSE, both halves in this file's own code:

  1. `PATHS` and the redirect pattern were anchored on `[~/]`, so a token starting with a DRIVE
     LETTER was never a path candidate at all. The Windows-absolute write was not "checked and
     allowed" — it was never extracted, which is why no amount of prefix-matching would have
     found it.
  2. `gated_path` called `os.path.realpath` BEFORE any namespace translation. A Windows python
     handed "/c/Users/..." reads the leading slash as the current drive's root and returns
     C:\\c\\Users\\... — a path that exists nowhere and prefix-matches nothing. The resolver has
     to be fed a spelling its own OS understands.

⚠️ WHAT THIS FILE CAN AND CANNOT CLAIM. It drives the REAL gate with a drive-lettered
CLAUDE_CONFIG_DIR, so the namespace logic, the regexes and the ordering are genuinely exercised —
on Linux, where CH can never carry a drive letter and this code is otherwise unreachable. It is
NOT a Windows harness: HOME here is POSIX, the interpreter is a POSIX python, and no MSYS layer
is involved. The two `known_gaps` rows in gate_acceptance.json stay open until win_conductor
re-runs them on silicon. A test that sets up conditions the real path never has is a mirror, and
this suite says which half it is rather than letting a green tick imply the other.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

GATE = Path(__file__).resolve().parent.parent / "bus" / "persist-gate.sh"
DENIED, ALLOWED = 2, 0


def gate(cmd: str, env: dict) -> int:
    payload = json.dumps({"cwd": "/tmp", "tool_name": "Bash", "tool_input": {"command": cmd}})
    return subprocess.run(["bash", str(GATE)], input=payload, text=True, encoding="utf-8", errors="replace",
                          capture_output=True, env=env).returncode


@pytest.fixture
def winenv(tmp_path):
    """A Windows-shaped namespace: CLAUDE_CONFIG_DIR carries a drive letter.

    That drive letter is the ONLY switch — the gate keys its translation on the namespace, never
    on sys.platform or os.name, because a Windows python reports "nt" and an MSYS python does not
    and the gate meets both.
    """
    return dict(PATH="/usr/bin:/bin", HOME=str(tmp_path), CLAUDE_BUS_PYTHON=sys.executable,
                CLAUDE_CONFIG_DIR="C:/Users/kyle/.claude")


@pytest.mark.parametrize("cmd", [
    r"echo pwned > C:\Users\kyle\.claude\bin\evil.sh",
    r"echo pwned >> C:\Users\kyle\.claude\commands\x.md",
    r"cp foo C:\Users\kyle\.claude\bin\evil.sh",
    r"echo x > C:\Users\kyle\.claude\settings.json",
])
def test_windows_absolute_writes_are_GATED(cmd, winenv):
    """Hole 1: a drive letter was not a path start, so these were never even candidates."""
    assert gate(cmd, winenv) == DENIED, f"an armed gate let this through: {cmd}"


@pytest.mark.parametrize("cmd", [
    "echo pwned > /c/Users/kyle/.claude/bin/evil.sh",
    "install -m 755 x /c/Users/kyle/.claude/bin/y",
    "sed -i s/a/b/ /c/Users/kyle/.claude/settings.json",
])
def test_msys_absolute_writes_are_GATED(cmd, winenv):
    """Hole 2: the same file spelled the Git Bash way, which the resolver mangled."""
    assert gate(cmd, winenv) == DENIED, f"an armed gate let this through: {cmd}"


def test_case_does_not_evade_the_gate(winenv):
    """Windows paths are case-insensitive; the previous fix left this open IN WRITING.

    A comment saying "still open, not claimed to be handled" is honest, but it is also a
    documented way through an armed control.
    """
    assert gate(r"echo x > c:\users\KYLE\.CLAUDE\bin\evil.sh", winenv) == DENIED
    assert gate("echo x > /C/USERS/kyle/.claude/bin/evil.sh", winenv) == DENIED


@pytest.mark.parametrize("cmd", [
    "echo hello > C:/Users/kyle/project/out.txt",      # a real write, nowhere near ~/.claude
    "cat /c/Users/kyle/.claude/bin/bus.sh",            # a READ of a gated file stays free
    "grep -c foo /c/Users/kyle/.claude/bin/x.sh > /dev/null",   # read + redirect elsewhere
    "curl https://example.com/x > out.txt",            # the URL must not become a path token
])
def test_the_false_positive_class_still_passes(cmd, winenv):
    """The half that decides whether the gate is USABLE rather than merely safe.

    A gate that blocks reads is not a gate, it is an obstacle, and an obstacle gets disabled —
    this file's own header says so after that exact thing happened. The URL row is here because
    the drive-letter pattern very nearly matched the "s://" inside "https://"; it is excluded by
    a lookbehind, and this row is what would notice if that lookbehind were ever dropped.
    """
    assert gate(cmd, winenv) == ALLOWED, f"false positive — the gate denied a safe command: {cmd}"


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="a Linux-namespace regression guard: its premise is that CH carries NO drive letter, "
           "which is false here because tmp_path is C:\\... — the Windows namespace is covered by "
           "the other rows in this file, which pass",
)
def test_posix_namespace_is_untouched(tmp_path):
    """⭐ THE REGRESSION GUARD. On Linux none of the above may change anything.

    `/c/Users/...` is a perfectly ordinary POSIX directory, and rewriting it to `c:/Users/...`
    on a Linux box would be the fix causing a worse bug than the one it closed. CH has no drive
    letter here, so the whole translation must be unreachable.
    """
    (tmp_path / "claude" / "bin").mkdir(parents=True)
    env = dict(PATH="/usr/bin:/bin", HOME=str(tmp_path), CLAUDE_BUS_PYTHON=sys.executable,
               CLAUDE_CONFIG_DIR=str(tmp_path / "claude"))
    ch = env["CLAUDE_CONFIG_DIR"]
    assert gate(f"echo x > {ch}/bin/evil.sh", env) == DENIED       # still gated
    assert gate("echo x > ~/claude/bin/evil.sh", env) == DENIED    # tilde still gated
    assert gate("echo x > /c/Users/kyle/notes.txt", env) == ALLOWED  # NOT read as a drive
    assert gate("echo hello > /tmp/out.txt", env) == ALLOWED
