"""When the gate's own logic crashes, what should it do?

The interpreter fix (see test_gate_interpreter.py) closed the case where python could not
run at all. This is the case one layer in: python runs fine and the gate's own code raises
— bad JSON, a payload shaped differently than expected, a bug in a regex. Until 2026-08-23
both gates resolved that to ALLOW, silently, because a crash and a clean "nothing to gate"
produced the identical observable: no output, status discarded by `|| true`.

Kyle's decision, after the trade was laid out:

  * fail CLOSED where the gate already promises an exact answer — the Edit/Write tools
    (the branch covering settings.json, i.e. fleet-wide RCE) and the push gate,
  * keep the Bash branch of the persistence gate best-effort and fail OPEN, because that
    is what its own header has always claimed and a shell cannot be fully analysed anyway,
  * and LOG every degraded path either way, because neither gate wrote a line anywhere,
    which is exactly how the first fail-open survived unnoticed.

An unparseable payload is treated as EXACT, not best-effort: we do not know what tool it
even is, so "the Bash branch is allowed to be incomplete" cannot be claimed for it. Blind
is not the same as best-effort.

⭐ NOTHING HERE IS SIMULATED. Every crash below is a real traceback out of the real script
under the real interpreter, provoked by a payload of the wrong shape — no fake python, no
monkeypatching. A gate whose failure behaviour is only ever tested against a stub is a
gate whose failure behaviour has never been tested.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

BUS = Path(__file__).resolve().parent.parent / "bus"
PERSIST, PUSH = BUS / "persist-gate.sh", BUS / "push-gate.sh"

DENIED, ALLOWED = 2, 0


@pytest.fixture
def env(tmp_path):
    (tmp_path / "claude" / "bin").mkdir(parents=True)
    (tmp_path / "coord").mkdir()
    return {
        "COORD_STATE_DIR": str(tmp_path / "coord"),
        "CLAUDE_CONFIG_DIR": str(tmp_path / "claude"),
        "BUS_STATE_DIR": str(tmp_path / "bus-state"),
        "HOME": str(tmp_path),
        # MEASURED: os.path.expanduser ignores HOME on Windows and honours USERPROFILE,
        # so with HOME alone every `~` in these payloads expands to the REAL profile of
        # whoever runs the suite -- the tilde rows then evaluate against that machine's
        # actual ~/.claude instead of the sandbox. The gate's bash half reads $HOME and
        # its embedded python calls expanduser, so both must land inside tmp_path.
        "USERPROFILE": str(tmp_path),
        "PATH": "/usr/bin:/bin",
        # Pin the interpreter. The PATH above is POSIX-only, so on Windows it resolves
        # NOTHING and the gate correctly reports blind and DENIES -- which turns every
        # "stays free" row red for a reason that is the gate working, not failing. This
        # suite tests the DECISION; test_gate_interpreter.py owns the RESOLUTION axis.
        "CLAUDE_BUS_PYTHON": sys.executable,
        "_root": tmp_path,
    }


def _run(gate: Path, env, raw: str) -> subprocess.CompletedProcess:
    e = {k: v for k, v in env.items() if not k.startswith("_")}
    return subprocess.run(["bash", str(gate)], input=raw, text=True,
                          capture_output=True, env=e)


def log(env) -> str:
    p = env["_root"] / "bus-state" / "gate.log"
    return p.read_text() if p.exists() else ""


def payload(**kw) -> str:
    return json.dumps({"cwd": "/tmp", **kw})


# A list where a string belongs. json.load is happy; re.sub and os.path.expanduser are not.
# This is how a real schema drift would arrive: valid JSON, unexpected shape.
WRONG_SHAPE = ["ls ~/.claude/bin/x"]


# --------------------------------------------------------------------------------------
# Controls first. Without these, "denies on crash" is indistinguishable from "denies".
# --------------------------------------------------------------------------------------

def test_control_normal_traffic_is_unaffected(env):
    gated = payload(tool_name="Edit",
                    tool_input={"file_path": str(env["_root"] / "claude" / "settings.json")})
    innocent = payload(tool_name="Bash", tool_input={"command": "ls -la /tmp"})
    assert _run(PERSIST, env, gated).returncode == DENIED
    assert _run(PERSIST, env, innocent).returncode == ALLOWED
    assert _run(PUSH, env, payload(tool_name="Bash",
                                   tool_input={"command": "git push origin main"})).returncode == DENIED
    assert _run(PUSH, env, innocent).returncode == ALLOWED
    assert log(env) == "", "a healthy run must not write to the anomaly log"


# --------------------------------------------------------------------------------------
# EXACT paths fail closed.
# --------------------------------------------------------------------------------------

def test_a_crash_on_the_edit_path_denies(env):
    """The branch that covers settings.json. Its header always claimed fail-closed."""
    r = _run(PERSIST, env, payload(tool_name="Edit", tool_input={"file_path": WRONG_SHAPE}))
    assert r.returncode == DENIED
    assert "the gate itself failed" in r.stderr
    assert "exact path" in log(env)
    assert "Traceback" in log(env), "denying without saying why is its own failure"


def test_an_unparseable_payload_denies(env):
    """Blind is not best-effort: we cannot even name the tool, so nothing may be assumed."""
    r = _run(PERSIST, env, '{"tool_name":"Edit","tool_input":{"file_path":"~/.claude/settings.json"')
    assert r.returncode == DENIED
    assert "JSONDecodeError" in log(env)


@pytest.mark.parametrize("raw", [
    json.dumps({"cwd": "/tmp", "tool_name": "Bash", "tool_input": {"command": ["git push origin main"]}}),
    '{"tool_name":"Bash","tool_input":{"command":"git push',
])
def test_the_push_gate_denies_when_it_cannot_parse(env, raw):
    """It cannot tell whether this is a push or where it lands. It will not guess."""
    r = _run(PUSH, env, raw)
    assert r.returncode == DENIED
    assert "the gate itself failed" in r.stderr
    assert "push\tparse crashed" in log(env)


# --------------------------------------------------------------------------------------
# The Bash path stays best-effort — but stops being silent.
# --------------------------------------------------------------------------------------

def test_a_crash_on_the_bash_path_still_allows(env):
    """Failing closed here would deny a large share of ordinary commands to defend a branch
    that has never claimed to be complete. In a repo whose path contains "claude", the
    prefilter matches nearly everything."""
    r = _run(PERSIST, env, payload(tool_name="Bash", tool_input={"command": WRONG_SHAPE}))
    assert r.returncode == ALLOWED


def test_but_that_allow_is_no_longer_silent(env):
    """The whole reason the original fail-open survived: nothing anywhere said a word."""
    _run(PERSIST, env, payload(tool_name="Bash", tool_input={"command": WRONG_SHAPE}))
    entry = log(env)
    assert "bash-path analysis crashed" in entry
    assert "ALLOWED" in entry
    assert "Traceback" in entry


# --------------------------------------------------------------------------------------
# The log must never be able to take the gate down.
# --------------------------------------------------------------------------------------

def test_an_unwritable_log_does_not_break_the_gate(env, tmp_path):
    """A logging bug becoming an outage in the thing being logged is the worst trade here."""
    env["BUS_STATE_DIR"] = "/proc/nonexistent-and-unwritable"
    gated = payload(tool_name="Edit",
                    tool_input={"file_path": str(env["_root"] / "claude" / "settings.json")})
    assert _run(PERSIST, env, gated).returncode == DENIED
    assert _run(PERSIST, env, payload(tool_name="Bash",
                                      tool_input={"command": "ls -la"})).returncode == ALLOWED


def test_the_fast_path_does_not_touch_the_filesystem(env):
    """The hot path must stay a grep.

    Both gates run on EVERY Bash/Edit/Write in EVERY session, and both headers promise an
    instant no-op for anything that is not a candidate. My first version of the logging
    prepared the log file at the top of the script — an mkdir and an open on every tool
    call in the fleet, to support a line that is written almost never. Preparation is now
    lazy, and this is how we know it stayed that way: a command that does not even reach
    the prefilter must leave no trace on disk.
    """
    nothing = payload(tool_name="Bash", tool_input={"command": "echo hello"})
    assert _run(PERSIST, env, nothing).returncode == ALLOWED
    assert _run(PUSH, env, nothing).returncode == ALLOWED
    assert not (env["_root"] / "bus-state").exists(), \
        "the fast path created the log directory — the hot path is doing filesystem work"
