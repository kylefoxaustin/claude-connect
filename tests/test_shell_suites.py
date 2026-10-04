"""Run the shell suites under pytest, because otherwise they do not run at all.

⚠️ MEASURED 2026-08-31: this repo carries 30 `tests/*.sh` suites and `make test` is `pytest -q`,
which collects none of them. They were run by hand when written and not since.

One of them had been red for some time and nobody knew — `test-push-gate-noop-token.sh`, failing
4 of 11. The cause was not the gate: `core.hooksPath` is global, so the pre-push hook fired
inside the suite's own scratch repo in /tmp and DENIED its setup push, leaving no upstream, so
the very branch the suite exists to test was unreachable. The security control broke its own test
fixture, and the suite reported a defect the gate does not have.

⭐ That is M51 turned on the test suite itself — *a check that did not run looks exactly like a
check that passed* — and it is worse for a shell suite than for a unit test, because these cover
the parts with no Python at all: the gates, the bus, the cursor protocol, the push hook. The
highest-consequence code in the tree was the least-run.

Each suite is its own test id, so a failure names the file rather than collapsing 30 suites into
one red line. Suites are expected to self-skip (exit 0) when a dependency is unavailable, which
is how they already behave on a box without git.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
SUITES = sorted(p.name for p in HERE.glob("test-*.sh"))

# A suite that hangs is worse than one that fails: it stops the whole run with no output.
TIMEOUT_S = 180


def test_the_shell_suites_are_actually_discovered():
    """If a rename or a move ever empties this list, the wiring must fail loudly.

    An empty glob would make every suite 'pass' by not existing — which is the exact failure
    this file was written to end, reintroduced one level up.
    """
    assert len(SUITES) >= 25, f"only {len(SUITES)} shell suites discovered — the glob is wrong"


def test_no_shell_suite_is_orphaned_by_its_name():
    """A shell test named test_*.sh is never collected, so it never runs.

    The glob above is `test-*.sh` (hyphen). Two suites written on 2026-09-29 used an
    UNDERSCORE and were therefore invisible to it: they passed only when run by hand, and
    the suite totals reported alongside them — "735 passed", "741 passed" — did not
    include them. A test that does not run is indistinguishable from a test that passes.

    This asserts the naming instead of relying on anyone noticing, which is the same move
    as the emptiness check above: make the wiring fail loudly rather than quietly cover
    less than it claims.
    """
    orphans = sorted(p.name for p in HERE.glob("test_*.sh"))
    assert not orphans, (
        f"shell suites invisible to the test-*.sh glob: {orphans}. "
        "Rename with hyphens (test-foo-bar.sh) so pytest collects them."
    )


@pytest.mark.parametrize("suite", SUITES)
def test_shell_suite(suite: str):
    r = subprocess.run(["bash", str(HERE / suite)], capture_output=True, text=True,
                       timeout=TIMEOUT_S)
    if r.returncode != 0:
        tail = "\n".join((r.stdout + r.stderr).splitlines()[-25:])
        pytest.fail(f"{suite} failed (rc={r.returncode}):\n{tail}")
