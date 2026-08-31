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
    """Split across two layers as of 2026-08-31, and the split is the point.

    `is_claude_process` answers "session process or infrastructure" — a question one process
    can answer alone. The launcher/worker choice needs to know whether a launcher EXISTS, so
    it moved to `select_sessions`. Keeping it in the predicate made a Linux daemon-hosted
    session (no launcher anywhere) invisible, because it is byte-identical to a Windows worker.
    """
    launcher, daemon, pty, worker = windows
    assert [is_claude_process(p) for p in windows] == [True, False, False, True]
    # ...and then exactly one survives, because a launcher exists for that cwd.
    cwd = "/proj"
    kept = scanner.select_sessions([(launcher, cwd, False), (worker, cwd, True)])
    assert kept == [launcher]


def test_the_launcher_is_the_one_kept_and_it_is_the_only_focusable_one(windows):
    """Not an aesthetic choice. The worker's ancestry runs back through the daemon, whose
    own parent is already gone, so find_terminal_pid can reach no terminal from it. The
    launcher's chain is claude.exe <- powershell.exe <- WindowsTerminal.exe."""
    launcher, _, _, worker = windows
    assert scanner.select_sessions(
        [(launcher, "/proj", False), (worker, "/proj", True)]) == [launcher]
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


# ==========================================================================================
# The daemon-hosted session: alive, remote-controllable from a phone, and INVISIBLE.
#
# Kyle, 2026-08-31: "95 qemu is up and running, i can talk to it remotely via my android
# phone but conductor on skippy isn't showing its tile."
#
# MEASURED on skippy, pid 135180. Claude Code 2.1.251 execs its VERSIONED BINARY directly
# instead of going through the `claude` shim, so both argv[0] and `comm` are a version
# number, and every branch of the predicate missed it:
#
#     comm        2.1.251
#     cmdline[0]  /home/kyle/.local/share/claude/versions/2.1.251
#
# This is win_conductor's Windows finding — "four live processes, zero matches, a board with
# no tiles" — arriving on Linux via a routine upgrade rather than a different OS. The class
# is what generalises: THE PROCESS IS NOT NECESSARILY NAMED AFTER THE PRODUCT, and a
# predicate keyed on the name silently stops finding sessions the day the launcher changes.
#
# The cmdlines below are copied verbatim from the live tree, not invented.
# ==========================================================================================

_VERSIONED = "/home/kyle/.local/share/claude/versions/2.1.251"
_TRANSCRIPT = "/home/kyle/.claude/projects/-home-kyle-Documents-GitHub-95emulator/324cd73c.jsonl"

DAEMON = ["/home/kyle/.local/bin/claude", "daemon", "run", "--json-path", "/home/kyle/.claude/x"]
PTY_HOST = ["claude bg-pty-host", "--bg-pty-host", "/tmp/cc-daemon-1000/941b46d9/pty/324c.sock",
            "168", "20", "--", _VERSIONED, "--resume", _TRANSCRIPT]
SESSION = [_VERSIONED, "--resume", _TRANSCRIPT, "--model", "claude-opus-5",
           "--permission-mode", "auto"]


def test_a_versioned_binary_is_a_session(table):
    """The bug itself: argv[0] is a version number, so the name test could never match."""
    add(table, 3180418, DAEMON)
    add(table, 135168, PTY_HOST, ppid=3180418)
    session = add(table, 135180, SESSION, ppid=135168)
    assert is_claude_process(session), \
        "a live session is invisible — this is the missing tile, exactly as Kyle saw it"


def test_the_daemon_and_its_pty_host_are_still_not_sessions(table):
    """Widening the predicate must not start counting the infrastructure.

    If it did, the cost is not a spare tile: `detect_collisions` counts live processes per
    cwd, and the pty host shares its session's cwd — so three processes in one repo would be
    reported to Kyle as an identity collision, which is a "close one of these" decision.
    """
    daemon = add(table, 3180418, DAEMON)
    pty = add(table, 135168, PTY_HOST, ppid=3180418)
    add(table, 135180, SESSION, ppid=135168)
    assert not is_claude_process(daemon), "the daemon would appear as a session"
    assert not is_claude_process(pty), "the pty host would double-count every daemon session"


def test_a_session_parented_to_a_pty_host_survives_the_parent_rule(table):
    """⭐ THE TRAP, and it would have kept the tile missing even after the argv fix.

    The parent-exclusion rule drops "a claude whose parent is also claude" because on Windows
    that means a worker spawned by a launcher. Here the parent IS the same binary — but it is
    a pty HOST, infrastructure that hosts the session rather than a session that spawned it.
    A bare "parent looks like claude" test excludes the very process we just made visible.

    "Parent is claude" and "parent is a session" were the same question until a topology
    arrived where they differed.
    """
    add(table, 135168, PTY_HOST, ppid=3180418)
    session = add(table, 135180, SESSION, ppid=135168)
    assert is_claude_process(session), \
        "the parent rule swallowed a real session hosted by a pty host"


def test_the_version_number_is_not_pinned(table):
    """A fix that hardcodes 2.1.251 re-breaks on the next upgrade, silently, the same way."""
    for ver in ("2.1.251", "2.2.0", "3.0.0-rc1", "99.99.99"):
        p = add(table, 1000, [f"/home/kyle/.local/share/claude/versions/{ver}", "--resume", "x"])
        assert is_claude_process(p), f"version {ver} would be invisible"


def test_a_launcher_spawning_a_worker_is_still_deduped():
    """The regression guard for what the parent rule was built for (win_conductor, Windows).

    Loosening it must not bring back two live processes for one session in one repo — that is
    a false identity collision, which asks Kyle to close one of them.
    """
    launcher, worker = object(), object()
    kept = scanner.select_sessions([(launcher, "/repo", False), (worker, "/repo", True)])
    assert kept == [launcher], "the worker came back as a second session in one repo"


def test_a_hosted_session_with_NO_launcher_survives():
    """⭐ Kyle's missing tile, at the layer that decides it.

    Same shape as the Windows worker, and nothing else is running for that cwd — so it is the
    session, not a duplicate. Dropping it unconditionally is what left him with a session he
    could drive from his phone and could not see.
    """
    worker = object()
    assert scanner.select_sessions([(worker, "/repo", True)]) == [worker]


def test_two_independent_launches_in_one_repo_are_still_a_collision():
    """The dedup must not swallow the thing detect_collisions exists to report."""
    a, b = object(), object()
    assert scanner.select_sessions([(a, "/repo", False), (b, "/repo", False)]) == [a, b]


def test_a_launcher_elsewhere_does_not_rescue_an_unrelated_worker():
    """has_launcher is keyed per-cwd; a launcher in another repo must not drop this worker."""
    other, worker = object(), object()
    kept = scanner.select_sessions([(other, "/other", False), (worker, "/repo", True)])
    assert kept == [other, worker]


def test_two_sessions_in_one_repo_survive_when_one_is_daemon_hosted(table, monkeypatch):
    """⚠️ MEASURED on skippy 2026-08-31, and it is the case that decides the dedup rule.

    The qualcomm repo held two live sessions with DIFFERENT --session-ids: one started in a
    terminal, one daemon-hosted under a pty host. Same cwd, unrelated conversations.

    If the daemon-hosted one counted as "hosted", the cwd rule would drop it as the terminal
    session's worker — silently hiding a genuine identity collision, which is precisely what
    detect_collisions exists to surface and what let two Claudes step on each other's git for
    ten hours in v2.35. Both must survive.
    """
    terminal = add(table, 1997819, ["claude"], ppid=1996108)
    add(table, 1996108, ["/bin/bash"], ppid=1)
    pty = add(table, 3844826, ["claude bg-pty-host", "--bg-pty-host", "/tmp/x.sock", "168", "42",
                               "--", _VERSIONED.replace("2.1.251", "2.1.237")], ppid=1675)
    hosted = add(table, 3844859, [_VERSIONED.replace("2.1.251", "2.1.237"),
                                  "--session-id", "b1e3c5a8", "--fork-session"], ppid=3844826)
    add(table, 1675, ["/lib/systemd/systemd", "--user"], ppid=1)

    assert is_claude_process(terminal) and is_claude_process(hosted)
    assert not is_claude_process(pty)
    # Neither is the other's worker, so neither is dropped and the collision stays visible.
    assert not scanner._is_hosted(hosted), \
        "the daemon-hosted session was read as a worker — a real second session would vanish"
    kept = scanner.select_sessions([(terminal, "/repo", False), (hosted, "/repo", False)])
    assert kept == [terminal, hosted]
