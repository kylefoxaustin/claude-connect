"""Tests for conductor.members — the member-registry write side (v4 §3.4).

The format is a contract with member-registry.sh (the referee reads what this writes), so these
assert the on-disk shape too, not just the round-trip."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from conductor import members


def test_bind_creates_and_reads_back(tmp_path: Path):
    members.bind(tmp_path, "sid-a", "backend", project="keyhole")
    got = members.read_members(tmp_path)
    assert got == {"sid-a": {"member": "backend", "role": "peer", "project": "keyhole"}}


def test_default_role_is_peer(tmp_path: Path):
    members.bind(tmp_path, "sid-a", "backend")
    assert members.read_members(tmp_path)["sid-a"]["role"] == "peer"


def test_rebind_preserves_a_human_set_role(tmp_path: Path):
    members.bind(tmp_path, "sid-a", "backend")
    members.set_role(tmp_path, "backend", "observer")
    # a later auto-bind (e.g. next scan) with no role must NOT reset it
    members.bind(tmp_path, "sid-a", "backend")
    assert members.read_members(tmp_path)["sid-a"]["role"] == "observer"


def test_set_role_updates_all_sessions_of_a_member(tmp_path: Path):
    members.bind(tmp_path, "sid-a", "backend")
    members.bind(tmp_path, "sid-b", "backend")
    members.bind(tmp_path, "sid-c", "docs")
    n = members.set_role(tmp_path, "backend", "trusted")
    assert n == 2
    rows = members.read_members(tmp_path)
    assert rows["sid-a"]["role"] == "trusted"
    assert rows["sid-b"]["role"] == "trusted"
    assert rows["sid-c"]["role"] == "peer"  # untouched


def test_ensure_bound_is_stable_and_never_redrifts(tmp_path: Path):
    # first sighting binds member = initial tag
    assert members.ensure_bound(tmp_path, "sid-a", "backend", project="keyhole") == "backend"
    # a human sets a role
    members.set_role(tmp_path, "backend", "observer")
    # the session `cd`s -> next scan sees a DIFFERENT derived tag, but ensure_bound must NOT re-derive
    assert members.ensure_bound(tmp_path, "sid-a", "other:some-adjacent-repo") == "backend"
    rows = members.read_members(tmp_path)
    assert rows["sid-a"]["member"] == "backend"      # stable
    assert rows["sid-a"]["role"] == "observer"        # human's role preserved


def test_invalid_role_rejected(tmp_path: Path):
    members.bind(tmp_path, "sid-a", "backend")
    with pytest.raises(ValueError):
        members.set_role(tmp_path, "backend", "root")


def test_forget(tmp_path: Path):
    members.bind(tmp_path, "sid-a", "backend")
    assert members.forget(tmp_path, "sid-a") is True
    assert members.read_members(tmp_path) == {}
    assert members.forget(tmp_path, "sid-a") is False


def test_bind_is_noop_when_unchanged(tmp_path: Path):
    members.bind(tmp_path, "sid-a", "backend", project="keyhole")
    mtime1 = members.members_path(tmp_path).stat().st_mtime_ns
    members.bind(tmp_path, "sid-a", "backend", project="keyhole")  # identical
    mtime2 = members.members_path(tmp_path).stat().st_mtime_ns
    assert mtime1 == mtime2  # file not rewritten


def test_summary_groups_by_member(tmp_path: Path):
    members.bind(tmp_path, "sid-a", "backend")
    members.bind(tmp_path, "sid-b", "backend")
    members.set_role(tmp_path, "backend", "observer")
    s = members.members_summary(tmp_path)
    assert len(s) == 1
    assert s[0]["member"] == "backend"
    assert s[0]["role"] == "observer"
    assert set(s[0]["session_ids"]) == {"sid-a", "sid-b"}


def test_format_is_readable_by_the_shell_referee(tmp_path: Path):
    """The load-bearing contract: member-registry.sh must resolve what members.py writes."""
    members.bind(tmp_path, "sid-obs", "backend", project="keyhole")
    members.set_role(tmp_path, "backend", "observer")
    reg = Path(__file__).resolve().parent.parent / "bus" / "member-registry.sh"
    script = f'''
        export MEMBERS_FILE="{members.members_path(tmp_path)}"
        . "{reg}"
        echo "member=$(member_of sid-obs)"
        echo "role=$(role_of sid-obs)"
        echo "unbound=$(role_of sid-nope)"
    '''
    out = subprocess.run(["bash", "-c", script], capture_output=True, text=True).stdout
    assert "member=backend" in out
    assert "role=observer" in out
    assert "unbound=peer" in out  # the referee's unbound default


# --- dual-session collision detection (holobench) ----------------------------
def test_no_collision_when_each_member_has_one_session():
    live = [
        {"member": "other:a", "session_id": "sid-1", "name": "a"},
        {"member": "other:b", "session_id": "sid-2", "name": "b"},
    ]
    assert members.detect_collisions(live) == []


def test_two_live_sessions_one_member_is_a_collision():
    live = [
        {"member": "other:rt1180", "session_id": "sid-1", "name": "rt1180"},
        {"member": "other:rt1180", "session_id": "sid-2", "name": "rt1180"},
        {"member": "other:solo", "session_id": "sid-3", "name": "solo"},
    ]
    got = members.detect_collisions(live)
    assert len(got) == 1
    assert got[0]["member"] == "other:rt1180" and got[0]["count"] == 2
    assert {s["session_id"] for s in got[0]["sessions"]} == {"sid-1", "sid-2"}


def test_same_session_id_seen_twice_is_NOT_a_collision():
    # one session appearing twice in the input (dedup) must not read as two — count DISTINCT sids.
    live = [
        {"member": "other:a", "session_id": "sid-1", "name": "a"},
        {"member": "other:a", "session_id": "sid-1", "name": "a"},
    ]
    assert members.detect_collisions(live) == []


def test_blank_member_or_session_id_is_ignored():
    live = [
        {"member": "", "session_id": "sid-1"},
        {"member": "other:a", "session_id": ""},
    ]
    assert members.detect_collisions(live) == []
