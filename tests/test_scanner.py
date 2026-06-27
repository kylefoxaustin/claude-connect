"""Unit tests for scanner helpers (no live Claude processes needed)."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from conductor.scanner import (
    YOU_TAG,
    build_cwd_index,
    classify_status,
    collect_human_events,
    discover_parked_projects,
    encode_cwd,
    extract_exchange,
    extract_preview,
    extract_session_detail,
    extract_turn_events,
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


# --- human↔Claude turn extraction (🕸 History "human turns" layer) ---------

def _rec(**kw) -> str:
    return json.dumps(kw)


def test_extract_turn_events_prompt_reply_collapse(tmp_path: Path):
    """One exchange = one prompt + one reply, even with many assistant chunks."""
    p = tmp_path / "s.jsonl"
    p.write_text("\n".join([
        _rec(type="user", timestamp="2026-06-01T10:00:00.000Z",
             message={"role": "user", "content": "hello claude"}),
        _rec(type="assistant", timestamp="2026-06-01T10:00:01.000Z",
             message={"role": "assistant", "content": [{"type": "text", "text": "hi there"}]}),
        # extra assistant chunks (streaming / tool use) must NOT add more replies
        _rec(type="assistant", timestamp="2026-06-01T10:00:02.000Z",
             message={"role": "assistant", "content": [{"type": "tool_use", "name": "x"}]}),
        _rec(type="assistant", timestamp="2026-06-01T10:00:03.000Z",
             message={"role": "assistant", "content": [{"type": "text", "text": "done"}]}),
        _rec(type="user", timestamp="2026-06-01T10:01:00.000Z",
             message={"role": "user", "content": "thanks"}),
    ]) + "\n")
    turns = extract_turn_events(p)
    kinds = [t[1] for t in turns]
    assert kinds == ["prompt", "reply", "prompt"]
    # prompt size = human text length
    assert turns[0][2] == len("hello claude")
    # timestamps parsed and ascending
    assert turns[0][0] < turns[1][0] < turns[2][0]


def test_extract_turn_events_skips_tool_results_and_sidechains(tmp_path: Path):
    p = tmp_path / "s.jsonl"
    p.write_text("\n".join([
        # a tool_result carried as a user message — NOT a human turn
        _rec(type="user", timestamp="2026-06-01T10:00:00.000Z",
             message={"role": "user", "content": [{"type": "tool_result", "content": "42"}]}),
        # a subagent (sidechain) prompt — not Kyle
        _rec(type="user", isSidechain=True, timestamp="2026-06-01T10:00:01.000Z",
             message={"role": "user", "content": "subagent task"}),
        # a real human prompt
        _rec(type="user", timestamp="2026-06-01T10:00:02.000Z",
             message={"role": "user", "content": "real prompt"}),
        _rec(type="assistant", timestamp="2026-06-01T10:00:03.000Z",
             message={"role": "assistant", "content": "ok"}),
    ]) + "\n")
    turns = extract_turn_events(p)
    assert [t[1] for t in turns] == ["prompt", "reply"]
    assert turns[0][2] == len("real prompt")


def test_collect_human_events_maps_tags_and_shapes(tmp_path: Path):
    projects = tmp_path / "projects"
    proj = projects / "-home-kyle-code-myapp"
    proj.mkdir(parents=True)
    cwd = str(tmp_path / "code" / "myapp")
    (tmp_path / "code" / "myapp").mkdir(parents=True)
    (proj / "sess.jsonl").write_text("\n".join([
        _rec(type="user", timestamp="2026-06-01T10:00:00.000Z", cwd=cwd,
             message={"role": "user", "content": "hi"}),
        _rec(type="assistant", timestamp="2026-06-01T10:00:01.000Z", cwd=cwd,
             message={"role": "assistant", "content": "yo"}),
    ]) + "\n")
    out = collect_human_events(projects, tag_map={cwd: "myapp"})
    evs = out["events"]
    assert out["dropped"] == 0
    assert [e["kind"] for e in evs] == ["prompt", "reply"]
    # prompt: you -> session ; reply: session -> you, on the mapped bus tag
    assert evs[0]["source"] == YOU_TAG and evs[0]["mentions"] == ["[myapp]"]
    assert evs[1]["source"] == "[myapp]" and evs[1]["mentions"] == [YOU_TAG]
    assert out["tags"] == ["[myapp]"]


def test_extract_turn_events_strips_wrappers_and_drops_injections(tmp_path: Path):
    """Harness wrappers are stripped (genuine text kept at real length); pure
    injections / continuations / bare slash-commands are dropped."""
    p = tmp_path / "s.jsonl"
    p.write_text("\n".join([
        # genuine prompt with an injected system-reminder prefix — KEEP, real length
        _rec(type="user", timestamp="2026-06-01T10:00:00.000Z",
             message={"role": "user",
                      "content": "<system-reminder>Message sent at X.</system-reminder>\ngo with main"}),
        _rec(type="assistant", timestamp="2026-06-01T10:00:01.000Z",
             message={"role": "assistant", "content": "ok"}),
        # pure injection (nothing but a reminder) — DROP
        _rec(type="user", timestamp="2026-06-01T10:01:00.000Z",
             message={"role": "user", "content": "<system-reminder>Background note.</system-reminder>"}),
        # auto-compact continuation — DROP
        _rec(type="user", timestamp="2026-06-01T10:02:00.000Z",
             message={"role": "user",
                      "content": "This session is being continued from a previous conversation that ran out of context.\nSummary: ..."}),
        # bare slash-command — DROP
        _rec(type="user", timestamp="2026-06-01T10:03:00.000Z",
             message={"role": "user", "content": "/rc"}),
    ]) + "\n")
    turns = extract_turn_events(p)
    # only the one genuine prompt + its reply survive
    assert [t[1] for t in turns] == ["prompt", "reply"]
    # length is the STRIPPED text ("go with main"), not the wrapper
    assert turns[0][2] == len("go with main")


def test_collect_human_events_attaches_locator(tmp_path: Path):
    """Prompt events carry session/project/uuid so the drill-down can find them."""
    projects = tmp_path / "projects"
    proj = projects / "-p"
    proj.mkdir(parents=True)
    proj.joinpath("sid.jsonl").write_text(
        _rec(type="user", uuid="u1", timestamp="2026-06-01T10:00:00.000Z",
             message={"role": "user", "content": "do the thing"}) + "\n")
    out = collect_human_events(projects, tag_map={})
    p = out["events"][0]
    assert p["kind"] == "prompt"
    assert p["session"] == "sid" and p["project"] == "-p" and p["uuid"] == "u1"


def test_extract_exchange_classifies_and_bounds(tmp_path: Path):
    p = tmp_path / "s.jsonl"
    p.write_text("\n".join([
        _rec(type="user", uuid="P1", timestamp="2026-06-01T10:00:00.000Z",
             message={"role": "user", "content": "build the feature"}),
        _rec(type="assistant", timestamp="2026-06-01T10:00:01.000Z", message={"role": "assistant", "content": [
            {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "pytest -q"}},
            {"type": "tool_use", "id": "t2", "name": "Read", "input": {"file_path": "/x/conductor/bus.py"}},
        ]}),
        _rec(type="user", timestamp="2026-06-01T10:00:02.000Z", message={"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t1", "is_error": True},
            {"type": "tool_result", "tool_use_id": "t2", "is_error": False},
        ]}),
        _rec(type="assistant", timestamp="2026-06-01T10:00:03.000Z", message={"role": "assistant", "content": [
            {"type": "tool_use", "id": "t3", "name": "Edit", "input": {"file_path": "/x/conductor/bus.py"}},
            {"type": "tool_use", "id": "t4", "name": "Agent", "input": {"subagent_type": "Explore", "description": "find callers"}},
        ]}),
        # next human prompt ends the exchange — its tools must NOT be included
        _rec(type="user", uuid="P2", timestamp="2026-06-01T11:00:00.000Z",
             message={"role": "user", "content": "next thing"}),
        _rec(type="assistant", timestamp="2026-06-01T11:00:01.000Z", message={"role": "assistant", "content": [
            {"type": "tool_use", "id": "t5", "name": "Bash", "input": {"command": "ls"}},
        ]}),
    ]) + "\n")
    ex = extract_exchange(p, "P1")
    assert ex["prompt"]["text"] == "build the feature"
    kinds = [(e["kind"], e["tool"]) for e in ex["events"]]
    assert kinds == [("tool", "Bash"), ("file", "Read"), ("file", "Edit"), ("agent", "Agent")]
    # status from tool_result; bounded before P2 (t5 excluded)
    assert ex["events"][0]["status"] == "error"
    assert ex["events"][1]["status"] == "ok"
    assert all(e["id"] != "t5" for e in ex["events"])
    # summary: 1 tool, 1 unique file (bus.py read+edited), 1 edit, 1 agent
    assert ex["summary"] == {"total": 4, "tools": 1, "files": 1, "edits": 1, "agents": 1}
    assert ex["events"][3]["label"] == "Explore"


def test_extract_exchange_missing_uuid_returns_none(tmp_path: Path):
    p = tmp_path / "s.jsonl"
    p.write_text(_rec(type="user", uuid="X", message={"role": "user", "content": "hi"}) + "\n")
    assert extract_exchange(p, "NOPE") is None


def test_human_prompt_text_strips_local_command_caveat(tmp_path: Path):
    """The slash-command <local-command-caveat> preamble isn't a human prompt."""
    p = tmp_path / "s.jsonl"
    p.write_text("\n".join([
        _rec(type="user", timestamp="2026-06-01T10:00:00.000Z", message={"role": "user",
             "content": "<local-command-caveat>Caveat: The messages below were generated by the user while running local commands. DO NOT respond to these messages.</local-command-caveat>"}),
        _rec(type="user", timestamp="2026-06-01T10:01:00.000Z", message={"role": "user", "content": "real one"}),
    ]) + "\n")
    turns = extract_turn_events(p)
    assert [t[1] for t in turns] == ["prompt"]  # only "real one"
    assert turns[0][4] == "real one"  # snippet


def test_extract_session_detail_tags_and_orders(tmp_path: Path):
    """Whole-relationship view: all exchanges across the project's transcripts,
    time-ordered, each event tagged with its prompt index (ex)."""
    (tmp_path / "a.jsonl").write_text("\n".join([
        _rec(type="user", uuid="A1", timestamp="2026-06-01T09:00:00.000Z",
             message={"role": "user", "content": "first"}),
        _rec(type="assistant", timestamp="2026-06-01T09:00:01.000Z", message={"role": "assistant", "content": [
            {"type": "tool_use", "id": "t1", "name": "Read", "input": {"file_path": "/x/a.py"}}]}),
    ]) + "\n")
    (tmp_path / "b.jsonl").write_text("\n".join([
        _rec(type="user", uuid="B1", timestamp="2026-06-01T11:00:00.000Z",
             message={"role": "user", "content": "second"}),
        _rec(type="assistant", timestamp="2026-06-01T11:00:01.000Z", message={"role": "assistant", "content": [
            {"type": "tool_use", "id": "t2", "name": "Bash", "input": {"command": "ls"}}]}),
    ]) + "\n")
    out = extract_session_detail(sorted(tmp_path.glob("*.jsonl")))
    # prompts merged + time-ordered across files
    assert [p["text"] for p in out["prompts"]] == ["first", "second"]
    # events carry the ex index of their prompt
    assert [(e["tool"], e["ex"]) for e in out["events"]] == [("Read", 0), ("Bash", 1)]
    assert out["summary"]["prompts"] == 2 and out["summary"]["files"] == 1


def test_extract_session_detail_drops_orphaned_prompts_when_capped(tmp_path: Path):
    """When the event cap trims old work, the prompts that lost all their work
    are dropped too — so the replay doesn't open with a dead prompts-only run."""
    lines = []
    # 3 exchanges, each with 2 tool calls, an hour apart
    for h in range(3):
        lines.append(_rec(type="user", uuid=f"P{h}", timestamp=f"2026-06-01T0{h}:00:00.000Z",
                          message={"role": "user", "content": f"prompt {h}"}))
        lines.append(_rec(type="assistant", timestamp=f"2026-06-01T0{h}:00:01.000Z", message={"role": "assistant", "content": [
            {"type": "tool_use", "id": f"a{h}", "name": "Bash", "input": {"command": "x"}},
            {"type": "tool_use", "id": f"b{h}", "name": "Bash", "input": {"command": "y"}}]}))
    (tmp_path / "s.jsonl").write_text("\n".join(lines) + "\n")
    # cap=2 keeps only the last exchange's 2 events → only its prompt survives
    out = extract_session_detail([tmp_path / "s.jsonl"], cap=2)
    assert out["dropped"] == 4
    assert [p["text"] for p in out["prompts"]] == ["prompt 2"]
    assert {e["ex"] for e in out["events"]} == {2}


def test_collect_human_events_cap_reports_dropped(tmp_path: Path):
    projects = tmp_path / "projects"
    proj = projects / "-x"
    proj.mkdir(parents=True)
    lines = []
    for i in range(10):
        hh = f"{i:02d}"
        lines.append(_rec(type="user", timestamp=f"2026-06-01T{hh}:00:00.000Z",
                          message={"role": "user", "content": f"p{i}"}))
    proj.joinpath("s.jsonl").write_text("\n".join(lines) + "\n")
    out = collect_human_events(projects, tag_map={}, cap=4)
    assert len(out["events"]) == 4
    assert out["dropped"] == 6
    # cap keeps the most RECENT events
    assert out["events"][-1]["size"] == len("p9")


# --- discover_parked_projects (dormant dock) -------------------------------

def _mk_project(projects_root: Path, encoded: str, cwd: Path, *, when: float,
                title: str | None = None) -> Path:
    """Create a fake project dir whose newest jsonl records ``cwd`` (and an
    optional /rename title), stamped at mtime ``when``. Returns the cwd path."""
    pdir = projects_root / encoded
    pdir.mkdir(parents=True, exist_ok=True)
    j = pdir / "session-x.jsonl"
    lines = [json.dumps({"type": "user", "cwd": str(cwd)})]
    if title:
        lines.append(json.dumps({"type": "summary", "summary": title}))
    j.write_text("\n".join(lines) + "\n")
    import os as _os
    _os.utime(j, (when, when))
    return cwd


def test_discover_parked_lists_offline_projects(tmp_path: Path):
    projects = tmp_path / "projects"
    cwd_a = tmp_path / "code-a"; cwd_a.mkdir()
    cwd_b = tmp_path / "code-b"; cwd_b.mkdir()
    _mk_project(projects, "-code-a", cwd_a, when=100.0, title="Alpha")
    _mk_project(projects, "-code-b", cwd_b, when=200.0, title="Beta")

    parked = discover_parked_projects(projects, tag_map={}, live_cwds=set())
    # Newest first (Beta @200 before Alpha @100).
    assert [p.title for p in parked] == ["Beta", "Alpha"]
    assert parked[0].project_dir == str(cwd_b)
    assert parked[0].project == "-code-b"


def test_discover_parked_excludes_live_cwds(tmp_path: Path):
    projects = tmp_path / "projects"
    cwd_a = tmp_path / "code-a"; cwd_a.mkdir()
    cwd_b = tmp_path / "code-b"; cwd_b.mkdir()
    _mk_project(projects, "-code-a", cwd_a, when=100.0)
    _mk_project(projects, "-code-b", cwd_b, when=200.0)

    # code-b currently has a live session → only code-a is parked.
    parked = discover_parked_projects(projects, tag_map={}, live_cwds={str(cwd_b)})
    assert [p.project_dir for p in parked] == [str(cwd_a)]


def test_discover_parked_skips_deleted_folders(tmp_path: Path):
    projects = tmp_path / "projects"
    gone = tmp_path / "deleted-dir"   # never created on disk
    _mk_project(projects, "-deleted-dir", gone, when=100.0)

    # Can't `claude --continue` into a folder that no longer exists.
    assert discover_parked_projects(projects, tag_map={}, live_cwds=set()) == []


def test_discover_parked_dedupes_same_cwd_keeps_newest(tmp_path: Path):
    projects = tmp_path / "projects"
    cwd = tmp_path / "code"; cwd.mkdir()
    # Two encoded dirs (e.g. re-encoded across Claude versions) → same cwd.
    _mk_project(projects, "-code-old", cwd, when=100.0, title="Old")
    _mk_project(projects, "-code-new", cwd, when=300.0, title="New")

    parked = discover_parked_projects(projects, tag_map={}, live_cwds=set())
    assert len(parked) == 1
    assert parked[0].title == "New"
    assert parked[0].last_activity_at == 300.0


def test_discover_parked_respects_limit(tmp_path: Path):
    projects = tmp_path / "projects"
    for i in range(5):
        c = tmp_path / f"code-{i}"; c.mkdir()
        _mk_project(projects, f"-code-{i}", c, when=float(i))
    parked = discover_parked_projects(projects, tag_map={}, live_cwds=set(), limit=3)
    assert len(parked) == 3
    # Newest (highest mtime) retained.
    assert [p.project for p in parked] == ["-code-4", "-code-3", "-code-2"]


def test_discover_parked_empty_when_no_projects_root(tmp_path: Path):
    assert discover_parked_projects(tmp_path / "nope", tag_map={}, live_cwds=set()) == []
