"""Which processes ARE a Claude session — and which merely run the same binary.

`win_conductor` booted Conductor on Windows 11 to check its rename and got this:

    {"sessions": [], "parked": [{... "session_id": "ffdcd7b5-...", "message_count": 604 ...}]}

That is the session writing the transcript, alive, reported as dormant. The scanner had
found the transcript, the title, the tag, 604 messages and the token usage — and then
classified the live session as parked, because `is_claude_process` returned False for all
four live `claude.exe` processes. A board with no tiles and everything in the dormant dock
reads as a scanner fault when it is process identification.

⚠️ ALL THREE ORIGINAL BRANCHES FAILED AT ONCE on the native build. Its own earlier report
named only the third (`basename` is `claude.exe`, not `claude`); measuring every branch
separately showed the first needs a literal `@anthropic-ai/claude-code` the native build
never emits, and the second needs a `node` that does not exist. There was no
almost-working branch to repair.

⭐ AND THE TRAP UNDER IT, which is why the fix is not a basename tweak: ONE SESSION RUNS
SEVERAL PROCESSES OF THE SAME BINARY. A daemon, a pty host, and the worker the pty host
starts. The pty host's argv carries the ENTIRE worker command after a bare `--`, so
`--session-id ffdcd7b5-...` appears in two different processes. Match on a joined argv and
you count one session twice, in one cwd, with one transcript — which `detect_collisions`
correctly reports as two Claudes in one repo. That is worse than zero tiles: it is a
plausible, self-consistent, false alarm on every Windows session.

Every Windows cmdline below is verbatim from `psutil.Process(pid).cmdline()` on that box.
"""

from __future__ import annotations

import pytest

from conductor import scanner
from conductor.scanner import is_claude_process


class FakeProc:
    """Only what the predicate touches: cmdline() and ppid()."""

    def __init__(self, pid: int, cmdline: list[str], ppid: int = 1) -> None:
        self.pid, self._cmdline, self._ppid = pid, cmdline, ppid

    def cmdline(self) -> list[str]:
        return self._cmdline

    def ppid(self) -> int:
        return self._ppid


@pytest.fixture
def table(monkeypatch):
    """A process table the parent lookup can walk, keyed by pid."""
    procs: dict[int, FakeProc] = {}

    def _lookup(pid):
        if pid not in procs:
            raise scanner.psutil.NoSuchProcess(pid)
        return procs[pid]

    monkeypatch.setattr(scanner.psutil, "Process", _lookup)
    return procs


def add(table, pid, cmdline, ppid=1):
    table[pid] = FakeProc(pid, cmdline, ppid)
    return table[pid]


# --------------------------------------------------------------------------------------
# The four live processes on the Windows box. Exactly one is the session.
# --------------------------------------------------------------------------------------

CLAUDE = r"C:\Users\kylef\.local\bin\claude.exe"
SID = "ffdcd7b5-fff1-486d-b155-b68f75e73321"
TRANSCRIPT = r"C:\Users\kylef\.claude\projects\...\fefd2bad.jsonl"
WORKER_ARGV = [CLAUDE, "--session-id", SID, "--fork-session", "--resume", TRANSCRIPT,
               "--reply-on-resume", "--permission-mode", "auto"]


@pytest.fixture
def windows(table):
    add(table, 20440, [r"C:\Windows\System32\powershell.exe"], ppid=9000)
    launcher = add(table, 19880, [CLAUDE], ppid=20440)
    daemon = add(table, 15948, [CLAUDE, "daemon", "run", "--origin", "transient",
                                "--spawned-by", '{"label":"claude","pid":19880}'], ppid=7484)
    pty = add(table, 10432, [CLAUDE, "--bg-pty-host", r"\\.\pipe\cc-daemon-979c-pty-ffdcd7b5",
                             "120", "30", "--"] + WORKER_ARGV, ppid=15948)
    worker = add(table, 16228, WORKER_ARGV, ppid=10432)
    return launcher, daemon, pty, worker


def test_exactly_one_of_the_four_is_a_session(windows):
    launcher, daemon, pty, worker = windows
    assert [is_claude_process(p) for p in windows] == [True, False, False, False]


def test_the_launcher_is_the_one_kept_and_it_is_the_only_focusable_one(windows):
    """Not an aesthetic choice. The worker's ancestry runs back through the daemon, whose
    own parent is already gone, so find_terminal_pid can reach no terminal from it. The
    launcher's chain is claude.exe <- powershell.exe <- WindowsTerminal.exe."""
    launcher, _, _, worker = windows
    assert is_claude_process(launcher) and not is_claude_process(worker)
    assert "WindowsTerminal.exe" in scanner.TERMINAL_NAMES


def test_the_pty_host_does_not_smuggle_the_worker_argv_in(windows):
    """`--session-id <sid>` appears in BOTH the pty host and the worker. A joined-argv test
    matches both; two live processes, one session id, one cwd = a false collision."""
    _, _, pty, worker = windows
    assert SID in " ".join(pty.cmdline()) and SID in " ".join(worker.cmdline())
    assert scanner._own_args(pty.cmdline()).count("--session-id") == 0
    assert not is_claude_process(pty)


# --------------------------------------------------------------------------------------
# POSIX must be untouched. This is the half that ships to Kyle's live fleet.
# --------------------------------------------------------------------------------------

@pytest.mark.parametrize("argv", [
    ["/home/kyle/.local/bin/claude"],                       # bare — a real session
    ["/home/kyle/.local/bin/claude", "--continue"],
    ["claude", "--continue"],
    ["/usr/bin/node", "/usr/lib/node_modules/@anthropic-ai/claude-code/cli.js"],
    ["/usr/bin/node", "/opt/bin/claude"],
])
def test_posix_sessions_still_match(table, argv):
    add(table, 100, ["/bin/bash"], ppid=1)
    assert is_claude_process(add(table, 101, argv, ppid=100))


def test_the_daemon_is_not_a_session(table):
    """True on Linux TODAY: skippy runs one. It lands in proc_groups and then reports "no
    resolvable transcript", which is noise about a process that was never a session."""
    add(table, 100, ["/bin/bash"], ppid=1)
    daemon = add(table, 101, ["/home/kyle/.local/bin/claude", "daemon", "run",
                              "--json-path", "/home/kyle/.claude/daemon.json"], ppid=100)
    assert not is_claude_process(daemon)


def test_a_tool_call_shell_spawned_by_a_session_is_not_a_session(table):
    """The old predicate matched this: a session's own `bash -c` whose command string
    mentions the claude-code path (the shell snapshot does). Parent-is-claude drops it."""
    session = add(table, 101, ["/home/kyle/.local/bin/claude", "--continue"], ppid=1)
    shell = add(table, 102, ["/bin/bash", "-c",
                             "source ~/.claude/shell-snapshots/snap.sh; "
                             "node /usr/lib/node_modules/@anthropic-ai/claude-code/cli.js --version"],
                ppid=101)
    assert is_claude_process(session) and not is_claude_process(shell)


def test_a_missing_parent_does_not_make_a_session_disappear(table):
    """The parent lookup must never be able to turn a real session into a non-session just
    because the parent exited between the two calls."""
    orphan = add(table, 101, ["/home/kyle/.local/bin/claude", "--continue"], ppid=999999)
    assert is_claude_process(orphan)


@pytest.mark.parametrize("argv", [[], ["/usr/bin/vim", "claude.py"], ["/bin/bash"],
                                  ["/usr/bin/node", "server.js"], ["/usr/bin/claudette"]])
def test_unrelated_processes_never_match(table, argv):
    assert not is_claude_process(add(table, 101, argv, ppid=1))
