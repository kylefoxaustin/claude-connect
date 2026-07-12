"""The wait-for graph — who is blocked on whom.

The load-bearing decision here is the DEADLOCK vs MUTUAL STALL distinction. A cycle of
resource holds can never resolve itself and needs a human; a cycle through mail or a
service queue is just two sessions politely waiting each other out, and either could
break it by answering. Labelling both "deadlock" would be a plausible-but-wrong label —
precisely the failure class this fleet spent a day cataloguing — so it gets pinned down.
"""

from __future__ import annotations

import time

from conductor.deps import build_wait_graph

NOW = 1_800_000_000.0


def _g(**kw):
    kw.setdefault("directed_unread", {})
    kw.setdefault("services", [])
    kw.setdefault("resources", [])
    kw.setdefault("live_tags", set())
    kw.setdefault("now", NOW)
    return build_wait_graph(**kw)


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
    }])
    pairs = {(e["src"], e["dst"]) for e in g["edges"]}
    assert pairs == {("tipometer", "image_gen"), ("docs", "image_gen")}
    assert all(e["kind"] == "service" for e in g["edges"])


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
