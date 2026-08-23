"""Tests for the pure helpers in conductor.x11.

The tilix focus path (gdbus / wmctrl / xdotool) is integration-only and isn't
exercised here; we cover the parsing/validation that decides whether that path
even runs.
"""

from conductor.x11 import _parse_tilix_id, _TILIX_UUID_RE

_UUID = "51ba9199-a37d-4d96-91ec-11cee132dab6"


def _environ(*pairs: str) -> bytes:
    """Build a NUL-separated /proc/<pid>/environ blob from KEY=VALUE strings."""
    return b"\0".join(p.encode() for p in pairs) + b"\0"


def test_parse_tilix_id_extracts_uuid():
    env = _environ("PATH=/usr/bin", f"TILIX_ID={_UUID}", "HOME=/home/kyle")
    assert _parse_tilix_id(env) == _UUID


def test_parse_tilix_id_absent_returns_none():
    assert _parse_tilix_id(_environ("PATH=/usr/bin", "HOME=/home/kyle")) is None


def test_parse_tilix_id_empty_value_returns_none():
    assert _parse_tilix_id(_environ("TILIX_ID=")) is None


def test_parse_tilix_id_rejects_malformed():
    # A non-UUID value must not flow through to the gdbus parameter.
    assert _parse_tilix_id(_environ("TILIX_ID=not-a-uuid")) is None


def test_parse_tilix_id_not_confused_by_prefix():
    # A different var that merely starts with the same letters must be ignored.
    env = _environ("TILIX_IDENTITY=nope", f"TILIX_ID={_UUID}")
    assert _parse_tilix_id(env) == _UUID


def test_uuid_re_rejects_injection_attempt():
    assert _TILIX_UUID_RE.match("'] }; evil") is None
    assert _TILIX_UUID_RE.match(_UUID) is not None
