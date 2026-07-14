"""FastAPI app + uvicorn entry for Conductor.

Wires the SessionScanner, ActivityWatcher, BusAdapter, and WebSocket hub.
Serves the vanilla-JS frontend at `/`.
"""

from __future__ import annotations

import asyncio
import getpass
import logging
import os
import shutil
import socket
import subprocess
import time
from collections import deque
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import __version__
from .activity import ActivityWatcher
from .auth import path_requires_auth, resolved_token, token_ok
from .autonomy import close_window, open_window, peers_in_window, read_windows
from .decisions import plan_keystrokes, read_decisions, reap_decision
from .members import ROLES as _MEMBER_ROLES
from .members import detect_collisions, ensure_bound, members_summary, read_members, set_role
from .provenance import attest, prune as prune_ledger
from .webpush import (
    add_sub,
    drop_sub,
    due,
    load_or_create_keys,
    notifiable,
    prune_sent,
    read_subs,
    send_one,
    vapid_subject,
)
from .bus import (
    BusAdapter,
    FakeBusAdapter,
    JSONLBusAdapter,
    MarkdownBusAdapter,
    active_tags_configured,
    append_message,
    build_mention_history,
    compute_pending,
    directed_unread_all,
    list_known_tags,
    list_sender_tags,
    read_active_tags,
    read_pending,
    set_active_tag,
    snapshot_history,
)
from .bus import _plain_name, _read_last_seen
from .coord import (
    clear_push_proposal,
    read_inflight,
    read_push_grants,
    read_persist_requests,
    read_push_proposals,
    read_push_requests,
    read_retractions,
    read_wake_state,
    write_wake_state,
)
from .deps import build_wait_graph, open_ask_edges, silent_addressees
from .models import BusEvent, BusTopology, ParkedSession, SessionRecord, Status
from .resources import resources_state, touch_lease_activity
from .services import read_services
from .tokens import TokenAccountant
from .scanner import (
    YOU_TAG,
    SessionScanner,
    collect_human_events,
    derive_tag,
    discover_parked_projects,
    encode_cwd,
    extract_exchange,
    extract_preview,
    extract_session_detail,
    last_recorded_cwd,
    newest_jsonl,
    parse_session_meta,
    tag_to_state_basename,
)
from .settings import DEFAULT_SETTINGS_PATH, Settings, dump_settings, load_settings
from .windows import (
    focus_session,
    send_key_sequence,
    send_keys_to_session,
    wmctrl_available,
)
from .ws import WSHub

log = logging.getLogger("conductor")


# Mirrors the frontend's ping guard: a session mid-task shouldn't get keystrokes.
_BUSY_STATUSES = frozenset({Status.ACTIVE, Status.WARM})

# Auto-delivery only wakes sessions that are clearly unattended and not working:
# not ACTIVE/WARM (busy) and not WAITING (Kyle may be typing at that prompt).
_WAKEABLE_STATUSES = frozenset({Status.IDLE, Status.DORMANT})

# A /msg-check the recipient hasn't run yet makes a second one pointless — one
# check drains the whole backlog. Re-arm after this long anyway, so a session
# that never writes a last-seen watermark isn't muted forever.
# How long before we'll consider re-injecting a /msg-check that a session still hasn't
# acted on. This used to be 600s and it caused a keystroke STORM: over one night a single
# session accumulated ~16 queued /msg-checks, and Conductor fired ~450 injections fleet-wide.
#
# The mistake was believing a busy session DROPS injected keystrokes. It doesn't — Claude
# Code QUEUES them ("Press up to edit queued messages"). So a re-injection is never a repair;
# it is just another identical command stacked behind the first. One /msg-check drains the
# entire backlog, so a second one can only ever be noise.
#
# The retry now exists solely for the case where the keystroke was genuinely LOST, and it is
# gated on evidence of that (see _wake_unread_recipients) rather than on a stopwatch.
_WAKE_RETRY_SECONDS = 3600.0

# A FLOOR on how often any one session may be woken, no matter how much mail arrives.
#
# The watermark dedup stops us re-waking for the SAME unread batch. It does nothing across
# batches — so a session the fleet is actively talking to gets woken on every new message.
# qualcomm took 12 keystroke injections in one hour, each one stealing focus mid-work.
#
# Auto-delivery is not a pager. Nothing on this bus is so urgent that it cannot wait ten
# minutes, and one /msg-check drains the whole backlog anyway — so a wake deferred is a wake
# that will deliver MORE when it fires, not less.
_WAKE_MIN_INTERVAL = 600.0

# Don't tell the same stall it's stalled twice inside this window. Once is a nudge;
# twice is noise, and noise is what makes the next one ignorable.
_UNSTALL_COOLDOWN = 300.0


def _bare_tag(tag: str | None) -> str:
    """Compare tags on a common form.

    Conductor stores a session's tag bracketed (``"[other:api]"``) because that's
    how it renders; ``bus.sh`` writes lease owners bare (``"other:api"``). Matching
    the two directly never succeeds — normalize before comparing.
    """
    return (tag or "").strip().strip("[]")


class _StripControlBytes(logging.Filter):
    """Keep the log READABLE BY grep. This is not cosmetic — it produced a false statement to
    Kyle about whether he had consented to something.

    Conductor logs session previews, and a transcript can contain NUL and other control bytes.
    2,426 of them ended up in conductor.log, so `file` called it `data` and **grep classified
    it as binary and searched NOTHING — returning EMPTY rather than an error.** (The "binary
    file matches" warning goes to stderr, so a piped check never sees it either.)

    image_gen tried to audit an injection with grep, got nothing, read the silence as "Conductor
    didn't wake me", and told Kyle the /msg-check was probably his. It wasn't.

    **A tool that could not fire, and its silence was treated as evidence.** Same failure class
    as ollama's crashed verify and rt1180's zero-run loop — this time inside the audit trail
    itself, which is the worst place for it, because an audit log a text tool cannot parse is a
    green light with nothing behind it.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str) and any(ord(c) < 32 and c not in "\n\t" for c in record.msg):
            record.msg = "".join(c if c.isprintable() or c in " \t" else "·" for c in record.msg)
        if record.args:
            record.args = tuple(
                "".join(c if c.isprintable() or c in " \t" else "·" for c in a)
                if isinstance(a, str) else a
                for a in (record.args if isinstance(record.args, tuple) else (record.args,))
            )
        return True


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
for _h in logging.getLogger().handlers:
    _h.addFilter(_StripControlBytes())

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
RECENT_EVENTS_MAX = 200


def _build_bus_adapter(settings: Settings) -> BusAdapter:
    name = settings.bus.adapter.lower()
    if name == "markdown":
        return MarkdownBusAdapter(settings.bus.markdown_path_resolved, poll_interval=0.5)
    if name == "jsonl":
        return JSONLBusAdapter(settings.bus.jsonl_path_resolved, poll_interval=0.5)
    if name == "fake":
        return FakeBusAdapter()
    log.warning("unknown bus.adapter %r — falling back to markdown", name)
    return MarkdownBusAdapter(settings.bus.markdown_path_resolved, poll_interval=0.5)


def _mint_grant(coord_root: Path, key: str, repo_name: str, repo: str) -> None:
    """Arm a push grant straight from an approved proposal.

    A proposal normally arrives BEFORE the session has ever tried to push, so there is no
    pending gate request for `bus.sh push approve` to consume. Kyle has still made the
    decision — with more context than the gate could ever have shown him — so the grant is
    written directly, in exactly the format the gate reads.
    """
    tdir = coord_root / "push-tokens"
    tdir.mkdir(parents=True, exist_ok=True)
    now = int(time.time())
    (tdir / key).write_text(
        f"expires={now + 86400}\nrepo={repo}\nrepo_name={repo_name}\n"
        f"approved={now}\napproved_at={time.strftime('%Y-%m-%d %H:%M')}\n",
        encoding="utf-8",
    )


def _unpack_wake(v: Any) -> tuple[str, float, float]:
    """``(seen, woke_at)`` (the old on-disk shape) or ``(seen, woke_at, activity_at)``.

    ``coord/wake-state.json`` persists across restarts, so the first run after this change
    reads 2-tuples. Treating a short tuple as corrupt and dropping it would re-prod every
    session with unread mail exactly once — which is the very storm this change exists to
    end. Default the missing activity stamp to +inf so a legacy entry can never satisfy the
    "it has been active since we typed" retry test.
    """
    if isinstance(v, (list, tuple)):
        if len(v) >= 3:
            return str(v[0]), float(v[1]), float(v[2])
        if len(v) == 2:
            return str(v[0]), float(v[1]), float("inf")
    return "", 0.0, float("inf")


class AppState:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.scanner = SessionScanner(settings.scanner, tag_map=settings.bus.tags)
        self.activity = ActivityWatcher()
        self.bus: BusAdapter = _build_bus_adapter(settings)
        self.hub = WSHub()

        self.sessions: dict[str, SessionRecord] = {}        # keyed by project_dir
        self.parked: list[ParkedSession] = []               # relaunchable offline sessions
        self.res_root = settings.bus.state_dir_resolved / "resources"   # shared-resource leases
        self.resources: dict[str, Any] = {"resources": []}
        self._pinged_offers: set[str] = set()                 # offers we've already woken
        self._owner_missing_since: dict[str, float] = {}      # lease -> when its owner went offline
        self._nudge_woken: set[str] = set()                   # idle episodes we already woke
        self.coord_root = settings.bus.state_dir_resolved / "coord"
        # tag -> (its last-seen when we woke it, when we woke it). Keeps us from
        # stacking /msg-checks on a session that hasn't run the first one yet.
        # PERSISTED: a restart that forgot this would re-prod every session with
        # unread mail, and a busy session's keystrokes queue -> stacked checks.
        # tag -> when we last injected into it. The FLOOR (_WAKE_MIN_INTERVAL) is
        # separate from the watermark dedup: dedup stops repeats for one batch;
        # this stops a busy conversation from injecting every few minutes.
        self._woke_at: dict[str, float] = {}
        self._unstalled: dict[str, float] = {}   # cycle-key -> when we last told it
        self._wake_outstanding: dict[str, tuple[str, float]] = read_wake_state(
            settings.bus.state_dir_resolved / "coord")
        self._directed_unread: dict[str, dict[str, Any]] = {} # tag -> unread addressed to it
        self._retraction_woken: set[str] = set()              # retraction records we already delivered
        self._retractions: list[dict[str, Any]] = []          # active retraction records
        self._push_requests: list[dict[str, Any]] = []        # git-push approvals awaiting Kyle
        self._push_grants: list[dict[str, Any]] = []          # approvals GIVEN, not yet used
        # Sessions asking 'is this the right MOMENT to push?' — with the context the gate
        # can never have: what's in the commits, and what they'd do instead.
        self._push_proposals: list[dict[str, Any]] = []
        # THE SECOND HARD CONTROL: acts whose consequences outlive the session.
        # settings.json is the RCE — a hook there is arbitrary code on every tool
        # call in every session, and it looks like editing a config file.
        self._persist_requests: list[dict[str, Any]] = []
        # THE MEMBER REGISTRY (v4 §3.4): Conductor is the registrar. It binds each live session's
        # unforgeable session_id -> a durable member ONCE (never re-derived from a drifting tag),
        # and the referee (persist-gate via member-registry.sh) reads the same file to enforce roles.
        self.bus_state = settings.bus.state_dir_resolved
        self._members: list[dict[str, Any]] = []              # member -> role summary for the UI
        self._role_by_session: dict[str, str] = {}            # session_id -> role, for the tiles
        # 'tell this session its push was approved' — delivered only when it's QUIET,
        # because a busy session swallows injected keystrokes without a trace.
        self._push_notices: dict[str, dict[str, Any]] = {}
        self._autonomy: list[dict[str, Any]] = []             # live "let them talk" windows
        self.services: dict[str, Any] = {"services": []}      # service Claudes (image_gen…)
        self.waiting: dict[str, Any] = {"edges": [], "cycles": [], "bottlenecks": [],
                                        "blocked_count": 0}   # who is blocked on whom
        self._silent: list[dict[str, Any]] = []               # dead-reader alarm (holobench)
        self._collisions: list[dict[str, Any]] = []           # two live sessions, one member (holobench)
        # Questions a Claude is BLOCKED ON, captured by the PreToolUse hook. Doubles as
        # the guard for keystroke injection: a session sitting on a picker must never be
        # typed at, because the picker swallows typed text into its free-text option.
        self.decisions: list[dict[str, Any]] = []
        # Second half of that same guard: a session with a tool in flight may be sitting on a
        # permission prompt (transcript-identical to idle), where a typed Return = "Yes".
        # Keyed by realpath(cwd). Written by the tool-inflight.sh hook; self-clears once the
        # transcript advances past the marker.
        self._inflight: dict[str, dict[str, Any]] = {}
        # Web Push. `_notified` maps a pending item's stable key -> when we last rang
        # about it, so a still-unanswered question gets a reminder (hourly) and not a
        # nag (every scan tick).
        self._notified: dict[str, float] = {}
        self.token_accountant = TokenAccountant()             # per-session token tally
        self._scan_misses: dict[str, int] = {}              # consecutive scans a session was absent
        self.recent_events: deque[BusEvent] = deque(maxlen=RECENT_EVENTS_MAX)
        self.bus_total = 0

        self._scan_task: asyncio.Task | None = None
        self._activity_task: asyncio.Task | None = None
        self._bus_task: asyncio.Task | None = None

    async def start(self) -> None:
        await self.activity.start()
        # Seed bus state from the historical log so the Bus tile reflects past
        # activity instead of starting at zero. The adapter itself tails from
        # EOF, so this won't double-count.
        if isinstance(self.bus, MarkdownBusAdapter):
            history, total = snapshot_history(self.settings.bus.markdown_path_resolved)
            self.bus_total = total
            for ev in history[-RECENT_EVENTS_MAX:]:
                self.recent_events.append(ev)
        await self.bus.start()
        self._scan_task = asyncio.create_task(self._scan_loop(), name="scan-loop")
        self._activity_task = asyncio.create_task(self._activity_loop(), name="activity-loop")
        self._bus_task = asyncio.create_task(self._bus_loop(), name="bus-loop")

    async def stop(self) -> None:
        for t in (self._scan_task, self._activity_task, self._bus_task):
            if t:
                t.cancel()
        await self.activity.stop()
        await self.bus.stop()

    # --- loops ---------------------------------------------------------------

    async def _scan_loop(self) -> None:
        while True:
            try:
                await self._do_scan()
            except Exception as e:  # noqa: BLE001
                log.exception("scan loop error: %s", e)
            try:
                await asyncio.sleep(self.settings.scanner.interval_seconds)
            except asyncio.CancelledError:
                return

    async def _do_scan(self) -> None:
        new_map = await asyncio.to_thread(self.scanner.scan)
        now = time.time()

        # Mark missing sessions ENDED — but only after 2 consecutive misses, so a
        # transient /proc read failure during a session's teardown doesn't flap
        # the tile in and out.
        for key, rec in list(self.sessions.items()):
            if rec.status == Status.ENDED:
                continue
            if key in new_map:
                self._scan_misses.pop(key, None)
            else:
                self._scan_misses[key] = self._scan_misses.get(key, 0) + 1
                if self._scan_misses[key] >= 2:
                    rec.status = Status.ENDED
                    rec.ended_at = now

        # Fold in new/updated sessions.
        for key, rec in new_map.items():
            self.sessions[key] = rec
            self._scan_misses.pop(key, None)

        # Drop ended sessions whose fade window expired.
        expire = self.settings.ui.end_fadeout_seconds
        for key in list(self.sessions):
            r = self.sessions[key]
            if r.status == Status.ENDED and r.ended_at is not None and now - r.ended_at > expire:
                self.sessions.pop(key, None)
                self._scan_misses.pop(key, None)

        # Hydrate per-session bus pending counts. We compute these from the log
        # + <tag>.last-seen rather than reading <tag>.pending, because the
        # destination's .pending file only updates when *that* session next runs
        # bus.sh prompt-check — so a freshly-arrived message wouldn't show up.
        for r in self.sessions.values():
            if r.tag:
                r.pending_count = self._pending_for(r.tag)

        # MEMBER REGISTRY (v4 §3.4): bind each live session's session_id -> a durable member ONCE
        # (the member is set from the tag at first sighting and NEVER re-derived, so it can't drift
        # with a `cd`). Off-thread — it may write a small file. Roles are only ever RAISED by Kyle.
        await asyncio.to_thread(self._sync_members)

        # Directed-unread (messages addressed `to:<tag>` that the session hasn't
        # read) drives auto-delivery — one log parse for all live tags.
        live_tags = [r.tag for r in self.sessions.values()
                     if r.tag and r.status != Status.ENDED]
        self._directed_unread = await asyncio.to_thread(
            directed_unread_all,
            self.settings.bus.markdown_path_resolved,
            self.settings.bus.state_dir_resolved,
            live_tags,
        )

        # Topology for the markdown bus = tags that are actually *wired up* to
        # the bus, i.e. have bus state (a `<tag>.last-seen` file). A session can
        # be tagged (every CWD derives one) yet never have touched the bus; such
        # un-wired sessions render as normal tiles but get no connection line, so
        # you can see at a glance who's on the tunnel and who's deliberately out.
        # list_known_tags() already covers wired sessions whether or not they
        # currently have a tile; lines.js skips subscriber tags with no tile.
        if isinstance(self.bus, MarkdownBusAdapter):
            state_dir = self.settings.bus.state_dir_resolved
            msgs_path = self.settings.bus.markdown_path_resolved
            # On the bus = has read-state (a `<tag>.last-seen`) OR has ever sent a
            # message (appears as a sender in the log). The latter covers `other:*`
            # tags that participate but aren't in bus.sh's auto-hook whitelist, so
            # they never get a `.last-seen`. dict.fromkeys keeps it de-duped/ordered.
            tags = dict.fromkeys([*list_known_tags(state_dir), *list_sender_tags(msgs_path)])
            subs: dict[str, list[str]] = {tag: [] for tag in tags}
            self.bus.set_topology(BusTopology(subscribers=subs))

        # Discover parked (offline) sessions for the dormant dock: project dirs
        # with on-disk history but no live process right now. Excludes cwds where
        # a session is currently running. Off-thread (walks every project dir).
        projects_root = self.settings.scanner.claude_home_path / "projects"
        live_cwds = {
            os.path.realpath(r.project_dir)
            for r in self.sessions.values()
            if r.status != Status.ENDED
        }
        self.parked = await asyncio.to_thread(
            discover_parked_projects, projects_root, self.settings.bus.tags, live_cwds
        )

        # Sync inotify watch set.
        watch_dirs = []
        for r in self.sessions.values():
            if r.status == Status.ENDED:
                continue
            # Watch the dir the jsonl actually lives in (which can differ from the
            # current cwd's encoded dir when a session cd'd away from its launch
            # dir); fall back to the encoded current cwd if unresolved.
            d = Path(r.jsonl_path).parent if r.jsonl_path else projects_root / encode_cwd(r.project_dir)
            if d.is_dir():
                watch_dirs.append(d)
        self.activity.sync_watched_dirs(watch_dirs)

        await self.hub.broadcast("sessions", self._sessions_payload())
        # Refresh the Bus tile too (topology + per-tag pending) so it stays live
        # between bus events, not just on WS reconnect.
        await self.hub.broadcast("bus", self._bus_payload())
        # Resource tiles: named-resource leases (+ nvidia-smi telemetry for the GPU).
        self.resources = await asyncio.to_thread(resources_state, self.res_root)
        await asyncio.to_thread(self._refresh_active_leases)
        self._annotate_orphans()
        await self.hub.broadcast("resources", self.resources)
        self._retractions = await asyncio.to_thread(read_retractions, self.coord_root)
        push_reqs = await asyncio.to_thread(read_push_requests, self.coord_root)
        grants = await asyncio.to_thread(read_push_grants, self.coord_root)
        self._push_proposals = await asyncio.to_thread(read_push_proposals, self.coord_root)
        self._persist_requests = await asyncio.to_thread(read_persist_requests, self.coord_root)
        # Compare grants on identity, not the live countdown — `expires_in` ticks down every
        # scan, so including it would rebroadcast (and re-render) the inbox forever.
        gid = [(g["key"], g["expires_epoch"]) for g in grants]
        if push_reqs != self._push_requests or gid != [
                (g["key"], g["expires_epoch"]) for g in self._push_grants]:
            self._push_requests = push_reqs
            self._push_grants = grants
            await self.hub.broadcast("push", {"requests": push_reqs, "grants": grants,
                                             "proposals": self._push_proposals,
                                             "persist": self._persist_requests})
        else:
            self._push_grants = grants
        svc = await asyncio.to_thread(read_services, self.coord_root)
        if svc != self.services:
            self.services = svc
            await self.hub.broadcast("services", svc)
        # Who is blocked on whom. Every input is already in hand — this is a VIEW over
        # state we collect anyway (directed mail, service queues, resource queues), which
        # is why it's cheap enough to rebuild every scan.
        _live_tags = {r.tag for r in self.sessions.values() if r.tag and r.status != Status.ENDED}
        # Wait-for edges come from OPEN ASKS (a directed, unreplied question) — bus.sh waiting's
        # rule — NOT unread counts, so a node with unread cc'd mail is never a phantom stall link.
        _mail_edges = await asyncio.to_thread(
            open_ask_edges, self.settings.bus.markdown_path_resolved, _live_tags)
        waiting = await asyncio.to_thread(
            build_wait_graph,
            mail_edges=_mail_edges,
            services=self.services.get("services", []),
            resources=self.resources.get("resources", []),
            live_tags=_live_tags,
        )
        if waiting != self.waiting:
            self.waiting = waiting
            await self.hub.broadcast("waiting", waiting)

        # DEAD-READER ALARM (holobench): a tag others are directly addressing that has posted
        # nothing for hours. Pure-bus signal; we annotate each with whether a live process
        # exists — no live session + an open ask = a near-certain outage a human must clear.
        live_plain = {_plain_name(r.tag) for r in self.sessions.values()
                      if r.tag and r.status != Status.ENDED}
        silent = await asyncio.to_thread(
            silent_addressees,
            self.settings.bus.markdown_path_resolved,
            silence_h=self.settings.bus.silent_reader_silence_hours,
            addressed_window_h=self.settings.bus.silent_reader_addressed_window_hours,
        )
        for s in silent:
            s["live"] = s["tag"] in live_plain
            # "dead" = nobody's running it AND someone has an open question waiting on it. That is
            # the case only a human can fix; a live-but-quiet session is merely unresponsive.
            s["dead"] = (not s["live"]) and s["open_ask_count"] > 0
        if silent != self._silent:
            self._silent = silent
            await self.hub.broadcast("silent", {"silent": silent})

        # DUAL-SESSION COLLISION (holobench): two live Claude PROCESSES under one tag — a tag that
        # points at two sessions because it's derived from the cwd. This MUST count processes, not
        # SessionRecords: the scanner keeps one record per dir (its dedup is exactly what hid the
        # 10h rt1180 collision), so the process groups it captured pre-dedup are the only place the
        # second session is visible. pid is the distinguishing credential here. bus.sh shouts too.
        collisions = detect_collisions([
            {"member": _bare_tag(tag), "session_id": str(p["pid"]),
             "name": p.get("name", ""), "project": p.get("cwd", "")}
            for tag, procs in self.scanner.proc_groups.items()
            for p in procs
        ])
        # "reshirt, reshirt" tells Kyle nothing about WHICH to close. Attach the repo's most-recent
        # transcripts (one per live session) with each one's last-activity + a preview, so the two
        # are distinguishable by the only thing that matters — what each is actually working on.
        for col in collisions:
            cwd = (col.get("sessions") or [{}])[0].get("project", "")
            col["recent"] = await asyncio.to_thread(self._recent_transcripts, cwd, col["count"])
        if collisions != self._collisions:
            self._collisions = collisions
            await self.hub.broadcast("collisions", {"collisions": collisions})

        decisions = await asyncio.to_thread(read_decisions, self.coord_root)
        # Drop records whose session is gone — a session killed mid-picker leaves its
        # file behind, and a dead question in the queue is a false alarm.
        decisions = [d for d in decisions if self._session_for_cwd(d.get('cwd', ''))]
        if decisions != self.decisions:
            self.decisions = decisions
            await self.hub.broadcast("decisions", {"decisions": decisions})
        # Tool-in-flight markers (the permission-prompt guard). Internal — not broadcast; it
        # only gates our own keystroke injection.
        self._inflight = await asyncio.to_thread(read_inflight, self.coord_root)
        autonomy = await asyncio.to_thread(read_windows, self.coord_root)
        if autonomy != self._autonomy:
            self._autonomy = autonomy
            await self.hub.broadcast("autonomy", {"windows": autonomy})
        await self._wake_offered_sessions()
        await self._wake_nudged_owners()
        await self._wake_unread_recipients()
        await self._wake_retractions()
        await self._deliver_push_notices()
        await asyncio.to_thread(prune_ledger, self.settings.bus.state_dir_resolved)
        await self._notify()

    async def _wake_retractions(self) -> None:
        """A retraction is urgent: the recipient may be about to act on the very
        instruction being pulled back. So wake it *immediately* and — unlike every
        other wake — **override the busy guard**, because a busy recipient is exactly
        the dangerous case. Once per record."""
        for r in self._retractions:
            if r["id"] in self._retraction_woken:
                continue
            rec = next((s for s in self.sessions.values()
                        if _bare_tag(s.tag).split(":")[-1].lower() == r["target_plain"]
                        and s.status != Status.ENDED), None)
            if rec is None:
                continue  # target not live -> the hook surfaces it on its next prompt
            await self._inject_msg_check(rec, f"RETRACTION from [{r['sender']}] (busy-guard overridden)")
            self._retraction_woken.add(r["id"])
        active = {r["id"] for r in self._retractions}
        self._retraction_woken &= active  # forget expired records

    async def _wake_unread_recipients(self) -> None:
        """Stop being the fleet's message courier: wake an *idle* session that has a
        message addressed to it (``to:<tag>``) it hasn't read, so it goes and reads
        it on its own. Only IDLE/DORMANT sessions (never busy, never one Kyle may be
        typing at), only *directed* messages (broadcasts don't trigger this), and
        once per unread batch (a newer message re-wakes; the same batch never nags)."""
        if not self.settings.bus.autodeliver:
            return
        # Sessions the operator is actively working in (the dev console) shouldn't
        # be auto-prodded to go read the bus — compared bare so bracketed/bare
        # spellings both match.
        exempt = {_bare_tag(t) for t in self.settings.bus.autodeliver_exempt}
        state_dir = self.settings.bus.state_dir_resolved
        now = time.time()
        changed = False
        for r in self.sessions.values():
            if not r.tag or _bare_tag(r.tag) in exempt:
                continue
            info = self._directed_unread.get(r.tag)
            if not info or not info.get("count"):
                if self._wake_outstanding.pop(r.tag, None) is not None:
                    changed = True                        # backlog cleared -> re-arm
                continue
            # Only mail actually AIMED at this session may wake it. A message cc'd to half the
            # fleet still shows in the badge (the human should see it) but is not an
            # interruption — see _WAKE_MAX_RECIPIENTS.
            if not info.get("wakeable", info.get("count", 0)):
                continue
            # THE FLOOR, AND IT IS CONDITIONAL — because a rate limit is a CONSTANT and the
            # situation is DYNAMIC. Kyle found this: with seven Claudes on one problem the load
            # is wildly asymmetric, and a fixed ceiling spends its one wake per ten minutes on
            # an FYI while the message that actually BLOCKS someone waits behind it.
            #
            # That is priority inversion, and no choice of constant fixes it. A bigger number
            # wakes you more for noise; a smaller one delays the thing that matters.
            #
            # We already built the only thing that can tell them apart and then ignored it:
            # THE WAIT-FOR GRAPH. It knows, right now, whether anyone is HARD-blocked on you —
            # queued for a board you hold, waiting on a service you run. That is not "someone
            # wants to tell you something". It is "someone CANNOT PROCEED without you".
            #
            # So the floor stops protecting the fleet from mail and starts protecting your
            # attention from UNIMPORTANT mail. Same mechanism; correct question.
            if not self._is_blocking_someone(r.tag):
                last = self._woke_at.get(r.tag, 0.0)
                if now - last < _WAKE_MIN_INTERVAL:
                    continue

            # Dedup on "has it READ yet?", NOT "is this a new batch?".
            #
            # Keying on the newest message meant every *new* message minted a new key
            # and injected another /msg-check — and a session deep in a long tool call
            # stops touching its transcript, so its activity-derived status decays to
            # IDLE and it looks wakeable while it's actually grinding. The keystrokes
            # then QUEUE, and we'd stack 3+ /msg-checks on one session (seen live on
            # rt1180emulator, 2026-07-11). But a queued check that hasn't run yet does
            # not need a sibling: ONE check drains the entire backlog. So: once woken,
            # stay quiet until the recipient's last-seen watermark actually advances.
            seen_now = _read_last_seen(state_dir, r.tag) or ""
            prev = self._wake_outstanding.get(r.tag)
            if prev is not None:
                prev_seen, woke_at, prev_activity = _unpack_wake(prev)
                if seen_now == prev_seen:
                    # It still hasn't read. There is a /msg-check outstanding — QUEUED, not
                    # lost (Claude Code queues input typed while it's busy), and one check
                    # drains the whole backlog. A second one cannot help and will simply
                    # stack. Stay quiet.
                    #
                    # The ONE exception is a keystroke that never landed at all. We can tell
                    # the difference: a session grinding through a long tool call stops
                    # writing its transcript (which is exactly why its status decayed to IDLE
                    # and made it look wakeable) — so a FROZEN transcript means our check is
                    # still queued and waiting its turn. A transcript that has MOVED since we
                    # woke it, with a watermark that hasn't, is the only real evidence the
                    # keystroke went missing.
                    moved = r.last_activity_at > prev_activity + 1.0
                    if not (moved and (now - woke_at) >= _WAKE_RETRY_SECONDS):
                        continue
                    log.info("re-waking [%s]: it has been active for %.0fm since we typed "
                             "and still hasn't read — the keystroke was probably lost",
                             r.tag, (now - woke_at) / 60)
            # WAITING = parked at its prompt. Normally we never inject there (Kyle
            # might be typing at it) — and since WAITING is the resting state of every
            # quiet session, that guard is what forces him to hand-click "check msgs"
            # across 30+ sessions. An AUTONOMY WINDOW is his permission slip: "I'm not
            # at these keyboards; let them wake each other." So inside a live window we
            # lift the WAITING guard — but ONLY for mail from a fellow member, and we
            # still never interrupt a session that is genuinely BUSY (active/warm).
            allowed = r.status in _WAKEABLE_STATUSES
            if not allowed and r.status == Status.WAITING:
                peers = peers_in_window(self._autonomy, r.tag)
                senders = {_plain_name(s) for s in (info.get("senders") or [])}
                if peers and (senders & peers):
                    allowed = True
            if not allowed:
                continue  # busy, or attended and not in a window — retry once quiet
            await self._inject_msg_check(r, f"{info['count']} unread addressed to it")
            self._wake_outstanding[r.tag] = (seen_now, now, r.last_activity_at)
            self._woke_at[r.tag] = now
            changed = True
        if changed:
            await asyncio.to_thread(write_wake_state, self.coord_root, self._wake_outstanding)

    # A busy holder can't run /keep, so its board looks abandoned; and our busy
    # guard (rightly) won't interrupt it to say so. Conductor knows the owner is
    # working, so it heartbeats for them: activity IS the heartbeat.
    _HEARTBEAT_MIN_AGE = 60  # don't rewrite the lease on every 3s scan

    def _refresh_active_leases(self) -> None:
        now = int(time.time())
        for r in self.resources.get("resources", []):
            lease = r.get("lease")
            if not lease or lease.get("offered") or r.get("smi"):
                continue  # the GPU has nvidia-smi; it tells the truth by itself
            rec = self._live_session_for(lease.get("owner", ""))
            if rec is None or rec.status not in _BUSY_STATUSES:
                continue  # holder quiet (or gone) -> let it look idle, honestly
            # The owner is working, so the resource is not idle — say so right away.
            # (``idle`` mirrors the watchdog's ``idle_since``, which only catches up
            # on its next tick, and we throttle the lease write below.)
            lease["idle"] = 0
            last = lease.get("last_active_epoch") or 0
            if now - last < self._HEARTBEAT_MIN_AGE:
                continue
            if touch_lease_activity(self.res_root / r["name"], now):
                lease["last_active_epoch"] = now
                log.info("heartbeat for %s on behalf of a working [%s]", r["name"], lease.get("owner"))

    def _live_session_for(self, owner: str) -> SessionRecord | None:
        return next((s for s in self.sessions.values()
                     if _bare_tag(s.tag) == _bare_tag(owner) and s.status != Status.ENDED), None)

    async def _notify(self) -> None:
        """Ring Kyle's phone about the things that stop work dead: a Claude blocked on a question,
        a gated ``git push``, and — only if ``[bus].page_dead_readers`` is on — a DEAD reader
        (a session that isn't running while someone has an open question waiting on it).

        Everything else — idle leases, queue depth, mutual stalls, unread mail — resolves
        itself or waits, and notifying about it would train him to swipe us away. **If the
        fix is robotic, it isn't a page.** The dead-reader page is off by default for exactly
        that reason: a third alarm is a deliberate choice, and it only fires on the case a human
        genuinely must clear (relaunch the session).
        """
        dead = [s for s in self._silent if s.get("dead")] if self.settings.bus.page_dead_readers else []
        items = notifiable(self.decisions, self._push_requests, dead)
        # Forget items that are no longer pending FIRST, so the same question asked again
        # later rings immediately rather than being suppressed by a stale timestamp.
        self._notified = prune_sent(self._notified, items)
        pending = due(items, self._notified)
        if not pending:
            return
        subs = await asyncio.to_thread(read_subs, self.coord_root)
        if not subs:
            return                     # no phone registered — nothing to do, and not an error
        keys = await asyncio.to_thread(load_or_create_keys, self.coord_root)
        subject = vapid_subject(socket.gethostname())
        now = time.time()
        for item in pending:
            for sub in list(subs):
                ok = await asyncio.to_thread(send_one, sub, item, keys, subject)
                if ok is None:         # 410/404: that device is gone for good, not retrying
                    await asyncio.to_thread(drop_sub, self.coord_root, sub["endpoint"])
                    subs.remove(sub)
            self._notified[item["key"]] = now
            log.info("notified: %s", item["title"])

    _NOTICE_TTL_S = 3600.0

    async def _deliver_push_notices(self) -> None:
        """Tell a session its push was approved — but only once it is actually listening.

        A session that was just denied a push is mid-turn and BUSY, and a busy Claude Code
        session eats injected keystrokes silently. So we wait for it to go quiet, exactly as
        the mail/nudge/offer wakes do. If it never does, no harm: the grant is durable and the
        agent's next push succeeds regardless. The notice is a courtesy, not the channel.
        """
        if not self._push_notices:
            return
        now = time.time()
        for key, note in list(self._push_notices.items()):
            if now - note["queued"] > self._NOTICE_TTL_S:
                del self._push_notices[key]        # it'll find out by pushing
                continue
            rec = self._session_for_cwd(note["cwd"])
            if rec is None or rec.status in _BUSY_STATUSES:
                continue                           # busy -> the keystrokes would vanish
            sent = await self._inject_text(
                rec,
                note.get("text") or (
                    f"✅ Kyle approved your git push to {note['repo']} — re-run it whenever "
                    "you're ready. The approval waits for you; it covers exactly one push."),
                f"push verdict for {note['repo']}",
            )
            if sent:
                del self._push_notices[key]

    def _is_blocking_someone(self, tag: str | None) -> bool:
        """Is another session HARD-blocked on this one right now?

        Hard = it genuinely cannot proceed: queued for a board this session holds, or its job
        is sitting behind this session in a service queue. NOT "awaiting a reply" — twenty
        sessions awaiting a reply on a fast fleet is a conversation, not a crisis, and if that
        counted here the exemption would swallow the floor whole.

        This is the ONE case where interrupting a session is unambiguously right, and it is
        the case a fixed rate limit is blindest to: the bottleneck is busy *because* it is the
        bottleneck. The session you should interrupt least and the one you should interrupt
        most are frequently the same session. A constant cannot adjudicate that. The graph can.
        """
        if not tag:
            return False
        me = _plain_name(tag)
        return any(
            e.get("hard") and e.get("dst") == me
            for e in self.waiting.get("edges", [])
        )

    def _has_open_picker(self, rec: SessionRecord) -> bool:
        """Is this session sitting on an AskUserQuestion picker right now?

        This is a HARD guard on every keystroke we inject, and it fixes a real bug:
        **an open picker swallows typed text into its free-text "Other" field.** Type
        ``/msg-check`` at a session that is asking Kyle a question and you do not send it a
        message — you silently add "/msg-check" as an option to the menu he is about to
        answer, and possibly submit it.

        The ``WAITING``-status guard used to hide this by accident (a session on a picker is
        WAITING, and WAITING is not wakeable). But autonomy windows deliberately lift that
        guard — which is *exactly* the case where this fires. So it needs its own guard,
        keyed on a signal that means what it says.
        """
        if not self.decisions:      # the overwhelmingly common case — nobody is asking
            return False
        target = os.path.realpath(getattr(rec, "project_dir", "") or "")
        return bool(target) and any(
            d.get("cwd") and os.path.realpath(d["cwd"]) == target
            for d in self.decisions
        )

    def _tool_in_flight(self, rec: SessionRecord) -> bool:
        """Is this session on a tool that may be blocked at a permission prompt right now?

        A session sitting on ``Dangerous rm … — 1. Yes / 2. No`` (cursor on Yes) stops writing
        its transcript, so its status decays to IDLE/WAITING and it looks wakeable — but a
        typed Return there confirms *Yes*. We can't see the prompt from the transcript (Claude
        Code doesn't flush the tool until it completes), so we rely on the marker the
        tool-inflight hook wrote at PreToolUse.

        The marker alone isn't enough — a denied tool may not fire PostToolUse, so we also
        require that the session's transcript has NOT advanced past the marker. Once it has,
        the tool resolved (ran or was denied) and the session is back at a real prompt: safe.
        ``last_activity_at`` is the newest transcript mtime — the ground-truth signal, so a
        stale marker can never wedge the guard shut.
        """
        if not self._inflight:      # common case — nothing in flight anywhere
            return False
        target = os.path.realpath(getattr(rec, "project_dir", "") or "")
        m = self._inflight.get(target) if target else None
        if m is None:
            return False
        # Transcript advanced past the tool start ⇒ resolved ⇒ safe. Equal/behind ⇒ still
        # pending (conservative: refuse). last_activity_at is seconds; a 1s margin absorbs
        # clock granularity between the hook's clock and the transcript's.
        return rec.last_activity_at <= m["started_epoch"] + 1

    async def _inject_text(self, rec: SessionRecord, text: str, why: str) -> bool:
        """Type ``text`` into a live session's terminal (raises its window).

        THE CHOKE POINT. Attestation lives here, not at the call sites — a new injection path
        added next month cannot forget to attest, OR to honour the modal guards, if it cannot
        inject without passing through here. Call-site guarding is the version that rots (the
        ping paths bypassed this and were exactly the ones that could type into a prompt).
        """
        if self._has_open_picker(rec):
            log.info("NOT typing at [%s] (%s) — it has a question open and the picker "
                     "would eat the keystrokes", rec.tag, why)
            return False
        if self._tool_in_flight(rec):
            log.info("NOT typing at [%s] (%s) — a tool is in flight (possibly a permission "
                     "prompt); a Return here could confirm it", rec.tag, why)
            return False
        # ATTEST BEFORE TYPING. Kyle said "I didn't type that /msg-check" — he was right, and
        # neither he nor the receiving Claude had any way to know. The keystrokes arrive as a
        # USER TURN, indistinguishable from him. The receiving session then answered him as
        # though he had asked.
        await asyncio.to_thread(
            attest, self.settings.bus.state_dir_resolved,
            target_pid=rec.pid, target_tag=rec.tag, text=text, why=why,
            source="conductor:_inject_text", actor="conductor",
        )
        try:
            ok = await asyncio.to_thread(
                send_keys_to_session, text=text, pid=rec.pid,
                terminal_pid=rec.terminal_pid, title=rec.title, window_title=rec.window_title,
            )
            log.info("woke [%s] — %s", rec.tag, why)
            return bool(ok)
        except Exception:
            log.exception("failed to wake [%s]", rec.tag)
            return False

    async def _inject_msg_check(self, rec: SessionRecord, why: str) -> None:
        await self._inject_text(rec, "/msg-check", why)

    def _session_for_cwd(self, cwd: str) -> SessionRecord | None:
        """The live session running in ``cwd`` — how a push request maps back to the
        Claude that made it (the gate records the *session's* cwd)."""
        if not cwd:
            return None
        target = os.path.realpath(cwd)
        return next(
            (s for s in self.sessions.values()
             if s.status != Status.ENDED and os.path.realpath(s.project_dir) == target),
            None,
        )

    async def _wake_nudged_owners(self) -> None:
        """Make the watchdog's idle nudge actually reachable.

        A nudge is a bus message, and bus messages surface through a session's
        *per-prompt* hook — so an idle holder (the only kind that gets nudged!)
        never sees it, and the resource stays locked until expiry. Wake the owner
        once per idle *episode* (keyed on ``idle_since_epoch``, which the watchdog
        clears on activity) rather than on every 20-minute re-nudge, so we never
        repeatedly steal focus. Busy sessions are left alone and retried later.
        """
        current: set[str] = set()
        for r in self.resources.get("resources", []):
            lease = r.get("lease")
            if not lease or lease.get("offered") or not lease.get("nudged_epoch"):
                continue
            owner = lease.get("owner", "")
            key = f"{r['name']}\x00{owner}\x00{lease.get('idle_since_epoch')}"
            current.add(key)
            if key in self._nudge_woken:
                continue
            rec = self._live_session_for(owner)
            if rec is None or rec.status in _BUSY_STATUSES:
                continue  # gone (orphan logic covers it), or mid-task — retry next scan
            await self._inject_msg_check(rec, f"watchdog nudge on {r['name']} (idle)")
            self._nudge_woken.add(key)
        self._nudge_woken &= current  # a new idle episode gets a fresh wake

    def _annotate_orphans(self) -> None:
        """Flag leases whose owner has no live session.

        Unlike the watchdog's boot-time check (a lease older than the boot has a
        *provably* dead owner), this is only strong evidence: a session can be
        closed and relaunched. So Conductor never reclaims on its own — after a
        debounce it just marks the lease ``orphan_suspect`` so the user can hand
        it on with one click. Offers are skipped; they auto-pass on their own.
        """
        now = time.time()
        threshold = self.settings.bus.orphan_flag_seconds
        live = {_bare_tag(s.tag) for s in self.sessions.values() if s.tag and s.status != Status.ENDED}
        offline_keys: set[str] = set()
        for r in self.resources.get("resources", []):
            lease = r.get("lease")
            if not lease or lease.get("offered"):
                continue
            owner = lease.get("owner", "")
            if not owner:
                continue
            key = f"{r['name']}\x00{owner}"
            if _bare_tag(owner) in live:
                self._owner_missing_since.pop(key, None)
                lease.update(owner_live=True, owner_offline_seconds=0, orphan_suspect=False)
                continue
            offline_keys.add(key)
            since = self._owner_missing_since.setdefault(key, now)
            off = int(now - since)
            lease.update(owner_live=False, owner_offline_seconds=off, orphan_suspect=off >= threshold)
        for k in list(self._owner_missing_since):  # forget leases that are gone
            if k not in offline_keys:
                self._owner_missing_since.pop(k, None)

    async def _wake_offered_sessions(self) -> None:
        """The moment a resource is OFFERED to the next-in-queue, inject /msg-check
        into that session so it wakes and reads its ``you're up`` ping — the real-time
        half of the queue (the bus message is always posted regardless). We ping once
        per offer; a session we can't resolve falls back to seeing it on its next prompt."""
        current: set[str] = set()
        for r in self.resources.get("resources", []):
            lease = r.get("lease")
            if not lease or not lease.get("offered"):
                continue
            owner = lease.get("owner", "")
            key = f"{r['name']}\x00{owner}\x00{lease.get('acquired_epoch')}"
            current.add(key)
            if key in self._pinged_offers:
                continue
            rec = self._live_session_for(owner)
            if rec is None or rec.status in _BUSY_STATUSES:
                continue  # gone/untracked, or mid-task -> bus fallback; retry next scan
            await self._inject_msg_check(rec, f"offered {r['name']}")
            self._pinged_offers.add(key)
        self._pinged_offers &= current  # forget offers that have resolved (bounded)

    async def _activity_loop(self) -> None:
        queue = await self.activity.events()
        projects_root = self.settings.scanner.claude_home_path / "projects"
        while True:
            try:
                jsonl_path, preview = await queue.get()
            except asyncio.CancelledError:
                return
            # Find the session this jsonl belongs to (match the resolved path,
            # so cd'd sessions still update; fall back to the encoded cwd dir).
            rec = None
            jp = str(jsonl_path)
            for r in self.sessions.values():
                if r.jsonl_path:
                    if r.jsonl_path == jp:
                        rec = r
                        break
                elif newest_jsonl(projects_root / encode_cwd(r.project_dir)) == jsonl_path:
                    rec = r
                    break
            if rec is None:
                continue
            # Don't resurrect a tile the scanner has ENDED — on /exit Claude
            # writes trailing jsonl records, and flipping ENDED back to ACTIVE on
            # each would flap the tile. The scanner re-adds it if it's truly alive.
            if rec.status == Status.ENDED:
                continue
            rec.last_activity_at = time.time()
            rec.preview = preview or extract_preview(jsonl_path)
            rec.status = Status.ACTIVE
            await self.hub.broadcast("session", rec.to_dict())

    async def _bus_loop(self) -> None:
        async for ev in self.bus.stream_events():
            self.recent_events.append(ev)
            self.bus_total += 1
            await self.hub.broadcast("bus_event", {
                "event": ev.to_dict(),
                "total": self.bus_total,
                "topology": self.bus.get_topology().to_dict(),
            })

    # --- helpers -------------------------------------------------------------

    def _sync_members(self) -> None:
        """Bind every live session's session_id -> a durable member (v4 §3.4). Runs off-thread.

        The member is set ONCE, from the bare tag at first sighting, and never re-derived — so a
        session that `cd`s keeps its identity, and a role Kyle set is never reset by a later scan
        (``ensure_bound`` is a no-op once bound). Conductor is the registrar; the referee reads the
        same file. A brand-new fleet that has never had a role set still gets a members file of all
        ``peer`` rows — which is byte-for-byte today, because the referee adds no denial for peer.
        """
        try:
            for r in self.sessions.values():
                sid = getattr(r, "session_id", "") or ""
                if not sid or r.status == Status.ENDED or not r.tag:
                    continue
                member = _bare_tag(r.tag)
                if member:
                    ensure_bound(self.bus_state, sid, member, project=member)
            self._members = members_summary(self.bus_state)
            self._role_by_session = {
                sid: rec["role"] for sid, rec in read_members(self.bus_state).items()
            }
        except Exception:
            log.exception("member sync failed (non-fatal)")

    def _recent_transcripts(self, cwd: str, count: int) -> list[dict[str, Any]]:
        """The ``count`` most-recently-active transcripts in ``cwd``'s project dir, each with its
        session_id, last-activity age, and a preview — so a collision card can show WHAT each of the
        colliding sessions is doing (the two live sessions are the two freshest transcripts here)."""
        out: list[dict[str, Any]] = []
        if not cwd:
            return out
        try:
            pdir = self.settings.scanner.claude_home_path / "projects" / encode_cwd(cwd)
            files = sorted(pdir.glob("*.jsonl"), key=lambda f: f.stat().st_mtime, reverse=True)
        except OSError:
            return out
        now = time.time()
        for f in files[:max(1, count)]:
            try:
                sid, title, _ = parse_session_meta(f)
                age = max(0.0, now - f.stat().st_mtime)
                out.append({"session_id": sid, "age": age,
                            "title": title or "", "preview": extract_preview(f)})
            except OSError:
                continue
        return out

    def _pending_for(self, tag: str) -> int:
        """Pending count for a tag. For the markdown bus, computed live from the
        log; for other adapters, falls back to reading <tag>.pending."""
        if isinstance(self.bus, MarkdownBusAdapter):
            return compute_pending(
                self.settings.bus.markdown_path_resolved,
                self.settings.bus.state_dir_resolved,
                tag,
            )
        return read_pending(self.settings.bus.state_dir_resolved, tag)

    # --- relaunch ------------------------------------------------------------

    def _claude_tracked_cmd(self) -> list[str] | None:
        """Locate the ``claude-tracked`` launcher: prefer one on PATH (installed
        to /usr/local/bin), else the repo's ``scripts/claude-tracked``. None if
        neither is usable."""
        exe = shutil.which("claude-tracked")
        if exe:
            return [exe]
        repo = Path(__file__).resolve().parent.parent / "scripts" / "claude-tracked"
        if repo.exists() and os.access(repo, os.X_OK):
            return [str(repo)]
        return None

    def relaunch_parked(self, cwd: str, name: str, rc: bool, rename: bool) -> tuple[bool, str]:
        """Spawn ``claude-tracked <name> --dir <cwd> --continue`` in a new tracked
        terminal. If any post-launch keystrokes are enabled (``rc`` → ``/rc``,
        ``rename`` → ``/rename``), schedule them to inject once the session
        appears; otherwise it's a clean resume with no injection. Returns
        ``(ok, detail)``."""
        base = self._claude_tracked_cmd()
        if base is None:
            return False, "claude-tracked not found (install scripts/claude-tracked to PATH)"
        cmd = [*base, name, "--dir", cwd, "--continue"]
        try:
            # Detached: its own session/pgid so it outlives the request and isn't
            # killed when Conductor exits. No pipes — it owns a terminal window.
            subprocess.Popen(
                cmd, stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except Exception as e:  # noqa: BLE001
            log.exception("relaunch spawn failed: %s", e)
            return False, f"spawn failed: {e}"
        if rc or rename:
            asyncio.create_task(self._bootstrap_relaunched(cwd, name, rc, rename))
        return True, "launched"

    async def _bootstrap_relaunched(self, cwd: str, name: str, rc: bool, rename: bool) -> None:
        """Wait for the relaunched Claude to come up, then inject the enabled
        keystrokes — ``/rc`` (remote-control) when ``rc`` is on and/or
        ``/rename <name>`` when ``rename`` is on.

        This is the flaky part of the feature: keystrokes only land once the TUI
        is drawn and at a prompt. We poll the scanner for the new live session in
        that cwd (with a terminal window), then give it a settle delay before the
        first keystroke. Injection steals focus by design (see windows.py)."""
        cmds = (["/rc"] if rc else []) + ([f"/rename {name}"] if rename else [])
        if not cmds:
            return
        cfg = self.settings.relaunch
        target = os.path.realpath(cwd)
        deadline = time.time() + cfg.appear_timeout_seconds

        def _find() -> SessionRecord | None:
            return next(
                (r for r in self.sessions.values()
                 if r.status != Status.ENDED
                 and r.terminal_pid
                 and os.path.realpath(r.project_dir) == target),
                None,
            )

        rec = None
        while time.time() < deadline:
            await asyncio.sleep(0.5)
            rec = _find()
            if rec is not None:
                break
        if rec is None:
            log.warning("relaunch: session for %s never appeared within %.0fs",
                        cwd, cfg.appear_timeout_seconds)
            return

        # Let the TUI finish drawing its prompt before typing.
        await asyncio.sleep(cfg.settle_seconds)
        for i, text in enumerate(cmds):
            if i:
                await asyncio.sleep(cfg.between_seconds)
            rec = _find() or rec      # refresh pid/window in case the scan replaced it
            ok = await asyncio.to_thread(
                send_keys_to_session,
                text=text, pid=rec.pid, terminal_pid=rec.terminal_pid,
                title=rec.title, window_title=rec.window_title,
            )
            if not ok:
                log.warning("relaunch: failed to inject %r into %s", text, cwd)

    async def relaunch_batch(self, items: list[tuple[str, str]], rc: bool, rename: bool) -> None:
        """Relaunch several parked sessions — one at a time, on purpose.

        Fleet recovery after a reboot/crash means bringing ~20 Claudes back. Firing
        them all at once would stampede the box (20 processes + 20 terminal windows),
        and each *resuming* session may auto-compact its transcript, which is CPU- and
        token-heavy. So we launch one, wait for it to actually come up, pause, then
        start the next. A failure on one never stops the rest.
        """
        cfg = self.settings.relaunch
        launched = 0
        for real, name in items:
            ok, detail = self.relaunch_parked(real, name, rc, rename)
            if not ok:
                log.warning("relaunch-batch: %s failed: %s", real, detail)
                continue
            launched += 1
            target = os.path.realpath(real)
            deadline = time.time() + cfg.appear_timeout_seconds
            while time.time() < deadline:
                await asyncio.sleep(0.5)
                if any(r.status != Status.ENDED and os.path.realpath(r.project_dir) == target
                       for r in self.sessions.values()):
                    break
            else:
                log.warning("relaunch-batch: %s never appeared within %.0fs",
                            real, cfg.appear_timeout_seconds)
            await asyncio.sleep(cfg.batch_gap_seconds)
        log.info("relaunch-batch: done — %d/%d launched", launched, len(items))

    # --- payloads ------------------------------------------------------------

    def _active_retraction_for(self, tag: str | None) -> dict[str, Any] | None:
        """Newest retraction targeting ``tag`` that it hasn't acknowledged yet (its
        ``last-seen`` predates the retraction). Mirrors the recipient's hook."""
        if not tag:
            return None
        plain = _bare_tag(tag).split(":")[-1].lower()
        last_seen = _read_last_seen(self.settings.bus.state_dir_resolved, tag) or ""
        for r in self._retractions:  # newest-first
            if r["target_plain"] == plain and r["created"] > last_seen:
                return r
        return None

    def _sessions_payload(self) -> dict[str, Any]:
        sessions = []
        for r in self.sessions.values():
            d = r.to_dict()
            if r.jsonl_path:  # tally tokens from the transcript (incremental → cheap)
                d["tokens"] = self.token_accountant.usage_for(r.jsonl_path)
            info = self._directed_unread.get(r.tag or "")
            if info:  # messages addressed to this session (subset of pending_count)
                d["pending_directed"] = info.get("count", 0)
                d["pending_directed_from"] = info.get("senders", [])
            ret = self._active_retraction_for(r.tag)  # unacknowledged pull-back → red banner
            if ret:
                d["retraction"] = {"sender": ret["sender"], "text": ret["text"]}
            sid = getattr(r, "session_id", "") or ""
            d["role"] = self._role_by_session.get(sid, "peer")   # member registry role (v4 §3.4)
            d["member"] = _bare_tag(r.tag)
            sessions.append(d)
        parked = []
        for p in self.parked:
            d = p.to_dict()
            jp = d.pop("jsonl_path", "")   # internal: don't ship the path
            if jp:  # tokens-to-date, so the relaunch picker can sort by weight
                d["tokens"] = self.token_accountant.usage_for(jp)
            parked.append(d)
        return {
            "sessions": sessions,
            "parked": parked,
            "members": self._members,        # member registry (v4 §3.4): member -> role summary
            "silent": self._silent,          # dead-reader alarm (holobench)
            "collisions": self._collisions,  # two live sessions, one member (holobench)
            "fadeout_seconds": self.settings.ui.end_fadeout_seconds,
            "wmctrl_available": wmctrl_available(),
        }

    def _bus_payload(self) -> dict[str, Any]:
        # Per-tag pending counts pulled fresh so the bus tile badge stays accurate.
        topology = self.bus.get_topology()
        pending_by_tag = {tag: self._pending_for(tag) for tag in topology.subscribers}
        # "Active" tags are auto-notified of new traffic (the bus.sh hooks fire
        # for them, which is also what writes <tag>.last-seen). The rest are
        # "passive" — they've used the bus manually but won't get broadcasts.
        # For non-markdown adapters there's no such distinction, so all are active.
        if isinstance(self.bus, MarkdownBusAdapter):
            sd = self.settings.bus.state_dir_resolved
            # Prefer the toggleable data-file whitelist once bus.sh has been
            # migrated to it; until then fall back to .last-seen presence.
            active_tags = read_active_tags(sd) if active_tags_configured(sd) else list_known_tags(sd)
        else:
            active_tags = list(topology.subscribers)
        return {
            "total": self.bus_total,
            "recent": [e.to_dict() for e in list(self.recent_events)[-20:]],
            "topology": topology.to_dict(),
            "pending_by_tag": pending_by_tag,
            "active_tags": active_tags,
            "adapter": self.settings.bus.adapter,
        }


# --- FastAPI app -------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = load_settings()
    state = AppState(settings)
    app.state.cond = state
    await state.start()
    try:
        yield
    finally:
        await state.stop()


app = FastAPI(title="Conductor", lifespan=lifespan)


@app.middleware("http")
async def _auth_gate(request: Request, call_next):
    """Require the configured token on gated paths (``/api/*`` + ``/ws``).

    No-ops entirely when no token is configured (the localhost-only default), so
    existing local/desktop usage is untouched. The WebSocket handshake is checked
    in its own handler (middleware only sees HTTP), reusing ``token_ok``.
    """
    if path_requires_auth(request.url.path):
        cond = getattr(request.app.state, "cond", None)
        configured = resolved_token(cond.settings) if cond else ""
        provided = request.headers.get("X-Conductor-Token") or request.query_params.get("token")
        if not token_ok(configured, provided):
            return JSONResponse({"detail": "authentication required"}, status_code=401)
    return await call_next(request)


@app.get("/api/health")
async def health() -> dict[str, Any]:
    return {"ok": True, "version": __version__}


@app.get("/api/auth/check")
async def auth_check() -> dict[str, Any]:
    """Reaching this (past the auth middleware) means the token was accepted — or
    auth is disabled. The mobile/PWA login uses it to validate a token the user
    entered before wiring up the WebSocket."""
    return {"ok": True}


@app.get("/api/sessions")
async def get_sessions(request: Request) -> dict[str, Any]:
    state: AppState = request.app.state.cond
    return state._sessions_payload()


@app.post("/api/sessions/{session_id}/focus")
async def focus(session_id: str, request: Request) -> dict[str, Any]:
    state: AppState = request.app.state.cond
    rec = next((r for r in state.sessions.values() if r.session_id == session_id), None)
    if rec is None:
        raise HTTPException(status_code=404, detail="session not found")
    ok = await asyncio.to_thread(
        focus_session,
        pid=rec.pid,
        terminal_pid=rec.terminal_pid,
        title=rec.title,
        window_title=rec.window_title,
    )
    return {"focused": ok, "wmctrl_available": wmctrl_available()}


@app.post("/api/sessions/{session_id}/check")
async def check_bus(session_id: str, request: Request) -> dict[str, Any]:
    """Drive the *live* Claude session to read the bus.

    Types ``/msg-check`` + Enter into the session's terminal window via xdotool
    (activating it first — this steals focus). We deliberately do *not* run
    `bus.sh check` server-side: letting the real Claude run the skill is what the
    user asked for, and its own check bumps ``<tag>.last-seen`` so the pending
    badge clears naturally on the next scan once the message is truly seen.
    """
    state: AppState = request.app.state.cond
    rec = next((r for r in state.sessions.values() if r.session_id == session_id), None)
    if rec is None:
        raise HTTPException(status_code=404, detail="session not found")
    # Through the choke point, not straight to send_keys_to_session — so the manual ping
    # button honours the picker / tool-in-flight guards and attests, exactly like every
    # autonomous wake. This path used to bypass both, and it was one of the ways a keystroke
    # could land in a permission prompt.
    injected = await state._inject_text(rec, "/msg-check", "manual ping (check bus)")
    return {
        "injected": injected,
        "tag": rec.tag,
        "wmctrl_available": wmctrl_available(),
    }


@app.get("/api/bus")
async def get_bus(request: Request) -> dict[str, Any]:
    state: AppState = request.app.state.cond
    return state._bus_payload()


@app.get("/api/resources")
async def get_resources(request: Request) -> dict[str, Any]:
    """Shared-resource leases (+ nvidia-smi for the GPU), for the resource tiles.

    Serves the same scan-cached, orphan-annotated payload the WebSocket broadcasts
    (recomputing here would silently drop ``orphan_suspect`` — those flags need the
    live-session list, which only the scan loop has).
    """
    state: AppState = request.app.state.cond
    return state.resources


@app.post("/api/resources/{name}/reclaim")
async def reclaim_resource(name: str, request: Request) -> dict[str, Any]:
    """Hand on a lease whose owner has no live session (user-triggered only).

    Refuses unless Conductor has actually flagged the lease as an orphan suspect,
    so a live holder's reservation can never be yanked from the dashboard. The
    hand-off itself goes through ``bus.sh res promote`` — the same race-safe path
    the watchdog uses — so it offers the resource to the next in the queue, or
    frees it when nobody is waiting.
    """
    state: AppState = request.app.state.cond
    if not name or not all(c.isalnum() or c in "._-" for c in name):
        raise HTTPException(status_code=400, detail="bad resource name")
    entry = next((r for r in state.resources.get("resources", []) if r.get("name") == name), None)
    lease = entry.get("lease") if entry else None
    if not lease:
        raise HTTPException(status_code=404, detail="no active lease on that resource")
    if not lease.get("orphan_suspect"):
        raise HTTPException(status_code=409, detail="owner's session is live (or not offline long enough)")
    owner = lease.get("owner", "")
    proc = await asyncio.to_thread(
        subprocess.run,
        [str(state.settings.bus.script_path_resolved), "res", "promote", name, owner],
        capture_output=True, text=True, timeout=15,
    )
    result = (proc.stdout or "").strip()
    log.info("reclaimed orphaned lease on %s from [%s]: %s", name, owner, result or proc.returncode)
    return {"resource": name, "owner": owner, "result": result, "ok": proc.returncode == 0}


@app.get("/api/push")
async def get_push(request: Request) -> dict[str, Any]:
    """Pending push approvals. These also ride the WebSocket, but a client whose socket
    died silently (a backgrounded phone tab — mobile browsers kill sockets without
    always firing `close`) would sit on stale state forever. An endpoint it can re-fetch
    on wake makes the inbox self-healing instead of needing a manual refresh."""
    state: AppState = request.app.state.cond
    return {"requests": state._push_requests, "grants": state._push_grants,
            "proposals": state._push_proposals, "persist": state._persist_requests}


@app.post("/api/push/{key}/{action}")
async def decide_push(key: str, action: str, request: Request) -> dict[str, Any]:
    """Approve, deny, or REVOKE a gated ``git push`` (all user-triggered).

    Approve arms a durable one-shot grant the gate consumes on the session's next push —
    durable because Kyle approves from his phone and the *session* is the one that has to
    notice and retry; a short fuse meant the approval could expire unused and vanish, and
    he'd see a duplicate request with no hint he'd already said yes.

    ``revoke`` is the counterweight that makes a long-lived grant safe: he can take it back
    before it's used. All three go through ``bus.sh push`` — one token path, no second
    implementation to drift.
    """
    if action not in ("approve", "deny", "revoke"):
        raise HTTPException(status_code=404, detail="unknown action")
    if not key or not all(c.isalnum() or c in "._-" for c in key):
        raise HTTPException(status_code=400, detail="bad request key")
    state: AppState = request.app.state.cond
    # Grab the request BEFORE bus.sh consumes it — we need its cwd to tell the
    # asking session that it's cleared to go.
    req = next((r for r in state._push_requests if r.get("key") == key), None)
    proc = await asyncio.to_thread(
        subprocess.run,
        [str(state.settings.bus.script_path_resolved), "push", action, key],
        capture_output=True, text=True, timeout=15,
    )
    ok = proc.returncode == 0
    log.info("push %s [%s]: %s", action, key, (proc.stdout or "").strip() or proc.returncode)

    # Close the loop: approving is useless if the session never hears about it. The
    # gate DENIED its push, so it's sitting there waiting — and without this Kyle has
    # to go tell it himself, which is exactly the couriering auto-delivery exists to
    # kill. Tell it directly (not via the bus: a session parked at its prompt is
    # WAITING, which auto-delivery deliberately never wakes). Status guard is skipped
    # on purpose — this is a direct answer to a request THIS session made, and Kyle
    # just clicked. Deny stays silent: "Dismiss" may only mean "clear my inbox".
    notified = None
    if ok and action == "approve" and req:
        # QUEUE it; do not fire it here. Firing it here used to "work" and silently didn't:
        # a session that has just been DENIED a push is usually still BUSY (it's mid-turn,
        # reacting to the denial), and **a busy Claude Code session swallows injected
        # keystrokes**. `send_keys_to_session` returns True because xdotool exited 0 — but
        # xdotool succeeding is not the message arriving. Kyle approved on his phone, the log
        # said "woke [claude-connect]", and the text landed in NO transcript at all. The
        # earlier pings only worked because the session happened to be idle. Luck.
        #
        # So the ping is now delivered by `_deliver_push_notices()` on a later scan, once the
        # session is genuinely quiet — the same discipline every other wake path already uses.
        # And it stays an ACCELERATOR, never the mechanism: the grant is durable, so an agent
        # that never hears a word still pushes fine on its next attempt. That is what saved
        # this one.
        state._push_notices[key] = {
            "cwd": req.get("cwd", ""),
            "repo": req.get("repo_name", key),
            "queued": time.time(),
        }
        rec = state._session_for_cwd(req.get("cwd", ""))
        notified = rec.tag if rec is not None else None
        log.info("push approved for %s — notice queued for %s",
                 key, (rec.tag if rec else "no live session (the grant waits)"))

    # Re-read now rather than waiting for the next scan tick: a just-approved request must
    # move to the "approved, waiting" list immediately, or the click looks like it did
    # nothing — the very confusion this whole change exists to kill.
    state._push_requests = await asyncio.to_thread(read_push_requests, state.coord_root)
    state._push_grants = await asyncio.to_thread(read_push_grants, state.coord_root)
    await state.hub.broadcast("push", {"requests": state._push_requests,
                                       "grants": state._push_grants})
    return {"key": key, "action": action, "ok": ok,
            "result": (proc.stdout or "").strip(), "notified": notified}


class AutonomyRequest(BaseModel):
    members: list[str]          # session tags
    hours: float = 8.0          # 3 min .. 24 h (clamped)


@app.get("/api/autonomy")
async def get_autonomy(request: Request) -> dict[str, Any]:
    state: AppState = request.app.state.cond
    return {"windows": state._autonomy}


@app.post("/api/autonomy")
async def post_autonomy(payload: AutonomyRequest, request: Request) -> dict[str, Any]:
    """Open an autonomy window: for `hours`, these sessions may wake each other on
    directed mail even while parked at a prompt (WAITING). Busy sessions are still
    never interrupted, and only directed mail wakes anyone — so a fleet-wide window
    can't storm itself. It expires on its own; that time-box IS the safety property."""
    state: AppState = request.app.state.cond
    members = [m for m in (t.strip() for t in payload.members) if m]
    if len(members) < 2:
        raise HTTPException(status_code=400, detail="pick at least two sessions")
    win = await asyncio.to_thread(open_window, state.coord_root, members, payload.hours)
    state._autonomy = await asyncio.to_thread(read_windows, state.coord_root)
    await state.hub.broadcast("autonomy", {"windows": state._autonomy})
    log.info("autonomy window %s opened over %d sessions for %.2fh",
             win["id"], len(members), payload.hours)
    return {"ok": True, "window": win}


@app.delete("/api/autonomy/{window_id}")
async def delete_autonomy(window_id: str, request: Request) -> dict[str, Any]:
    """End a window early ("I'm back at the keyboard")."""
    state: AppState = request.app.state.cond
    ok = await asyncio.to_thread(close_window, state.coord_root, window_id)
    state._autonomy = await asyncio.to_thread(read_windows, state.coord_root)
    await state.hub.broadcast("autonomy", {"windows": state._autonomy})
    log.info("autonomy window %s closed early: %s", window_id, ok)
    return {"ok": ok}


@app.get("/api/waiting")
async def get_waiting(request: Request) -> dict[str, Any]:
    """The fleet's wait-for graph: who is blocked on whom, which cycles exist, and who is
    holding up the most sessions. Edge A -> B means "A is blocked on B"."""
    state: AppState = request.app.state.cond
    return state.waiting


@app.get("/api/services")
async def get_services(request: Request) -> dict[str, Any]:
    state: AppState = request.app.state.cond
    return state.services


@app.post("/api/services/{name}/{action}")
async def service_action(name: str, action: str, request: Request) -> dict[str, Any]:
    """Kyle's override on a service Claude.

    ``hold`` = "serve me next": it finishes the job it's on (no half-done render, no
    wasted GPU) and then WAITS for him instead of pulling the next queued job. He is
    never a queue entry — he talks to the service directly — so his priority is a hold
    on the queue, not a place in it. ``resume`` hands it back to the fleet.
    """
    if action not in ("hold", "resume"):
        raise HTTPException(status_code=404, detail="unknown action")
    if not name or not all(c.isalnum() or c in "._-" for c in name):
        raise HTTPException(status_code=400, detail="bad service name")
    state: AppState = request.app.state.cond
    args = [str(state.settings.bus.script_path_resolved), "svc", action, name]
    if action == "hold":
        args.append("Kyle claimed the next opening from the dashboard")
    proc = await asyncio.to_thread(subprocess.run, args, capture_output=True, text=True, timeout=15)
    state.services = await asyncio.to_thread(read_services, state.coord_root)
    await state.hub.broadcast("services", state.services)
    log.info("service %s %s: %s", name, action, (proc.stdout or "").strip() or proc.returncode)
    return {"ok": proc.returncode == 0, "result": (proc.stdout or "").strip()}


@app.get("/api/decisions")
async def get_decisions(request: Request) -> dict[str, Any]:
    """Questions the fleet is blocked on, waiting for a human. Oldest first."""
    state: AppState = request.app.state.cond
    return {"decisions": state.decisions}


class DecisionAnswer(BaseModel):
    # One list of chosen option LABELS per question (a single-select question gets a
    # one-item list). Labels, not indices: an index is only meaningful against the option
    # order we captured, and if that has changed underneath us we want a mismatch we can
    # DETECT, not a digit that happens to be in range.
    answers: list[list[str]]


@app.post("/api/decisions/{session_id}")
async def answer_decision(session_id: str, payload: DecisionAnswer,
                          request: Request) -> dict[str, Any]:
    """Answer a Claude's question by driving its picker.

    This types into a terminal we do not own, so it verifies before it acts and refuses
    rather than guesses:

      * the question must still be pending (not already answered at the keyboard);
      * its session must still be live and locatable;
      * every chosen label must exist on the captured question — a label we can't find is
        a state mismatch, and pressing a digit we guessed at would submit an answer Kyle
        never gave, silently.
    """
    state: AppState = request.app.state.cond
    rec_dec = next((d for d in state.decisions if d["session_id"] == session_id), None)
    if rec_dec is None:
        # Almost always benign: Kyle answered it at the keyboard between the phone
        # rendering it and him tapping. Say so plainly rather than 500-ing.
        raise HTTPException(status_code=409,
                            detail="that question is no longer pending — it was already answered")

    session = state._session_for_cwd(rec_dec.get("cwd", ""))
    if session is None:
        raise HTTPException(status_code=409,
                            detail="the session that asked is no longer running")

    try:
        keys = plan_keystrokes(rec_dec["questions"], payload.answers)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    # ⚠️ THE CONSENT CHANNEL, AND IT IS THE ONE image_gen's OWN SPEC MISSED.
    #
    # `/msg-check` is a read-only nudge. THIS is how "yes, install it" reaches a Claude — we
    # answer its AskUserQuestion picker by typing keystrokes. A provenance ledger that attests
    # the harmless nudge and not the channel that answers consent dialogs is theatre: it
    # watches the door nobody breaks in through.
    #
    # So we record WHO drove it. "Genuinely Kyle" must be a VERIFIED join against the ledger,
    # never an assumption made because the answer looked plausible. image_gen assumed today.
    # It happened to be true. "It happened to be true" is not a control.
    client = request.client.host if request.client else "?"
    await asyncio.to_thread(
        attest, state.settings.bus.state_dir_resolved,
        target_pid=session.pid, target_tag=session.tag,
        text=f"[picker] {payload.answers}", why=f"answered via {client}",
        source="conductor:answer_decision", actor=f"human:{client}",
    )
    ok = await asyncio.to_thread(
        send_key_sequence, keys=keys, pid=session.pid,
        terminal_pid=session.terminal_pid, title=session.title,
        window_title=session.window_title,
    )
    if not ok:
        raise HTTPException(status_code=502,
                            detail="couldn't reach that session's window — answer it at the keyboard")

    # Clear it now rather than waiting for the PostToolUse hook to land on the next scan:
    # a question that still shows as pending after you answered it invites a second answer.
    await asyncio.to_thread(reap_decision, state.coord_root, session_id)
    state.decisions = [d for d in state.decisions if d["session_id"] != session_id]
    await state.hub.broadcast("decisions", {"decisions": state.decisions})
    log.info("answered [%s]: %s -> keys %s", session.tag, payload.answers, keys)
    return {"ok": True, "keys": keys}


@app.get("/api/webpush/key")
async def webpush_key(request: Request) -> dict[str, Any]:
    """The VAPID public key the browser needs to create a subscription."""
    state: AppState = request.app.state.cond
    keys = await asyncio.to_thread(load_or_create_keys, state.coord_root)
    return {"key": keys["public"]}


class WebPushSub(BaseModel):
    endpoint: str
    keys: dict[str, str]


@app.post("/api/webpush/subscribe")
async def webpush_subscribe(sub: WebPushSub, request: Request) -> dict[str, Any]:
    state: AppState = request.app.state.cond
    subs = await asyncio.to_thread(
        add_sub, state.coord_root, {"endpoint": sub.endpoint, "keys": sub.keys})
    log.info("webpush: device registered (%d total)", len(subs))
    return {"ok": True, "devices": len(subs)}


class WebPushDrop(BaseModel):
    endpoint: str


@app.post("/api/webpush/unsubscribe")
async def webpush_unsubscribe(payload: WebPushDrop, request: Request) -> dict[str, Any]:
    """Turn notifications off for a device.

    The browser can unsubscribe on its own, but if we weren't told, the server would keep a
    dead endpoint and keep pushing into it — every send failing silently, forever. Off has to
    mean off on BOTH sides or it doesn't mean anything.
    """
    state: AppState = request.app.state.cond
    await asyncio.to_thread(drop_sub, state.coord_root, payload.endpoint)
    remaining = await asyncio.to_thread(read_subs, state.coord_root)
    log.info("webpush: device unsubscribed (%d left)", len(remaining))
    return {"ok": True, "devices": len(remaining)}


@app.post("/api/webpush/test")
async def webpush_test(request: Request) -> dict[str, Any]:
    """Ring every registered device once.

    This exists because every failure mode of Web Push is SILENT — a wrong VAPID key, a
    revoked permission, a service worker that never activated — and all of them look exactly
    like "nothing needs you right now". You cannot debug a notification system by waiting to
    see whether it notifies you.
    """
    state: AppState = request.app.state.cond
    subs = await asyncio.to_thread(read_subs, state.coord_root)
    if not subs:
        raise HTTPException(status_code=404, detail="no device is registered for notifications")
    keys = await asyncio.to_thread(load_or_create_keys, state.coord_root)
    payload = {"title": "🔔 Conductor",
               "body": "Notifications are working.",
               "url": "/m", "tag": "test"}
    subject = vapid_subject(socket.gethostname())
    sent = 0
    for sub in list(subs):
        ok = await asyncio.to_thread(send_one, sub, payload, keys, subject)
        if ok is None:
            await asyncio.to_thread(drop_sub, state.coord_root, sub["endpoint"])
        elif ok:
            sent += 1
    return {"ok": sent > 0, "sent": sent, "devices": len(subs)}


class UnstallRequest(BaseModel):
    nodes: list[str]


def _stall_message(nodes: list[str], deadlock: bool, edges: list[dict[str, Any]]) -> str:
    """The message a stalled Claude cannot write for itself.

    A mutual stall is invisible from the inside — *by construction*. Each side believes it is
    politely awaiting a reply, which is a completely reasonable thing to believe, and neither
    can see that the other believes the same thing about them. Both are behaving correctly and
    the pair is stuck. **The only actor who can see the loop is the one standing outside it.**

    So this doesn't nag them to hurry up. It tells them the one fact they are missing.
    """
    who = " → ".join(nodes + [nodes[0]])
    to_line = " ".join(f"to:{n}" for n in nodes)
    why = "\n".join(
        f"  • **{e['src']} is waiting on {e['dst']}** — {e['why']}"
        for e in edges
    )

    if deadlock:
        return (
            f"{to_line} — [operator] 🛑 **DEADLOCK — you are in a resource cycle and it will "
            f"NEVER resolve itself. Kyle is telling you from outside the loop.**\n\n"
            f"    {who}\n\n{why}\n\n"
            "**Each of you is holding a resource the other is queued for.** Neither can make "
            "progress by waiting, no matter how long you wait — and waiting is exactly what "
            "each of you is currently doing. This is not a delay; it is a permanent stop.\n\n"
            "**One of you has to release.** Decide between yourselves who is closer to a "
            "natural stopping point and `/release` that resource — the other will be offered "
            "it immediately and can hand it back when done. **Do not both wait for the other "
            "to go first: that is precisely the state you are already in.**"
        )

    return (
        f"{to_line} — [operator] 🔁 **MUTUAL STALL — you are each waiting for the other to "
        f"speak. Neither of you can see this from inside; Kyle can, from outside.**\n\n"
        f"    {who}\n\n{why}\n\n"
        "**Nobody is blocked and nothing is broken.** Each of you sent something, is politely "
        "awaiting a reply, and reasonably assumes the silence means the other is still "
        "thinking. **You are both assuming that about each other, which is why neither of you "
        "has spoken, which is why the silence continues.** It can run indefinitely, and it "
        "costs you nothing to notice — because from where you are sitting, it looks exactly "
        "like a conversation in progress.\n\n"
        "**Either of you can end it right now by replying — so do, both of you.** If you were "
        "waiting on an answer, ask again plainly. If you already have what you need, say so "
        "and close the thread. If you are genuinely blocked on the other, say what you need "
        "and by when. **A short 'I have nothing further' is a complete and useful answer** — "
        "silence is not."
    )


@app.post("/api/unstall")
async def unstall(payload: UnstallRequest, request: Request) -> dict[str, Any]:
    """Tell a stalled cycle that it is stalled.

    Kyle's ask, and it's the right shape: **a mutual stall is invisible to its participants
    by definition.** Each one thinks it's awaiting a reply. The only actor who can see the
    loop is the one outside it — which, right now, is the dashboard.

    Posts a directed bus message naming the loop and every edge in it, then wakes each member
    that is quiet enough to actually hear it. Busy members are left alone: a busy Claude Code
    session swallows injected keystrokes without a trace (learned the hard way tonight), and
    the message is directed mail anyway, so auto-delivery reaches them when they surface.
    """
    state: AppState = request.app.state.cond
    if not isinstance(state.bus, MarkdownBusAdapter):
        raise HTTPException(status_code=409, detail="sending requires the markdown bus adapter")

    want = [n.strip() for n in payload.nodes if n.strip()]
    if len(want) < 2:
        raise HTTPException(status_code=400, detail="a cycle needs at least two members")

    # Only nudge a cycle the backend ITSELF currently sees. Otherwise this endpoint is an
    # arbitrary "message these N sessions and wake them all" primitive, which is a much
    # bigger gun than the button Kyle asked for.
    cycle = next(
        (c for c in state.waiting.get("cycles", []) if sorted(c["nodes"]) == sorted(want)),
        None,
    )
    if cycle is None:
        raise HTTPException(status_code=409,
                            detail="that stall is no longer active — it may have resolved itself")

    nodes = cycle["nodes"]

    # IDEMPOTENCY. The cycle stays in `state.waiting` until the next scan, so a second tap
    # re-posts — and Kyle tapped three times, because the UI gave him no sign the first one
    # landed. THREE identical "you are both waiting" messages went to the fleet.
    #
    # This is the Approve-button bug, and I made it again: I fixed the optimistic-state-wiped-
    # by-re-render problem for push approvals two hours ago and did not carry it one column to
    # the right. rt1180 named this disease TODAY — "a correctly-flagged gap you stop thinking
    # about BECAUSE you flagged it" — and I did it inside the same afternoon.
    #
    # The UI fix follows, but the guard belongs HERE: a frontend bug must never be able to spam
    # ten sessions. Telling a stall it is stalled twice in five minutes is not a nudge, it's
    # noise — and noise is what makes the next one ignorable.
    ck = "|".join(sorted(nodes))
    last = state._unstalled.get(ck, 0.0)
    if time.time() - last < _UNSTALL_COOLDOWN:
        raise HTTPException(
            status_code=429,
            detail="they've already been told — give them a few minutes to answer")
    state._unstalled[ck] = time.time()

    pairs = {(nodes[i], nodes[(i + 1) % len(nodes)]) for i in range(len(nodes))}
    edges = [e for e in state.waiting.get("edges", []) if (e["src"], e["dst"]) in pairs]

    body = _stall_message(nodes, bool(cycle.get("deadlock")), edges)
    await asyncio.to_thread(
        append_message,
        state.settings.bus.markdown_path_resolved,
        state.settings.bus.sender_tag,
        body,
    )

    pinged: list[str] = []
    for name in nodes:
        rec = next((r for r in state.sessions.values()
                    if _plain_name(r.tag or "") == name and r.status != Status.ENDED), None)
        if rec is None or rec.status in _BUSY_STATUSES:
            continue          # busy sessions eat keystrokes; the directed mail still reaches them
        if await state._inject_text(rec, "/msg-check", f"mutual stall: {' → '.join(nodes)}"):
            pinged.append(name)

    log.info("unstalled %s (deadlock=%s), pinged %s",
             " → ".join(nodes), cycle.get("deadlock"), pinged or "nobody (all busy)")
    return {"ok": True, "nodes": nodes, "pinged": pinged,
            "deadlock": bool(cycle.get("deadlock"))}


class ProposalAnswer(BaseModel):
    # "" (empty) = push now. Otherwise the exact alternative label Kyle picked.
    choice: str = ""


# NOT "/api/push/proposals/{key}": `@app.post("/api/push/{key}/{action}")` is registered
# earlier and would match it first, with key="proposals" and action="<the real key>" — so
# every tap came back "unknown action". A route that is a strict prefix-shape of another
# route is shadowed by whichever was registered first, silently. Its own namespace, no
# ambiguity possible.
@app.post("/api/proposals/{key}")
async def answer_proposal(key: str, payload: ProposalAnswer,
                          request: Request) -> dict[str, Any]:
    """Answer a session's *"should I push now, or keep digging?"*.

    **Choosing "push now" ARMS the grant.** That's the whole point: Kyle makes ONE decision,
    at the moment he actually has the information — what's in the commits, and what the
    session would do instead. Without this, he'd answer the real question here and then be
    asked a second, content-free question ("approve claude-connect — git push origin main")
    ten minutes later, which is a rubber stamp on a decision he already made.

    The gate is untouched. A grant is still one push, still consumed on use, still revocable.
    We are not weakening the control — we are moving Kyle's tap to where the information is.
    """
    if not key or not all(c.isalnum() or c in "._-" for c in key):
        raise HTTPException(status_code=400, detail="bad proposal key")
    state: AppState = request.app.state.cond
    prop = next((p for p in state._push_proposals if p["key"] == key), None)
    if prop is None:
        raise HTTPException(status_code=409, detail="that proposal is no longer open")

    choice = payload.choice.strip()
    if choice and choice not in prop["alts"]:
        # A label we don't recognise means our view of the question is stale. Refuse rather
        # than tell a session to do something Kyle didn't pick.
        raise HTTPException(status_code=400, detail="that isn't one of the options")

    approved = not choice
    if approved:
        proc = await asyncio.to_thread(
            subprocess.run,
            [str(state.settings.bus.script_path_resolved), "push", "approve",
             prop["repo_name"]],
            capture_output=True, text=True, timeout=15,
        )
        if proc.returncode != 0:
            # No pending gate request yet (the usual case — a proposal comes BEFORE the
            # session ever tries to push), so mint the grant directly from the proposal.
            await asyncio.to_thread(_mint_grant, state.coord_root, key, prop["repo_name"],
                                    prop.get("repo", ""))
        msg = (f"✅ Kyle says PUSH — the approval is already armed for {prop['repo_name']}, "
               "so just run your push. It covers exactly one push.")
    else:
        msg = (f"🛑 Kyle says NOT YET. Instead: {choice}\n"
               "Do not push. Carry on with that, and propose again when you're ready.")

    await asyncio.to_thread(clear_push_proposal, state.coord_root, key)
    state._push_proposals = await asyncio.to_thread(read_push_proposals, state.coord_root)
    state._push_grants = await asyncio.to_thread(read_push_grants, state.coord_root)

    # Deliver the verdict the same way as an approval notice: QUEUED, and typed only once the
    # session is quiet. A session waiting on an answer is often mid-work, and a busy Claude
    # Code session QUEUES injected keystrokes rather than dropping them — which is how we got
    # 16 stacked /msg-checks. Never type at a busy one.
    state._push_notices[f"proposal:{key}"] = {
        "cwd": prop.get("cwd", ""), "repo": prop["repo_name"],
        "queued": time.time(), "text": msg,
    }
    await state.hub.broadcast("push", {"requests": state._push_requests,
                                       "grants": state._push_grants,
                                       "proposals": state._push_proposals})
    log.info("push proposal %s: %s", key, "PUSH" if approved else f"defer -> {choice}")
    return {"ok": True, "approved": approved, "choice": choice}


@app.post("/api/persist/{key}/{action}")
async def decide_persist(key: str, action: str, request: Request) -> dict[str, Any]:
    """Approve / deny / revoke an act whose consequences outlive the session.

    Same machinery as the push gate, because that shape is proven — and because the property
    that matters is identical: **the grant is bound to the ACTION, not conveyed in PROSE.**
    Kyle clicks; a token appears in a file; the gate consumes it once. No amount of a Claude
    saying "Kyle approved this" can substitute, which is precisely the failure that happened
    this morning.
    """
    if action not in ("approve", "deny", "revoke"):
        raise HTTPException(status_code=404, detail="unknown action")
    if not key or not all(c.isalnum() or c in "._-" for c in key):
        raise HTTPException(status_code=400, detail="bad request key")
    state: AppState = request.app.state.cond
    req = next((r for r in state._persist_requests if r.get("key") == key), None)
    name = (req or {}).get("target_name") or key
    proc = await asyncio.to_thread(
        subprocess.run,
        [str(state.settings.bus.script_path_resolved), "persist", action, name],
        capture_output=True, text=True, timeout=15,
    )
    ok = proc.returncode == 0
    state._persist_requests = await asyncio.to_thread(read_persist_requests, state.coord_root)
    await state.hub.broadcast("push", {"requests": state._push_requests,
                                       "grants": state._push_grants,
                                       "proposals": state._push_proposals,
                                       "persist": state._persist_requests})
    log.info("persist %s [%s]: %s", action, name, (proc.stdout or "").strip() or proc.returncode)
    return {"ok": ok, "result": (proc.stdout or "").strip()}


@app.post("/api/members/{member}/role")
async def set_member_role(member: str, request: Request) -> dict[str, Any]:
    """Set a member's role (v4 §3.4) — the deliberate human act. Observer *lowers* authority,
    Trusted *raises* it, so it is always Kyle's tap and never inferred. The referee reads the same
    file on its next tool call and enforces; there is no push to the sessions, and nothing is
    consumed — a role is durable state, visible and revocable (set it back to peer to revoke)."""
    body = await request.json()
    role = (body or {}).get("role", "")
    if not member or not all(c.isalnum() or c in "._:-" for c in member):
        raise HTTPException(status_code=400, detail="bad member")
    state: AppState = request.app.state.cond
    try:
        changed = await asyncio.to_thread(set_role, state.bus_state, member, role)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    state._members = await asyncio.to_thread(members_summary, state.bus_state)
    state._role_by_session = {
        sid: rec["role"] for sid, rec in (await asyncio.to_thread(read_members, state.bus_state)).items()
    }
    log.info("member role set: %s -> %s (%d session(s))", member, role, changed)
    await state.hub.broadcast("members", {"members": state._members})
    return {"ok": True, "member": member, "role": role, "sessions_changed": changed}


@app.get("/api/members")
async def get_members(request: Request) -> dict[str, Any]:
    state: AppState = request.app.state.cond
    return {"members": state._members, "roles": list(_MEMBER_ROLES)}


@app.get("/api/ops")
async def get_ops(request: Request) -> dict[str, Any]:
    """Everything the phone console needs, in ONE call.

    The phone talks over a Tailscale tunnel where six round-trips is the difference
    between "instant" and "sluggish", and the ops console is a glance-and-act tool — it
    must be usable in the seconds before you put the phone back in your pocket.

    Deliberately NOT the desktop payload: no tile geometry, no groups, no token
    histories, no bus feed. Counts and the things that are blocked on a human.
    """
    state: AppState = request.app.state.cond
    live = [s for s in state.sessions.values() if s.status != Status.ENDED]
    busy = [s for s in live if s.status in _BUSY_STATUSES]
    return {
        "decisions": state.decisions,
        "push": state._push_requests,
        # Approvals already GIVEN, not yet used. Shown so a durable grant is a permission
        # Kyle can see and take back, rather than one that quietly expires behind his back.
        "grants": state._push_grants,
        "proposals": state._push_proposals,
        "persist": state._persist_requests,
        "retractions": state._retractions,
        # read_windows() already drops expired windows — re-filtering here on a field name
        # I guessed at ("expires_epoch") silently zeroed the list while 14 sessions were
        # live and talking. A permission display that lies in the SAFE direction is still
        # lying, and this is the one screen that tells Kyle the fleet is unattended.
        "autonomy": state._autonomy,
        "waiting": state.waiting,
        # Dead-reader alarm + dual-session collisions (holobench). Both are "something is wrong
        # with a session's REACHABILITY that only a human resolves" — surfaced on the phone too.
        "silent": state._silent,
        "collisions": state._collisions,
        "services": state.services.get("services", []),
        "resources": state.resources.get("resources", []),
        "counts": {
            "needs_you": (len(state.decisions) + len(state._push_requests)
                          + len(state._push_proposals) + len(state._persist_requests)),
            "blocked": state.waiting.get("blocked_count", 0),
            "dead": sum(1 for s in state._silent if s.get("dead")),
            "collisions": len(state._collisions),
            "working": len(busy),
            "live": len(live),
            "idle": len(live) - len(busy),
            "parked": len(state.parked),
        },
        # Reuse the canonical record shape rather than inventing a parallel one — a second
        # definition of "a session" is a second thing to keep in sync, and it will drift.
        "sessions": sorted(
            (_ops_session_of(state, s) for s in live),
            key=lambda d: (d["status"] != Status.ACTIVE.value, d.get("name") or ""),
        ),
    }


def _ops_session_of(state: AppState, r: SessionRecord) -> dict[str, Any]:
    d = r.to_dict()
    info = state._directed_unread.get(r.tag or "")
    target = os.path.realpath(r.project_dir)
    return {
        "tag": d.get("tag"),
        "project": r.project_dir,
        "name": Path(r.project_dir).name,
        "status": d.get("status"),
        "preview": d.get("preview") or "",
        "idle_seconds": max(0.0, time.time() - (r.last_activity_at or 0.0)),
        "pending": (info or {}).get("count", 0),
        "asking": any(
            dd.get("cwd") and os.path.realpath(dd["cwd"]) == target
            for dd in state.decisions
        ),
        # Member registry (v4 §3.4): the durable member + its role, so the phone can set roles too.
        "member": _bare_tag(r.tag),
        "role": state._role_by_session.get(getattr(r, "session_id", "") or "", "peer"),
    }


def _human_label() -> str:
    """Display name for the ``[you]`` node — the OS username (capitalized), so it
    reads sensibly for whoever is running Conductor; ``"You"`` if unavailable."""
    try:
        u = getpass.getuser()
    except Exception:
        u = ""
    return (u[:1].upper() + u[1:]) if u else "You"


@app.get("/api/bus/heatmap")
async def get_bus_heatmap(request: Request, human: bool = False) -> dict[str, Any]:
    """Mention graph over the entire bus history (live log + monthly archives).

    Feeds the 🕸 History time-lapse: nodes are sessions, events are timestamped
    messages with the list of other sessions each one named. Parsed off-thread
    since it reads every archive file. See ``build_mention_history``.

    With ``?human=1`` it also weaves in the **human↔Claude** layer: a ``[you]``
    node plus turn-level prompt/reply events read from ``~/.claude/projects``
    transcripts (``collect_human_events``), keyed to the same bus tags. Each
    event carries ``kind`` (``bus`` | ``prompt`` | ``reply``) so the frontend can
    style the human edges distinctly. Default (no param) is byte-for-byte the
    bus-only graph.
    """
    state: AppState = request.app.state.cond
    path = state.settings.bus.markdown_path_resolved
    base = await asyncio.to_thread(build_mention_history, path)
    if not human:
        return base

    projects_root = state.settings.scanner.claude_home_path / "projects"
    tag_map = state.settings.bus.tags
    hres = await asyncio.to_thread(collect_human_events, projects_root, tag_map)

    for e in base["events"]:
        e["kind"] = "bus"
    merged = base["events"] + hres["events"]
    merged.sort(key=lambda e: e["ts"])

    # Recompute nodes from the merged stream: a tag's first_seen = its earliest
    # appearance, count = times it's a source (bus sends + human turns). Preserve
    # the bus's first-appearance ordering, then append new tags by first_seen.
    first_seen: dict[str, float] = {}
    count: dict[str, int] = {}
    for e in merged:
        s = e["source"]
        first_seen.setdefault(s, e["ts"])
        count[s] = count.get(s, 0) + 1
        for m in e["mentions"]:
            first_seen.setdefault(m, e["ts"])
    order = [n["tag"] for n in base["nodes"]]
    for t in sorted(first_seen, key=lambda t: first_seen[t]):
        if t not in order:
            order.append(t)
    you_label = _human_label()
    nodes = [
        {
            "tag": t, "first_seen": first_seen.get(t, 0.0), "count": count.get(t, 0),
            "is_you": t == YOU_TAG,
            **({"label": you_label} if t == YOU_TAG else {}),
        }
        for t in order
    ]
    return {"nodes": nodes, "events": merged, "dropped": hres["dropped"]}


@app.get("/api/session-detail")
async def get_session_detail(request: Request, project: str) -> dict[str, Any]:
    """Drill-down: the WHOLE working relationship for one session tag.

    Reads every transcript in ``<projects>/<project>/`` and returns the
    time-ordered prompt list + tool/file/agent events (each tagged with its
    prompt index ``ex``), so the frontend can replay the whole relationship or
    focus one exchange. Path validated to stay within the projects root.
    """
    state: AppState = request.app.state.cond
    projects_root = (state.settings.scanner.claude_home_path / "projects").resolve()
    pdir = (projects_root / project).resolve()
    if not str(pdir).startswith(str(projects_root) + "/"):
        raise HTTPException(status_code=400, detail="path outside projects root")
    if not pdir.is_dir():
        raise HTTPException(status_code=404, detail="project not found")
    paths = sorted(pdir.glob("*.jsonl"))
    return await asyncio.to_thread(extract_session_detail, paths)


@app.get("/api/exchange")
async def get_exchange(request: Request, project: str, session: str, uuid: str) -> dict[str, Any]:
    """Drill-down: one human prompt → the tool/file/agent fan-out it triggered.

    Reads the specific session transcript (``<projects>/<project>/<session>.jsonl``)
    and extracts that single exchange via ``extract_exchange``. Path is validated
    to stay within the projects root (no traversal). Backs the 🔬 drill-down view.
    """
    state: AppState = request.app.state.cond
    projects_root = (state.settings.scanner.claude_home_path / "projects").resolve()
    jsonl = (projects_root / project / f"{session}.jsonl").resolve()
    if not str(jsonl).startswith(str(projects_root) + "/"):
        raise HTTPException(status_code=400, detail="path outside projects root")
    if not jsonl.exists():
        raise HTTPException(status_code=404, detail="session transcript not found")
    out = await asyncio.to_thread(extract_exchange, jsonl, uuid)
    if out is None:
        raise HTTPException(status_code=404, detail="prompt not found in transcript")
    return out


class RelaunchRequest(BaseModel):
    project: str                 # encoded project-dir name (from the parked list)
    rc: bool | None = None       # override settings.relaunch.rc for this click
    rename: bool | None = None   # override settings.relaunch.rename for this click


def _resolve_parked(state: AppState, project: str) -> tuple[str, str]:
    """Validate an encoded project dir and resolve it to ``(cwd, session-name)``.

    Resolves the encoded ``~/.claude/projects`` dir → its newest transcript → the cwd
    that session last ran in; validates the dir is inside the projects root (no
    traversal) and still exists, and refuses if a session is already live there.
    Raises ``HTTPException`` for anything unrelaunchable. Shared by the single and
    batch relaunch endpoints.
    """
    projects_root = (state.settings.scanner.claude_home_path / "projects").resolve()
    pdir = (projects_root / project).resolve()
    if not str(pdir).startswith(str(projects_root) + "/"):
        raise HTTPException(status_code=400, detail="path outside projects root")
    if not pdir.is_dir():
        raise HTTPException(status_code=404, detail="project not found")
    jsonl = newest_jsonl(pdir)
    if jsonl is None:
        raise HTTPException(status_code=404, detail="no transcript for project")
    cwd = last_recorded_cwd(jsonl)
    real = os.path.realpath(cwd) if cwd else None
    if not real or not os.path.isdir(real):
        raise HTTPException(status_code=409, detail="session folder no longer exists")
    if any(
        r.status != Status.ENDED and os.path.realpath(r.project_dir) == real
        for r in state.sessions.values()
    ):
        raise HTTPException(status_code=409, detail="a session is already running in that folder")
    return real, tag_to_state_basename(derive_tag(real, state.settings.bus.tags))


@app.post("/api/relaunch")
async def relaunch(payload: RelaunchRequest, request: Request) -> dict[str, Any]:
    """Relaunch a parked (offline) session: open ``claude --continue`` in its
    folder in a tracked terminal. Optionally inject ``/rc`` and/or ``/rename``
    afterwards (both opt-in via ``[relaunch]`` settings; default is a clean
    resume with no injection). The spawn + post-launch keystroke injection is
    handled by ``AppState.relaunch_parked`` / ``_bootstrap_relaunched``.
    """
    state: AppState = request.app.state.cond
    real, name = _resolve_parked(state, payload.project)
    rc = state.settings.relaunch.rc if payload.rc is None else payload.rc
    rename = state.settings.relaunch.rename if payload.rename is None else payload.rename
    ok, detail = state.relaunch_parked(real, name, rc, rename)
    if not ok:
        raise HTTPException(status_code=500, detail=detail)
    return {"launched": True, "name": name, "cwd": real, "rc": rc, "rename": rename, "detail": detail}


class RelaunchBatchRequest(BaseModel):
    projects: list[str]          # encoded project-dir names (from the parked list)
    rc: bool | None = None
    rename: bool | None = None


@app.post("/api/relaunch-batch")
async def relaunch_batch(payload: RelaunchBatchRequest, request: Request) -> dict[str, Any]:
    """Fleet recovery: relaunch a *set* of parked sessions (one click after a
    reboot/crash). Every project is validated up-front, then the launches run in a
    background task **staggered** — one at a time, waiting for each to come up —
    because 20 Claudes spawning at once would stampede the machine and each resuming
    session may auto-compact. Returns immediately with what it accepted; anything
    unrelaunchable is reported in ``skipped`` rather than failing the whole batch.
    """
    state: AppState = request.app.state.cond
    if not payload.projects:
        raise HTTPException(status_code=400, detail="no projects given")
    items: list[tuple[str, str]] = []
    skipped: list[dict[str, str]] = []
    for proj in payload.projects:
        try:
            items.append(_resolve_parked(state, proj))
        except HTTPException as e:
            skipped.append({"project": proj, "reason": str(e.detail)})
    if not items:
        raise HTTPException(status_code=409, detail="nothing relaunchable in that selection")
    rc = state.settings.relaunch.rc if payload.rc is None else payload.rc
    rename = state.settings.relaunch.rename if payload.rename is None else payload.rename
    asyncio.create_task(state.relaunch_batch(items, rc, rename))
    log.info("relaunch-batch: accepted %d (skipped %d)", len(items), len(skipped))
    return {"launching": len(items), "skipped": skipped}


class BusMessage(BaseModel):
    text: str
    recipients: list[str] = []  # session tags; empty = broadcast to all
    ping: bool = False          # also inject /msg-check into recipient windows


@app.post("/api/bus/send")
async def send_bus_message(payload: BusMessage, request: Request) -> dict[str, Any]:
    """Compose-and-send a message to the bus from the dashboard (the human).

    Broadcast when ``recipients`` is empty; otherwise soft-addressed with a
    leading ``@to [tag]…`` line so receivers and Conductor know who it's for.
    With ``ping`` (specific recipients only), also inject ``/msg-check`` into
    each recipient's window so they read it now.
    """
    state: AppState = request.app.state.cond
    text = payload.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="message text is required")
    if not isinstance(state.bus, MarkdownBusAdapter):
        raise HTTPException(status_code=409, detail="sending requires the markdown bus adapter")

    recipients = [t for t in (r.strip() for r in payload.recipients) if t]
    body = text
    if recipients:
        body = "@to " + " ".join(recipients) + "\n" + text

    await asyncio.to_thread(
        append_message,
        state.settings.bus.markdown_path_resolved,
        state.settings.bus.sender_tag,
        body,
    )

    # Optional ping: inject /msg-check into each recipient session (specific
    # recipients only — broadcast-ping would steal focus across every window).
    pinged: list[str] = []
    if payload.ping and recipients:
        wanted = set(recipients)
        for rec in state.sessions.values():
            if rec.tag in wanted and rec.status != Status.ENDED:
                # Choke point, not a raw send — same guard/attest as every other wake.
                ok = await state._inject_text(rec, "/msg-check", "compose ping")
                if ok:
                    pinged.append(rec.tag)

    return {
        "ok": True,
        "sender": state.settings.bus.sender_tag,
        "recipients": recipients or "all",
        "pinged": pinged,
    }


class ActiveToggle(BaseModel):
    tag: str
    active: bool


@app.post("/api/bus/active")
async def set_bus_active(payload: ActiveToggle, request: Request) -> dict[str, Any]:
    """Flip a tag's bus membership between active (auto-notified) and passive.

    Writes the ``active-tags`` data file that the migrated bus.sh reads, so the
    change takes effect on that session's next prompt. Seeds the file from the
    current active set on first use so nothing changes until you toggle.
    """
    state: AppState = request.app.state.cond
    if not isinstance(state.bus, MarkdownBusAdapter):
        raise HTTPException(status_code=409, detail="active/passive requires the markdown bus adapter")
    sd = state.settings.bus.state_dir_resolved
    seed = list_known_tags(sd)
    new_active = await asyncio.to_thread(set_active_tag, sd, payload.tag, payload.active, seed=seed)
    # Push the refreshed view so every client restyles wires immediately.
    await state.hub.broadcast("bus", state._bus_payload())
    return {"ok": True, "active_tags": new_active}


class SettingsUpdate(BaseModel):
    interval_seconds: float | None = None
    end_fadeout_seconds: float | None = None


def _tunable_settings(s: Settings) -> dict[str, Any]:
    return {
        "interval_seconds": s.scanner.interval_seconds,
        "end_fadeout_seconds": s.ui.end_fadeout_seconds,
    }


@app.get("/api/settings")
async def get_settings(request: Request) -> dict[str, Any]:
    state: AppState = request.app.state.cond
    return _tunable_settings(state.settings)


@app.post("/api/settings")
async def update_settings(payload: SettingsUpdate, request: Request) -> dict[str, Any]:
    """Update the live, UI-tunable settings and persist them to settings.toml.

    Applied in-memory immediately (the scan loop reads these each tick) and
    written to disk so they survive a restart."""
    state: AppState = request.app.state.cond
    s = state.settings
    if payload.interval_seconds is not None:
        s.scanner.interval_seconds = max(0.5, min(60.0, payload.interval_seconds))
    if payload.end_fadeout_seconds is not None:
        s.ui.end_fadeout_seconds = max(0.0, min(600.0, payload.end_fadeout_seconds))
    await asyncio.to_thread(dump_settings, s, DEFAULT_SETTINGS_PATH)
    # Push the new fadeout to clients (it rides in the sessions payload).
    await state.hub.broadcast("sessions", state._sessions_payload())
    return _tunable_settings(s)


@app.websocket("/ws")
async def websocket(ws: WebSocket) -> None:
    state: AppState = ws.app.state.cond
    # Auth: the browser can't set headers on a WS handshake, so the token rides in
    # the query string (?token=…). Reject before accepting when it doesn't match.
    if not token_ok(resolved_token(state.settings), ws.query_params.get("token")):
        await ws.close(code=1008)  # policy violation
        return
    await state.hub.connect(ws)
    try:
        # Send initial snapshot.
        import json
        await ws.send_text(json.dumps({"kind": "sessions", "payload": state._sessions_payload()}))
        await ws.send_text(json.dumps({"kind": "bus", "payload": state._bus_payload()}))
        await ws.send_text(json.dumps({"kind": "resources", "payload": state.resources}))
        await ws.send_text(json.dumps({"kind": "push", "payload": {
            "requests": state._push_requests, "grants": state._push_grants,
            "proposals": state._push_proposals}}))
        await ws.send_text(json.dumps({"kind": "autonomy", "payload": {"windows": state._autonomy}}))
        await ws.send_text(json.dumps({"kind": "services", "payload": state.services}))
        await ws.send_text(json.dumps({"kind": "waiting", "payload": state.waiting}))
        await ws.send_text(json.dumps({"kind": "silent", "payload": {"silent": state._silent}}))
        await ws.send_text(json.dumps({"kind": "collisions", "payload": {"collisions": state._collisions}}))
        await ws.send_text(json.dumps({"kind": "decisions", "payload": {"decisions": state.decisions}}))
        while True:
            # We don't expect messages from the client right now; await any to detect close.
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await state.hub.disconnect(ws)


# Static frontend at "/". Mounted last so /api/* and /ws aren't shadowed.
@app.get("/")
async def index() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "index.html")


# PWA plumbing served at the ROOT so the service worker controls the whole origin
# (a SW under /static/ would only scope /static/). Both are public (part of the
# installable shell); the API behind them stays gated.
@app.get("/manifest.webmanifest")
async def manifest() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "manifest.webmanifest",
                        media_type="application/manifest+json")


@app.get("/sw.js")
async def service_worker() -> FileResponse:
    return FileResponse(
        FRONTEND_DIR / "sw.js",
        media_type="text/javascript",
        headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": "/"},
    )


@app.middleware("http")
async def no_cache_the_app_shell(request: Request, call_next):
    """Never let a browser cache the app's own code.

    StaticFiles sends an ETag and a Last-Modified but NO Cache-Control — which means the
    browser is free to guess how long to keep the file, and mobile browsers guess
    generously. Kyle's phone quietly ran the previous night's `ops.js` for hours: the backend
    had a push proposal, the API returned it, and the phone rendered nothing, because the JS
    it was running had never heard of proposals. **A stale frontend against a live backend
    fails SILENTLY — the app looks fine and is simply blind to whatever is new**, which is the
    exact shape of the zombie-UI bug the desktop service worker caused.

    `no-cache` does not mean "don't store"; it means "revalidate before use". With the ETag
    already there, an unchanged file is a 304 and costs nothing.
    """
    resp = await call_next(request)
    path = request.url.path
    if path.startswith("/m") or path in ("/", "/index.html") or path.startswith("/static/"):
        resp.headers["Cache-Control"] = "no-cache, must-revalidate"
    return resp


@app.get("/m")
@app.get("/m/")
async def ops_console() -> FileResponse:
    """The phone console. A SEPARATE app, not a responsive skin on the board.

    The desktop board is a spatial workbench — you arranged those tiles and the
    arrangement means something. A phone is episodic: you open it for thirty seconds
    because something needs you. Responsive CSS can shrink a workbench; it cannot turn one
    into a console. So this is its own frontend, sharing nothing but the API.
    """
    return FileResponse(FRONTEND_DIR / "m" / "index.html")


@app.get("/m/manifest.webmanifest")
async def ops_manifest() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "m" / "manifest.webmanifest",
                        media_type="application/manifest+json")


@app.get("/m/sw.js")
async def ops_service_worker() -> FileResponse:
    """The ops console's service worker. Scoped to /m — that's all it needs, since its only
    job is receiving a push. Deliberately not a cache: a cache-first SW once served a stale
    shell against a changed backend and produced a UI that rendered fine with every button
    dead."""
    return FileResponse(
        FRONTEND_DIR / "m" / "sw.js",
        media_type="text/javascript",
        headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": "/m"},
    )


app.mount("/m", StaticFiles(directory=str(FRONTEND_DIR / "m")), name="ops")
app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


def run() -> None:
    """Console-script entry point: `conductor`."""
    import uvicorn
    settings = load_settings()
    uvicorn.run(
        "conductor.main:app",
        host=settings.server.host,
        port=settings.server.port,
        reload=False,
    )
