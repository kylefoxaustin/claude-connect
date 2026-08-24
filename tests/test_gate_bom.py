"""A UTF-8 BOM used to make the gate deny everything.

`win_conductor` found it while building the Windows bootstrap: PowerShell prepends a BOM
whenever it pipes to a native process (144 bytes in, 146 received), `json.loads` raises
"Unexpected UTF-8 BOM", and the fail-closed path added the same day then correctly refuses
an unparseable payload. The gate behaves exactly as designed and the OUTCOME is that every
gated act is denied.

It matters beyond a test harness because Claude Code runs a hook's command through
PowerShell when Git Bash is not installed — the default state of a fresh Windows box. That
end-to-end case is NOT measured (it has Git Bash and was not going to uninstall it to find
out), so this is a hypothesis with a measured mechanism.

⭐ The right reading is that the fail-closed change did not cause this; it CONVERTED it.
Before, a BOM made the gate silently allow. After, it makes it loudly deny. The bug was
always there — failing closed is what made it visible, which is the argument for failing
closed, not against it.

Second default fixed here at the same time: `sys.stdin` decodes with the locale encoding,
cp1252 on Windows, so any non-ASCII byte in a payload mangles before json sees it. Reading
`.buffer` and decoding `utf-8-sig` fixes both. Same family as the os.sep and posixpath
bugs — a default that is invisible on the platform you develop on.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

BUS = Path(__file__).resolve().parent.parent / "bus"
PERSIST, PUSH = BUS / "persist-gate.sh", BUS / "push-gate.sh"
DENIED, ALLOWED = 2, 0
BOM = "﻿"


@pytest.fixture
def env(tmp_path):
    (tmp_path / "claude" / "bin").mkdir(parents=True)
    (tmp_path / "coord").mkdir()
    return {
        "COORD_STATE_DIR": str(tmp_path / "coord"),
        "CLAUDE_CONFIG_DIR": str(tmp_path / "claude"),
        "BUS_STATE_DIR": str(tmp_path / "bus-state"),
        "HOME": str(tmp_path),
        "PATH": "/usr/bin:/bin",
        "_root": tmp_path,
    }


def run(gate, env, raw: str):
    e = {k: v for k, v in env.items() if not k.startswith("_")}
    return subprocess.run(["bash", str(gate)], input=raw.encode("utf-8"),
                          capture_output=True, env=e)


def payload(**kw) -> str:
    return json.dumps({"cwd": "/tmp", **kw})


def gated_edit(env) -> str:
    return payload(tool_name="Edit",
                   tool_input={"file_path": str(env["_root"] / "claude" / "settings.json")})


PUSH_CMD = payload(tool_name="Bash", tool_input={"command": "git push origin main"})
INNOCENT = payload(tool_name="Bash", tool_input={"command": "ls -la /tmp"})


def test_a_bom_does_not_change_the_persist_verdict(env):
    """Same payload, same answer, and — the part that matters — the same REASON."""
    plain = run(PERSIST, env, gated_edit(env))
    withbom = run(PERSIST, env, BOM + gated_edit(env))
    assert plain.returncode == withbom.returncode == DENIED
    assert b"needs Kyle's approval" in withbom.stderr
    assert b"the gate itself failed" not in withbom.stderr, \
        "denied because it could not parse — that is the deny-everything bug, not a gate decision"


def test_a_bom_does_not_change_the_push_verdict(env):
    withbom = run(PUSH, env, BOM + PUSH_CMD)
    assert withbom.returncode == DENIED
    assert b"the gate itself failed" not in withbom.stderr


@pytest.mark.parametrize("gate", [PERSIST, PUSH])
def test_a_bom_on_innocent_work_still_allows(env, gate):
    """The expensive half. A BOM must not turn ordinary work into a denial."""
    assert run(gate, env, BOM + INNOCENT).returncode == ALLOWED


def test_non_ascii_in_a_payload_survives(env):
    """cp1252 would mangle this before json saw it. A path with an em dash is not exotic."""
    p = env["_root"] / "claude" / "bin" / "réservé — notes.sh"
    r = run(PERSIST, env, BOM + payload(tool_name="Write", tool_input={"file_path": str(p)}))
    assert r.returncode == DENIED
    assert b"the gate itself failed" not in r.stderr


def test_a_genuinely_broken_payload_still_denies(env):
    """The control: hardening the decode must not re-open the unparseable case."""
    r = run(PERSIST, env, BOM + '{"tool_name":"Edit","tool_input":{"file_path":"~/.claude/settings.json"')
    assert r.returncode == DENIED
    assert b"the gate itself failed" in r.stderr
