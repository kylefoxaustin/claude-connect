"""Tests for the disaster-recovery fleet roster (conductor/roster.py)."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from conductor.roster import build_roster
from conductor.scanner import encode_cwd


def _write_transcript(
    projects_root: Path,
    cwd: str,
    *,
    usages: list[tuple[int, int]] | None = None,  # (output, cache_read) per turn
    name: str = "s1",
    summary: str | None = None,
    project_dir_name: str | None = None,
) -> Path:
    """Create ``projects_root/<encoded>/<name>.jsonl`` with records carrying cwd
    and optional usage blocks. Returns the transcript path."""
    enc = project_dir_name or encode_cwd(cwd)
    d = projects_root / enc
    d.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    for out, cache in usages or [(0, 0)]:
        lines.append(
            json.dumps(
                {
                    "type": "assistant",
                    "cwd": cwd,
                    "message": {
                        "usage": {
                            "output_tokens": out,
                            "cache_read_input_tokens": cache,
                            "input_tokens": 0,
                            "cache_creation_input_tokens": 0,
                        }
                    },
                }
            )
        )
    if summary:
        lines.append(json.dumps({"type": "summary", "summary": summary}))
    p = d / f"{name}.jsonl"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def _by_cwd(roster: dict, cwd: str) -> dict:
    real = os.path.realpath(cwd)
    for e in roster["sessions"]:
        if e["cwd"] == real:
            return e
    raise AssertionError(f"{cwd} not in roster")


def test_plain_dir_is_not_a_repo(tmp_path):
    proj = tmp_path / "work" / "plain"
    proj.mkdir(parents=True)
    root = tmp_path / "projects"
    _write_transcript(root, str(proj))
    e = _by_cwd(build_roster(root), str(proj))
    assert e["exists"] is True
    assert e["is_repo"] is False
    assert e["git_remote"] is None
    assert e["git_dirty"] is None


def test_cwd_gone_flagged_but_still_listed(tmp_path):
    """A transcript whose cwd was deleted is transcript-only recoverable."""
    gone = tmp_path / "work" / "vanished"
    root = tmp_path / "projects"
    _write_transcript(root, str(gone))  # note: never created on disk
    e = _by_cwd(build_roster(root), str(gone))
    assert e["exists"] is False
    assert e["is_repo"] is False
    assert e["transcript_paths"]  # still carries the --continue fuel


def test_tokens_aggregate_across_all_transcripts_for_a_cwd(tmp_path):
    proj = tmp_path / "work" / "multi"
    proj.mkdir(parents=True)
    root = tmp_path / "projects"
    _write_transcript(root, str(proj), name="a", usages=[(100, 900), (50, 400)])
    _write_transcript(root, str(proj), name="b", usages=[(25, 75)])
    e = _by_cwd(build_roster(root), str(proj))
    assert e["tokens_out"] == 175            # 100+50+25
    assert e["tokens_total"] == 100 + 900 + 50 + 400 + 25 + 75
    assert e["turns"] == 3
    assert len(e["transcript_paths"]) == 2


def test_multiple_encoded_dirs_same_cwd_grouped(tmp_path):
    """Re-encoded project dirs pointing at one cwd collapse to a single entry."""
    proj = tmp_path / "work" / "regrp"
    proj.mkdir(parents=True)
    root = tmp_path / "projects"
    _write_transcript(root, str(proj), name="old", project_dir_name="encoded-v1")
    _write_transcript(root, str(proj), name="new", project_dir_name="encoded-v2")
    roster = build_roster(root)
    matches = [e for e in roster["sessions"] if e["cwd"] == os.path.realpath(str(proj))]
    assert len(matches) == 1
    assert set(matches[0]["project_dirs"]) == {"encoded-v1", "encoded-v2"}
    assert len(matches[0]["transcript_paths"]) == 2


def test_member_map_divergence(tmp_path):
    """member != bare tag when the members file records a rename (keyhole->backend)."""
    proj = tmp_path / "work" / "keyhole"
    proj.mkdir(parents=True)
    root = tmp_path / "projects"
    _write_transcript(root, str(proj))
    e = _by_cwd(
        build_roster(root, member_map={"other:keyhole": "backend"}), str(proj)
    )
    assert e["tag"] == "[other:keyhole]"
    assert e["member"] == "backend"


def test_member_defaults_to_bare_tag(tmp_path):
    proj = tmp_path / "work" / "solo"
    proj.mkdir(parents=True)
    root = tmp_path / "projects"
    _write_transcript(root, str(proj))
    e = _by_cwd(build_roster(root), str(proj))
    assert e["member"] == "other:solo"


def test_tag_map_matches_live_bus(tmp_path):
    proj = tmp_path / "code" / "my-api"
    proj.mkdir(parents=True)
    root = tmp_path / "projects"
    _write_transcript(root, str(proj))
    e = _by_cwd(build_roster(root, {str(proj): "api"}), str(proj))
    assert e["tag"] == "[api]"


def test_roster_envelope_fields(tmp_path):
    root = tmp_path / "projects"
    root.mkdir()
    proj = tmp_path / "p"
    proj.mkdir()
    _write_transcript(root, str(proj))
    r = build_roster(root)
    assert r["schema"] == 1
    assert r["session_count"] == 1
    assert r["projects_root"] == str(root)
    assert "host" in r and "home" in r


def test_sorted_newest_first(tmp_path):
    root = tmp_path / "projects"
    a = tmp_path / "a"; a.mkdir()
    b = tmp_path / "b"; b.mkdir()
    pa = _write_transcript(root, str(a), name="a")
    pb = _write_transcript(root, str(b), name="b")
    os.utime(pa, (1000, 1000))
    os.utime(pb, (2000, 2000))
    r = build_roster(root)
    assert r["sessions"][0]["cwd"] == os.path.realpath(str(b))


def _have_git() -> bool:
    try:
        subprocess.run(["git", "--version"], capture_output=True, timeout=5)
        return True
    except (OSError, subprocess.SubprocessError):
        return False


@pytest.mark.skipif(not _have_git(), reason="git not available")
def test_git_repo_attribution_and_dirty(tmp_path):
    repo = tmp_path / "work" / "arepo"
    repo.mkdir(parents=True)
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@e",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@e"}

    def g(*a):
        subprocess.run(["git", "-C", str(repo), *a], check=True,
                       capture_output=True, env=env)

    g("init", "-q")
    g("remote", "add", "origin", "https://example.com/foo.git")
    (repo / "f.txt").write_text("hi\n")
    g("add", "f.txt")
    g("commit", "-q", "-m", "init")

    root = tmp_path / "projects"
    _write_transcript(root, str(repo))
    e = _by_cwd(build_roster(root), str(repo))
    assert e["is_repo"] is True
    assert e["git_remote"] == "https://example.com/foo.git"
    assert e["git_head"] and len(e["git_head"]) == 40
    assert e["git_dirty"] is False

    # Make it dirty.
    (repo / "f.txt").write_text("changed\n")
    e2 = _by_cwd(build_roster(root), str(repo))
    assert e2["git_dirty"] is True
