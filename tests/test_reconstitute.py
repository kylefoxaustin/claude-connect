"""Reconstitute plan logic (conductor/reconstitute.py) — the DR capstone's core.

Pure function of (roster, live_cwds, filesystem), so the fresh-machine rebuild is fully
testable off the target box.
"""

from __future__ import annotations

import os

from conductor.reconstitute import build_plan, plan_for


def _entry(cwd, **kw):
    e = {
        "tag": "[other:x]", "member": "x", "cwd": cwd, "is_repo": False,
        "git_remote": None, "git_branch": None, "git_head": None, "git_dirty": False,
        "last_active": 0.0, "tokens_out": 0, "transcript_bytes": 0, "transcript_paths": [],
    }
    e.update(kw)
    return e


def test_live_session_needs_nothing(tmp_path):
    d = tmp_path / "p"; d.mkdir()
    real = os.path.realpath(str(d))
    p = plan_for(_entry(str(d)), {real})
    assert p["status"] == "live"
    assert p["steps"] == []


def test_present_cwd_relaunches(tmp_path):
    d = tmp_path / "p"; d.mkdir()
    tx = tmp_path / "t.jsonl"; tx.write_text("{}\n")
    p = plan_for(_entry(str(d), transcript_paths=[str(tx)]), set())
    assert p["status"] == "present"
    assert any("--continue" in s for s in p["steps"])
    assert p["transcripts_present"] is True
    assert p["blockers"] == []


def test_repo_needs_clone_when_cwd_absent(tmp_path):
    gone = tmp_path / "notyet"       # never created
    tx = tmp_path / "t.jsonl"; tx.write_text("{}\n")
    p = plan_for(_entry(str(gone), is_repo=True, git_remote="https://h/r.git",
                        git_branch="main", transcript_paths=[str(tx)]), set())
    assert p["status"] == "clone"
    assert any("git clone https://h/r.git" in s for s in p["steps"])
    assert any("checkout main" in s for s in p["steps"])


def test_transcript_only_when_no_repo_and_gone(tmp_path):
    gone = tmp_path / "gone"
    tx = tmp_path / "t.jsonl"; tx.write_text("{}\n")
    p = plan_for(_entry(str(gone), is_repo=False, transcript_paths=[str(tx)]), set())
    assert p["status"] == "transcript-only"
    assert p["recoverable"] is True


def test_blocked_when_nothing_to_restore(tmp_path):
    gone = tmp_path / "gone"          # no dir, no repo, no transcript
    p = plan_for(_entry(str(gone)), set())
    assert p["status"] == "blocked"
    assert p["recoverable"] is False
    assert p["blockers"]


def test_missing_transcript_is_a_blocker_but_still_launchable(tmp_path):
    d = tmp_path / "p"; d.mkdir()
    # transcript path points at a file that doesn't exist
    p = plan_for(_entry(str(d), transcript_paths=[str(tmp_path / "missing.jsonl")]), set())
    assert p["status"] == "present"
    assert p["transcripts_present"] is False
    assert any("transcript not found" in b for b in p["blockers"])


def test_dirty_repo_warns_about_uncommitted_work(tmp_path):
    gone = tmp_path / "notyet"
    tx = tmp_path / "t.jsonl"; tx.write_text("{}\n")
    p = plan_for(_entry(str(gone), is_repo=True, git_remote="https://h/r.git",
                        git_dirty=True, transcript_paths=[str(tx)]), set())
    assert any("uncommitted work" in b for b in p["blockers"])


def test_build_plan_orders_action_first_and_counts(tmp_path):
    live_dir = tmp_path / "live"; live_dir.mkdir()
    present_dir = tmp_path / "present"; present_dir.mkdir()
    tx = tmp_path / "t.jsonl"; tx.write_text("{}\n")
    roster = {
        "host": "skippy", "home": "/home/kyle",
        "sessions": [
            _entry(str(live_dir), last_active=100.0, transcript_paths=[str(tx)]),
            _entry(str(tmp_path / "clone_me"), is_repo=True, git_remote="https://h/r.git",
                   last_active=50.0, transcript_paths=[str(tx)]),
            _entry(str(present_dir), last_active=200.0, transcript_paths=[str(tx)]),
        ],
    }
    live_cwds = {os.path.realpath(str(live_dir))}
    plan = build_plan(roster, live_cwds)
    assert plan["session_count"] == 3
    assert plan["counts"]["live"] == 1
    # clone + present rank before live; live sinks last
    assert plan["sessions"][0]["status"] == "clone"
    assert plan["sessions"][-1]["status"] == "live"
