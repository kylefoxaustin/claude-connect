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
from .coord import read_push_requests, read_retractions, read_wake_state, write_wake_state
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
    tag_to_state_basename,
)
from .settings import DEFAULT_SETTINGS_PATH, Settings, dump_settings, load_settings
from .windows import focus_session, send_keys_to_session, wmctrl_available
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
_WAKE_RETRY_SECONDS = 600.0


def _bare_tag(tag: str | None) -> str:
    """Compare tags on a common form.

    Conductor stores a session's tag bracketed (``"[other:api]"``) because that's
    how it renders; ``bus.sh`` writes lease owners bare (``"other:api"``). Matching
    the two directly never succeeds — normalize before comparing.
    """
    return (tag or "").strip().strip("[]")


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

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
        self._wake_outstanding: dict[str, tuple[str, float]] = read_wake_state(
            settings.bus.state_dir_resolved / "coord")
        self._directed_unread: dict[str, dict[str, Any]] = {} # tag -> unread addressed to it
        self._retraction_woken: set[str] = set()              # retraction records we already delivered
        self._retractions: list[dict[str, Any]] = []          # active retraction records
        self._push_requests: list[dict[str, Any]] = []        # git-push approvals awaiting Kyle
        self._autonomy: list[dict[str, Any]] = []             # live "let them talk" windows
        self.services: dict[str, Any] = {"services": []}      # service Claudes (image_gen…)
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
        if push_reqs != self._push_requests:
            self._push_requests = push_reqs
            await self.hub.broadcast("push", {"requests": push_reqs})
        svc = await asyncio.to_thread(read_services, self.coord_root)
        if svc != self.services:
            self.services = svc
            await self.hub.broadcast("services", svc)
        autonomy = await asyncio.to_thread(read_windows, self.coord_root)
        if autonomy != self._autonomy:
            self._autonomy = autonomy
            await self.hub.broadcast("autonomy", {"windows": autonomy})
        await self._wake_offered_sessions()
        await self._wake_nudged_owners()
        await self._wake_unread_recipients()
        await self._wake_retractions()

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
                prev_seen, woke_at = prev
                # Re-arm anyway after a while, so a session that can't write a
                # last-seen at all (not on the bus whitelist) isn't muted forever.
                if seen_now == prev_seen and (now - woke_at) < _WAKE_RETRY_SECONDS:
                    continue
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
            self._wake_outstanding[r.tag] = (seen_now, now)
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

    async def _inject_text(self, rec: SessionRecord, text: str, why: str) -> bool:
        """Type ``text`` into a live session's terminal (raises its window)."""
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
    injected = await asyncio.to_thread(
        send_keys_to_session,
        text="/msg-check",
        pid=rec.pid,
        terminal_pid=rec.terminal_pid,
        title=rec.title,
        window_title=rec.window_title,
    )
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
    return {"requests": state._push_requests}


@app.post("/api/push/{key}/{action}")
async def decide_push(key: str, action: str, request: Request) -> dict[str, Any]:
    """Approve or deny a gated ``git push`` (user-triggered). Approve writes a
    short-lived token the PreToolUse gate consumes on the session's next push; deny
    just dismisses the request. Both go through ``bus.sh push`` — one token path."""
    if action not in ("approve", "deny"):
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
        rec = state._session_for_cwd(req.get("cwd", ""))
        if rec is not None:
            sent = await state._inject_text(
                rec,
                "✅ Kyle approved your git push — re-run it now. "
                "The approval is valid for 30 minutes and covers exactly one push.",
                f"push approved for {req.get('repo_name', key)}",
            )
            if sent:
                notified = rec.tag
        else:
            log.info("push approved for %s but no live session in %s — it'll have to be told",
                     key, req.get("cwd", "?"))
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
                ok = await asyncio.to_thread(
                    send_keys_to_session,
                    text="/msg-check",
                    pid=rec.pid,
                    terminal_pid=rec.terminal_pid,
                    title=rec.title,
                    window_title=rec.window_title,
                )
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
        await ws.send_text(json.dumps({"kind": "push", "payload": {"requests": state._push_requests}}))
        await ws.send_text(json.dumps({"kind": "autonomy", "payload": {"windows": state._autonomy}}))
        await ws.send_text(json.dumps({"kind": "services", "payload": state.services}))
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
