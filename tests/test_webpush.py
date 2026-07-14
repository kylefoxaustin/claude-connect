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


def test_the_private_key_is_parseable_by_the_library_that_will_use_it(tmp_path):
    """THE TEST THAT WAS MISSING, and it cost a live failure.

    The first version stored a PEM. `test_keys_are_stable_across_calls` passed. So did
    `test_public_key_is_raw_base64url_not_pem`. Both tested the key against MY model of it.

    But `pywebpush` hands the private string straight to `Vapid.from_string`, which only
    understands base64url of the raw 32-byte scalar (or DER) — never a PEM. So every send
    raised, `send_one` caught it, and the phone said "couldn't deliver" with no clue why.
    The keys were exactly what I said they were, and useless to the only consumer that
    mattered.

    So this test asserts against the LIBRARY, not against my description of the format.
    """
    from py_vapid import Vapid01

    keys = load_or_create_keys(tmp_path)
    v = Vapid01.from_string(private_key=keys["private"])   # must not raise

    # ...and the round-tripped key must be the SAME one, i.e. it still matches the public
    # key baked into every existing subscription. A key that parses but is a different key
    # would silently authenticate nothing.
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
    raw = v.public_key.public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
    import base64
    assert base64.urlsafe_b64encode(raw).decode().rstrip("=") == keys["public"]


def test_a_legacy_PEM_key_is_migrated_not_regenerated(tmp_path):
    """Converting is not optional: the PUBLIC key is baked into the subscription the browser
    already made. Regenerating would leave the phone looking subscribed and never ringing —
    the exact silent failure this whole module is trying to avoid."""
    import json as _json

    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.serialization import (
        Encoding, NoEncryption, PrivateFormat, PublicFormat,
    )

    key = ec.generate_private_key(ec.SECP256R1())
    pem = key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()).decode()
    pub = key.public_key().public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
    import base64
    pub_b64 = base64.urlsafe_b64encode(pub).decode().rstrip("=")
    (tmp_path / "webpush-vapid.json").write_text(
        _json.dumps({"private": pem, "public": pub_b64}))

    got = load_or_create_keys(tmp_path)

    assert got["public"] == pub_b64            # SAME key — the subscription still works
    assert "-----BEGIN" not in got["private"]  # but now in the format pywebpush can read
    from py_vapid import Vapid01
    Vapid01.from_string(private_key=got["private"])   # and it parses


def test_the_vapid_subject_is_one_py_vapid_accepts():
    """The second config bug of the night, same root cause as the first: a value that was
    exactly what I said it was, and rejected by the library that had to use it.

    `socket.gethostname()` on this box is `skippy` — no dot — so `mailto:conductor@skippy`
    failed py_vapid's email regex, every send raised, and the phone said "couldn't deliver"
    with no clue why. So don't assert the SHAPE of the subject. Ask py_vapid.
    """
    from py_vapid import _check_sub

    from conductor.webpush import vapid_subject

    assert _check_sub(vapid_subject("skippy"))            # bare hostname -> skippy.local
    assert _check_sub(vapid_subject("skippy.tail1682c8.ts.net"))
    assert _check_sub(vapid_subject(""))                  # no hostname at all
    assert _check_sub(vapid_subject("weird host name"))   # garbage in, valid claim out


def test_the_vapid_subject_never_leaks_a_real_email():
    """It rides in a JWT to Google/Mozilla's push servers on every single notification, and
    this repo is public."""
    from conductor.webpush import vapid_subject
    assert "@gmail" not in vapid_subject("skippy")
    assert vapid_subject("skippy").startswith("mailto:conductor@")


# --- dead-reader page (holobench), opt-in only -------------------------------
def _dead():
    return {"tag": "rt1180", "open_ask_count": 2, "open_ask_from": ["holobench"],
            "addressed_by": ["holobench", "mcxn"], "dead": True, "live": False}


def test_dead_reader_absent_by_default():
    # notifiable's default two: passing no dead_readers means no third page.
    assert notifiable([], []) == []


def test_dead_reader_pages_when_passed():
    items = notifiable([], [], [_dead()])
    assert len(items) == 1
    it = items[0]
    assert it["key"] == "dead:rt1180" and it["tag"] == "deadreader"
    assert "holobench" in it["title"] and "isn't running" in it["title"]
