"""Tests for the markdown (claude-bus) adapter."""

from __future__ import annotations

import asyncio
import textwrap
from pathlib import Path

import pytest

from conductor.bus import (
    MarkdownBusAdapter,
    compute_pending,
    list_known_tags,
    parse_markdown_blocks,
    read_pending,
    snapshot_history,
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


def _write_log(path: Path, blocks: list[tuple[str, str, str]]) -> None:
    """blocks = [(ts, tag, body), ...] → write a claude-bus markdown log."""
    parts = []
    for ts, tag, body in blocks:
        parts.append(f"## {ts} [{tag}]\n\n{body}\n")
    path.write_text("\n".join(parts))


def test_compute_pending_counts_unseen_from_other_tags(tmp_path: Path):
    log = tmp_path / "messages.md"
    _write_log(log, [
        ("2026-05-19 10:00", "sizer", "first"),
        ("2026-05-19 11:00", "backend", "second"),
        ("2026-05-19 12:00", "sizer", "third"),
    ])
    # pai-sizer last saw the bus at 10:30 — so 11:00 and 12:00 are pending.
    (tmp_path / "pai-sizer.last-seen").write_text("2026-05-19 10:30")
    assert compute_pending(log, tmp_path, "[pai-sizer]") == 2


def test_compute_pending_excludes_own_messages(tmp_path: Path):
    log = tmp_path / "messages.md"
    _write_log(log, [
        ("2026-05-19 11:00", "sizer", "from me"),
        ("2026-05-19 12:00", "backend", "from other"),
    ])
    (tmp_path / "sizer.last-seen").write_text("2026-05-19 10:00")
    # Only the [backend] message counts; [sizer] is the reader's own tag.
    assert compute_pending(log, tmp_path, "[sizer]") == 1


def test_compute_pending_no_last_seen_returns_zero(tmp_path: Path):
    log = tmp_path / "messages.md"
    _write_log(log, [("2026-05-19 11:00", "backend", "hi")])
    # No last-seen baseline → don't flood with historical messages.
    assert compute_pending(log, tmp_path, "[pai-sizer]") == 0


def test_compute_pending_accepts_bracketed_last_seen(tmp_path: Path):
    log = tmp_path / "messages.md"
    _write_log(log, [("2026-05-19 11:00", "backend", "hi")])
    (tmp_path / "[docs].last-seen").write_text("2026-05-19 10:00")
    assert compute_pending(log, tmp_path, "[docs]") == 1


def test_snapshot_history_counts_all_blocks(tmp_path: Path):
    log = tmp_path / "messages.md"
    _write_log(log, [
        ("2026-05-19 10:00", "sizer", "a"),
        ("2026-05-19 11:00", "backend", "b"),
    ])
    events, total = snapshot_history(log)
    assert total == 2
    assert [e.source_session for e in events] == ["[sizer]", "[backend]"]


def test_snapshot_history_missing_file(tmp_path: Path):
    assert snapshot_history(tmp_path / "nope.md") == ([], 0)


@pytest.mark.asyncio
async def test_markdown_bus_flushes_final_block_when_quiescent(tmp_path: Path):
    log = tmp_path / "messages.md"
    log.write_text("")

    adapter = MarkdownBusAdapter(log, poll_interval=0.05)
    await adapter.start()
    try:
        await asyncio.sleep(0.1)
        # A single appended block with no following header. The old behavior
        # buffered it forever; now it should flush once the file goes quiet.
        with log.open("a") as f:
            f.write("## 2026-05-19 16:21 [sizer]\n\n[pai-sizer] test message\n")
        gen = adapter.stream_events()
        ev = await asyncio.wait_for(gen.__anext__(), timeout=2.0)
        assert ev.source_session == "[sizer]"
        assert "test message" in ev.payload_summary
    finally:
        await adapter.stop()


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
