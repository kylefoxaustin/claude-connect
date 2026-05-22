"""Unit tests for scanner helpers (no live Claude processes needed)."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from conductor.scanner import (
    build_cwd_index,
    classify_status,
    encode_cwd,
    extract_preview,
    last_recorded_cwd,
    newest_jsonl,
    parse_custom_title,
    parse_session_meta,
)
from conductor.models import Status
from conductor.windows import _best_title_match, _token_match


def test_encode_cwd_replaces_slashes():
    assert encode_cwd("/home/kyle/code/keyhole") == "-home-kyle-code-keyhole"
    assert encode_cwd("/") == "-"


def test_encode_cwd_replaces_underscores_and_dots():
    # Current Claude replaces every non-alphanumeric char with '-', so paths with
    # underscores or dots map to hyphens (e.g. elm7_engine -> elm7-engine).
    assert encode_cwd("/home/u/elm7_engine") == "-home-u-elm7-engine"
    assert encode_cwd("/home/u/my.app") == "-home-u-my-app"
    # Existing hyphens are preserved (already valid).
    assert encode_cwd("/home/u/riscv-tools/riscv-baremetal") == "-home-u-riscv-tools-riscv-baremetal"


def test_last_recorded_cwd_tracks_latest(tmp_path: Path):
    j = tmp_path / "s.jsonl"
    j.write_text(
        json.dumps({"type": "user", "cwd": "/home/u/launch-dir"}) + "\n"
        + json.dumps({"type": "assistant", "cwd": "/home/u/launch-dir"}) + "\n"
        + json.dumps({"type": "user", "cwd": "/home/u/moved-dir"}) + "\n"
    )
    assert last_recorded_cwd(j) == "/home/u/moved-dir"


def test_last_recorded_cwd_none_when_absent(tmp_path: Path):
    j = tmp_path / "s.jsonl"
    j.write_text(json.dumps({"type": "user", "message": {}}) + "\n")
    assert last_recorded_cwd(j) is None


def test_build_cwd_index_maps_recorded_cwd_to_jsonl(tmp_path: Path):
    # A session launched in "launch-dir" (so its folder is named for that) but
    # whose latest record says it cd'd to "moved-dir" should be findable by the
    # moved cwd — this is the cwd-drift fallback.
    proj = tmp_path / "-home-u-launch-dir"
    proj.mkdir()
    (proj / "abc.jsonl").write_text(
        json.dumps({"type": "user", "cwd": "/home/u/launch-dir"}) + "\n"
        + json.dumps({"type": "user", "cwd": str(tmp_path / "moved-dir")}) + "\n"
    )
    (tmp_path / "moved-dir").mkdir()
    index = build_cwd_index(tmp_path)
    assert index[str(tmp_path / "moved-dir")] == proj / "abc.jsonl"


def test_classify_status_active():
    assert classify_status(0.5, alive=True, low_cpu=False) == Status.ACTIVE


def test_classify_status_warm():
    assert classify_status(15, alive=True, low_cpu=False) == Status.WARM


def test_classify_status_waiting_when_quiet_low_cpu():
    assert classify_status(60, alive=True, low_cpu=True) == Status.WAITING


def test_classify_status_idle():
    # 60s old, but high CPU → not waiting → idle.
    assert classify_status(60, alive=True, low_cpu=False) == Status.IDLE


def test_classify_status_dormant():
    assert classify_status(600, alive=True, low_cpu=False) == Status.DORMANT


def test_classify_status_ended():
    assert classify_status(1, alive=False, low_cpu=False) == Status.ENDED


def test_newest_jsonl_picks_most_recent(tmp_path: Path):
    a = tmp_path / "a.jsonl"; a.write_text("{}")
    time.sleep(0.01)
    b = tmp_path / "b.jsonl"; b.write_text("{}")
    assert newest_jsonl(tmp_path) == b


def test_parse_session_meta_finds_summary(tmp_path: Path):
    p = tmp_path / "session-abc.jsonl"
    lines = [
        {"type": "user", "message": {"role": "user", "content": "hi"}},
        {"type": "summary", "summary": "keyhole-yolo", "leafUuid": "x"},
        {"type": "assistant", "message": {"role": "assistant", "content": "ok"}},
    ]
    p.write_text("\n".join(json.dumps(o) for o in lines))
    sid, title, count = parse_session_meta(p)
    assert sid == "session-abc"
    assert title == "keyhole-yolo"
    assert count == 3


def test_parse_session_meta_no_summary(tmp_path: Path):
    p = tmp_path / "session-noname.jsonl"
    p.write_text(json.dumps({"type": "user", "message": {"content": "hi"}}))
    sid, title, count = parse_session_meta(p)
    assert sid == "session-noname"
    assert title is None
    assert count == 1


def test_parse_custom_title_from_head(tmp_path: Path):
    p = tmp_path / "s.jsonl"
    lines = [
        {"type": "customTitle", "customTitle": "Project: 95emulator", "sessionId": "s"},
        {"type": "user", "message": {"content": "hi"}},
    ]
    p.write_text("\n".join(json.dumps(o) for o in lines))
    assert parse_custom_title(p) == "Project: 95emulator"


def test_parse_custom_title_newest_wins(tmp_path: Path):
    p = tmp_path / "s.jsonl"
    lines = [
        {"type": "customTitle", "customTitle": "Old Name", "sessionId": "s"},
        {"type": "user", "message": {"content": "hi"}},
        {"type": "customTitle", "customTitle": "New Name", "sessionId": "s"},
    ]
    p.write_text("\n".join(json.dumps(o) for o in lines))
    assert parse_custom_title(p) == "New Name"


def test_parse_custom_title_absent(tmp_path: Path):
    p = tmp_path / "s.jsonl"
    p.write_text(json.dumps({"type": "user", "message": {"content": "hi"}}))
    assert parse_custom_title(p) is None


def test_best_title_match_prefers_most_specific():
    # tilix windows all share a pid; titles disambiguate.
    windows = [
        (0x1, 8040, "skippy ✳ Project keyhole-sizer"),
        (0x2, 8040, "skippy ✳ Project: Keyhole"),
        (0x3, 8040, "skippy ⠐ Project: 95emulator"),
    ]
    # "keyhole" appears in two titles; the shorter (Keyhole) is the better match.
    assert _best_title_match(windows, "keyhole") == 0x2
    # "keyhole-sizer" only matches the sizer window.
    assert _best_title_match(windows, "keyhole-sizer") == 0x1
    # customTitle match is exact.
    assert _best_title_match(windows, "Project: 95emulator") == 0x3


def test_token_match_handles_reworded_topic_title():
    # Session "rk182x-evk-setup-guide" vs an auto-topic window title that doesn't
    # substring-match it — token overlap should still pick the right window over
    # unrelated siblings sharing the terminal PID.
    windows = [
        (0x1, 8040, "✳ Project keyhole-sizer"),
        (0x2, 8040, "✳ Project: Keyhole"),
        (0x3, 8040, "✳ Build Rockchip RK182X EVK setup guide"),
    ]
    assert _token_match(windows, None, "rk182x-evk-setup-guide") == 0x3
    # No shared tokens anywhere -> no false positive.
    assert _token_match(windows, None, "totally-different-xyz") is None
    assert _token_match(windows, None, None) is None


def test_best_title_match_no_match_returns_none():
    windows = [(0x1, 8040, "skippy ✳ Project: Keyhole")]
    assert _best_title_match(windows, "nonexistent") is None
    assert _best_title_match(windows, None) is None


def test_extract_preview_text_blocks(tmp_path: Path):
    p = tmp_path / "s.jsonl"
    lines = [
        {"type": "user", "message": {"role": "user", "content": "old message"}},
        {"type": "assistant", "message": {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "Running yolo training "},
                {"type": "tool_use", "name": "Bash", "input": {"cmd": "ignore me"}},
                {"type": "text", "text": "at epoch 4/12, loss 0.341"},
            ],
        }},
    ]
    p.write_text("\n".join(json.dumps(o) for o in lines))
    preview = extract_preview(p)
    assert "Running yolo training" in preview
    assert "loss 0.341" in preview
    assert "ignore me" not in preview


def test_extract_preview_empty(tmp_path: Path):
    p = tmp_path / "empty.jsonl"
    p.write_text("")
    assert extract_preview(p) == ""
