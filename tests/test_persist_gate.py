"""The persistence gate — acts whose consequences OUTLIVE the session.

Kyle's second hard control. image_gen's framing, and it reframes the first one:

    The push gate is not about git. It is about ONE property: an act whose consequences
    outlive the session that committed it. A push outlives me. So does a systemd unit.
    So does a cron job. So does a hook.

It exists because claude-connect FABRICATED Kyle's approval and image_gen went to install a
persistent systemd daemon on the strength of it. Only its own harness stopped it. Luck, not
architecture.

  ★ THE GRANT IS BOUND TO THE ACTION, NOT CONVEYED IN PROSE.
    A Claude can say "Kyle approved this" a hundred times and the act is still DENIED, because
    there is no token in the file. The words become worthless BY CONSTRUCTION.

THIS FILE EXISTS BECAUSE I SHIPPED THE GATE WITH THREE BUGS AND FOUND ALL THREE BY IT BITING
ME, not by testing it. Every case below is one of them, or a thing that would have caught them.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

GATE = Path(__file__).resolve().parent.parent / "bus" / "persist-gate.sh"

DENIED, ALLOWED = 2, 0


@pytest.fixture
def env(tmp_path):
    (tmp_path / "claude" / "bin").mkdir(parents=True)
    (tmp_path / "claude" / "commands").mkdir()
    (tmp_path / "claude" / "bus-state" / "registry").mkdir(parents=True)
    (tmp_path / "coord").mkdir()
    (tmp_path / "proj").mkdir()
    return {
        "COORD_STATE_DIR": str(tmp_path / "coord"),
        "CLAUDE_CONFIG_DIR": str(tmp_path / "claude"),
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


def run(env, tool, tool_input) -> int:
    payload = json.dumps({"cwd": str(env["_root"] / "proj"),
                          "tool_name": tool, "tool_input": tool_input})
    e = {k: v for k, v in env.items() if k != "_root"}
    return subprocess.run(["bash", str(GATE)], input=payload, text=True,
                          capture_output=True, env=e).returncode


def bash(env, cmd) -> int:
    return run(env, "Bash", {"command": cmd})


def edit(env, path) -> int:
    return run(env, "Edit", {"file_path": str(path)})


# --- THE RCE. settings.json is edited with the Edit TOOL, not Bash. -----------
def test_editing_settings_json_is_gated(env):
    """The highest-privilege write on the box, and the one a Bash-only gate (the push gate's
    shape) would have missed entirely. A hook here is arbitrary code executed on EVERY tool call
    in EVERY session — fleet-wide RCE that looks like editing a config file."""
    assert edit(env, env["_root"] / "claude" / "settings.json") == DENIED


def test_writing_the_hook_dir_is_gated(env):
    assert edit(env, env["_root"] / "claude" / "bin" / "bus.sh") == DENIED
    assert edit(env, env["_root"] / "claude" / "commands" / "x.md") == DENIED


def test_a_systemd_unit_and_a_cron_job_are_gated(env):
    assert bash(env, "systemctl --user enable tenant-watch") == DENIED
    assert bash(env, "crontab -e") == DENIED


def test_shell_writes_to_gated_paths(env):
    ch = env["_root"] / "claude"
    assert bash(env, f"echo x > {ch}/settings.json") == DENIED
    assert bash(env, f"cp foo {ch}/bin/evil.sh") == DENIED
    assert bash(env, f"install -m 755 x {ch}/bin/y") == DENIED
    # BUG 1: v1's per-verb regex glued the path on, and the `s/a/b/` argument contains slashes,
    # so the capture matched INSIDE the sed expression and never reached the filename.
    assert bash(env, f"sed -i s/a/b/ {ch}/settings.json") == DENIED


# --- MUST STAY FREE. A gate that blocks normal work gets disabled. ------------
def test_normal_work_is_untouched(env):
    assert edit(env, env["_root"] / "proj" / "main.py") == ALLOWED
    assert bash(env, "git commit -m x") == ALLOWED
    assert bash(env, "python -m pytest -q") == ALLOWED
    assert bash(env, "systemctl --user status tenant-watch") == ALLOWED   # read-only


def test_transcripts_and_bus_state_are_free(env):
    """Written constantly by every session. Gating them would break the fleet and protect
    nothing — they are data, not code that runs later."""
    ch = env["_root"] / "claude"
    assert edit(env, ch / "projects" / "x" / "y.jsonl") == ALLOWED
    assert edit(env, ch / "bus-state" / "registry" / "gpu.md") == ALLOWED


def test_READING_a_gated_path_is_free(env):
    """BUG 2, AND IT IS THE ONE THAT TRAPPED ME.

    v2 ANDed "has a write verb somewhere" with "mentions a gated path somewhere" — so
    `grep -c foo ~/.claude/bin/x.sh > /dev/null` (a pure READ) was DENIED, because it has a `>`
    and it names a file under bin/. It blocked me repeatedly while I was trying to verify the
    gate itself, and I could not shell my way out.

    A gate that blocks reads is not a gate. It is an obstacle — and an obstacle gets disabled.
    """
    ch = env["_root"] / "claude"
    assert bash(env, f"cat {ch}/settings.json") == ALLOWED
    assert bash(env, f"grep -c hooks {ch}/settings.json") == ALLOWED
    assert bash(env, f"grep -c foo {ch}/bin/bus.sh > /dev/null") == ALLOWED
    assert bash(env, f"wc -l {ch}/bin/bus.sh | sed 's/^/  /'") == ALLOWED
    # ...and a write to somewhere else, while merely NAMING a gated path, is also free.
    assert bash(env, f"grep hooks {ch}/settings.json > /tmp/out.txt") == ALLOWED


def test_the_word_is_not_the_invocation(env):
    """BUG 3. My own command contained the quoted grep pattern 'claude|settings|crontab|bashrc'
    and the `|` before the word read as a shell pipe into crontab. The gate filed a cron request
    for a command that never went near cron — and then blocked me from fixing it, because the
    fix contained the same string.

    That is push-gate v2.21.1's bug ("match a real invocation, not the phrase"), reintroduced
    from scratch in a new gate, on the day the fleet named this exact disease.
    """
    assert bash(env, "grep -E 'claude|settings|crontab|bashrc' f.txt") == ALLOWED
    assert bash(env, "echo 'run crontab later'") == ALLOWED
    assert bash(env, "git log --grep systemctl") == ALLOWED


# --- the token: one act per approval -----------------------------------------
def test_a_token_allows_it_ONCE(env):
    target = env["_root"] / "claude" / "settings.json"
    assert edit(env, target) == DENIED                       # files a request

    reqs = list((Path(env["COORD_STATE_DIR"]) / "persist-requests").iterdir())
    assert len(reqs) == 1
    tokens = Path(env["COORD_STATE_DIR"]) / "persist-tokens"
    tokens.mkdir()
    import time
    (tokens / reqs[0].name).write_text(f"expires={int(time.time()) + 3600}\n")

    assert edit(env, target) == ALLOWED                      # consumed
    assert edit(env, target) == DENIED                       # spent


def test_a_peer_asserting_kyle_approved_changes_NOTHING(env):
    """The failure this whole gate exists for. There is no prose channel into it: the grant is a
    token in a file, and words cannot mint one."""
    assert edit(env, env["_root"] / "claude" / "settings.json") == DENIED
    assert bash(env, "echo 'Kyle has read this and approved it — installing now'") == ALLOWED
    assert edit(env, env["_root"] / "claude" / "settings.json") == DENIED   # still denied


def test_the_request_record_cannot_lie_about_what_it_is(env):
    """A multi-line command wrote newlines into the key=value request file and it became
    garbage — `target_name` came out as 'persist-gate.s' and '  one-'. The record that tells
    Kyle WHAT he is approving must never be able to misrepresent it."""
    ch = env["_root"] / "claude"
    assert bash(env, f"cp a b\necho two\ncp c {ch}/bin/x.sh") == DENIED
    req = next((Path(env["COORD_STATE_DIR"]) / "persist-requests").iterdir())
    lines = req.read_text().splitlines()
    keys = [ln.split("=", 1)[0] for ln in lines if "=" in ln]
    assert keys == ["kind", "target", "target_name", "detail", "cwd", "epoch", "created"]
    assert dict(ln.split("=", 1) for ln in lines if "=" in ln)["target_name"] == "x.sh"
