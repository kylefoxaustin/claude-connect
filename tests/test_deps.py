"""The wait-for graph — who is blocked on whom.

The load-bearing decision here is the DEADLOCK vs MUTUAL STALL distinction. A cycle of
resource holds can never resolve itself and needs a human; a cycle through mail or a
service queue is just two sessions politely waiting each other out, and either could
break it by answering. Labelling both "deadlock" would be a plausible-but-wrong label —
precisely the failure class this fleet spent a day cataloguing — so it gets pinned down.
"""

from __future__ import annotations

import time

from conductor.deps import build_wait_graph, open_ask_edges

NOW = 1_800_000_000.0


def _bare(tag):
    t = tag.strip("[]")
    return t[6:] if t.startswith("other:") else t


def _g(**kw):
    # Existing tests express mail intent as directed_unread; translate to the mail_edges the graph
    # now consumes (an open-ask edge sender->recipient), so they keep testing the graph/cycle logic.
    du = kw.pop("directed_unread", {})
    mail = kw.pop("mail_edges", None)
    if mail is None:
        mail = []
        for tag, info in du.items():
            dst = _bare(tag)
            ts = info.get("latest_ts") or "2026-07-11 10:00"
            since = time.mktime(time.strptime(ts, "%Y-%m-%d %H:%M"))
            for s in info.get("senders", []):
                mail.append({"src": _bare(s), "dst": dst, "kind": "mail", "hard": False,
                             "why": "open question", "since": since, "age": max(0.0, NOW - since)})
    kw.setdefault("services", [])
    kw.setdefault("resources", [])
    kw.setdefault("live_tags", set())
    kw.setdefault("now", NOW)
    return build_wait_graph(mail_edges=mail, **kw)


# --- edges from each source --------------------------------------------------
def test_unread_mail_makes_the_sender_wait_on_the_recipient():
    g = _g(directed_unread={
        "[other:qualcomm]": {"count": 2, "senders": ["docs"], "latest_ts": "2026-07-11 10:00"},
    })
    assert len(g["edges"]) == 1
    e = g["edges"][0]
    assert (e["src"], e["dst"], e["kind"]) == ("docs", "qualcomm", "mail")   # docs waits ON qualcomm


def test_a_queued_job_makes_the_requester_wait_on_the_service():
    g = _g(services=[{
        "name": "image_gen",
        "serving": {"requester": "[other:tipometer]", "text": "buttons", "started": NOW - 60},
        "queue": [{"requester": "[other:docs]", "text": "banner", "epoch": NOW - 300}],
    }], live_tags={"[other:image_gen]"})
    pairs = {(e["src"], e["dst"]) for e in g["edges"]}
    assert pairs == {("tipometer", "image_gen"), ("docs", "image_gen")}
    assert all(e["kind"] == "service" for e in g["edges"])


def test_a_LIVE_service_is_in_flight_not_a_stall():
    """image_gen, 2026-07-17: it did the whole job off-book (never ran /svc-next), so the entry
    sat in the queue and the Blocked pane read it as a stall — while image_gen was the one WORKING.
    A queued/serving job in front of a LIVE service is fire-and-forget async work, not a trap:
    the edges exist (a real dependency) but they are SOFT (awaiting), so nobody is 'stuck'."""
    g = _g(services=[{
        "name": "image_gen",
        "serving": {"requester": "[other:tipometer]", "text": "buttons", "started": NOW - 60},
        "queue": [{"requester": "[other:docs]", "text": "banner", "epoch": NOW - 300}],
    }], live_tags={"[other:image_gen]"})
    assert all(e["hard"] is False for e in g["edges"])   # in-flight, not trapped
    assert g["blocked_count"] == 0                        # the phone shows "nobody stuck"
    assert g["awaiting_count"] == 2                       # tipometer + docs merely awaiting


def test_a_DEAD_service_with_a_queue_IS_a_stall():
    """The genuine stall: a queue in front of a service with NO live session — nobody is going to
    serve it, exactly the dead-reader signal. THAT is hard/stuck (a human must relaunch it)."""
    g = _g(services=[{
        "name": "image_gen",
        "serving": None,
        "queue": [{"requester": "[other:docs]", "text": "banner", "epoch": NOW - 300}],
    }], live_tags=set())          # image_gen not running
    assert all(e["hard"] is True for e in g["edges"])
    assert g["blocked_count"] == 1
    assert "OFFLINE" in g["edges"][0]["why"]


def test_a_resource_queue_points_at_the_HOLDER_not_the_board():
    """A board can't unblock you — the holder can. The edge must name the human-actionable
    target."""
    g = _g(resources=[{
        "name": "orin-agx",
        "lease": {"owner": "[other:qualcomm]", "queue": ["[other:docs]"], "acquired_epoch": NOW - 900},
    }])
    e = g["edges"][0]
    assert (e["src"], e["dst"]) == ("docs", "qualcomm")      # not ("docs", "orin-agx")
    assert e["resource"] == "orin-agx"


def test_an_OFFER_is_not_a_block():
    """Being offered a resource is your turn, not a wait."""
    g = _g(resources=[{
        "name": "gpu",
        "lease": {"owner": "[other:docs]", "offered": True, "queue": ["[other:qualcomm]"]},
    }])
    assert g["edges"] == []


def test_self_edges_are_dropped():
    g = _g(directed_unread={
        "[other:docs]": {"count": 1, "senders": ["docs"], "latest_ts": "2026-07-11 10:00"},
    })
    assert g["edges"] == []


# --- the distinction that matters -------------------------------------------
def test_resource_cycle_is_a_TRUE_DEADLOCK():
    """A holds board1 and wants board2; B holds board2 and wants board1. Nobody can move,
    ever, without a human."""
    g = _g(resources=[
        {"name": "orin", "lease": {"owner": "[other:a]", "queue": ["[other:b]"], "acquired_epoch": NOW}},
        {"name": "iq9",  "lease": {"owner": "[other:b]", "queue": ["[other:a]"], "acquired_epoch": NOW}},
    ])
    assert len(g["cycles"]) == 1
    c = g["cycles"][0]
    assert c["deadlock"] is True
    assert set(c["nodes"]) == {"a", "b"}
    assert "DEADLOCK" in c["label"]


def test_mail_cycle_is_a_MUTUAL_STALL_not_a_deadlock():
    """Each is waiting for the other to reply. Annoying and invisible — but either one
    could end it by simply answering. Calling this a deadlock would be a lie."""
    g = _g(directed_unread={
        "[other:a]": {"count": 1, "senders": ["b"], "latest_ts": "2026-07-11 10:00"},
        "[other:b]": {"count": 1, "senders": ["a"], "latest_ts": "2026-07-11 10:00"},
    })
    assert len(g["cycles"]) == 1
    c = g["cycles"][0]
    assert c["deadlock"] is False
    assert "mutual stall" in c["label"]


def test_mixed_cycle_is_not_called_a_deadlock():
    """A resource edge + a mail edge closing a loop is NOT a true deadlock: the mail half
    can be broken by replying. Only an all-resource cycle is unbreakable."""
    g = _g(
        resources=[{"name": "gpu", "lease": {"owner": "[other:b]", "queue": ["[other:a]"],
                                             "acquired_epoch": NOW}}],
        directed_unread={"[other:a]": {"count": 1, "senders": ["b"], "latest_ts": "2026-07-11 10:00"}},
    )
    assert len(g["cycles"]) == 1
    assert g["cycles"][0]["deadlock"] is False


def test_no_false_cycle_on_a_plain_chain():
    g = _g(directed_unread={
        "[other:b]": {"count": 1, "senders": ["a"], "latest_ts": "2026-07-11 10:00"},
        "[other:c]": {"count": 1, "senders": ["b"], "latest_ts": "2026-07-11 10:00"},
    })
    assert g["cycles"] == []            # a -> b -> c is a chain, not a loop


# --- bottlenecks -------------------------------------------------------------
def test_bottleneck_ranks_who_holds_up_the_most_sessions():
    g = _g(directed_unread={
        "[other:qualcomm]": {"count": 3, "senders": ["a", "b", "c"], "latest_ts": "2026-07-11 10:00"},
        "[other:docs]":     {"count": 1, "senders": ["a"],           "latest_ts": "2026-07-11 10:00"},
    }, live_tags={"[other:qualcomm]"})
    top = g["bottlenecks"][0]
    assert top["tag"] == "qualcomm"
    assert top["count"] == 3
    assert sorted(top["blocking"]) == ["a", "b", "c"]
    assert top["live"] is True
    assert g["bottlenecks"][1]["tag"] == "docs"
    # These are MAIL edges, so a/b/c are awaiting a reply — not trapped. Bottleneck
    # ranking still works (qualcomm IS the fleet's critical path) without the headline
    # number crying wolf.
    assert g["blocked_count"] == 0
    assert g["awaiting_count"] == 3


def test_edges_sorted_longest_suffering_first():
    g = _g(directed_unread={
        "[other:x]": {"count": 1, "senders": ["fresh"], "latest_ts": time.strftime(
            "%Y-%m-%d %H:%M", time.localtime(NOW - 60))},
        "[other:y]": {"count": 1, "senders": ["ancient"], "latest_ts": time.strftime(
            "%Y-%m-%d %H:%M", time.localtime(NOW - 7200))},
    })
    assert g["edges"][0]["src"] == "ancient"


def test_empty_fleet_is_quiet():
    g = _g()
    assert g == {"edges": [], "cycles": [], "bottlenecks": [], "blocked_count": 0,
                 "awaiting_count": 0}


def test_awaiting_a_reply_is_NOT_being_blocked():
    """The alarm must not cry wolf. Twenty sessions awaiting a reply on a fast fleet is a
    conversation, not a crisis — and a dashboard that shouts on a healthy fleet is one you
    learn to ignore, so it won't be believed the night something genuinely deadlocks.
    Only a resource/service wait means "cannot proceed"."""
    g = _g(directed_unread={
        "[other:b]": {"count": 3, "senders": ["a", "c"], "latest_ts": "2026-07-11 10:00"},
    })
    assert g["blocked_count"] == 0        # nobody is TRAPPED
    assert g["awaiting_count"] == 2       # a and c are merely awaiting a reply
    assert all(e["hard"] is False for e in g["edges"])


def test_a_resource_wait_IS_a_block():
    g = _g(resources=[{
        "name": "orin-agx",
        "lease": {"owner": "[other:h]", "queue": ["[other:a]"], "acquired_epoch": NOW},
    }])
    assert g["blocked_count"] == 1        # `a` genuinely cannot proceed
    assert g["awaiting_count"] == 0
    assert g["edges"][0]["hard"] is True


# --- open_ask_edges: the phantom-stall fix (image_gen, 2026-07-13) --------------------
def _bus(tmp_path, msgs):
    """msgs = [(ts, sender, body)] -> a markdown bus file path."""
    p = tmp_path / "messages.md"
    p.write_text("".join(f"## {ts} [{snd}]\n{body}\n\n" for ts, snd, body in msgs), encoding="utf-8")
    return p


def _edges(path, live, now):
    return {(e["src"], e["dst"]) for e in open_ask_edges(path, live, now=now)}


def test_open_ask_directed_question_unreplied_makes_an_edge(tmp_path):
    now = time.mktime(time.strptime("2026-07-13 12:00", "%Y-%m-%d %H:%M"))
    path = _bus(tmp_path, [("2026-07-13 11:00", "other:a", "to:other:b — got a sec? what's the offset?")])
    assert _edges(path, {"other:a", "other:b"}, now) == {("a", "b")}   # a waits on b


def test_open_ask_REPLIED_question_makes_NO_edge(tmp_path):
    now = time.mktime(time.strptime("2026-07-13 12:00", "%Y-%m-%d %H:%M"))
    path = _bus(tmp_path, [
        ("2026-07-13 11:00", "other:a", "to:other:b — what's the offset?"),
        ("2026-07-13 11:30", "other:b", "to:other:a — it's 0x1000"),   # b replied to a
    ])
    assert _edges(path, {"other:a", "other:b"}, now) == set()          # closed by reply


def test_open_ask_NON_question_directed_mail_makes_NO_edge(tmp_path):
    # "b has unread from a" but a asked nothing -> NOT a wait-for edge. The core of the bug.
    now = time.mktime(time.strptime("2026-07-13 12:00", "%Y-%m-%d %H:%M"))
    path = _bus(tmp_path, [("2026-07-13 11:00", "other:a", "to:other:b — fyi, shipped the fix.")])
    assert _edges(path, {"other:a", "other:b"}, now) == set()


def test_open_ask_BROADCAST_question_makes_NO_edge(tmp_path):
    now = time.mktime(time.strptime("2026-07-13 12:00", "%Y-%m-%d %H:%M"))
    path = _bus(tmp_path, [("2026-07-13 11:00", "other:a", "to:all — anyone know the offset?")])
    assert _edges(path, {"other:a", "other:b"}, now) == set()          # broadcast != directed ask


def test_open_ask_MIXED_cc_plus_all_is_still_a_broadcast(tmp_path):
    """The live false positive (93emulator, 2026-07-17): a fleet-wide CONCLUSION that cc's specific
    tags AND `to:all`, and happens to contain a `?`, minted a phantom "waiting on B" edge to every
    session it thanked. `to:all` is the broadcast signal even alongside named cc's — stripping it and
    counting the 3 remaining names as "directed" was the hole. No edge from a to:all message, period."""
    now = time.mktime(time.strptime("2026-07-13 12:00", "%Y-%m-%d %H:%M"))
    path = _bus(tmp_path, [(
        "2026-07-13 11:00", "other:a",
        "to:other:b to:other:c to:all — RESOLVED. isn't that great? thank you all.")])
    assert _edges(path, {"other:a", "other:b", "other:c"}, now) == set()


def test_open_ask_genuine_cc_WITHOUT_all_still_makes_edges(tmp_path):
    """The fix must not over-reach: a real directed question to a few named tags (no `to:all`) is
    still an open ask to each until they reply."""
    now = time.mktime(time.strptime("2026-07-13 12:00", "%Y-%m-%d %H:%M"))
    path = _bus(tmp_path, [(
        "2026-07-13 11:00", "other:a", "to:other:b to:other:c — which offset do you two use?")])
    assert _edges(path, {"other:a", "other:b", "other:c"}, now) == {("a", "b"), ("a", "c")}


def test_the_image_gen_phantom_a_cc_recipient_is_not_a_link(tmp_path):
    # image_gen is cc'd on a small directed msg but never ASKS orb_slam -> no image_gen->orb_slam edge.
    now = time.mktime(time.strptime("2026-07-13 20:10", "%Y-%m-%d %H:%M"))
    path = _bus(tmp_path, [
        ("2026-07-13 20:00", "other:holobench", "to:other:image_gen to:other:orb_slam — status ping, no q here"),
    ])
    assert ("image_gen", "orb_slam") not in _edges(path, {"other:image_gen", "other:orb_slam", "other:holobench"}, now)


def test_open_ask_stale_beyond_window_makes_NO_edge(tmp_path):
    now = time.mktime(time.strptime("2026-07-14 12:00", "%Y-%m-%d %H:%M"))   # >12h later
    path = _bus(tmp_path, [("2026-07-13 11:00", "other:a", "to:other:b — what's the offset?")])
    assert _edges(path, {"other:a", "other:b"}, now) == set()


def test_open_ask_to_operator_makes_NO_edge(tmp_path):
    # You don't "stall waiting on Kyle" — he acts, he doesn't post replies. Excluded like bus.sh waiting.
    now = time.mktime(time.strptime("2026-07-13 20:10", "%Y-%m-%d %H:%M"))
    path = _bus(tmp_path, [("2026-07-13 20:00", "other:a", "to:operator — should I push?")])
    assert _edges(path, {"other:a"}, now) == set()
    # but a co-addressed peer still gets an edge; operator is just dropped
    path2 = _bus(tmp_path, [("2026-07-13 20:00", "other:a", "to:other:b to:operator — offset? and fyi Kyle")])
    assert _edges(path2, {"other:a", "other:b"}, now) == {("a", "b")}


# --- dead-reader alarm (holobench) -------------------------------------------
from conductor.deps import silent_addressees


def _silent(path, **kw):
    kw.setdefault("silence_h", 4.0)
    kw.setdefault("addressed_window_h", 12.0)
    return {s["tag"]: s for s in silent_addressees(path, **kw)}


def test_silent_addressee_addressed_but_quiet_is_flagged(tmp_path):
    # b was addressed 1h ago, last posted 6h ago (> 4h silence) -> a silent addressee.
    now = time.mktime(time.strptime("2026-07-13 20:00", "%Y-%m-%d %H:%M"))
    path = _bus(tmp_path, [
        ("2026-07-13 14:00", "other:b", "to:all — shipping now"),          # b's last post, 6h ago
        ("2026-07-13 19:00", "other:a", "to:other:b — you there? status?"),  # addressed 1h ago
    ])
    s = _silent(path, now=now)
    assert "b" in s
    assert s["b"]["open_ask_count"] == 1 and s["b"]["addressed_by"] == ["a"]
    assert s["b"]["ever_posted"] and abs(s["b"]["silent_for"] - 6 * 3600) < 120


def test_a_session_that_HAS_been_posting_is_not_silent(tmp_path):
    now = time.mktime(time.strptime("2026-07-13 20:00", "%Y-%m-%d %H:%M"))
    path = _bus(tmp_path, [
        ("2026-07-13 19:00", "other:a", "to:other:b — status?"),
        ("2026-07-13 19:50", "other:b", "to:all — still grinding, no news"),  # posted 10m ago
    ])
    assert "b" not in _silent(path, now=now)                                  # talking, not silent


def test_a_session_nobody_addresses_is_not_flagged(tmp_path):
    now = time.mktime(time.strptime("2026-07-13 20:00", "%Y-%m-%d %H:%M"))
    path = _bus(tmp_path, [("2026-07-13 09:00", "other:b", "to:all — hello")])  # quiet 11h, unaddressed
    assert _silent(path, now=now) == {}                                        # no one waiting on it


def test_never_posted_but_addressed_is_the_worst_case(tmp_path):
    # holobench's dead /tmp watcher: addressed directly, has NEVER posted -> silent_for=None, severe.
    now = time.mktime(time.strptime("2026-07-13 20:00", "%Y-%m-%d %H:%M"))
    path = _bus(tmp_path, [("2026-07-13 19:30", "other:a", "to:other:ghost — you alive? answer?")])
    s = _silent(path, now=now)
    assert s["ghost"]["silent_for"] is None and s["ghost"]["ever_posted"] is False


def test_stale_addressing_outside_the_window_does_not_flag(tmp_path):
    # addressed 20h ago (> 12h window) -> nobody's tried recently, so not surfaced.
    now = time.mktime(time.strptime("2026-07-13 20:00", "%Y-%m-%d %H:%M"))
    path = _bus(tmp_path, [("2026-07-13 00:00", "other:a", "to:other:b — ping?")])
    assert _silent(path, now=now) == {}


def test_broadcast_is_not_addressing(tmp_path):
    # being cc'd on a to:all is not "being addressed" -> a quiet session cc'd on broadcasts is fine.
    now = time.mktime(time.strptime("2026-07-13 20:00", "%Y-%m-%d %H:%M"))
    path = _bus(tmp_path, [
        ("2026-07-13 10:00", "other:b", "to:all — hi"),
        ("2026-07-13 19:00", "other:a", "to:all — big announcement everyone should see?"),
    ])
    assert _silent(path, now=now) == {}


def test_operator_is_never_a_silent_addressee(tmp_path):
    # Kyle never posts bus replies, so he'd always look "silent" — excluded like the wait-graph.
    now = time.mktime(time.strptime("2026-07-13 20:00", "%Y-%m-%d %H:%M"))
    path = _bus(tmp_path, [("2026-07-13 19:00", "other:a", "to:operator — should I push?")])
    assert "operator" not in _silent(path, now=now)
