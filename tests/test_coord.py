"""Fleet-coordination Phase 1 — auto-delivery (Part A).

The point: stop Kyle from being the fleet's message courier. A message *addressed
to* a session (``to:<tag>``) that the session hasn't read should wake an idle
recipient on its own — but never a busy one, never a broadcast, and never twice for
the same batch.
"""

from __future__ import annotations

import asyncio
import time
import types

import pytest

from conductor.bus import _address_targets, _plain_name, directed_unread_all
from conductor.main import _WAKE_MIN_INTERVAL, AppState, _WAKEABLE_STATUSES
from conductor.models import Status
from conductor.settings import load_settings


# --- addressing parse --------------------------------------------------------
def test_plain_name_normalizes():
    assert _plain_name("[other:qualcomm]") == "qualcomm"
    assert _plain_name("other:orb_slam") == "orb_slam"
    assert _plain_name("[backend]") == "backend"


def test_address_targets():
    assert _address_targets("to:qualcomm to:all — [x] hi") == frozenset({"qualcomm", "all"})
    assert _address_targets("to:other:orb_slam — [x] hi") == frozenset({"orb_slam"})
    assert _address_targets("just a broadcast, no address line") == frozenset()


# --- directed_unread_all -----------------------------------------------------
LOG = """\
## 2026-07-10 10:00 [other:alice]

to:bob — [alice] please run the thing

## 2026-07-10 10:05 [other:bob]

to:all — [bob] status update for everyone

## 2026-07-10 10:10 [other:carol]

to:bob to:dave — [carol] need both of you
"""


def _write(tmp_path, log=LOG, seen=None):
    msgs = tmp_path / "messages.md"
    msgs.write_text(log)
    state = tmp_path / "state"
    state.mkdir(exist_ok=True)
    for tag, ts in (seen or {}).items():
        (state / f"{tag}.last-seen").write_text(ts)
    return msgs, state


def test_directed_counts_only_addressed_messages(tmp_path):
    # bob and dave have a read-baseline (any live session does after its first prompt).
    seen = {"[other:bob]": "2026-01-01 00:00", "[other:dave]": "2026-01-01 00:00",
            "[other:alice]": "2026-01-01 00:00"}
    msgs, state = _write(tmp_path, seen=seen)
    r = directed_unread_all(msgs, state, ["[other:bob]", "[other:dave]", "[other:alice]"])
    assert r["[other:bob]"]["count"] == 2           # alice's + carol's, addressed to bob
    assert set(r["[other:bob]"]["senders"]) == {"alice", "carol"}
    assert r["[other:dave]"]["count"] == 1           # only carol's
    assert r["[other:alice]"]["count"] == 0          # nobody addressed alice


def test_never_checked_never_sent_has_no_unread_basis(tmp_path):
    """A brand-new session (no last-seen, never posted) must NOT get history dumped
    on it — same conservative baseline as the 📬 badge (v2.5.1)."""
    msgs, state = _write(tmp_path)  # no last-seen for anyone
    assert directed_unread_all(msgs, state, ["[other:dave]"])["[other:dave]"]["count"] == 0


def test_broadcast_does_not_count_as_directed(tmp_path):
    msgs, state = _write(tmp_path, seen={"[other:zed]": "2026-01-01 00:00"})
    # zed is on nobody's to: list, and bob's to:all broadcast must not count
    assert directed_unread_all(msgs, state, ["[other:zed]"])["[other:zed]"]["count"] == 0


def test_last_seen_baseline_excludes_read(tmp_path):
    msgs, state = _write(tmp_path, seen={"[other:bob]": "2026-07-10 10:07"})
    # bob read through 10:07 -> alice's 10:00 is read, carol's 10:10 is not
    assert directed_unread_all(msgs, state, ["[other:bob]"])["[other:bob]"]["count"] == 1


def test_own_messages_never_count(tmp_path):
    log = "## 2026-07-10 10:00 [other:bob]\n\nto:bob — [bob] note to self\n"
    msgs, state = _write(tmp_path, log=log, seen={"[other:bob]": "2026-01-01 00:00"})
    assert directed_unread_all(msgs, state, ["[other:bob]"])["[other:bob]"]["count"] == 0


# --- the wake ----------------------------------------------------------------
@pytest.fixture
def state(tmp_path):
    s = AppState(load_settings())
    # Isolate from the REAL coordination state: AppState loads the persisted wake
    # map on init and writes it back on change, so a test must never read the live
    # fleet's file — nor scribble on it.
    s.coord_root = tmp_path / "coord"
    s._wake_outstanding = {}
    return s


def _sess(tag, status):
    # `last_activity_at` and `project_dir` are on every real SessionRecord. A fake that
    # omits them is a fake that can pass while production crashes on the same path.
    return types.SimpleNamespace(tag=tag, status=status, pid=1, terminal_pid=2, title="t",
                                 window_title="w", project_dir="/p",
                                 last_activity_at=time.time())


def _run_wake(state, monkeypatch):
    calls = []
    monkeypatch.setattr("conductor.main.send_keys_to_session", lambda **kw: calls.append(kw) or True)
    asyncio.run(state._wake_unread_recipients())
    return calls


def _directed(ts="2026-07-10 17:00", count=1):
    return {"[other:qualcomm]": {"count": count, "senders": ["imx95"], "latest_ts": ts}}


def _seen(monkeypatch, value):
    """Stub the recipient's last-seen watermark (what it has actually read)."""
    monkeypatch.setattr("conductor.main._read_last_seen", lambda sd, tag: value)


def test_idle_recipient_woken_once_until_it_reads(state, monkeypatch):
    """Wake once, then stay quiet until the recipient's watermark advances."""
    _seen(monkeypatch, "2026-07-10 16:00")
    state.sessions = {"q": _sess("[other:qualcomm]", Status.IDLE)}
    state._directed_unread = _directed()
    assert len(_run_wake(state, monkeypatch)) == 1
    assert len(_run_wake(state, monkeypatch)) == 0          # still unread -> no re-nag


def test_new_mail_does_not_stack_a_second_check(state, monkeypatch):
    """THE ANTI-STACKING PROPERTY (rt1180emulator, 2026-07-11): more mail arriving
    while an injected /msg-check is still un-run must NOT queue another one. One
    check drains the whole backlog."""
    _seen(monkeypatch, "2026-07-10 16:00")                  # hasn't read anything new
    state.sessions = {"q": _sess("[other:qualcomm]", Status.IDLE)}
    state._directed_unread = _directed()
    assert len(_run_wake(state, monkeypatch)) == 1          # first wake
    state._directed_unread = _directed(ts="2026-07-10 17:30", count=2)   # more mail lands
    assert len(_run_wake(state, monkeypatch)) == 0          # was: 1 (the stacking bug)
    state._directed_unread = _directed(ts="2026-07-10 18:00", count=5)   # and more
    assert len(_run_wake(state, monkeypatch)) == 0


def test_wakes_again_once_the_recipient_has_read_AND_the_floor_has_passed(state, monkeypatch):
    """After it reads (watermark advances), fresh mail may wake it again — but NOT immediately.

    This test used to assert an instant re-wake, and that assertion was the bug. Reading
    clears the dedup, so a session the fleet is actively talking to got woken on EVERY new
    message: qualcomm took **12 keystroke injections in one hour**, each one stealing focus
    mid-work. The watermark dedup only ever stopped repeats WITHIN one batch; nothing capped
    the rate ACROSS batches.

    So there is now a floor. Auto-delivery is not a pager — nothing on this bus is so urgent
    it cannot wait ten minutes, and one /msg-check drains the whole backlog anyway, so a
    deferred wake delivers MORE when it fires, not less.
    """
    _seen(monkeypatch, "2026-07-10 16:00")
    state.sessions = {"q": _sess("[other:qualcomm]", Status.IDLE)}
    state._directed_unread = _directed()
    assert len(_run_wake(state, monkeypatch)) == 1

    _seen(monkeypatch, "2026-07-10 17:05")                  # it ran the check
    state._directed_unread = _directed(ts="2026-07-10 17:30", count=1)   # new mail arrives

    # Inside the floor: silence, even though it has read and there IS fresh mail.
    assert _run_wake(state, monkeypatch) == []

    # Once the floor has passed, it is eligible again.
    state._woke_at["[other:qualcomm]"] = time.time() - _WAKE_MIN_INTERVAL - 1
    assert len(_run_wake(state, monkeypatch)) == 1


def test_a_message_ccd_to_half_the_fleet_does_not_wake_you(state, monkeypatch):
    """An announcement wearing directed-mail clothes.

    `to:a to:b to:c to:d to:e to:f` is not six people each blocking on you — it is one person
    telling everyone something. The fleet tag-ccs nearly every broadcast, which defeated the
    directed/broadcast distinction entirely: `docs` asked THREE TIMES to be exempted, and
    qualcomm was woken 12 times in an hour. Exempting sessions one at a time treats the
    symptom; the cc IS the disease.

    It still COUNTS (the badge shows it — the human should see the cc). It just isn't an
    interruption.
    """
    _seen(monkeypatch, "2026-07-10 16:00")
    state.sessions = {"q": _sess("[other:qualcomm]", Status.IDLE)}
    state._directed_unread = {
        "[other:qualcomm]": {"count": 5, "senders": ["docs"], "latest_ts": "2026-07-10 17:00",
                             "wakeable": 0},          # all five were mass-ccs
    }
    assert _run_wake(state, monkeypatch) == []


@pytest.mark.parametrize("status", [Status.ACTIVE, Status.WARM, Status.WAITING])
def test_busy_or_attended_recipient_never_woken(state, monkeypatch, status):
    state.sessions = {"q": _sess("[other:qualcomm]", status)}
    state._directed_unread = _directed()
    assert _run_wake(state, monkeypatch) == []
    assert status not in _WAKEABLE_STATUSES


def test_idle_recipient_not_rewoken_after_active_blip(state, monkeypatch):
    """Regression for the '17 /msg-checks in a row' loop (95emulator, 2026-07-10).

    Injecting /msg-check flips the recipient ACTIVE while it runs `bus.sh check`.
    The same unread batch must NOT re-wake it when it returns to idle — even though
    it left and re-entered the wakeable set. Before the fix this re-armed every scan.
    """
    _seen(monkeypatch, "2026-07-10 16:00")
    sess = _sess("[other:qualcomm]", Status.IDLE)
    state.sessions = {"q": sess}
    state._directed_unread = _directed()
    assert len(_run_wake(state, monkeypatch)) == 1     # legit first wake
    sess.status = Status.ACTIVE                          # running the injected check
    assert len(_run_wake(state, monkeypatch)) == 0     # busy: skipped, key retained
    sess.status = Status.IDLE                            # check done, batch still unread
    assert len(_run_wake(state, monkeypatch)) == 0     # MUST stay quiet (was 17x)


def test_no_directed_unread_no_wake(state, monkeypatch):
    state.sessions = {"q": _sess("[other:qualcomm]", Status.IDLE)}
    state._directed_unread = {"[other:qualcomm]": {"count": 0, "senders": [], "latest_ts": ""}}
    assert _run_wake(state, monkeypatch) == []


def test_autodeliver_off_switch(state, monkeypatch):
    state.settings.bus.autodeliver = False
    state.sessions = {"q": _sess("[other:qualcomm]", Status.IDLE)}
    state._directed_unread = _directed()
    assert _run_wake(state, monkeypatch) == []


def test_autodeliver_exempts_the_operator_console(state, monkeypatch):
    """The session you're actively working in (e.g. the dev console) must never be
    auto-woken. Bracketed/bare spellings both match."""
    state.settings.bus.autodeliver_exempt = ["[other:claude-connect]"]
    state.sessions = {"c": _sess("[other:claude-connect]", Status.IDLE)}
    state._directed_unread = {"[other:claude-connect]": {"count": 3, "senders": ["x"], "latest_ts": "t"}}
    assert _run_wake(state, monkeypatch) == []
    # a non-exempt session with the same unread is still woken
    state.sessions = {"q": _sess("[other:qualcomm]", Status.IDLE)}
    state._directed_unread = _directed()
    assert len(_run_wake(state, monkeypatch)) == 1


# --- retraction (Part B) -----------------------------------------------------
# A retraction is urgent: the recipient may be about to run the very step being
# pulled back. So it's the ONE wake that overrides the busy guard.

from conductor.coord import read_retractions  # noqa: E402


def _write_retraction(tmp_path, target_plain="qualcomm", sender="[other:orb_slam]",
                      created="2026-07-10 17:25", epoch=None, text="scrap the int8 patch"):
    import time as _t
    epoch = int(_t.time()) if epoch is None else epoch
    rdir = tmp_path / "retractions"
    rdir.mkdir(exist_ok=True)
    (rdir / f"{epoch}-{target_plain}").write_text(
        f"sender={sender}\ntarget={target_plain}\ntarget_plain={target_plain}\n"
        f"kind=RETRACTION\ncreated={created}\nepoch={epoch}\ntext={text}\n"
    )


def test_read_retractions_skips_expired(tmp_path):
    _write_retraction(tmp_path, epoch=100)                      # ancient -> expired
    _write_retraction(tmp_path, target_plain="docs")           # fresh
    active = read_retractions(tmp_path)
    assert [r["target_plain"] for r in active] == ["docs"]


def _run_retraction_wake(state, monkeypatch):
    calls = []
    monkeypatch.setattr("conductor.main.send_keys_to_session", lambda **kw: calls.append(kw) or True)
    asyncio.run(state._wake_retractions())
    return calls


@pytest.mark.parametrize("status", [Status.ACTIVE, Status.WARM, Status.IDLE, Status.WAITING])
def test_retraction_wakes_even_a_busy_target(state, monkeypatch, status):
    """The busy-guard is intentionally overridden here — a busy recipient is the
    dangerous case (it may be mid-action)."""
    state.sessions = {"q": _sess("[other:qualcomm]", status)}
    state._retractions = [{"id": "r1", "sender": "[other:orb_slam]",
                           "target_plain": "qualcomm", "text": "stop", "created": "x", "epoch": 1}]
    assert len(_run_retraction_wake(state, monkeypatch)) == 1     # woken regardless of status
    assert len(_run_retraction_wake(state, monkeypatch)) == 0     # once per record


def test_retraction_for_dead_target_is_left_to_the_hook(state, monkeypatch):
    state.sessions = {}
    state._retractions = [{"id": "r1", "sender": "[x]", "target_plain": "qualcomm",
                           "text": "stop", "created": "x", "epoch": 1}]
    assert _run_retraction_wake(state, monkeypatch) == []


# --- push gate (Phase 2) -----------------------------------------------------
from conductor.coord import read_push_requests  # noqa: E402


def test_read_push_requests(tmp_path):
    pdir = tmp_path / "push-requests"
    pdir.mkdir()
    (pdir / "_home_kyle_repo").write_text(
        "repo=/home/kyle/repo\nrepo_name=repo\ncwd=/home/kyle/repo\n"
        "cmd=git push origin main\ncreated=2026-07-10 17:44\nepoch=1783720000\n"
    )
    reqs = read_push_requests(tmp_path)
    assert len(reqs) == 1
    assert reqs[0]["repo_name"] == "repo"
    assert reqs[0]["key"] == "_home_kyle_repo"


def test_read_push_requests_empty(tmp_path):
    assert read_push_requests(tmp_path) == []


# --- the floor is CONDITIONAL, not constant -----------------------------------
# Kyle: "when 7 Claudes are working a big problem together, asymmetric in how busy each one
# is, that could break through just about any ceiling we put in place."
#
# He is right, and the failure is not overflow — the mail always arrives and one /msg-check
# drains it all. The failure is PRIORITY INVERSION: a fixed floor spends its one wake per ten
# minutes on an FYI, while the message that actually BLOCKS someone waits behind it.
#
# No choice of constant fixes that. A bigger number wakes you more for noise; a smaller one
# delays the thing that matters. So the floor asks the wait-for graph instead: is anyone
# HARD-blocked on you? That is the one case where interrupting is unambiguously right — and
# it is exactly the case a rate limit is blindest to, because the bottleneck is busy BECAUSE
# it is the bottleneck.
def test_the_floor_silences_an_FYI(state, monkeypatch):
    _seen(monkeypatch, "2026-07-10 16:00")
    state.sessions = {"q": _sess("[other:qualcomm]", Status.IDLE)}
    state._directed_unread = _directed()
    state.waiting = {"edges": []}                       # nobody is stuck on qualcomm
    assert len(_run_wake(state, monkeypatch)) == 1      # first one goes through
    _seen(monkeypatch, "2026-07-10 17:05")
    state._directed_unread = _directed(ts="2026-07-10 17:30")
    assert _run_wake(state, monkeypatch) == []          # ...and then it is quiet


def test_but_a_session_someone_is_STUCK_ON_is_woken_regardless(state, monkeypatch):
    """The exemption. Someone is queued for a board qualcomm holds — they cannot proceed, and
    no amount of politeness about focus changes that."""
    _seen(monkeypatch, "2026-07-10 16:00")
    state.sessions = {"q": _sess("[other:qualcomm]", Status.IDLE)}
    state._directed_unread = _directed()
    state.waiting = {"edges": [
        {"src": "docs", "dst": "qualcomm", "kind": "resource", "hard": True},
    ]}
    assert len(_run_wake(state, monkeypatch)) == 1
    _seen(monkeypatch, "2026-07-10 17:05")
    state._directed_unread = _directed(ts="2026-07-10 17:30")
    assert len(_run_wake(state, monkeypatch)) == 1      # floor does NOT apply


def test_merely_AWAITING_A_REPLY_does_not_lift_the_floor(state, monkeypatch):
    """If a soft edge counted, the exemption would swallow the floor whole — twenty sessions
    awaiting a reply on a fast fleet is a conversation, not a crisis, and every one of them
    would become a licence to interrupt."""
    _seen(monkeypatch, "2026-07-10 16:00")
    state.sessions = {"q": _sess("[other:qualcomm]", Status.IDLE)}
    state._directed_unread = _directed()
    state.waiting = {"edges": [
        {"src": "docs", "dst": "qualcomm", "kind": "mail", "hard": False},
    ]}
    assert len(_run_wake(state, monkeypatch)) == 1
    _seen(monkeypatch, "2026-07-10 17:05")
    state._directed_unread = _directed(ts="2026-07-10 17:30")
    assert _run_wake(state, monkeypatch) == []          # soft edge -> still throttled


def test_being_blocked_ON_SOMEONE_ELSE_does_not_lift_your_own_floor(state, monkeypatch):
    """Direction matters. The edge must point AT you (`dst`), not away from you."""
    _seen(monkeypatch, "2026-07-10 16:00")
    state.sessions = {"q": _sess("[other:qualcomm]", Status.IDLE)}
    state._directed_unread = _directed()
    state.waiting = {"edges": [
        {"src": "qualcomm", "dst": "docs", "kind": "resource", "hard": True},
    ]}
    assert len(_run_wake(state, monkeypatch)) == 1
    _seen(monkeypatch, "2026-07-10 17:05")
    state._directed_unread = _directed(ts="2026-07-10 17:30")
    assert _run_wake(state, monkeypatch) == []


# --- sender-declared priority (Kyle's proposal, via orb_slam) ------------------
# orb_slam SIGNED OFF at 09:00 — work delivered, "don't wait on me" — and was woken across the
# next SIX HOURS, once per fleet broadcast it was merely cc'd on. Each wake spent tokens reading
# traffic that needed no reply and returned "nothing for me".
#
# Kyle's framing is the useful part: "high annoyance, chews up tokens, but LOW workflow impact."
# That is its own class of failure — not dangerous, just expensive — and it wants its own fix.
#
# The recipient-count heuristic (>4 = announcement) fixes it with ZERO adoption. But inferring
# priority opens the mirror hole: what if a mass-cc genuinely IS urgent? So the sender gets an
# override, and the DEFAULT stays inferred — because a system that REQUIRES senders to classify
# their mail gets mail that is all one class.
from conductor.bus import _address_targets


def test_p_wake_forces_a_wake_even_on_a_mass_cc():
    """The escape hatch for the message that really cannot wait — a retraction, a 'stop' —
    even though it is addressed to everyone."""
    t = _address_targets("to:a to:b to:c to:d to:e to:f p:wake — [x] STOP, revert that")
    assert "p:wake" in t
    assert "a" in t


def test_p_low_suppresses_a_wake_even_on_DIRECTED_mail():
    """The courteous reply that needs no action — which is most of them. orb_slam's case,
    declared rather than inferred."""
    t = _address_targets("to:orb_slam p:low — [x] thanks, nothing further")
    assert "p:low" in t
    assert "orb_slam" in t


def test_priority_tokens_are_not_counted_as_RECIPIENTS():
    """`p:wake` is not a session. If it were counted, it would push a 4-recipient message over
    the announcement threshold and silence a message the sender explicitly marked urgent —
    exactly inverting the feature."""
    from conductor.bus import _PRIORITY_TOKENS, _WAKE_MAX_RECIPIENTS
    t = _address_targets("to:a to:b to:c to:d p:wake — [x] hi")
    real = t - _PRIORITY_TOKENS - {"all"}
    assert len(real) == 4 <= _WAKE_MAX_RECIPIENTS


def test_a_plain_message_still_works_with_no_priority_at_all():
    """Zero adoption: the default is inferred, and nobody has to learn anything."""
    t = _address_targets("to:qualcomm — [x] a real question")
    assert t == frozenset({"qualcomm"})


# --- slice 6: seconds-granularity fix for same-minute silent mail loss ------
def test_same_minute_directed_mail_is_not_lost(tmp_path):
    """The RQ1 bug: minute-granularity timestamps + `ts <= last_seen` silently dropped any directed
    message that arrived in the same minute a session last checked. Seconds granularity + a tolerant
    parser fix it, with backward-compat for old minute-format messages."""
    from conductor.bus import directed_unread_all
    md = tmp_path / "messages.md"
    sd = tmp_path / "state"; sd.mkdir()
    md.write_text(
        "## 2026-07-26 15:05 [other:q]\n\nto:worker — old minute-format\n\n"
        "## 2026-07-26 15:19:10 [other:q]\n\nto:worker — read up to here\n\n"
        "## 2026-07-26 15:19:47 [other:q]\n\nto:worker — SAME MINUTE, later second\n\n"
    )
    (sd / "other:worker.last-seen").write_text("2026-07-26 15:19:10\n")
    r = directed_unread_all(md, sd, ["[other:worker]"])["[other:worker]"]
    assert r["count"] == 1 and r["wakeable"] == 1, "same-minute-later-second message was lost"

    (sd / "other:worker.last-seen").write_text("2026-07-26 15:19:47\n")
    assert directed_unread_all(md, sd, ["[other:worker]"])["[other:worker]"]["count"] == 0, "over-delivered"

    (sd / "other:worker.last-seen").write_text("2026-07-26 15:04\n")   # old minute watermark
    assert directed_unread_all(md, sd, ["[other:worker]"])["[other:worker]"]["count"] == 3, "minute-format broke"
