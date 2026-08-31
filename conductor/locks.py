"""One exclusive-lock primitive, so the rest of the tree never imports ``fcntl``.

``fcntl`` does not exist on Windows, and ``import fcntl`` at module scope in
``members.py`` took 21 test modules down at collection — everything that reaches
``conductor.main`` — which is a lot of blast radius for five lines.

⚠️ THE THING TO BE AFRAID OF HERE, and it is not portability:

    A lock that silently does nothing looks exactly like a lock that works,
    right up until two writers collide.

There is no output to check, no exception to catch, and the failure only appears
under contention that a single-threaded test never creates. So this module ships
with ``tests/test_locks.py``, which spawns real competing PROCESSES and fails if
updates are lost. If you change anything here, that test is the only thing that
can tell you whether you broke it — reading the code cannot.

─────────────────────────────────────────────────────────────────────────────
SCOPE, stated because the docstring it replaces claims more than this delivers
─────────────────────────────────────────────────────────────────────────────
``resources.py`` says of its lock: *"the same flock on <res>/.lock that bus.sh
uses, so this can never race a reserve/release/promote."* That is a claim about
**cross-language** exclusion — Python taking a lock that a bash process respects.

On Linux it holds: both sides call ``flock(2)`` on the same file, and the kernel
arbitrates. **On Windows it does not, and this module cannot fix it.** Git Bash
ships no ``flock`` at all (measured 2026-08-23), so `bus.sh` currently takes no
lock there for Python to contend with. What this module gives Windows is
Python↔Python exclusion, which is what ``members.py`` needs and is half of what
``resources.py`` claims.

Closing the other half needs the bash side, which is blocked on the pid question
(a lockfile shim needs a stale-lock breaker, a breaker needs a liveness test, and
`_claude_pid` has no MSYS process tree to walk). Until then, treat the
``resources.py`` comment as true on Linux and aspirational on Windows.
"""
from __future__ import annotations

import os
import sys
import time
from contextlib import contextmanager
from typing import IO, Iterator

_WINDOWS = sys.platform == "win32"

if _WINDOWS:
    import msvcrt
else:
    import fcntl

# msvcrt locks a BYTE RANGE from the current file position, not the whole file the
# way flock does. Both sides must agree on the same range or they do not contend at
# all — which is precisely the silent no-op above. One byte at offset 0 is the
# convention here; nothing outside this module should know or care.
_RANGE = 1

# msvcrt's blocking mode (LK_LOCK) gives up after ~10 attempts and raises OSError,
# so "blocking" is a lie at the C level and a caller that trusted it would surface a
# lock failure as a crash under load. Retry explicitly instead, and cap it, because
# waiting forever on a lock is its own outage.
_ACQUIRE_TIMEOUT_S = 30.0
_RETRY_STEP_S = 0.05


@contextmanager
def exclusive(fileobj: IO) -> Iterator[IO]:
    """Hold an exclusive lock on ``fileobj`` for the duration of the block.

    The file must be open for writing (``"w"``, ``"a+"``, ...); Windows will not
    lock a read-only handle. Released on the way out even if the body raises —
    which matters more here than usual, because a lock leaked by a crashed writer
    on Windows is not cleaned up by the OS as promptly as an flock is.
    """
    fd = fileobj.fileno()
    if _WINDOWS:
        fileobj.seek(0)
        deadline = time.monotonic() + _ACQUIRE_TIMEOUT_S
        while True:
            try:
                msvcrt.locking(fd, msvcrt.LK_NBLCK, _RANGE)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise TimeoutError(
                        f"could not acquire an exclusive lock on {getattr(fileobj, 'name', fd)!r} "
                        f"within {_ACQUIRE_TIMEOUT_S}s"
                    ) from None
                time.sleep(_RETRY_STEP_S)
        try:
            yield fileobj
        finally:
            # Unlock the SAME range from the SAME offset, or the lock leaks for the
            # lifetime of the handle and every later writer blocks on a ghost.
            try:
                fileobj.seek(0)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, _RANGE)
            except OSError:
                pass
    else:
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            yield fileobj
        finally:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            except OSError:
                pass
