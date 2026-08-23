"""The version is stamped in three places, and v2.40.0 bumped two of them.

win_conductor caught this from the Windows box while checking its rename: pyproject
said 2.40.0, `conductor/__init__.py` still said 2.39.0, and `/api/health` — which is
what the desktop settings header displays (CLAUDE.md, v2.7.0) — served the stale one
live. Nothing failed. Nothing logged. The UI simply told Kyle he was running the
previous release.

A stale version is the cheapest possible lie and one of the more expensive ones to
debug later, because every bug report that quotes it points at the wrong tree.
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
