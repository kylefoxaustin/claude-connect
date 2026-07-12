"""Web Push — and specifically, what we REFUSE to notify about.

The restraint is the feature. An alarm that fires on a healthy fleet is one you learn to
swipe away, and a swiped-away alarm is not believed on the night it matters. So the policy
gets tests, not just the plumbing.
"""

from __future__ import annotations

import json

from conductor.webpush import (
    RENOTIFY_AFTER_S,
    add_sub,
    drop_sub,
    due,
    load_or_create_keys,
    notifiable,
    prune_sent,
    read_subs,
)


def _decision(sid="s1", q="Kill the process?"):
    return {
        "session_id": sid,
        "cwd": "/home/kyle/Documents/GitHub/image_gen",
        "questions": [{"question": q, "header": "H", "multiSelect": False,
                       "options": [{"label": "Yes", "description": ""}]}],
        "age": 120.0,
    }


def _push(key="k1"):
    return {"key": key, "repo_name": "claude-connect", "cwd": "/x",
            "cmd": "git push", "epoch": 1}


# --- the policy: two things page, nothing else -------------------------------
def test_a_blocked_question_pages():
    items = notifiable([_decision()], [])
    assert len(items) == 1
    assert items[0]["key"] == "decision:s1"
    assert "image_gen" in items[0]["title"]
    assert items[0]["body"] == "Kill the process?"
    assert items[0]["url"] == "/m?pane=inbox"     # lands on the SCREEN, not the front door


def test_a_gated_push_pages():
    items = notifiable([], [_push()])
    assert [i["key"] for i in items] == ["push:k1"]
    assert "claude-connect" in items[0]["title"]


def test_a_healthy_fleet_is_silent():
    """The whole point. Idle leases, queue depth, mutual stalls and unread mail all resolve
    themselves or wait — notifying about them would train Kyle to swipe us away, and then
    the one notification that mattered would be swiped away too."""
    assert notifiable([], []) == []


# --- reminder vs nag ---------------------------------------------------------
def test_a_new_item_rings_immediately():
    items = notifiable([_decision()], [])
    assert due(items, {}, now=1000.0) == items


def test_the_same_unanswered_item_does_not_ring_every_scan():
    items = notifiable([_decision()], [])
    sent = {"decision:s1": 1000.0}
    assert due(items, sent, now=1000.0 + 30) == []          # 30s later: silence


def test_but_it_does_remind_after_an_hour():
    items = notifiable([_decision()], [])
    sent = {"decision:s1": 1000.0}
    assert due(items, sent, now=1000.0 + RENOTIFY_AFTER_S + 1) == items


def test_an_answered_item_is_forgotten_so_the_next_one_rings():
    """If we kept the timestamp of a question that has since been answered, the SAME session
    asking a NEW question inside the hour would be silently suppressed — and the phone would
    look like it was working."""
    sent = {"decision:s1": 1000.0}
    assert prune_sent(sent, notifiable([], [])) == {}       # nothing pending -> forget it
    # And now a fresh question from that same session rings straight away.
    items = notifiable([_decision()], [])
    assert due(items, prune_sent(sent, notifiable([], [])), now=1000.0 + 5) == items


# --- subscriptions -----------------------------------------------------------
def test_resubscribing_the_same_device_replaces_it(tmp_path):
    """Browsers re-subscribe on their own schedule. If that appended, one phone would ring
    three times."""
    add_sub(tmp_path, {"endpoint": "https://push/1", "keys": {"p256dh": "a", "auth": "b"}})
    add_sub(tmp_path, {"endpoint": "https://push/1", "keys": {"p256dh": "c", "auth": "d"}})
    subs = read_subs(tmp_path)
    assert len(subs) == 1
    assert subs[0]["keys"]["p256dh"] == "c"      # the newer one wins


def test_two_devices_both_ring(tmp_path):
    add_sub(tmp_path, {"endpoint": "https://push/1", "keys": {}})
    add_sub(tmp_path, {"endpoint": "https://push/2", "keys": {}})
    assert len(read_subs(tmp_path)) == 2


def test_a_dead_device_can_be_dropped(tmp_path):
    add_sub(tmp_path, {"endpoint": "https://push/1", "keys": {}})
    drop_sub(tmp_path, "https://push/1")
    assert read_subs(tmp_path) == []


def test_garbage_subs_file_is_just_empty(tmp_path):
    (tmp_path / "webpush-subs.json").write_text("{not json")
    assert read_subs(tmp_path) == []


# --- VAPID -------------------------------------------------------------------
def test_keys_are_stable_across_calls(tmp_path):
    """Rotating the public key silently invalidates every existing subscription — the phone
    keeps 'working' and simply never rings again. So it must be generated once and kept."""
    a = load_or_create_keys(tmp_path)
    b = load_or_create_keys(tmp_path)
    assert a["public"] == b["public"]
    assert a["private"] == b["private"]
    assert (tmp_path / "webpush-vapid.json").stat().st_mode & 0o777 == 0o600


def test_public_key_is_raw_base64url_not_pem(tmp_path):
    """`applicationServerKey` must be the raw uncompressed P-256 point. A PEM here produces
    a subscription that every later push silently fails to authenticate against."""
    k = load_or_create_keys(tmp_path)["public"]
    assert "BEGIN" not in k and "=" not in k     # unpadded base64url, not PEM
    import base64
    raw = base64.urlsafe_b64decode(k + "==")
    assert len(raw) == 65 and raw[0] == 0x04     # uncompressed point marker
