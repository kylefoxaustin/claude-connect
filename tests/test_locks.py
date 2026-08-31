"""Does conductor.locks.exclusive actually EXCLUDE?

The failure this guards against has no symptom you can read: a lock that silently
does nothing looks exactly like a lock that works, until two writers collide. There
is no exception, no output, and single-threaded tests never create the contention
that would show it. So the only honest test is real competing PROCESSES over a real
file, with a read-modify-write wide enough to lose updates if the lock is absent.

⭐ The load-bearing test here is `test_the_control_loses_updates`. It runs the SAME
workers with the lock removed and asserts the counter comes out WRONG. Without it,
`test_no_lost_updates` proves nothing — it would pass just as happily against a
no-op lock, and a test that passes whether or not the feature works is not a test.
"""
from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
WORKERS = 8
BUMPS = 12          # each worker's read-modify-write cycles
EXPECTED = WORKERS * BUMPS

# A window wide enough that an unlocked interleave is near-certain, and narrow
# enough that the suite stays quick. The sleep is BETWEEN the read and the write:
# that is the whole race, and closing the window would make the control pass and
# the test worthless.
_WORKER = textwrap.dedent("""
    import sys, time
    sys.path.insert(0, {repo!r})
    from conductor.locks import exclusive
    counter, bumps, use_lock = sys.argv[1], int(sys.argv[2]), sys.argv[3] == "lock"

    for _ in range(bumps):
        with open(counter, "r+") as f:
            if use_lock:
                with exclusive(f):
                    f.seek(0)
                    n = int(f.read().strip() or "0")
                    time.sleep(0.002)
                    f.seek(0); f.truncate(); f.write(str(n + 1)); f.flush()
            else:
                f.seek(0)
                n = int(f.read().strip() or "0")
                time.sleep(0.002)
                f.seek(0); f.truncate(); f.write(str(n + 1)); f.flush()
""")


def _race(tmp_path: Path, mode: str) -> int:
    counter = tmp_path / f"counter-{mode}"
    counter.write_text("0", encoding="utf-8")
    worker = tmp_path / f"worker-{mode}.py"
    worker.write_text(_WORKER.format(repo=str(REPO)), encoding="utf-8")

    procs = [
        subprocess.Popen([sys.executable, str(worker), str(counter), str(BUMPS), mode])
        for _ in range(WORKERS)
    ]
    for p in procs:
        assert p.wait(timeout=120) == 0, "a worker crashed; the count would be meaningless"
    return int(counter.read_text(encoding="utf-8").strip())


def test_no_lost_updates(tmp_path):
    """8 processes x 12 read-modify-writes. Every bump must survive."""
    got = _race(tmp_path, "lock")
    assert got == EXPECTED, (
        f"lost {EXPECTED - got} of {EXPECTED} updates -- the lock is not excluding. "
        "On Windows this usually means the byte RANGE or the seek offset disagree "
        "between acquire and release, so two holders never contend."
    )


def test_the_control_loses_updates(tmp_path):
    """The same workers with the lock removed MUST corrupt the counter.

    This is what gives the test above its meaning. If this ever passes, the race
    window has closed (a faster disk, a changed sleep) and `test_no_lost_updates`
    has quietly stopped testing anything -- it would then be green against a lock
    that does nothing at all.
    """
    got = _race(tmp_path, "nolock")
    assert got < EXPECTED, (
        f"unlocked workers produced the correct answer ({got}); the race window has "
        "closed, so the locked test above is no longer evidence of anything. Widen "
        "the sleep between read and write, or add workers, until this fails again."
    )


def test_lock_is_released_after_an_exception(tmp_path):
    """A body that raises must not leak the lock -- the next acquire must not hang.

    Windows does not reclaim a leaked byte-range lock as promptly as the kernel
    reclaims an flock, so a leak here becomes an outage rather than a slow path.
    """
    from conductor.locks import exclusive

    f = tmp_path / "leaky"
    f.write_text("x", encoding="utf-8")
    with open(f, "r+") as fh:
        with pytest.raises(RuntimeError):
            with exclusive(fh):
                raise RuntimeError("boom")
        # Same handle, immediately: this would raise TimeoutError if the lock leaked.
        with exclusive(fh):
            pass
