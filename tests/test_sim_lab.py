"""Simulation lab — drive a REAL Conductor AppState through scripted fleet scenarios and
assert on what it *decides* (who it injects /msg-check into), with the X11 layer mocked so
it's deterministic and cheap.

WHY THIS EXISTS: every real coordination bug this project has hit — the /msg-check storm, the
keystroke mis-delivery, the push-notice re-delivery — lived at a seam the unit tests mocked
away, and shipped past 316 green tests. This harness exercises the seams on purpose. Scenario
one is the storm: a resource-holder that others are hard-blocked on is EXEMPT from the wake
floor (correctly — it's the bottleneck), so the ONLY thing keeping it from being re-woken is
the dedup key. If that key is recorded after an await, any concurrency re-wakes it — which is
what qualcomm saw (11 /msg-check in ~200ms).
"""

from __future__ import annotations

import asyncio
import types

import pytest

from conductor.main import AppState, _WAKE_MIN_INTERVAL
from conductor.models import Status
from conductor.settings import load_settings

NOW = 1_800_000_000.0


class Fleet:
    """Builds an AppState with scripted sessions and records every /msg-check it would type.

    The injection primitive is replaced with a counter that yields (like the real one, which
    awaits xdotool in a thread) — so concurrent wake passes interleave exactly as they would
    live, and a dedup key recorded too late is exposed rather than hidden.
    """

    def __init__(self, monkeypatch, *, slow=False):
        self.app = AppState(load_settings())
        self.injects: list[tuple[str, str]] = []      # (tag, why)
        self._slow = slow
        self.app.sessions = {}
        self.app._directed_unread = {}
        self.app._wake_outstanding = {}
        self.app._woke_at = {}
        self.app.waiting = {"edges": []}
        self.app._autonomy = []
        self.app._last_seen = {}
        # deterministic clock + no disk
        monkeypatch.setattr("conductor.main.time", types.SimpleNamespace(time=lambda: NOW))
        monkeypatch.setattr("conductor.main.write_wake_state", lambda *a, **k: None)
        monkeypatch.setattr("conductor.main._read_last_seen",
                            lambda sd, tag: self.app._last_seen.get(tag, ""))
        monkeypatch.setattr("conductor.main.attest", lambda *a, **k: None)

        # ⚠️ **_kw ON PURPOSE. The real _inject_text has always had `*, actor=...`; a fake
        # with a NARROWER signature than the thing it replaces passes right up until a
        # caller uses the argument, then fails as a TypeError in production code rather
        # than as a wrong answer. Same family as the v2.26.1 fakes that lacked
        # last_activity_at — a fake missing what the real one always has is a fake that
        # passes while production breaks on the same line.
        async def fake_inject(rec, text, why, **_kw):
            # record intent the way _inject_text does, then yield (mirrors the real awaits on
            # attest + send_keys_to_session running in a thread pool)
            self.injects.append((rec.tag, why))
            if self._slow:
                await asyncio.sleep(0.02)
            return True

        # patch the choke point directly — every wake path funnels through it
        monkeypatch.setattr(self.app, "_inject_text", fake_inject)

    def session(self, tag, *, status=Status.IDLE, activity=NOW, cwd=None):
        cwd = cwd or f"/proj/{tag}"
        rec = types.SimpleNamespace(
            tag=tag, status=status, pid=4321, terminal_pid=99, title=tag,
            window_title=f"Project {tag}", project_dir=cwd, last_activity_at=activity)
        self.app.sessions[cwd] = rec
        return rec

    def unread(self, tag, *, count=1, senders=("alice",), ts="2026-07-12 02:00"):
        self.app._directed_unread[tag] = {"count": count, "wakeable": count,
                                          "senders": list(senders), "latest_ts": ts}
        self.app._last_seen[tag] = "2026-07-11 20:00"       # behind the mail -> unread

    def hard_block_on(self, tag):
        """Make `tag` a bottleneck: someone is hard-blocked on it -> floor-exempt."""
        from conductor.main import _plain_name
        self.app.waiting["edges"].append({"hard": True, "dst": _plain_name(tag)})


# ── the wake function is sound when called sequentially ──────────────────────
def test_floor_exempt_holder_is_woken_exactly_once_per_batch(monkeypatch):
    f = Fleet(monkeypatch)
    f.session("[other:qualcomm]")
    f.unread("[other:qualcomm]")
    f.hard_block_on("[other:qualcomm]")            # exempt from the floor
    asyncio.run(f.app._wake_unread_recipients())
    assert f.injects == [("[other:qualcomm]", "1 unread addressed to it")]


def test_repeated_scans_do_not_re_wake_a_floor_exempt_holder(monkeypatch):
    """Sequential scans (the real scan loop) must NOT storm even a floor-exempt session whose
    transcript is frozen: the dedup key holds because its watermark hasn't advanced."""
    f = Fleet(monkeypatch)
    f.session("[other:qualcomm]", activity=NOW - 7200)   # frozen transcript
    f.unread("[other:qualcomm]")
    f.hard_block_on("[other:qualcomm]")

    async def three_scans():
        for _ in range(3):
            await f.app._wake_unread_recipients()
    asyncio.run(three_scans())
    assert len(f.injects) == 1, f"sequential scans stormed: {f.injects}"


# ── THE STORM: concurrent wake passes must still wake it only once ───────────
def test_concurrent_wake_passes_do_not_storm_a_floor_exempt_holder(monkeypatch):
    """The qualcomm bug reproduced: with the floor exempted, the dedup key is the only guard —
    and if it is recorded only AFTER the inject's awaits, concurrent passes each pass the check
    before any records it, and the session is woken N times. This asserts exactly-once under
    concurrency; it is RED if the dedup slot is reserved too late."""
    f = Fleet(monkeypatch, slow=True)              # slow inject => the await window is real
    f.session("[other:qualcomm]", activity=NOW - 7200)
    f.unread("[other:qualcomm]")
    f.hard_block_on("[other:qualcomm]")

    async def stormy():
        await asyncio.gather(*(f.app._wake_unread_recipients() for _ in range(11)))
    asyncio.run(stormy())
    qc = [i for i in f.injects if i[0] == "[other:qualcomm]"]
    assert len(qc) == 1, f"STORM: woke qualcomm {len(qc)}x under concurrency"


def test_an_over_cc_announcement_does_not_wake(monkeypatch):
    """cc-suppression: a message naming >4 recipients is an ANNOUNCEMENT — it shows in the
    badge but must not wake anyone (the emulator cluster cc's to:all + 5-7 tags on nearly every
    message; without this the whole fleet would storm itself). The wake gate keys on the
    `wakeable` count the directed-unread computation sets to 0 for a mass-cc."""
    f = Fleet(monkeypatch)
    f.session("[other:qualcomm]")
    # count=1 (it IS unread and badged) but wakeable=0 (mass-cc -> announcement)
    f.app._directed_unread["[other:qualcomm]"] = {
        "count": 1, "wakeable": 0, "senders": ["holobench"], "latest_ts": "2026-07-12 02:00"}
    f.app._last_seen["[other:qualcomm]"] = "2026-07-11 20:00"
    asyncio.run(f.app._wake_unread_recipients())
    assert f.injects == [], "an over-cc announcement woke a session"


def test_a_directed_message_still_wakes(monkeypatch):
    """Control for the above: a genuinely directed message (wakeable>0) DOES wake."""
    f = Fleet(monkeypatch)
    f.session("[other:qualcomm]")
    f.unread("[other:qualcomm]")               # wakeable defaults to count
    asyncio.run(f.app._wake_unread_recipients())
    assert len(f.injects) == 1


def test_concurrent_retraction_wakes_fire_once(monkeypatch):
    """Same race on the retraction path — qualcomm got 4 duplicate RETRACTION wakes in the
    live burst. One retraction record, concurrent passes, must inject once."""
    f = Fleet(monkeypatch, slow=True)
    f.session("[other:qualcomm]")
    f.app._retractions = [{"id": "r1", "sender": "orb_slam", "target_plain": "qualcomm"}]
    f.app._retraction_woken = set()

    async def stormy():
        await asyncio.gather(*(f.app._wake_retractions() for _ in range(4)))
    asyncio.run(stormy())
    assert len([i for i in f.injects if "RETRACTION" in i[1]]) == 1


def test_concurrent_push_notice_delivers_once(monkeypatch):
    """The phantom-approval bug: 'Kyle approved your git push' was injected 3x with no grant
    behind it, because the notice was deleted only AFTER the inject's await. Concurrent passes
    must deliver it exactly once."""
    f = Fleet(monkeypatch, slow=True)
    rec = f.session("[other:claude-connect]", cwd="/proj/cc")
    f.app._push_notices = {"cc": {"cwd": "/proj/cc", "repo": "claude-connect",
                                  "queued": NOW, "text": "✅ approved"}}
    monkeypatch.setattr(f.app, "_session_for_cwd", lambda cwd: rec)

    async def stormy():
        await asyncio.gather(*(f.app._deliver_push_notices() for _ in range(3)))
    asyncio.run(stormy())
    assert len([i for i in f.injects if "push verdict" in i[1]]) == 1
    assert f.app._push_notices == {}          # delivered -> gone, can't re-fire


def test_push_notice_is_kept_when_the_inject_fails(monkeypatch):
    """Restore-on-failure: if the keystroke didn't land, the notice must stay for a retry."""
    f = Fleet(monkeypatch)
    rec = f.session("[other:cc]", cwd="/proj/cc")
    f.app._push_notices = {"cc": {"cwd": "/proj/cc", "repo": "cc", "queued": NOW, "text": "x"}}
    monkeypatch.setattr(f.app, "_session_for_cwd", lambda cwd: rec)

    async def fail_inject(rec, text, why, **_kw):
        f.injects.append((rec.tag, why))
        return False                          # keystroke didn't land
    monkeypatch.setattr(f.app, "_inject_text", fail_inject)
    asyncio.run(f.app._deliver_push_notices())
    assert "cc" in f.app._push_notices, "a failed notice must be kept for retry"


def test_concurrent_notify_rings_the_phone_once(monkeypatch):
    """The webpush path is the same class as the wake dedup: `pending` is computed once, so two
    concurrent _notify passes both see an item as due. Claim-and-check before send_one's await
    means only the first rings the phone — no duplicate push."""
    app = AppState(load_settings())
    app._notified = {}
    app.decisions = []
    app._push_requests = []
    app._silent = []
    sent = []
    item = {"key": "q1", "title": "a question"}
    monkeypatch.setattr("conductor.main.notifiable", lambda *a, **k: [item])
    monkeypatch.setattr("conductor.main.due", lambda items, n: [i for i in items if i["key"] not in n])
    monkeypatch.setattr("conductor.main.prune_sent", lambda n, items: n)
    monkeypatch.setattr("conductor.main.read_subs", lambda root: [{"endpoint": "e"}])
    monkeypatch.setattr("conductor.main.load_or_create_keys", lambda root: object())
    monkeypatch.setattr("conductor.main.vapid_subject", lambda h: "mailto:x@example.com")

    def slow_send(sub, it, keys, subj):    # sync — it runs via asyncio.to_thread
        sent.append(it["key"])
        return True
    monkeypatch.setattr("conductor.main.send_one", slow_send)

    async def stormy():
        await asyncio.gather(*(app._notify() for _ in range(4)))
    asyncio.run(stormy())
    assert sent.count("q1") == 1, f"double-rang the phone: {sent}"


def test_start_is_idempotent_no_second_scan_loop(monkeypatch):
    """The storm's SOURCE: start() had no guard, so a second call spawned a second scan loop
    (create_task doesn't cancel the overwritten one) — two loops => concurrent scans. A second
    start() must be a no-op."""
    app = AppState(load_settings())
    app.activity = types.SimpleNamespace(start=lambda: asyncio.sleep(0))
    app.bus = types.SimpleNamespace(start=lambda: asyncio.sleep(0))   # not a MarkdownBusAdapter

    async def go():
        await app.start()
        first = app._scan_task
        await app.start()                    # second call must NOT replace the loop
        second = app._scan_task
        # tidy up the background loops
        for t in (app._scan_task, app._activity_task, app._bus_task):
            t.cancel()
        return first, second

    first, second = asyncio.run(go())
    assert first is second, "start() spawned a second scan loop"
