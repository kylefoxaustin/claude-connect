"""Tests for the settings loader."""

from __future__ import annotations

import textwrap
from pathlib import Path

from conductor.settings import Settings, dump_settings, load_settings


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


def test_dump_settings_round_trips(tmp_path: Path):
    p = tmp_path / "settings.toml"
    s = Settings()
    s.scanner.interval_seconds = 1.5
    s.ui.end_fadeout_seconds = 12.0
    s.bus.adapter = "markdown"
    dump_settings(s, p)
    reloaded = load_settings(p)
    assert reloaded.scanner.interval_seconds == 1.5
    assert reloaded.ui.end_fadeout_seconds == 12.0
    assert reloaded.bus.adapter == "markdown"
    assert reloaded.server.port == 8765


def test_dump_settings_preserves_types(tmp_path: Path):
    # bool/int/float/str must survive the hand-rolled TOML writer.
    p = tmp_path / "settings.toml"
    dump_settings(Settings(), p)
    text = p.read_text()
    assert "port = 8765" in text          # int, unquoted
    assert "interval_seconds = 3.0" in text  # float, unquoted
    assert 'adapter = "markdown"' in text    # str, quoted
