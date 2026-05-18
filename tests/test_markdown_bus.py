"""Tests for the markdown (claude-bus) adapter."""

from __future__ import annotations

import asyncio
import textwrap
from pathlib import Path

import pytest

from conductor.bus import (
    MarkdownBusAdapter,
    list_known_tags,
    parse_markdown_blocks,
    read_pending,
)
from conductor.scanner import derive_tag, tag_to_state_basename


def test_parse_markdown_blocks_basic():
    text = textwrap.dedent("""
        ## 2025-05-01 09:30 [backend]

        Trained YOLO model, val mAP 0.87. Pushing weights.

        ## 2025-05-01 09:35 [frontend]

        Got it — wiring up the new endpoint.
    """).strip() + "\n"
    events = parse_markdown_blocks(text)
    assert len(events) == 2
    assert events[0].source_session == "[backend]"
    assert events[0].destination_session == "broadcast"
    assert events[0].topic == ""
    assert "Trained YOLO" in events[0].payload_summary
    assert events[1].source_session == "[frontend]"


def test_parse_markdown_blocks_skips_garbage_before_first_header():
    text = "ignored preamble\n\n## 2025-05-01 09:30 [docs]\n\nbody\n"
    events = parse_markdown_blocks(text)
    assert len(events) == 1
    assert events[0].source_session == "[docs]"
    assert events[0].payload_summary == "body"


def test_parse_markdown_blocks_handles_other_tag():
    text = "## 2025-05-01 12:00 [other:my-stuff]\n\nhi\n"
    events = parse_markdown_blocks(text)
    assert events[0].source_session == "[other:my-stuff]"


def test_parse_markdown_blocks_truncates_to_80():
    body = "x" * 200
    text = f"## 2025-05-01 09:30 [backend]\n\n{body}\n"
    events = parse_markdown_blocks(text)
    assert len(events[0].payload_summary) == 80


def test_derive_tag_known_dirs(monkeypatch, tmp_path: Path):
    # Map ~ → tmp_path so we can build the canonical paths without polluting $HOME.
    monkeypatch.setenv("HOME", str(tmp_path))
    backend_dir = tmp_path / "Documents/GitHub/keyhole"
    backend_dir.mkdir(parents=True)
    assert derive_tag(backend_dir) == "[backend]"

    frontend_dir = tmp_path / "Documents/GitHub/keyhole-UI"
    frontend_dir.mkdir(parents=True)
    assert derive_tag(frontend_dir) == "[frontend]"


def test_derive_tag_other_falls_back_to_basename(tmp_path: Path):
    weird = tmp_path / "anywhere/quux"
    weird.mkdir(parents=True)
    assert derive_tag(weird) == "[other:quux]"


def test_tag_to_state_basename():
    assert tag_to_state_basename("[backend]") == "backend"
    assert tag_to_state_basename("[other:my-stuff]") == "other:my-stuff"


def test_read_pending_present_and_absent(tmp_path: Path):
    # Canonical filename is the bracketed tag verbatim.
    (tmp_path / "[backend].pending").write_text("3\n")
    assert read_pending(tmp_path, "[backend]") == 3
    assert read_pending(tmp_path, "[frontend]") == 0


def test_read_pending_handles_garbage(tmp_path: Path):
    (tmp_path / "[docs].pending").write_text("not a number")
    assert read_pending(tmp_path, "[docs]") == 0


def test_read_pending_accepts_unbracketed_filename(tmp_path: Path):
    # Defensive fallback in case bus.sh ever strips brackets when writing.
    (tmp_path / "sizer.pending").write_text("9")
    assert read_pending(tmp_path, "[sizer]") == 9


def test_list_known_tags(tmp_path: Path):
    (tmp_path / "[backend].last-seen").write_text("")
    (tmp_path / "[docs].last-seen").write_text("")
    (tmp_path / "ignore.txt").write_text("")
    tags = sorted(list_known_tags(tmp_path))
    assert tags == ["[backend]", "[docs]"]


def test_list_known_tags_unbracketed_fallback(tmp_path: Path):
    (tmp_path / "frontend.last-seen").write_text("")
    assert list_known_tags(tmp_path) == ["[frontend]"]


def test_list_known_tags_missing_dir(tmp_path: Path):
    assert list_known_tags(tmp_path / "nope") == []


@pytest.mark.asyncio
async def test_markdown_bus_adapter_tails_appended_blocks(tmp_path: Path):
    log = tmp_path / "messages.md"
    log.write_text("")  # exists, empty

    adapter = MarkdownBusAdapter(log, poll_interval=0.05)
    await adapter.start()
    try:
        await asyncio.sleep(0.1)
        # Append two complete blocks; the adapter should emit the FIRST
        # immediately (its end is bounded by the second header), and the
        # second after the next poll if a sentinel header follows.
        with log.open("a") as f:
            f.write("## 2025-05-01 09:30 [backend]\n\nfirst body\n\n")
            f.write("## 2025-05-01 09:31 [frontend]\n\nsecond body\n\n")
            # Append a closing header so the second block becomes "complete".
            f.write("## 2025-05-01 09:32 [docs]\n\n")

        gen = adapter.stream_events()
        ev1 = await asyncio.wait_for(gen.__anext__(), timeout=2.0)
        ev2 = await asyncio.wait_for(gen.__anext__(), timeout=2.0)
        sources = {ev1.source_session, ev2.source_session}
        assert sources == {"[backend]", "[frontend]"}
    finally:
        await adapter.stop()
