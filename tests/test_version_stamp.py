"""The version is stamped in three places, and v2.40.0 bumped two of them.

win_conductor caught this from the Windows box while checking its rename: pyproject
said 2.40.0, `conductor/__init__.py` still said 2.39.0, and `/api/health` — which is
what the desktop settings header displays (CLAUDE.md, v2.7.0) — served the stale one
live. Nothing failed. Nothing logged. The UI simply told Kyle he was running the
previous release.

A stale version is the cheapest possible lie and one of the more expensive ones to
debug later, because every bug report that quotes it points at the wrong tree.

⚠️ AND THE SECOND WAY IT LIES, WHICH COST A RESTART TO FIND. Fixing the constant did
not fix the endpoint: `/api/health` kept serving 2.39.0 from a correct source file,
across a genuine service restart. CPython's default .pyc invalidation compares
(source mtime SECONDS, source SIZE) — and `"2.39.0"` and `"2.40.0"` are the same
number of bytes. A test run had imported the module while the file briefly held the
old string, and the restore landed in the SAME SECOND at the SAME SIZE, so the stale
bytecode matched on both fields and python trusted it forever. `conductor.__file__`
pointed at the right file the whole time. Cleared with `rm -rf conductor/__pycache__`.

⭐ THIS IS WHY THE TEST BELOW IMPORTS THE PACKAGE INSTEAD OF GREPPING ITS SOURCE.
Grepping the file would have been green while the running app served the old number —
i.e. it would have agreed with the bug. The import is what the app actually loads, so
the import is what must be compared. A check that reads something other than what
ships is not a weaker check; it is a check of the wrong thing.
"""

from __future__ import annotations

import re
from pathlib import Path

import conductor

ROOT = Path(__file__).resolve().parent.parent


def _pyproject_version() -> str:
    m = re.search(r'^version\s*=\s*"([^"]+)"', (ROOT / "pyproject.toml").read_text(), re.M)
    assert m, "pyproject.toml has no version line"
    return m.group(1)


def test_package_version_matches_pyproject():
    assert conductor.__version__ == _pyproject_version()


def test_readme_badge_matches_the_release_minor():
    """The badge carries MAJOR.MINOR only — patch releases do not touch it."""
    badge = re.search(r'version-(\d+\.\d+)-blue', (ROOT / "README.md").read_text())
    assert badge, "README lost its version badge"
    major_minor = ".".join(_pyproject_version().split(".")[:2])
    assert badge.group(1) == major_minor
