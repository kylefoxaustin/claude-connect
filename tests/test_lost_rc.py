"""Tests for the live-but-lost-/RC alarm (ARCHITECTURE_VISION §3.4.1, the rt1180 fix)."""
from conductor.deps import compute_lost_rc


def _sess(sid, bridged=False, rc_pending=False, member="m", preview="p"):
    return {"session_id": sid, "bridged": bridged, "rc_pending": rc_pending,
            "member": member, "project_dir": f"/repo/{member}", "preview": preview,
            "last_activity_at": 100.0}


def test_never_bridged_never_alarms():
    """A session Kyle simply doesn't drive from the phone must not be noise."""
    ever, since = set(), {}
    for t in (0, 3600, 7200):  # unbridged for two hours straight
        out = compute_lost_rc([_sess("s1", bridged=False)], ever, since, now=t, threshold_min=15)
    assert out == []
    assert "s1" not in ever


def test_bridged_tracks_and_does_not_alarm():
    ever, since = set(), {}
    out = compute_lost_rc([_sess("s1", bridged=True)], ever, since, now=0, threshold_min=15)
    assert out == []
    assert "s1" in ever          # remembered as having been on the phone
    assert "s1" not in since


def test_lost_it_below_threshold_no_alarm_yet():
    ever, since = {"s1"}, {}
    # first unbridged sighting at t=0, then 10 min later — still under the 15-min floor
    compute_lost_rc([_sess("s1")], ever, since, now=0, threshold_min=15)
    out = compute_lost_rc([_sess("s1")], ever, since, now=600, threshold_min=15)
    assert out == []
    assert since["s1"] == 0      # debounce anchor held


def test_lost_it_past_threshold_alarms():
    ever, since = {"s1"}, {}
    compute_lost_rc([_sess("s1", member="rt1180")], ever, since, now=0, threshold_min=15)
    out = compute_lost_rc([_sess("s1", member="rt1180")], ever, since, now=16 * 60, threshold_min=15)
    assert len(out) == 1
    assert out[0]["session_id"] == "s1"
    assert out[0]["member"] == "rt1180"
    assert out[0]["lost_rc_minutes"] == 16


def test_queued_reconnect_suppresses_alarm():
    """rc_pending means a /rc is already queued — recovering, not lost."""
    ever, since = {"s1"}, {}
    compute_lost_rc([_sess("s1")], ever, since, now=0, threshold_min=15)
    out = compute_lost_rc([_sess("s1", rc_pending=True)], ever, since, now=16 * 60, threshold_min=15)
    assert out == []
    assert "s1" not in since      # timer cleared while recovering


def test_rebridge_clears_the_alarm():
    ever, since = {"s1"}, {}
    compute_lost_rc([_sess("s1")], ever, since, now=0, threshold_min=15)
    out = compute_lost_rc([_sess("s1")], ever, since, now=16 * 60, threshold_min=15)
    assert len(out) == 1
    # Kyle reconnects -> bridged again -> alarm clears, timer reset
    out = compute_lost_rc([_sess("s1", bridged=True)], ever, since, now=17 * 60, threshold_min=15)
    assert out == []
    assert "s1" not in since


def test_dead_session_state_is_gc_d():
    """A relaunch mints a NEW session_id; the old one's state must not leak forever."""
    ever, since = {"s1"}, {}
    compute_lost_rc([_sess("s1")], ever, since, now=0, threshold_min=15)
    assert "s1" in since
    # s1 gone (session ended / relaunched as s2); it should be dropped from tracking
    compute_lost_rc([_sess("s2", bridged=True)], ever, since, now=60, threshold_min=15)
    assert "s1" not in since
    assert "s1" not in ever


def test_only_lost_sessions_alarm_among_a_mix():
    ever, since = {"lost", "fine"}, {}
    sessions = [
        _sess("lost", bridged=False, member="rt1180"),   # was bridged, now not
        _sess("fine", bridged=True, member="docs"),      # still on the phone
        _sess("virgin", bridged=False, member="new"),    # never bridged
    ]
    compute_lost_rc(sessions, ever, since, now=0, threshold_min=15)
    out = compute_lost_rc(sessions, ever, since, now=20 * 60, threshold_min=15)
    assert [a["member"] for a in out] == ["rt1180"]
