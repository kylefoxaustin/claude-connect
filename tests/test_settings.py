"""Tests for the settings loader."""

from __future__ import annotations

import textwrap
from pathlib import Path

from conductor.settings import load_settings


def test_load_settings_defaults_when_missing(tmp_path: Path):
    s = load_settings(tmp_path / "no-such.toml")
    assert s.server.port == 8765
    assert s.scanner.interval_seconds == 3.0


def test_load_settings_overrides(tmp_path: Path):
    p = tmp_path / "settings.toml"
    p.write_text(textwrap.dedent("""
        [server]
        port = 9000

        [scanner]
        interval_seconds = 1.5

        [ui]
        end_fadeout_seconds = 10.0
    """).strip())
    s = load_settings(p)
    assert s.server.port == 9000
    assert s.scanner.interval_seconds == 1.5
    assert s.ui.end_fadeout_seconds == 10.0
