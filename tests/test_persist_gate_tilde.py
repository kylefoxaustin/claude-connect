"""The tilde hole in the persistence gate — it shipped ARMED, twice, and the first test
suite missed it entirely.

THE BUG: the fast-path prefilter keyed on the EXPANDED path (`$CLAUDE_HOME/bin`), but a command
written with a TILDE (`> ~/.claude/bin/x`) does not contain that expanded string. So the gate
exited at the prefilter and the REAL CHECK NEVER RAN. Writes into ~/.claude/bin sailed straight
through an armed gate.

It is FAILURE_MODES' own documented bug #1 for this file — "a gate that did not run looks
exactly like a gate that found nothing" — re-shipped after the sentence describing it was
written. The original test suite missed it because every case passed an already-expanded
tmp_path and only exercised the Edit tool (which receives an expanded file_path). These force
the tilde form through the Bash path, which is where the hole lived.

THE FIX: the prefilter matches BROAD NOUNS ONLY (`claude|settings|systemctl|...`), never a path.
`claude` is present in both `~/.claude/...` and `/home/kyle/.claude/...`, so no spelling slips
past. A path in a prefilter is the bug; the noun is the fix.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

GATE = Path(__file__).resolve().parent.parent / "bus" / "persist-gate.sh"
DENIED, ALLOWED = 2, 0


def gate(cmd: str, env: dict) -> int:
    payload = json.dumps({"cwd": "/tmp", "tool_name": "Bash", "tool_input": {"command": cmd}})
    return subprocess.run(["bash", str(GATE)], input=payload, text=True,
                          capture_output=True, env=env).returncode


@pytest.fixture
def env(tmp_path):
    (tmp_path / "claude" / "bin").mkdir(parents=True)
    (tmp_path / "claude" / "commands").mkdir()
    e = dict(PATH="/usr/bin:/bin", HOME=str(tmp_path),
             CLAUDE_CONFIG_DIR=str(tmp_path / "claude"))
    return e


def test_tilde_write_to_bin_is_GATED(env):
    """The exact hole: a literal `~` in the command, not an expanded path. `~` expands against
    HOME, which the fixture points at tmp_path, so ~/claude/bin is the gated dir."""
    assert gate("echo x > ~/claude/bin/evil.sh", env) == DENIED
    assert gate("cp foo ~/claude/bin/evil.sh", env) == DENIED
    assert gate("echo x >> ~/claude/commands/z.md", env) == DENIED
    assert gate("install -m 755 x ~/claude/bin/y", env) == DENIED


def test_tilde_write_to_settings_is_GATED(env):
    assert gate("echo x > ~/claude/settings.json", env) == DENIED
    assert gate("sed -i s/a/b/ ~/claude/settings.json", env) == DENIED


def test_expanded_form_still_gated(env):
    ch = env["CLAUDE_CONFIG_DIR"]
    assert gate(f"echo x > {ch}/bin/evil.sh", env) == DENIED
    assert gate(f"echo x > {ch}/settings.json", env) == DENIED


def test_reads_and_normal_work_stay_free(env):
    assert gate("echo x > ~/claude/bin/z.sh".replace(">", "<"), env) == ALLOWED  # read
    assert gate("cat ~/claude/settings.json", env) == ALLOWED
    assert gate("grep -c foo ~/claude/bin/x.sh > /dev/null", env) == ALLOWED
    assert gate("git commit -m x", env) == ALLOWED
    assert gate("echo done", env) == ALLOWED
    assert gate("grep -E 'a|settings|crontab|b' f.txt", env) == ALLOWED  # word, not invocation
