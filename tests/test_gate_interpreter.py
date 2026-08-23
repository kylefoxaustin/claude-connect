"""Both hard controls disarmed together on one missing binary — and the obvious fix
would not have closed it.

Found by `win_conductor`, the Windows-port session, on 2026-08-23, and reproduced here
with a control the same day. Every case in this file is either that bug or the trap that
sat one layer under it.

THE BUG. Both gates ran `python3 -c ...` and swallowed the failure (`2>/dev/null || true`
in persist-gate, `|| printf '\\n\\n'` in push-gate). With no usable python3 the
substitution produced nothing, the "nothing matched" branch fired, and the gate exited 0
— SILENTLY ALLOWING the act it exists to stop. An armed gate that is not there.

⭐ THE TRAP, which is the reason this file has more than one test. The fix I had written
down was "try python3, then python, then py -3, and take the first that resolves." On
Windows that closes nothing: `WindowsApps\\python3.exe` is a ZERO-BYTE App Execution Alias
that satisfies `command -v`, `where` and `test -x`, and exits 49 with "Python was not
found". An existence check picks the stub on its FIRST try, declares success, and leaves
the gate open — now with a fix in front of it and a comment claiming it is handled. That
is strictly worse than the undisguised failure it replaces.

    A check that cannot observe the thing it claims to check is not a weak check.
    It is a green light with nothing behind it.

`command -v` cannot observe whether an interpreter interprets. So: RUN the candidate.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

BUS = Path(__file__).resolve().parent.parent / "bus"
PERSIST, PUSH = BUS / "persist-gate.sh", BUS / "push-gate.sh"

DENIED, ALLOWED = 2, 0

# The Microsoft Store redirector, in the only two properties that matter here: it exists
# on PATH, and it is not an interpreter. rc=49 is what the real alias returns.
STORE_ALIAS = "#!/bin/sh\necho 'Python was not found; run without arguments to install"\
              " from the Microsoft Store...' >&2\nexit 49\n"


def _stub(d: Path, name: str, body: str) -> None:
    p = d / name
    p.write_text(body)
    p.chmod(0o755)


@pytest.fixture
def env(tmp_path):
    """A gate environment whose PATH we can poison one interpreter at a time."""
    (tmp_path / "claude" / "bin").mkdir(parents=True)
    (tmp_path / "coord").mkdir()
    (tmp_path / "proj").mkdir()
    (tmp_path / "shims").mkdir()
    return {
        "COORD_STATE_DIR": str(tmp_path / "coord"),
        "CLAUDE_CONFIG_DIR": str(tmp_path / "claude"),
        "HOME": str(tmp_path),
        "PATH": f"{tmp_path / 'shims'}:/usr/bin:/bin",
        "_root": tmp_path,
        "_shims": tmp_path / "shims",
    }


def _run(gate: Path, env, payload: dict) -> subprocess.CompletedProcess:
    e = {k: v for k, v in env.items() if not k.startswith("_")}
    return subprocess.run(["bash", str(gate)], input=json.dumps(payload), text=True,
                          capture_output=True, env=e)


def persist(env) -> subprocess.CompletedProcess:
    """Edit settings.json — the fleet-wide RCE, the one act this gate exists for."""
    return _run(PERSIST, env, {
        "cwd": str(env["_root"] / "proj"), "tool_name": "Edit",
        "tool_input": {"file_path": str(env["_root"] / "claude" / "settings.json")}})


def push(env) -> subprocess.CompletedProcess:
    return _run(PUSH, env, {"cwd": str(env["_root"] / "proj"), "tool_name": "Bash",
                            "tool_input": {"command": "git push origin main"}})


# --------------------------------------------------------------------------------------
# 0. THE CONTROL. Without this the tests below prove nothing: a gate that denies
#    everything unconditionally would pass every one of them.
# --------------------------------------------------------------------------------------

def test_control_a_healthy_interpreter_still_denies(env):
    assert persist(env).returncode == DENIED
    assert push(env).returncode == DENIED


def test_control_an_innocent_command_is_still_allowed(env):
    """Fail-CLOSED must not become deny-everything. The fast path still exits 0 first."""
    r = _run(PERSIST, env, {"cwd": str(env["_root"] / "proj"), "tool_name": "Bash",
                            "tool_input": {"command": "ls -la /tmp"}})
    assert r.returncode == ALLOWED


# --------------------------------------------------------------------------------------
# 1. THE BUG AS REPORTED — no usable interpreter at all.
# --------------------------------------------------------------------------------------

@pytest.mark.parametrize("gate", ["persist", "push"])
def test_no_usable_interpreter_denies_instead_of_silently_allowing(env, gate):
    for name in ("python3", "python", "py"):
        _stub(env["_shims"], name, "#!/bin/sh\nexit 127\n")
    r = persist(env) if gate == "persist" else push(env)
    assert r.returncode == DENIED, "a gate that cannot evaluate MUST NOT allow"
    assert "gate is blind" in r.stderr, "and it must SAY so — silence was the whole bug"


# --------------------------------------------------------------------------------------
# 2. THE TRAP — an interpreter that RESOLVES and does not RUN.
#    This is the case the resolve-don't-run fix would have shipped straight past.
# --------------------------------------------------------------------------------------

@pytest.mark.parametrize("gate", ["persist", "push"])
def test_a_windows_store_alias_is_skipped_not_selected(env, gate):
    """python3 exists, is executable, and is not python. The gate must move on."""
    _stub(env["_shims"], "python3", STORE_ALIAS)
    _stub(env["_shims"], "python", f'#!/bin/sh\nexec "{sys.executable}" "$@"\n')
    r = persist(env) if gate == "persist" else push(env)
    assert r.returncode == DENIED
    assert "gate is blind" not in r.stderr, "a working candidate existed; it should be used"


def test_the_stub_really_does_satisfy_an_existence_check(env):
    """The premise, pinned. If this ever fails, the test above stopped testing anything."""
    _stub(env["_shims"], "python3", STORE_ALIAS)
    p = env["_shims"] / "python3"
    assert p.exists() and os.access(p, os.X_OK)
    e = {**{k: v for k, v in env.items() if not k.startswith("_")}}
    assert subprocess.run(["bash", "-c", "command -v python3"], env=e,
                          capture_output=True, text=True).returncode == 0
    assert subprocess.run([str(p), "-c", "pass"], capture_output=True).returncode == 49


# --------------------------------------------------------------------------------------
# 3. THE ESCAPE HATCH — an absolute path cannot be shadowed tomorrow by a venv, a PATH
#    edit, or a Windows feature update re-enabling the Store aliases. win_conductor's
#    point: a bootstrap changes the PROBABILITY that python works; it does not change
#    what happens when it does not.
# --------------------------------------------------------------------------------------

@pytest.mark.parametrize("gate", ["persist", "push"])
def test_claude_bus_python_overrides_a_broken_path(env, gate):
    for name in ("python3", "python", "py"):
        _stub(env["_shims"], name, STORE_ALIAS)
    env["CLAUDE_BUS_PYTHON"] = sys.executable
    r = persist(env) if gate == "persist" else push(env)
    assert r.returncode == DENIED
    assert "gate is blind" not in r.stderr


def test_a_broken_override_falls_through_to_a_working_candidate(env):
    """The override is a hint, not a suicide pact — but it must not silently allow."""
    env["CLAUDE_BUS_PYTHON"] = str(env["_root"] / "nope" / "python")
    assert persist(env).returncode == DENIED
