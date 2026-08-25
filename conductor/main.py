"""FastAPI app + uvicorn entry for Conductor.

Wires the SessionScanner, ActivityWatcher, BusAdapter, and WebSocket hub.
Serves the vanilla-JS frontend at `/`.
"""

from __future__ import annotations

import asyncio
import getpass
import logging
import json
import os
import sys
import shutil
import socket
import subprocess
import time
from collections import deque
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import psutil
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import __version__
from .activity import ActivityWatcher
from .auth import path_requires_auth, resolved_token, token_ok
from .autonomy import close_window, open_window, peers_in_window, read_windows
from .decisions import OTHER_TEXT, plan_keystrokes, read_decisions, reap_decision
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
    read_winddown,
    write_wake_state,
)
from .deps import (build_wait_graph, compute_lost_rc, open_ask_edges, silent_addressees,
                   stale_cursors)
from .projects import (
    open_escalations,
    projects_needing_operator,
    read_projects,
    total_in_flight,
)
from .project_spend import ProjectSpendMeter
from .bridge import read_bridge
from .models import BusEvent, BusTopology, ParkedSession, SessionRecord, Status
from .registry import attach_cards
from .resources import resources_state, slim_resource_cards, touch_lease_activity
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
from .reconstitute import build_plan
from .roster import build_roster
from .settings import DEFAULT_SETTINGS_PATH, Settings, dump_settings, load_settings
from .x11 import (
    focus_session,
    send_key_sequence,
    send_key_to_session,
    send_keys_to_session,
    wmctrl_available,
    x11_health,
)
from .ws import WSHub

log = logging.getLogger("conductor")


# Mirrors the frontend's ping guard: a session mid-task shouldn't get keystrokes.
_BUSY_STATUSES = frozenset({Status.ACTIVE, Status.WARM})

# Re-nudge schedule for un-acked sessions during a wind-down: 5m, 10m, 20m — then STOP.
# WIDENING, and FINITE, on purpose. A fixed interval is how the v2.26.1 /msg-check storm happened;
# and a session that has ignored three nudges has a reason a fourth won't fix, so it becomes a
# decision for Kyle rather than a louder alarm. The list length IS the attempt cap.
_WD_RENUDGE_BACKOFF_S = (300.0, 600.0, 1200.0)

# Project Layer §5b — admission control. Dispatching a job spins up a worker session (which itself
# fans out ~5× into subagents), so unbounded parallel dispatch is exactly the `overloaded` swamp the
# throttle exists to prevent. The cap is FLEET-GLOBAL (in-flight jobs across ALL projects), because
# every project competes for the same API ceiling as Kyle's own session and every autonomy window.
# This is the concurrency control (the acute risk, §5e); the cumulative token meter is slice 5.
_PROJECT_MAX_IN_FLIGHT = 3
# And a busy-fleet guard: if this many sessions are already ACTIVE/WARM, don't admit more work.
_PROJECT_FLEET_BUSY_CEILING = 8

# §4a lead-timeout auto-escalate: a worker's escalation to the lead that sits unanswered this long
# auto-escalates to Kyle — the latency relief on the critical path, WITHOUT a self-declared "urgent"
# category (only the clock flips it). Generous by default: the lead usually answers fast; this is
# the backstop for a lead that's asleep/stuck, not the common path.
_PROJECT_LEAD_TIMEOUT_SECONDS = 30 * 60


def _project_subenv() -> dict[str, str]:
    """Conductor acts for KYLE on the project, so it identifies as 'operator' (not its cwd-derived
    tag) for every ``bus.sh project`` call. Without this, when the project's lead happens to run
    where Conductor does, the shield's 'the lead may not answer a Kyle-bound escalation' guard (and
    the dispatch lead-guard) misfire on Conductor. operator = Kyle: it may answer any escalation and
    admit any dispatch, and it is never a lead, so the guards resolve correctly."""
    return {**os.environ, "PROJECT_ME_OVERRIDE": "operator"}

# Auto-delivery only wakes sessions that are clearly unattended and not working:
# not ACTIVE/WARM (busy) and not WAITING (Kyle may be typing at that prompt).
_WAKEABLE_STATUSES = frozenset({Status.IDLE, Status.DORMANT})

# A service Claude is woken to serve a job by the REQUESTER at request time (svc-request
# posts directed mail; auto-delivery injects the /msg-check). That is a ONE-SHOT wake — and
# if Conductor is down when the job lands (image_gen, 2026-07-17: a job sat 28m while Conductor
# was crashed), or the service was busy and never came back to it, the nudge is lost forever:
# there is no re-wake, and the per-prompt hook carries no service-queue line to remind an idle
# service of its backlog. So Conductor re-issues the wake for a queue HEAD older than this, once
# per job. A queued job is a hard block on the requester, so this fires regardless of the wake
# floor — but never at a BUSY service (it's already working; the busy-guard leaves it alone).
_SVC_STALE_SECONDS = 180

# Force a Bus-tile resend at least this often even when the gate says "unchanged".
# Insurance against a stale UI, which this codebase has shipped more than once.
# A relaunch injection is triggered BY a human clicking a button, and x11.py refuses to
# type while a human has been active within _HUMAN_ACTIVE_MS (4 s) — so the first attempt lands
# inside that refusal window almost by construction. The guard's contract is explicitly "the
# caller retries once they go idle"; these are that retry. Kyle, 2026-08-17: three of four
# relaunches logged "failed to inject '/rc'" for exactly this reason.
_INJECT_RETRY_SECONDS = 90.0
_INJECT_RETRY_STEP_S = 3.0

_BUS_REFRESH_SECONDS = 60.0
_PROJECTS_REFRESH_SECONDS = 60.0
_SESSIONS_FULL_REFRESH_SECONDS = 60.0

# Sub-keys of the sessions payload that are STATIC in practice. MEASURED 2026-08-16
# across 8 consecutive broadcasts: `parked` (13.4 KB) and `members` (5.8 KB) changed
# ZERO times, while only `sessions` (3.0 KB) and `silent` (0.9 KB) moved — 19.2 KB of
# a 23.2 KB payload (83%) retransmitted every 3 s purely because it shares a message
# with something that ticks. Same defect as the asset cards, one level further in.
#
# These are OMITTED from a broadcast when unchanged. Absence means "unchanged, keep
# what you have" and the frontend merges on presence. The REST endpoint and the WS
# connect snapshot always send the FULL payload, so a new or resyncing client never
# reconstructs anything from deltas — and a forced full resend every
# _SESSIONS_FULL_REFRESH_SECONDS bounds how long any divergence could survive.
_SESSIONS_STATIC_KEYS = (
    "parked", "members", "collisions", "lost_rc", "webpush", "x11",
    "winddown", "fadeout_seconds", "wmctrl_available",
)

# Fields stamped onto a project's jobs from LIVE session state each scan. They are
# excluded from the change-gate because they flip constantly (a working assignee
# oscillates active/warm), which defeated the gate entirely; they still ride the
# payload, and the authoritative copy is the per-tick `sessions` broadcast.
_PROJECT_VOLATILE_JOB_FIELDS = ("assignee_status", "assignee_busy")


def thin_unchanged_keys(
    full: dict[str, Any],
    digests: dict[str, str],
    keys: tuple[str, ...],
    *,
    force_full: bool = False,
) -> dict[str, Any]:
    """Drop ``keys`` from ``full`` whose value is unchanged since the last call.

    Delta-by-omission: **absence means "unchanged, keep yours", never "empty"**.
    That contract is the whole risk of this optimisation, so it is stated on both
    sides — see the merge-on-presence comment in ``app.js``'s ``sessions`` handler.

    ``digests`` is mutated in place (per-key state across calls). ``force_full``
    reseeds every digest and returns everything, which is what bounds how long any
    client/server divergence could survive.

    Pure apart from that one mutation, so the contract can be pinned by a test.
    """
    if force_full:
        for k in keys:
            if k in full:
                digests[k] = json.dumps(full[k], sort_keys=True, default=str)
        return full
    out = dict(full)
    for k in keys:
        if k not in full:
            continue
        digest = json.dumps(full[k], sort_keys=True, default=str)
        if digests.get(k) == digest:
            out.pop(k, None)
        else:
            digests[k] = digest
    return out


def _projects_gate_key(projs: list[dict[str, Any]]) -> str:
    """A stable digest of project state, ignoring live per-tick annotations.

    Pure function so the gate can be pinned by a test rather than trusted.
    """
    stripped: list[Any] = []
    for p in projs:
        p2 = dict(p)
        jobs = p2.get("jobs")
        if isinstance(jobs, list):
            p2["jobs"] = [
                {k: v for k, v in j.items() if k not in _PROJECT_VOLATILE_JOB_FIELDS}
                if isinstance(j, dict) else j
                for j in jobs
            ]
        stripped.append(p2)
    return json.dumps(stripped, sort_keys=True, default=str)

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


def _known_request_key(key: str, directory: Path) -> bool:
    """Is ``key`` safe to pass on as a request identifier?

    Two ways to qualify, and the second exists because of a real nag (Kyle, 2026-08-06):

      1. it is charset-clean (alnum plus ``._-``) — the fast path, and a path-traversal guard; or
      2. it EXACTLY matches a file already sitting in ``directory``.

    The gate that FILES these sanitizes with `tr '/ ' '__'` — slashes and spaces only — so any
    repo path containing anything else (``$``, ``+``, ``(``, ``&``…) produced a request the API
    then refused to act on with "bad request key". Filable but not dismissible: it sat in Kyle's
    inbox re-ringing his phone every hour with no way to clear it from Conductor OR the phone.
    A control surface that can raise an alarm it cannot lower is worse than one that never raised
    it, because the only way out is to learn to ignore the alarm.

    Matching against the actual directory listing is what keeps this safe: we never build a path
    from the caller's string, we compare it to names that already exist, so ``../`` and friends
    simply do not match anything."""
    # `.` and `..` are CHARSET-CLEAN — `.` is in the allowed set — so the original check let them
    # through on the fast path. Reject them before anything else, for both routes. (Found by the
    # traversal test written for the fallback; the hole predates it.)
    if not key or key in (".", "..") or "/" in key or "\\" in key or "\0" in key:
        return False
    if all(c.isalnum() or c in "._-" for c in key):
        return True
    try:
        return key in {p.name for p in directory.iterdir()}
    except OSError:
        return False


def _wd_plain(tag: str | None) -> str:
    """Plain member name matching ``bus.sh``'s ``_coord_plain`` (which keys the wind-down acks):
    ``[other:qualcomm]`` == ``other:qualcomm`` == ``qualcomm``."""
    t = _bare_tag(tag)
    if t.lower().startswith("other:"):
        t = t[6:]
    return t.lower()


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


def _unpack_wake(v: Any) -> tuple[str, float, float, str]:
    """``(seen, woke_at)`` / ``(…, activity_at)`` / ``(…, activity_at, latest_ts)`` — the tuple
    has grown over time; older entries are read back safely.

    ``coord/wake-state.json`` persists across restarts, and only the first two fields ever reach
    disk (see write_wake_state), so any run reads back short tuples. Treating a short one as
    corrupt and dropping it would re-prod every session with unread mail once — the very storm
    this machinery exists to end. Missing ``activity_at`` defaults to +inf so a legacy entry can
    never satisfy the "active since we typed" retry test; missing ``latest_ts`` defaults to ""
    (harmless — with activity +inf the retry is already blocked).
    """
    if isinstance(v, (list, tuple)):
        if len(v) >= 4:
            return str(v[0]), float(v[1]), float(v[2]), str(v[3])
        if len(v) == 3:
            return str(v[0]), float(v[1]), float(v[2]), ""
        if len(v) == 2:
            return str(v[0]), float(v[1]), float("inf"), ""
    return "", 0.0, float("inf"), ""


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
        self._registry_root = settings.bus.state_dir_resolved / "registry"  # asset cards (access/setup/…)
        self.resources: dict[str, Any] = {"resources": []}
        self._last_bus_payload: dict[str, Any] | None = None  # change-gate for the Bus broadcast
        self._last_bus_sent: float = 0.0                      # monotonic; forces a periodic resend
        self._sessions_static_digest: dict[str, str] = {}     # per-key digests for delta-by-omission
        self._sessions_full_sent: float = 0.0                 # monotonic; forces a periodic FULL send
        self._projects_gate: str | None = None                # digest ignoring live annotations
        self._projects_sent: float = 0.0                      # monotonic; forces a periodic resend
        self._pinged_offers: set[str] = set()                 # offers we've already woken
        self._owner_missing_since: dict[str, float] = {}      # lease -> when its owner went offline
        self._nudge_woken: set[str] = set()                   # idle episodes we already woke
        self._svc_woken: set[str] = set()                     # service jobs we already re-woke a service for
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
        # In memory each value is (seen, woke_at, activity_at, latest_ts); only (seen, woke_at)
        # persists (write_wake_state), and _unpack_wake reads any width back safely.
        self._wake_outstanding: dict[str, tuple] = read_wake_state(
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
        # Remote prompts: a message the operator @-addressed to a session (from the phone, or via
        # the prompt-route hook), delivered into that session's terminal as a prompt — but only
        # when it's QUIET, same discipline as the push notices (a busy session eats keystrokes).
        self._remote_prompts: dict[str, dict[str, Any]] = {}
        self._remote_prompt_seq = 0
        # 'reconnect this session's remote control' (/rc), queued when the target is busy —
        # an /rc injected mid-turn queues in the TUI and silently fails to bridge, so we fire
        # it only once the session is idle, exactly like the push notices above.
        self._rc_pending: dict[str, dict[str, Any]] = {}
        self._autonomy: list[dict[str, Any]] = []             # live "let them talk" windows
        self.services: dict[str, Any] = {"services": []}      # service Claudes (image_gen…)
        self.projects: list[dict[str, Any]] = []              # Project Layer: lead-owned multi-session work
        self._spend_meter = ProjectSpendMeter()               # measured per-project token spend (§5c)
        self._budget_alarmed: set[str] = set()                # projects we've raised a budget decision for
        self.waiting: dict[str, Any] = {"edges": [], "cycles": [], "bottlenecks": [],
                                        "blocked_count": 0}   # who is blocked on whom
        self._silent: list[dict[str, Any]] = []               # dead-reader alarm (holobench)
        self._stale_cursors: list[dict[str, Any]] = []        # stale read cursor (image_gen)
        self._collisions: list[dict[str, Any]] = []           # two live sessions, one member (holobench)
        self._lost_rc: list[dict[str, Any]] = []              # live-but-lost-/RC alarm (§3.4.1, rt1180)
        self._x11: dict[str, Any] = {}                        # can we reach a display? (2026-08-05)
        self._wd_nudges: dict[str, int] = {}                  # member -> wind-down nudges sent
        self._wd_nudged_at: dict[str, float] = {}             # member -> epoch of the last one
        self._rc_ever: set[str] = set()                       # sids seen bridged (LOST vs never-had)
        self._lost_rc_since: dict[str, float] = {}            # sid -> when it went unbridged-after-bridged
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
        # Set once if web-push can't run (its optional deps — pywebpush/cryptography —
        # aren't installed in the service venv). A MISSING DEPENDENCY won't fix itself
        # mid-run, so we log it ONCE and stop trying, rather than raising every scan
        # tick — which (a) killed phone paging silently for hours [ollama_95_neutron
        # blocked 6h, 2026-07-22] and (b) spammed the scan-loop error channel, masking
        # real scan errors. An observability feature must never break the fleet.
        self._webpush_broken = False
        self.token_accountant = TokenAccountant()             # per-session token tally
        self._scan_misses: dict[str, int] = {}              # consecutive scans a session was absent
        self.recent_events: deque[BusEvent] = deque(maxlen=RECENT_EVENTS_MAX)
        self.bus_total = 0

        self._scan_task: asyncio.Task | None = None
        self._activity_task: asyncio.Task | None = None
        self._bus_task: asyncio.Task | None = None

    async def start(self) -> None:
        # Idempotent: a second start() must NOT spawn a second scan loop. create_task doesn't
        # cancel the old task when the attribute is overwritten, so two loops would run forever,
        # offset by their sleeps — concurrent _do_scan -> concurrent wakes -> the /msg-check
        # storm. (The per-path dedup is now concurrency-safe too, but the loops themselves must
        # be single.)
        if self._scan_task is not None and not self._scan_task.done():
            log.warning("AppState.start() called again while already running — ignoring")
            return
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

        await self.hub.broadcast("sessions", self._sessions_broadcast_payload())
        # Refresh the Bus tile too (topology + per-tag pending) so it stays live
        # between bus events, not just on WS reconnect.
        #
        # Change-gated: MEASURED 2026-08-16 this payload was byte-identical across
        # 9/9 consecutive ticks, i.e. ~197 MB/day per client of pure repetition.
        # (`sessions` is deliberately NOT gated — measured 9/9 ticks CHANGED, since
        # live previews and token tallies genuinely move; a gate there would never
        # fire and would only add a way to go stale.)
        #
        # The forced periodic resend is deliberate insurance, not redundancy: this
        # codebase has been bitten repeatedly by a UI that renders fine while being
        # silently stale, so a gate bug can cost at most _BUS_REFRESH_SECONDS rather
        # than persisting until the next reconnect.
        bus_payload = self._bus_payload()
        now_mono = time.monotonic()
        if (bus_payload != self._last_bus_payload
                or now_mono - self._last_bus_sent >= _BUS_REFRESH_SECONDS):
            self._last_bus_payload = bus_payload
            self._last_bus_sent = now_mono
            await self.hub.broadcast("bus", bus_payload)
        # Resource tiles: named-resource leases (+ nvidia-smi telemetry for the GPU).
        self.resources = await asyncio.to_thread(resources_state, self.res_root)
        # Attach each resource's asset card (access / setup / gotchas …) so the tile can show
        # 'how do I reach this EVK?' next to the live lease.
        await asyncio.to_thread(attach_cards, self.resources.get("resources", []), self._registry_root)
        await asyncio.to_thread(self._refresh_active_leases)
        self._annotate_orphans()
        await self.hub.broadcast("resources", self._resources_payload())
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
        # Project Layer: a lead submits a plan → it lands in plan_review → Kyle approves it from
        # his phone (Gate #1). Read the record and broadcast on change so the approval surfaces.
        projs = await asyncio.to_thread(read_projects, self.coord_root)
        # Slice 2: advance the job DAG. Any dispatched job whose order reached CLOSED becomes done
        # (unblocking dependents) — driven here so a completed order flows the graph forward with no
        # human. Only sync projects that actually have an in-flight job, and only re-read if we did.
        if any(p.get("in_flight", 0) for p in projs):
            await self._sync_project_dags(projs)
            projs = await asyncio.to_thread(read_projects, self.coord_root)
        # Slice 3: a lead-bound escalation the lead hasn't answered within the timeout auto-escalates
        # to Kyle (§4a). Only the clock flips it — never a worker — so it isn't a route-around-the-lead.
        if any(p.get("open_lead_escalations", 0) for p in projs):
            await self._auto_escalate_timeouts(projs)
            projs = await asyncio.to_thread(read_projects, self.coord_root)
        # Slice 5: the MEASURED spend meter (annotates spend/spend_pct/over_budget) + lead-death flag.
        self._spend_meter.update(projs, self._member_output_tokens)
        self._annotate_lead_offline(projs)
        self._annotate_assignee_status(projs)
        # Budget alarm: a project crossing the warn threshold raises a Kyle-bound decision (extend /
        # checkpoint / finish) THROUGH the shield — reusing the queue+paging, not a new alarm class.
        if await self._check_budget_alarms(projs):
            projs = await asyncio.to_thread(read_projects, self.coord_root)
            self._spend_meter.update(projs, self._member_output_tokens)
            self._annotate_lead_offline(projs)
        # Gate on DURABLE content, not on the live annotations stamped above.
        #
        # `_annotate_assignee_status` writes each job's assignee session status
        # (active/warm/idle/offline), which flips as sessions work — so a plain
        # `projs != self.projects` was true on ~9 of every 10 ticks and this gate
        # never actually gated. MEASURED 2026-08-16: 14.4 KB x ~9 per 30 s =
        # ~414 MB/day per connected client, for a payload that had not meaningfully
        # changed. This is precisely the trap the push-grant gate documents 60 lines
        # up ("compare on identity, not the live countdown") — written down, then
        # not applied one function later.
        #
        # The dropped fields are not lost: assignee liveness is derived from the
        # `sessions` broadcast, which ships every tick anyway. The periodic resend
        # bounds how stale the copy inside `projects` can get.
        now_mono = time.monotonic()
        gate = _projects_gate_key(projs)
        if (gate != self._projects_gate
                or now_mono - self._projects_sent >= _PROJECTS_REFRESH_SECONDS):
            self._projects_gate = gate
            self._projects_sent = now_mono
            self.projects = projs
            await self.hub.broadcast("projects", {"projects": projs})
        else:
            self.projects = projs
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

        # STALE READ CURSOR (image_gen, 2026-08-24): a reader whose bus watermark has fallen
        # behind the log. The failure is self-concealing — a stuck cursor and a quiet inbox both
        # render as "the number goes up" — and image_gen's sat three weeks behind before anyone
        # thought the count looked absurd.
        #
        # ⚠️ SCOPED TO LIVE MEMBERS, and that scoping is the whole design. Raw cursor age fires on
        # the graveyard: this fleet has watermarks at 06-14, 06-28, 06-30, 07-04, nearly all of
        # them dormant or deleted projects. image_gen itself was CLOSED for the three weeks in
        # question, and a closed session's cursor is supposed to stand still. An alarm that fires
        # on every dormant project is one you learn to swipe away — which is the same argument
        # that keeps Conductor paging on exactly two things.
        cursors = await asyncio.to_thread(
            stale_cursors,
            self.settings.bus.markdown_path_resolved,
            Path(self.settings.bus.state_dir_resolved),
            stale_h=self.settings.bus.stale_cursor_hours,
        )
        stale = [c for c in cursors if c["stale"] and _plain_name(c["tag"]) in live_plain]
        for c in stale:
            c["live"] = True
        if stale != self._stale_cursors:
            self._stale_cursors = stale
            await self.hub.broadcast("stale_cursors", {"stale_cursors": stale})

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

        # LIVE-BUT-LOST-/RC ALARM (§3.4.1, rt1180): a session that WAS on the phone (/rc bridged) and
        # lost it is alive but invisible in the phone's Claude app — the exact trap that made Kyle
        # relaunch a "crashed" session and create a duplicate. Conductor watches the PROCESS, so it can
        # say "alive, lost /RC Nm ago — Reconnect, don't relaunch" instead of letting it look dead.
        # Fires only on lost-it (was bridged), aged, and not already reconnecting — so it isn't noise.
        rc_inputs = [
            {"session_id": getattr(r, "session_id", "") or "",
             "bridged": read_bridge(r.pid)["bridged"],
             "rc_pending": (getattr(r, "session_id", "") or "") in self._rc_pending,
             "member": _bare_tag(r.tag), "project_dir": r.project_dir,
             "preview": r.preview, "last_activity_at": r.last_activity_at}
            for r in self.sessions.values() if r.status != Status.ENDED
        ]
        lost_rc = compute_lost_rc(
            rc_inputs, self._rc_ever, self._lost_rc_since,
            now=time.time(),
            threshold_min=getattr(self.settings.bus, "lost_rc_alert_minutes", 15.0),
        )
        if lost_rc != self._lost_rc:
            self._lost_rc = lost_rc
            await self.hub.broadcast("lost_rc", {"lost_rc": lost_rc})

        # CAN WE REACH THE DISPLAY AT ALL? (Kyle, 2026-08-05) The meta-alarm. Focus, wake,
        # /msg-check, decision answers and wind-down close ALL ride keystroke injection, and
        # X11 tools report "Cannot open display" on stderr while exiting 0 — so without this
        # the whole action surface dies silently and the dashboard keeps looking healthy.
        # A monitor that cannot see its own blindness is the failure it exists to prevent.
        x11 = await asyncio.to_thread(x11_health)
        if x11 != self._x11:
            if not x11["ok"] and (self._x11 or {}).get("ok") is not False:
                log.warning("X11 unreachable: %s", x11["detail"])
            self._x11 = x11
            await self.hub.broadcast("x11", {"x11": x11})

        decisions = await asyncio.to_thread(read_decisions, self.coord_root)
        # Drop records whose session is gone — a session killed mid-picker leaves its
        # file behind, and a dead question in the queue is a false alarm.
        decisions = [d for d in decisions if self._session_for_decision(d)]
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
        await self._wake_stale_service_heads()
        await self._wake_unread_recipients()
        await self._wake_retractions()
        await self._deliver_push_notices()
        await self._deliver_remote_prompts()
        await self._deliver_rc_reconnects()
        await self._renudge_unacked()
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
            # Mark it woken BEFORE the await — same concurrency race as _wake_unread_recipients
            # (qualcomm got 4 duplicate retraction wakes in one burst). The inject yields; a
            # concurrent pass must see the id already claimed and skip.
            self._retraction_woken.add(r["id"])
            await self._inject_msg_check(rec, f"RETRACTION from [{r['sender']}] (busy-guard overridden)")
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
            retry_reason = ""          # set only on the lost-keystroke retry path; logged at inject
            prev = self._wake_outstanding.get(r.tag)
            if prev is not None:
                prev_seen, woke_at, prev_activity, prev_latest = _unpack_wake(prev)
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
                    # AND genuinely-new directed mail must have arrived since we woke it. Without
                    # this, a DIRECT READER — a session that reads messages.md itself and never
                    # runs `check`/`catchup`, so its watermark is permanently stuck — is
                    # indistinguishable from a lost keystroke (active, watermark unmoved) and gets
                    # re-woken every hour forever on a STATIC bus (holobench, 2026-07-16: ~5 fires,
                    # zero new content between them). "Watermark stuck" alone cannot tell a lost
                    # keystroke from a reader who will never advance it; "new mail since we woke"
                    # can. A truly lost keystroke with no new mail still surfaces on the recipient's
                    # next prompt-hook — the injection is an accelerator, never the only door.
                    new_mail = (info.get("latest_ts") or "") > prev_latest
                    if not (moved and (now - woke_at) >= _WAKE_RETRY_SECONDS and new_mail):
                        continue
                    # DO NOT LOG HERE. This decision is re-evaluated every 3 s tick, and when the
                    # wakeability gate below refuses — which is the COMMON case here, because a
                    # session described as "active Nm since we typed" is by definition BUSY — we
                    # fall through without recording anything, so the identical decision recurs
                    # forever. Logging at this point emitted one line every 3 SECONDS indefinitely:
                    # a log storm inside the fix for the /msg-check storm (v2.26.1, b199e74), and
                    # log spam is exactly what masked real scan errors in v2.37.
                    #
                    # Nothing is hidden by staying quiet: a blocked retry types nothing, and this
                    # path is an accelerator rather than the only door — the recipient still sees
                    # the mail on its next prompt-hook. So we log if and only if we actually type.
                    retry_reason = (
                        "active %.0fm since we typed, watermark still stuck, and newer directed "
                        "mail has since arrived — the keystroke was probably lost"
                        % ((now - woke_at) / 60))
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
            # Reserve the dedup slot BEFORE the inject, not after. _inject_msg_check awaits
            # (it runs xdotool in a thread), and a floor-exempt holder — a session others are
            # hard-blocked on — has no rate limit behind it. So if we recorded this only after
            # the await, concurrent scan passes would each read an empty slot and re-wake it:
            # qualcomm saw 11 /msg-check in ~200ms exactly this way. Reserving first makes any
            # later pass see it and skip. A reserved-but-unsent wake is harmless — a queued
            # check drains the whole backlog, and the retry path re-arms a genuinely lost one.
            self._wake_outstanding[r.tag] = (seen_now, now, r.last_activity_at,
                                             info.get("latest_ts") or "")
            self._woke_at[r.tag] = now
            changed = True
            if retry_reason:
                log.info("re-waking [%s]: %s", r.tag, retry_reason)
            await self._inject_msg_check(r, f"{info['count']} unread addressed to it")
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

    async def _sync_project_dags(self, projs: list[dict[str, Any]]) -> None:
        """Run ``bus.sh project sync`` for each project with an in-flight job, so a job whose order
        reached CLOSED advances to done (unblocking dependents) with no human in the loop."""
        for p in projs:
            if not p.get("in_flight"):
                continue
            try:
                await asyncio.to_thread(
                    subprocess.run,
                    [str(self.settings.bus.script_path_resolved), "project", "sync", p["id"]],
                    capture_output=True, text=True, timeout=15, env=_project_subenv(),
                )
            except (OSError, subprocess.SubprocessError) as e:
                log.warning("project sync %s failed: %s", p.get("id"), e)

    async def _auto_escalate_timeouts(self, projs: list[dict[str, Any]]) -> None:
        """Flip any open LEAD-bound escalation older than the timeout to Kyle (§4a). Uses the system
        ``timeout-forward`` verb (no lead guard) so the clock — not a worker — is what escalates."""
        now = time.time()
        for p in projs:
            for e in p.get("escalations") or []:
                if e.get("state") != "open" or e.get("target") != "lead":
                    continue
                if now - e.get("created", now) < _PROJECT_LEAD_TIMEOUT_SECONDS:
                    continue
                try:
                    await asyncio.to_thread(
                        subprocess.run,
                        [str(self.settings.bus.script_path_resolved), "project",
                         "timeout-forward", p["id"], e["id"]],
                        capture_output=True, text=True, timeout=15, env=_project_subenv(),
                    )
                    log.info("escalation %s/%s auto-escalated to Kyle (lead timeout)", p["id"], e["id"])
                except (OSError, subprocess.SubprocessError) as ex:
                    log.warning("timeout-forward %s/%s failed: %s", p["id"], e.get("id"), ex)

    def _member_session(self, member: str) -> SessionRecord | None:
        """Resolve a PROJECT member (a bare name like ``claude-connect``) to its live session.

        NOT ``_live_session_for`` — that keeps the ``other:`` prefix (it matches lease owners, which
        bus.sh writes as ``other:qualcomm``), but project.sh stores members bare (``_coord_plain``
        strips ``other:``), so ``claude-connect`` would never match ``[other:claude-connect]``. Strip
        BOTH sides fully — the same bracket/other: normalization the service resolver learned."""
        want = _bare_tag(member).replace("other:", "")
        for s in self.sessions.values():
            if s.status == Status.ENDED:
                continue
            if _bare_tag(s.tag).replace("other:", "") == want:
                return s
        return None

    def _member_output_tokens(self, member: str) -> int | None:
        """A member's cumulative session OUTPUT tokens, or None if it has no live session. The unit
        the spend meter attributes project cost from (§5c)."""
        rec = self._member_session(member)
        jp = getattr(rec, "jsonl_path", None) if rec else None
        if not jp:
            return None
        try:
            return int(self.token_accountant.usage_for(jp).get("output", 0))
        except (OSError, ValueError, KeyError):
            return None

    def _annotate_lead_offline(self, projs: list[dict[str, Any]]) -> None:
        """Lead-death surfacing (§10.5): an active project whose lead has no live session. Surfaced,
        never auto-reassigned — deciding who inherits a half-run project is Kyle's call."""
        for p in projs:
            lead = p.get("lead") or ""
            p["lead_offline"] = bool(p.get("state") == "active" and lead
                                     and self._member_session(lead) is None)

    def _annotate_assignee_status(self, projs: list[dict[str, Any]]) -> None:
        """Capacity-awareness (slice 7): tag each job with its assignee's live status, so the lead
        and Kyle can SEE they're about to route work into a session that's already busy — the fix for
        'dispatch a job to a working session and it has to ask the human which to do first'. Advisory:
        it surfaces load, it doesn't block; prefer an idle peer, but a BACKGROUND job to a busy one is
        fine (the worker fits it around its own work)."""
        for p in projs:
            for j in p.get("jobs") or []:
                rec = self._member_session(j.get("to", "")) if j.get("to") else None
                st = (rec.status.value if rec and hasattr(rec.status, "value")
                      else str(rec.status) if rec else "offline")
                j["assignee_status"] = st
                j["assignee_busy"] = st in ("active", "warm")

    async def _check_budget_alarms(self, projs: list[dict[str, Any]]) -> bool:
        """Raise a Kyle-bound budget decision once when a project crosses the warn threshold. Reuses
        the shield: it becomes an escalation in the same queue Kyle answers (extend / checkpoint /
        finish) and pages by the same rule. Resets when spend drops back under (e.g. ceiling raised)."""
        raised = False
        for p in projs:
            pid = p["id"]
            if not p.get("budget_warn"):
                self._budget_alarmed.discard(pid)     # back under threshold -> re-arm
                continue
            if pid in self._budget_alarmed:
                continue
            # Don't pile on if a budget escalation for this project is already open.
            if any(e.get("state") == "open" and e.get("deny") == "budget"
                   for e in p.get("escalations", [])):
                self._budget_alarmed.add(pid)
                continue
            spend, ceiling, pct = p.get("spend", 0), p.get("ceiling", 0), p.get("spend_pct")
            body = (
                f"question: project '{pid}' has spent {spend:,} of its {ceiling:,}-token ceiling "
                f"({pct}%). Extend the budget, checkpoint and stop, or let it finish?\n"
                f"why: measured spend crossed {int(self._spend_meter.WARN_FRACTION * 100)}% — deciding "
                f"now beats a hard stop at a half-built state\n"
                f"option: extend the ceiling\noption: checkpoint and stop\noption: let it finish\n"
                f"recommendation: checkpoint and reassess before the cap bites")
            eid = f"budget-{spend}"
            try:
                await asyncio.to_thread(
                    subprocess.run,
                    [str(self.settings.bus.script_path_resolved), "project", "escalate",
                     pid, eid, "deny:budget"],
                    input=body, capture_output=True, text=True, timeout=15, env=_project_subenv())
                self._budget_alarmed.add(pid)
                raised = True
                log.info("budget alarm: project %s at %s%% of ceiling", pid, pct)
            except (OSError, subprocess.SubprocessError) as e:
                log.warning("budget escalate for %s failed: %s", pid, e)
        return raised

    def _dispatch_admission(self) -> tuple[bool, str, dict[str, int]]:
        """Fleet-global admission decision for dispatching one more job (§5b). NOT the lead's call —
        the lead requests, Conductor admits by load — because a lead eager to finish rationalizes
        'one more parallel job'. Returns (ok, reason, meter)."""
        in_flight = total_in_flight(self.projects)
        busy = sum(1 for s in self.sessions.values()
                   if s.status in _BUSY_STATUSES and s.status != Status.ENDED)
        meter = {"in_flight": in_flight, "cap": _PROJECT_MAX_IN_FLIGHT,
                 "fleet_busy": busy, "fleet_ceiling": _PROJECT_FLEET_BUSY_CEILING}
        if in_flight >= _PROJECT_MAX_IN_FLIGHT:
            return False, (f"admission throttled: {in_flight} job(s) already in flight across the "
                           f"fleet (cap {_PROJECT_MAX_IN_FLIGHT}). Let one land first."), meter
        if busy >= _PROJECT_FLEET_BUSY_CEILING:
            return False, (f"admission throttled: {busy} sessions already ACTIVE/WARM (ceiling "
                           f"{_PROJECT_FLEET_BUSY_CEILING}) — the fleet is near the API ceiling."), meter
        return True, "", meter

    def _live_session_for(self, owner: str) -> SessionRecord | None:
        return next((s for s in self.sessions.values()
                     if _bare_tag(s.tag) == _bare_tag(owner) and s.status != Status.ENDED), None)

    def _resolve_live_by_name(self, name: str) -> SessionRecord | None:
        """Resolve a FRIENDLY name the operator typed (``claude-connect``) to a live session,
        matching either the full bare tag (``other:claude-connect``) or its ident (the part
        after ``other:``). Used by remote prompt routing, where you @-mention the short name."""
        want = _bare_tag(name).lower()
        want_id = want[6:] if want.startswith("other:") else want
        for s in self.sessions.values():
            if s.status == Status.ENDED:
                continue
            bare = _bare_tag(s.tag).lower()
            ident = bare[6:] if bare.startswith("other:") else bare
            if want in (bare, ident) or want_id in (bare, ident):
                return s
        return None

    def _live_session_for_service(self, name: str) -> SessionRecord | None:
        """Resolve a service by its registered NAME (``image_gen``) to the live session
        running it. Unlike a lease owner (``bus.sh`` writes those already tag-shaped), a
        service dir is named for the session's bare identity — the basename — while the
        session's tag normalizes to ``other:<basename>``. So strip a leading ``other:``
        before comparing, or the match silently never succeeds and no wake ever fires
        (the bracket/bare mismatch that hid v2.16's orphan wake, in service form)."""
        for s in self.sessions.values():
            if s.status == Status.ENDED:
                continue
            bare = _bare_tag(s.tag)  # "other:image_gen" | "backend"
            ident = bare.split("other:", 1)[1] if bare.startswith("other:") else bare
            if ident == name or bare == name:
                return s
        return None

    def _webpush_status(self) -> dict[str, Any]:
        """Can phone paging actually reach a device right now? Surfaced to the UI so it
        can warn — an app that can't alert you should at least TELL you it can't. The
        2026-07-22 incident: paging was dead 6h (a missing dep) and nothing said so, so a
        Claude sat blocked on a human decision the whole time. ``healthy=False`` means a
        page that should fire cannot; the reason drives the message.
        """
        if self._webpush_broken:
            return {"healthy": False, "reason": "dependency_missing",
                    "detail": ("Phone notifications are offline — a server dependency is "
                               "missing (install it and restart Conductor). Blocked "
                               "questions and pushes are still in the inbox.")}
        try:
            subs = read_subs(self.coord_root)
        except Exception:  # noqa: BLE001 — a status probe must never raise
            subs = []
        if not subs:
            # No device registered. This is only an ALARM when something needs you RIGHT
            # NOW — otherwise it just means you never turned notifications on, which is
            # a choice, not a fault.
            pending = bool(notifiable(self.decisions, self._push_requests,
                                      escalations=open_escalations(self.projects, target="kyle")))
            return {"healthy": not pending, "reason": "no_subscription",
                    "detail": ("Something needs you, but no phone is set to receive "
                               "notifications — enable them, or use the inbox.") if pending
                              else "Notifications aren't set up on any phone."}
        return {"healthy": True, "reason": "ok", "detail": ""}

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
        if self._webpush_broken:
            return                     # deps missing — already logged once; don't retry-spam
        dead = [s for s in self._silent if s.get("dead")] if self.settings.bus.page_dead_readers else []
        items = notifiable(self.decisions, self._push_requests, dead,
                           escalations=open_escalations(self.projects, target="kyle"))
        # Forget items that are no longer pending FIRST, so the same question asked again
        # later rings immediately rather than being suppressed by a stale timestamp.
        self._notified = prune_sent(self._notified, items)
        pending = due(items, self._notified)
        if not pending:
            return
        subs = await asyncio.to_thread(read_subs, self.coord_root)
        if not subs:
            return                     # no phone registered — nothing to do, and not an error
        try:
            keys = await asyncio.to_thread(load_or_create_keys, self.coord_root)
        except ImportError as e:
            # pywebpush/cryptography not in the service venv. This CANNOT self-heal mid-run,
            # so disable web-push and log ONCE — never raise into the scan loop (paging is an
            # accelerator, never the only door: the item stays in the /m inbox regardless).
            self._webpush_broken = True
            log.error(
                "web-push disabled — missing dependency (%s). Phone paging is OFF until "
                "the service venv has pywebpush installed (pip install pywebpush) and "
                "Conductor is restarted. Blocked questions/pushes remain visible in /m.", e,
            )
            return
        subject = vapid_subject(socket.gethostname())
        now = time.time()
        for item in pending:
            # Claim-and-check BEFORE the send awaits — same concurrency discipline as the wake
            # paths. `pending` was computed once up top, so two concurrent passes both see the
            # item as due; re-checking _notified here (and marking before send_one yields) means
            # only the first pass rings, the rest skip. (The double-start guard makes this single
            # today; this keeps the whole class uniformly safe.) Failure behaviour is unchanged —
            # it was marked regardless of `ok` before — and due() re-rings hourly.
            if item["key"] in self._notified:
                continue                   # a concurrent pass already claimed it
            self._notified[item["key"]] = now
            for sub in list(subs):
                ok = await asyncio.to_thread(send_one, sub, item, keys, subject)
                if ok is None:         # 410/404: that device is gone for good, not retrying
                    await asyncio.to_thread(drop_sub, self.coord_root, sub["endpoint"])
                    subs.remove(sub)
            log.info("notified: %s", item["title"])

    _NOTICE_TTL_S = 3600.0
    _RC_TTL_S = 1800.0        # a queued reconnect waits ≤30m for the session to go idle, then drops

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
                continue                           # busy -> keep it, retry once quiet
            # CLAIM the notice before the await, restore it only if the inject fails. Deleting
            # after the await (as this did) let a concurrent pass re-send it — that is how "Kyle
            # approved your git push" was delivered 3x with no grant behind it, long after the
            # grant it referred to had been consumed. Claiming first makes it deliver at most
            # once; restore-on-failure keeps the retry for a genuinely missed keystroke.
            if self._push_notices.pop(key, None) is None:
                continue                           # another pass already claimed it
            sent = await self._inject_text(
                rec,
                note.get("text") or (
                    f"✅ Kyle approved your git push to {note['repo']} — re-run it whenever "
                    "you're ready. The approval waits for you; it covers exactly one push."),
                f"push verdict for {note['repo']}",
            )
            if not sent:
                self._push_notices[key] = note     # inject failed -> put it back to retry

    _REMOTE_PROMPT_TTL_S = 900.0        # 15 min — a remote prompt that never lands goes stale

    def _drain_prompt_route_files(self) -> None:
        """Pick up route requests the prompt-route hook dropped — an @-mention you typed inside
        a session, or in the Claude app over /rc — and enqueue them for delivery, exactly like
        the phone @-bar. The hook writes a file (it can't touch Conductor's in-memory queue);
        this is the bridge."""
        rdir = self.coord_root / "prompt-routes"
        try:
            files = sorted(rdir.glob("*.json"))
        except OSError:
            return
        for f in files:
            rec = None
            try:
                rec = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                pass
            if isinstance(rec, dict):
                target = (rec.get("target") or "").strip()
                message = (rec.get("message") or "").strip()
                if target and message:
                    self._remote_prompt_seq += 1
                    src = str(rec.get("source_session", "?"))[:8]
                    self._remote_prompts[f"{target}:{self._remote_prompt_seq}"] = {
                        "tag": target, "message": message, "queued": time.time(),
                        "source": f"human via [{src}]", "actor": "human",
                    }
            try:
                f.unlink()
            except OSError:
                pass

    async def _deliver_remote_prompts(self) -> None:
        """Deliver operator @-addressed prompts into the target session's terminal — but only
        once it is QUIET (a busy Claude eats injected keystrokes). Same claim-before-await
        discipline as the push notices, so a prompt is delivered at most once; attributed to the
        human in the provenance ledger, since the operator genuinely composed it."""
        await asyncio.to_thread(self._drain_prompt_route_files)   # hook-dropped routes -> queue
        if not self._remote_prompts:
            return
        now = time.time()
        for key, rp in list(self._remote_prompts.items()):
            if now - rp["queued"] > self._REMOTE_PROMPT_TTL_S:
                del self._remote_prompts[key]
                log.info("remote prompt to [%s] expired undelivered", rp.get("tag"))
                continue
            rec = self._resolve_live_by_name(rp["tag"])
            if rec is None or rec.status in _BUSY_STATUSES:
                continue                           # gone / busy -> keep, retry once live+quiet
            if self._remote_prompts.pop(key, None) is None:
                continue                           # another pass already claimed it
            sent = await self._inject_text(
                rec, rp["message"], f"remote prompt from {rp.get('source', 'operator')}",
                actor=rp.get("actor", "human"),
            )
            if not sent:
                self._remote_prompts[key] = rp     # picker/tool guard refused -> retry once quiet

    async def _deliver_rc_reconnects(self) -> None:
        """Fire a queued ``/rc`` reconnect the moment its session is idle.

        An /rc typed into a BUSY Claude Code session queues in the TUI and never establishes
        the remote-control bridge (found live 2026-07-17). So when the phone asks to reconnect a
        busy session we hold it here and deliver once the session is genuinely quiet — the same
        discipline as the push notices. We drop it when: it bridged (worked), the session went
        away (a dead one is the relaunch path's job, not this), or 30 minutes passed.
        """
        if not self._rc_pending:
            return
        now = time.time()
        for sid, item in list(self._rc_pending.items()):
            if now - item["queued"] > self._RC_TTL_S:
                del self._rc_pending[sid]
                continue
            rec = next((r for r in self.sessions.values()
                        if getattr(r, "session_id", "") == sid), None)
            if rec is None:
                del self._rc_pending[sid]              # session gone -> relaunch, not reconnect
                continue
            if read_bridge(rec.pid)["bridged"]:
                del self._rc_pending[sid]              # already connected -> done
                continue
            if rec.status in _BUSY_STATUSES:
                continue                              # still mid-task -> keep waiting
            # Claim before the await so a concurrent scan can't double-inject (the push-notice
            # 3x-delivery lesson). Restore only if the keystroke couldn't be sent.
            if self._rc_pending.pop(sid, None) is None:
                continue
            sent = await self._inject_text(rec, "/rc", "reconnect remote control (queued)")
            if not sent:
                self._rc_pending[sid] = item          # window unreachable -> retry next scan

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
        return self._decision_for(rec) is not None

    def _decision_for(self, rec: SessionRecord) -> dict[str, Any] | None:
        """The pending decision (open picker) for this session — or None. Prefers the
        session_id join (exact — the record is literally ``<session_id>.json``), then falls
        back to a cwd match, mirroring ``_session_for_decision`` in the other direction. This
        is the session→decision lookup behind both the picker guard and the UI's "go answer
        it" routing, so it must catch a picker even when the session cd'd away from its cwd."""
        if not self.decisions:      # the overwhelmingly common case — nobody is asking
            return None
        sid = getattr(rec, "session_id", "") or ""
        if sid:
            for d in self.decisions:
                if d.get("session_id") == sid:
                    return d
        target = os.path.realpath(getattr(rec, "project_dir", "") or "")
        if target:
            for d in self.decisions:
                cwd = d.get("cwd")
                if cwd and os.path.realpath(cwd) == target:
                    return d
        return None

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

    async def _inject_text(self, rec: SessionRecord, text: str, why: str,
                           *, actor: str = "conductor") -> bool:
        """Type ``text`` into a live session's terminal (raises its window).

        THE CHOKE POINT. Attestation lives here, not at the call sites — a new injection path
        added next month cannot forget to attest, OR to honour the modal guards, if it cannot
        inject without passing through here. Call-site guarding is the version that rots (the
        ping paths bypassed this and were exactly the ones that could type into a prompt).

        ``actor`` names who drove this injection for the provenance ledger — "conductor" for an
        automated nudge, "human:<ip>" for a message the operator actually composed (a remote
        prompt). It's the same distinction the decision-answer path records: the ledger must say
        who really typed, since the keystrokes land as a user turn either way.
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
            source="conductor:_inject_text", actor=actor,
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

    def _session_for_decision(self, d: dict[str, Any]) -> SessionRecord | None:
        """Map a captured AskUserQuestion back to its live session — for surfacing it AND for
        injecting the answer.

        Join on ``session_id`` FIRST: the capture hook names each record ``<session_id>.json`` and
        that id is the transcript stem, the exact id Conductor derives for the same live session.
        We used to match on cwd alone, and it silently dropped questions off the phone: the hook
        records the session's launch cwd while Conductor stores ``proc.cwd()``, and the two diverge
        (a symlinked path, a chdir, a subdir launch) — a mismatch there made the ask never appear.
        cwd stays as a fallback for any record written before this join existed."""
        sid = (d.get("session_id") or "").strip()
        if sid:
            rec = next(
                (s for s in self.sessions.values()
                 if s.status != Status.ENDED and s.session_id == sid),
                None,
            )
            if rec is not None:
                return rec
        return self._session_for_cwd(d.get("cwd", ""))

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
            # Claim the episode BEFORE the await — same race as the other wake paths (qualcomm
            # got 2 duplicate nudges in one burst).
            self._nudge_woken.add(key)
            await self._inject_msg_check(rec, f"watchdog nudge on {r['name']} (idle)")
        self._nudge_woken &= current  # a new idle episode gets a fresh wake

    async def _wake_stale_service_heads(self) -> None:
        """Re-deliver a service Claude's lost wake.

        A service is nudged to serve a job by the requester at request time — a one-shot.
        If Conductor was down then (image_gen sat 28m on tipometer's job, 2026-07-17), or
        the service was busy and never returned to it, that wake is gone: nothing re-fires,
        and an idle service has no prompt-hook line telling it a job is waiting. So we watch
        for a queue HEAD that has been waiting longer than ``_SVC_STALE_SECONDS`` in front of
        an idle service and inject one /msg-check — once per job (keyed on the job id, so a
        new head re-arms but the same job never nags). Honours the ``[bus].autodeliver``
        off-switch, same as every other wake path.

        Skipped when: the service is HELD (Kyle claimed the next opening), it's already
        ``serving`` something, or its session is BUSY (it's working — very possibly on this
        very job, which it can take without running /svc-next, leaving the entry queued; the
        busy-guard is exactly what stops us prodding a service mid-render).
        """
        if not self.settings.bus.autodeliver:
            return
        now = time.time()
        current: set[str] = set()
        for svc in self.services.get("services", []):
            if svc.get("held") or svc.get("serving"):
                continue
            queue = svc.get("queue") or []
            if not queue:
                continue
            head = queue[0]
            epoch = head.get("epoch", 0)
            if not epoch or now - epoch < _SVC_STALE_SECONDS:
                continue  # give the request-time wake / requester ping first crack
            name = svc.get("name", "")
            key = f"{name}\x00{head.get('id', '')}"
            current.add(key)
            if key in self._svc_woken:
                continue
            rec = self._live_session_for_service(name)
            if rec is None or rec.status in _BUSY_STATUSES:
                continue  # not live (nothing to wake), or working — retry next scan
            self._svc_woken.add(key)  # claim before the await (same race as the other wakes)
            await self._inject_msg_check(rec, f"stale service job for {name} (queued {int(now - epoch)}s)")
        self._svc_woken &= current  # forget jobs that have left the queue

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
            self._pinged_offers.add(key)      # claim before the await (concurrency race)
            await self._inject_msg_check(rec, f"offered {r['name']}")
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

    async def _retry_while_deferred(self, attempt, *, what: str, cwd: str):
        """Call ``attempt()`` until it succeeds or the deadline passes.

        ``windows._focus_session_input`` returns False both for "couldn't find the window" and
        for "a human is at the keyboard, deferring" — and it CANNOT distinguish them for us,
        so we simply retry a bounded number of times. That is safe for both callers here: a
        deferred attempt typed nothing at all, and the text path clears the line (ctrl+u)
        before typing, so a partial landing cannot compound.
        """
        deadline = time.time() + _INJECT_RETRY_SECONDS
        tries = 0
        while True:
            tries += 1
            if await attempt():
                if tries > 1:
                    log.info("relaunch: %s landed in %s after %d tries (a human held the "
                             "keyboard)", what, cwd, tries)
                return True
            if time.time() >= deadline:
                log.warning("relaunch: %s never landed in %s after %d tries over %.0fs — a "
                            "human was active the whole time, or the window is gone",
                            what, cwd, tries, _INJECT_RETRY_SECONDS)
                return False
            await asyncio.sleep(_INJECT_RETRY_STEP_S)

    async def _bootstrap_relaunched(self, cwd: str, name: str, rc: bool, rename: bool) -> None:
        """Wait for the relaunched Claude to come up, then inject the enabled
        keystrokes — ``/rc`` (remote-control) when ``rc`` is on and/or
        ``/rename <name>`` when ``rename`` is on.

        This is the flaky part of the feature: keystrokes only land once the TUI
        is drawn and at a prompt. We poll the scanner for the new live session in
        that cwd (with a terminal window), then give it a settle delay before the
        first keystroke. Injection steals focus by design (see x11.py)."""
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
            async def _type(_text=text):
                nonlocal rec
                rec = _find() or rec   # refresh pid/window in case the scan replaced it
                return await asyncio.to_thread(
                    send_keys_to_session,
                    text=_text, pid=rec.pid, terminal_pid=rec.terminal_pid,
                    title=rec.title, window_title=rec.window_title,
                )

            ok = await self._retry_while_deferred(_type, what=repr(text), cwd=cwd)
            if not ok:
                pass  # already logged with the reason by _retry_while_deferred
            elif text == "/rc":
                # `/rc` does not merely enable remote control — it opens the Remote Control
                # MENU ("Disconnect this session / Show QR code / Continue · Enter to select,
                # Esc to continue") and the session then sits BLOCKED on that modal until a
                # human answers it.
                #
                # Kyle, 2026-08-17, observed live: EVERY relaunched session came up parked on
                # this dialog. So the relaunch feature was reliably walking each session it
                # revived straight into a prompt only he could clear — the opposite of the
                # unattended recovery it exists to provide.
                #
                # Remote control is already ON by the time the menu renders (the pane says so),
                # so the menu is pure status and is safe to dismiss. Dismiss with ESC, NEVER
                # Return: Return SELECTS whatever the cursor happens to be sitting on, and one
                # of the three options is "Disconnect this session" — the v2.24 lesson that an
                # open picker turns stray input into an answer nobody gave.
                await asyncio.sleep(cfg.between_seconds)

                async def _esc():
                    nonlocal rec
                    rec = _find() or rec
                    return await asyncio.to_thread(
                        send_key_to_session, key="Escape", pid=rec.pid,
                        terminal_pid=rec.terminal_pid, title=rec.title,
                        window_title=rec.window_title,
                    )

                # Retried for the same reason the /rc itself is: the person who clicked
                # Relaunch is still at the keyboard. Getting this wrong leaves the session
                # parked on a modal, which is the whole bug being fixed.
                if not await self._retry_while_deferred(_esc, what="the /rc menu dismissal",
                                                        cwd=cwd):
                    log.warning("relaunch: %s is left sitting on the /rc Remote Control menu "
                                "— it is blocked until someone presses Esc", cwd)

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

    # Asset cards are 99% of the resources payload (MEASURED 2026-08-16: 53.5 KB of
    # 54.0 KB) and they are STATIC — yet they rode the 3s broadcast because the
    # 0.5 KB of lease/telemetry beside them ticks (GPU utilization). That is the
    # scan-loop defect one layer up: *a payload that mixes volatile and static data
    # forces the static part to travel at the volatile rate.*
    #
    # The tile needs only `has_access` (to choose its label) and `kind`; the body is
    # read ONLY when the card modal opens, so it is fetched on demand from
    # /api/resources/{name}/card. `self.resources` keeps the full card server-side —
    # the wire gets the stub. Saves ~53.5 KB every 3 s to every connected client
    # (~1.5 GB/day each), which matters most on the phone over Tailscale.
    def _resources_payload(self) -> dict[str, Any]:
        return slim_resource_cards(self.resources)

    def _sessions_broadcast_payload(self) -> dict[str, Any]:
        """The per-tick payload with unchanged STATIC sub-keys omitted.

        See ``_SESSIONS_STATIC_KEYS``. Only the periodic broadcast is thinned — the
        REST endpoint and the WS connect snapshot always serve the full object.
        """
        now_mono = time.monotonic()
        force_full = now_mono - self._sessions_full_sent >= _SESSIONS_FULL_REFRESH_SECONDS
        if force_full:
            self._sessions_full_sent = now_mono
        return thin_unchanged_keys(
            self._sessions_payload(), self._sessions_static_digest,
            _SESSIONS_STATIC_KEYS, force_full=force_full,
        )

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
            # Remote-control bridge state (is it on the phone?) + a queued reconnect, if any.
            d["bridged"] = read_bridge(r.pid)["bridged"]
            d["rc_pending"] = sid in self._rc_pending
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
            "stale_cursors": self._stale_cursors,   # live but not reading its mail (image_gen)
            "collisions": self._collisions,  # two live sessions, one member (holobench)
            "lost_rc": self._lost_rc,        # alive but lost /RC (§3.4.1, rt1180)
            "webpush": self._webpush_status(),  # can we actually page the phone? (2026-07-22)
            "x11": self._x11,                # can we reach a display to type at all? (2026-08-05)
            "fadeout_seconds": self.settings.ui.end_fadeout_seconds,
            "wmctrl_available": wmctrl_available(),
            "winddown": self._winddown_payload(),  # fleet shutdown state, if a wind-down is active
        }

    def _winddown_managers(self, wd: dict[str, Any] | None = None) -> set[str]:
        """Members that must NEVER be auto-closed by a sweep: the session DRIVING the wind-down.

        Kyle, 2026-08-05, live: "Close idle" closed the managing ``claude-connect`` session —
        it was idle at tap-time, because orchestrating a wind-down means sitting at a prompt
        waiting — and that killed the session running the wind-down, mid-wind-down. The sweep's
        own operator is the one session whose idleness is EXPECTED rather than suspicious.

        Two sources, because either alone leaves a hole: the recorded ``initiator`` (whoever
        called ``shutdown begin``) and the configured operator console (``autodeliver_exempt``,
        already the fleet's "this is Kyle's console" marker — a wind-down begun from the phone
        has no session initiator at all)."""
        wd = wd if wd is not None else read_winddown(self.coord_root)
        managers = {_wd_plain(t) for t in self.settings.bus.autodeliver_exempt}
        initiator = ((wd.get("active") or {}).get("initiator") or "").strip()
        if initiator:
            managers.add(_wd_plain(initiator))
        managers.discard("")
        return managers

    @staticmethod
    def _proc_start_epoch(pid: int | None) -> float:
        """When this session's process started. 0.0 if unknowable."""
        if not pid:
            return 0.0
        try:
            return psutil.Process(pid).create_time()
        except (psutil.Error, OSError):
            return 0.0

    def _restarted_since_winddown(self, r: SessionRecord, began: float) -> bool:
        """Did this session start AFTER the wind-down was called?

        Found live 2026-08-05: a wind-down marker SURVIVES A REBOOT. Yesterday's was still
        `active` with 12 `.done` files while the fleet had since been restarted — so a session
        brought back by ⟳ Fleet recovery was, on paper, a straggler of a wind-down it was never
        part of, wearing a `.done` written by its previous incarnation. Two live hazards:
        "Close wound-down" offered to close a freshly-relaunched session on a stale ack, and the
        new re-nudge would have told every restored session to wind down again — turning fleet
        RECOVERY into a second shutdown.

        A process that did not exist when the order was given cannot have obeyed or ignored it.
        So we compare the claude process's own start time against the wind-down epoch, which is
        the one fact neither file can fake. Unknown start time ⇒ False (treat as part of it), so
        a box where we cannot read /proc degrades to the old behaviour rather than silently
        exempting the whole fleet."""
        if not began:
            return False
        started = self._proc_start_epoch(r.pid)
        return bool(started and started > began)

    def _winddown_payload(self) -> dict[str, Any]:
        """State of an in-progress fleet wind-down, for the shutdown panel.

        Per session, the wind-down state is DERIVED, not self-reported: ``wound-down`` only if
        the session has a VERIFIED ack on disk (``bus.sh shutdown ack`` wrote it after checking
        git+leases); otherwise ``asking`` (open picker — never inject/close), ``busy`` (working —
        wait, never interrupt), or ``flushing`` (reachable, not yet acked). This is what lets
        Conductor close only what has provably persisted, and surface the rest for Kyle."""
        wd = read_winddown(self.coord_root)
        active = wd.get("active")
        if not active:
            return {"active": False}
        acks = wd.get("acks", {})
        managers = self._winddown_managers(wd)
        began = float(active.get("epoch", 0) or 0)
        rows: list[dict[str, Any]] = []
        for r in self.sessions.values():
            if r.status == Status.ENDED:
                continue
            plain = _wd_plain(r.tag or "")
            ack = acks.get(plain)
            restarted = self._restarted_since_winddown(r, began)
            if restarted:
                # Started after the order was given: not a straggler, and any .done on disk
                # belongs to its previous incarnation. Never closed, never nudged.
                st = "restarted"
                ack = None
            elif ack is not None:
                st = "wound-down"
            elif self._has_open_picker(r):
                st = "asking"
            elif r.status in _BUSY_STATUSES:
                st = "busy"
            else:
                # "flushing" USED TO COVER BOTH OF THESE, and that was a lie of the reassuring
                # kind (Kyle, 2026-08-05): a session woken by the wind-down that has done
                # NOTHING since looked identical to one actively persisting its state. The first
                # needs a nudge or a decision; the second needs patience. Split them on the only
                # evidence we have — has the transcript moved since the wind-down began?
                st = "flushing" if (began and (r.last_activity_at or 0) > began) else "idle-unacked"
            rows.append({
                "tag": r.tag, "member": plain, "status": r.status.value, "state": st,
                "summary": (ack or {}).get("summary", ""),
                "unpushed": int((ack or {}).get("unpushed", 0) or 0),
                "manager": plain in managers,   # never swept; it is running the wind-down
                "nudges": self._wd_nudges.get(plain, 0),
            })
        counts: dict[str, int] = {}
        for row in rows:
            counts[row["state"]] = counts.get(row["state"], 0) + 1
        return {
            "active": True,
            "initiator": active.get("initiator", ""),
            "created": active.get("created", ""),
            "sessions": rows,
            "counts": counts,
            # Managers are excluded here too: the button's number must match what it will do.
            "closable": sum(1 for r in rows if r["state"] == "wound-down" and not r["manager"]),
            "idle_closable": sum(1 for r in rows if r["state"] == "idle-unacked" and not r["manager"]),
        }

    async def begin_winddown(self) -> dict[str, Any]:
        """Broadcast the wind-down protocol, then wake the sessions that can safely act on it.
        Never prods a session that is asking Kyle a question (open picker) or busy (mid-task) —
        the broadcast reaches those when they next pause; only reachable idle/waiting sessions
        are woken. This is the whole safety property: we do not interrupt, and we do not corrupt
        an open picker."""
        proc = await asyncio.to_thread(
            subprocess.run,
            [str(self.settings.bus.script_path_resolved), "shutdown", "begin"],
            capture_output=True, text=True, timeout=15,
        )
        woke: list[str] = []
        skipped: list[dict[str, str]] = []
        for r in list(self.sessions.values()):
            if r.status == Status.ENDED:
                continue
            if self._has_open_picker(r):
                skipped.append({"tag": r.tag, "why": "asking"})
                continue
            if r.status in _BUSY_STATUSES:
                skipped.append({"tag": r.tag, "why": "busy"})
                continue
            await self._inject_msg_check(r, "fleet wind-down")
            woke.append(r.tag)
        log.info("fleet wind-down begun: woke %d, skipped %d (busy/asking)", len(woke), len(skipped))
        return {"ok": proc.returncode == 0, "woke": woke, "skipped": skipped,
                "result": (proc.stdout or "").strip()}

    async def clear_winddown(self) -> dict[str, Any]:
        proc = await asyncio.to_thread(
            subprocess.run,
            [str(self.settings.bus.script_path_resolved), "shutdown", "clear"],
            capture_output=True, text=True, timeout=15,
        )
        return {"ok": proc.returncode == 0, "result": (proc.stdout or "").strip()}

    async def close_wound_down(self) -> dict[str, Any]:
        """Close ONLY sessions with a VERIFIED wound-down ack — inject ``/exit`` into each.

        A session with no ack is never touched (it has not provably persisted); a busy or
        picker-open session is never touched (defensive — an acked session should be neither).
        After the last close, refresh the DR roster so a later Reconstitute rebuilds from the
        wound-down state (Kyle's 'snapshot after flush')."""
        wd = read_winddown(self.coord_root)
        if not wd.get("active"):
            return {"ok": False, "error": "no wind-down active", "closed": []}
        acks = wd.get("acks", {})
        managers = self._winddown_managers(wd)
        began = float((wd.get("active") or {}).get("epoch", 0) or 0)
        closed: list[str] = []
        refused: list[dict[str, str]] = []
        for r in list(self.sessions.values()):
            if r.status == Status.ENDED:
                continue
            plain = _wd_plain(r.tag or "")
            if plain not in acks:
                continue  # not acked → not closable; leave it, it is waited for
            if self._restarted_since_winddown(r, began):
                # Its .done was written by a PREVIOUS incarnation (a wind-down marker survives a
                # reboot). Closing on that ack would close a freshly-recovered session using a
                # verification of a process that no longer exists.
                refused.append({"tag": r.tag, "why": "restarted"})
                continue
            if plain in managers:
                refused.append({"tag": r.tag, "why": "manager"})  # do not close the driver
                continue
            if self._has_open_picker(r):
                refused.append({"tag": r.tag, "why": "asking"})  # never inject into a picker
                continue
            ok = await asyncio.to_thread(
                send_keys_to_session, text="/exit", pid=r.pid,
                terminal_pid=r.terminal_pid, title=r.title, window_title=r.window_title,
            )
            how = "/exit"
            if not ok:
                # PID FALLBACK — ONLY ON THIS PATH, and only because of what the ack proves.
                # Every close rides keystroke injection, so a session whose window can't be
                # resolved was uncloseable: the 2026-08-05 wind-down reached ~2 of 25 windows and
                # Kyle closed the rest by hand. But a session with a VERIFIED ack has already been
                # checked against disk — tracked tree committed, no leases held — so terminating
                # it loses nothing that was not already persisted. That is exactly why the
                # fallback is confined to the acked path and is NOT offered to the idle sweep,
                # where the whole point is that the session never proved anything.
                ok = await asyncio.to_thread(self._terminate_session, r)
                how = "SIGTERM"
            (closed if ok else refused).append(
                r.tag if ok else {"tag": r.tag, "why": "close-failed"})
            if ok:
                log.info("wind-down: closed [%s] (%s) after verified ack", r.tag, how)
        snapshot = await self._winddown_snapshot()
        return {"ok": True, "closed": closed, "refused": refused, "snapshot": snapshot}

    async def close_idle_stragglers(self) -> dict[str, Any]:
        """Close the passive tail: un-acked sessions that are IDLE (the 'flushing' state) — a
        DELIBERATE, eyes-open close of sessions that never self-acked. This is NOT the safe path:
        these sessions are NOT verified-clean, so the caller must warn. Still never touches a BUSY
        or ASKING session (those are genuinely mid-something and stay waited-for). Closing via
        ``/exit`` ends the session but does NOT delete its working tree — uncommitted changes remain
        on disk and are captured by the post-close DR roster snapshot, recoverable later."""
        wd = read_winddown(self.coord_root)
        if not wd.get("active"):
            return {"ok": False, "error": "no wind-down active", "closed": []}
        acks = wd.get("acks", {})
        managers = self._winddown_managers(wd)
        began = float((wd.get("active") or {}).get("epoch", 0) or 0)
        closed: list[str] = []
        skipped: list[dict[str, str]] = []
        for r in list(self.sessions.values()):
            if r.status == Status.ENDED:
                continue
            plain = _wd_plain(r.tag or "")
            if plain in acks:
                continue  # acked → use the safe verified close, not this
            if self._restarted_since_winddown(r, began):
                skipped.append({"tag": r.tag, "why": "restarted"})   # never part of this wind-down
                continue
            if plain in managers:
                # THE SELF-SWEEP BUG (Kyle, 2026-08-05): this closed the session running the
                # wind-down, because orchestrating one means sitting idle at a prompt — the sweep
                # ate its own operator. A manager is never un-acked "suspiciously"; it is un-acked
                # because it is still working.
                skipped.append({"tag": r.tag, "why": "manager"})
                continue
            if self._has_open_picker(r):
                skipped.append({"tag": r.tag, "why": "asking"})  # never close a session asking Kyle
                continue
            if r.status in _BUSY_STATUSES:
                skipped.append({"tag": r.tag, "why": "busy"})  # never interrupt a working session
                continue
            ok = await asyncio.to_thread(
                send_keys_to_session, text="/exit", pid=r.pid,
                terminal_pid=r.terminal_pid, title=r.title, window_title=r.window_title,
            )
            (closed if ok else skipped).append(
                r.tag if ok else {"tag": r.tag, "why": "close-failed"})
            if ok:
                log.warning("wind-down: closed IDLE un-acked [%s] (/exit) — NOT verified-clean", r.tag)
        snapshot = await self._winddown_snapshot()
        return {"ok": True, "closed": closed, "skipped": skipped, "snapshot": snapshot, "unverified": True}

    def _terminate_session(self, r: SessionRecord) -> bool:
        """SIGTERM a session's ``claude`` process. Blocking; call via ``to_thread``.

        The close path of last resort, used ONLY for a session with a verified wind-down ack.
        SIGTERM, never SIGKILL: claude handles TERM and shuts down in an orderly way, and the one
        thing we must not do is turn "I couldn't find your window" into "I destroyed your process
        mid-write". If it is still alive after the grace period we report FAILURE rather than
        escalating — an honest 'could not close' is a state Kyle can act on; a forced kill is not
        something he can undo."""
        pid = r.pid
        if not pid:
            return False
        try:
            proc = psutil.Process(pid)
            if proc.name() != "claude":
                # The pid was recycled, or we were handed the wrapper shell (which SURVIVES
                # claude's death — the v2.27.2 lesson). Killing either is killing a stranger.
                log.warning("wind-down: refusing to terminate pid %s — it is %r, not claude",
                            pid, proc.name())
                return False
            proc.terminate()
            proc.wait(timeout=10)
            return True
        except psutil.NoSuchProcess:
            return True          # already gone: the outcome we wanted
        except (psutil.TimeoutExpired, psutil.AccessDenied, psutil.Error, OSError) as e:
            log.warning("wind-down: SIGTERM to [%s] pid %s did not close it: %s", r.tag, pid, e)
            return False

    async def _renudge_unacked(self) -> None:
        """While a wind-down is active, re-prod un-acked sessions on a WIDENING interval.

        Kyle, 2026-08-05: un-acked sessions had to be re-tapped by hand, one at a time, across
        ~25 sessions. But the obvious fix — a fixed-interval nudge — is how the /msg-check storm
        happened (v2.26.1: ~450 injections overnight, 16 stacked on one session), because a busy
        session QUEUES keystrokes and a re-nudge is never a repair. So this backs off and then
        STOPS: a session that has ignored three nudges is not going to be fixed by a fourth, and
        at that point it is a decision for Kyle, not a louder alarm.

        Honours every existing guard — busy, open picker, and the manager set — and only ever
        sends /msg-check (the wind-down order is already on the bus; this just makes them read it).
        """
        wd = read_winddown(self.coord_root)
        if not wd.get("active"):
            self._wd_nudges.clear(); self._wd_nudged_at.clear()
            return
        acks = wd.get("acks", {})
        managers = self._winddown_managers(wd)
        began = float((wd.get("active") or {}).get("epoch", 0) or 0)
        now = time.time()
        for r in list(self.sessions.values()):
            if r.status == Status.ENDED:
                continue
            plain = _wd_plain(r.tag or "")
            if plain in acks:
                self._wd_nudges.pop(plain, None); self._wd_nudged_at.pop(plain, None)
                continue                     # it acked — stop nudging, and forget it
            if plain in managers or self._has_open_picker(r) or r.status in _BUSY_STATUSES:
                continue                     # never prod the driver, a picker, or a working session
            if self._restarted_since_winddown(r, began):
                # A session recovered AFTER the order was given is not ignoring it. Nudging it
                # would turn fleet recovery into a second shutdown — the marker outlives a reboot.
                continue
            n = self._wd_nudges.get(plain, 0)
            if n >= len(_WD_RENUDGE_BACKOFF_S):
                continue                     # exhausted: it is Kyle's call now, not another wake
            due = self._wd_nudged_at.get(plain, 0) + _WD_RENUDGE_BACKOFF_S[n]
            if now < due:
                continue
            # Claim BEFORE the await: _inject_text yields, and a concurrent scan pass that sees a
            # stale count re-sends — the duplicate-wake race that gave qualcomm four retraction
            # nudges in one burst.
            self._wd_nudges[plain] = n + 1
            self._wd_nudged_at[plain] = now
            await self._inject_msg_check(r, f"wind-down re-nudge {n + 1}/{len(_WD_RENUDGE_BACKOFF_S)}")

    async def _winddown_snapshot(self) -> dict[str, Any]:
        """Refresh the DR roster after a wind-down so the reconstitution record reflects the
        wound-down state. Best-effort: a failure here must never make the close look failed."""
        script = Path(__file__).resolve().parent.parent / "scripts" / "fleet-roster.py"
        if not script.exists():
            return {"ok": False, "why": "fleet-roster.py not found"}
        try:
            proc = await asyncio.to_thread(
                subprocess.run, [sys.executable, str(script)],
                capture_output=True, text=True, timeout=60,
            )
            return {"ok": proc.returncode == 0, "result": (proc.stdout or "").strip()[-400:]}
        except Exception as e:  # noqa: BLE001 — snapshot must never break the close
            log.warning("wind-down roster snapshot failed: %s", e)
            return {"ok": False, "why": str(e)}

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


@app.post("/api/rescan")
async def rescan(request: Request) -> dict[str, Any]:
    """Force a fresh scan NOW — what the Refresh button actually needs.

    ``GET /api/sessions`` only returns the LAST cached scan, so 'Refresh' was a no-op against a
    stale record (a session whose window title changed and dropped off the focus radar stayed
    stale until a full restart). This runs a complete scan pass — re-discovering live processes and
    re-resolving windows — broadcasts the result to every client, and returns the fresh payload.
    """
    state: AppState = request.app.state.cond
    await state._do_scan()
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
    resp: dict[str, Any] = {
        "injected": injected,
        "tag": rec.tag,
        "wmctrl_available": wmctrl_available(),
    }
    if not injected:
        # Say WHY the keystroke didn't land, so the click isn't a silent no-op. "asking" =
        # an open picker (typing would corrupt its question — go ANSWER it); "busy" = a tool
        # in flight (don't interrupt; it'll read mail when it pauses); else the window just
        # couldn't be reached.
        if state._has_open_picker(rec):
            resp["reason"] = "asking"
            d = state._decision_for(rec)
            if d:
                resp["decision_session_id"] = d.get("session_id")
        elif state._tool_in_flight(rec):
            resp["reason"] = "busy"
        else:
            resp["reason"] = "no_window"
    return resp


@app.post("/api/sessions/{session_id}/reconnect")
async def reconnect_session(session_id: str, request: Request) -> dict[str, Any]:
    """Re-establish a live session's remote-control bridge so it shows on the phone.

    Injects ``/rc`` (``/remote-control``). The catch, found live: an /rc typed into a BUSY
    session queues in the TUI and silently never bridges — so we fire it now only if the
    session is idle, and otherwise QUEUE it to go the instant it quiets (Kyle's choice: tap
    once, walk away). Either way the truth is the ``bridged`` field on the next scan — this
    reports what it DID (sent / queued / already connected), never a false "done".
    """
    state: AppState = request.app.state.cond
    rec = next((r for r in state.sessions.values()
                if getattr(r, "session_id", "") == session_id), None)
    if rec is None:
        raise HTTPException(status_code=404, detail="session not found")

    if read_bridge(rec.pid)["bridged"]:
        state._rc_pending.pop(session_id, None)
        return {"ok": True, "state": "connected", "tag": rec.tag,
                "detail": "already remote-controlled — it should be on your phone"}

    # Busy -> queue (an /rc mid-turn silently fails to bridge). Idle -> send now.
    if rec.status in _BUSY_STATUSES:
        state._rc_pending[session_id] = {"queued": time.time()}
        return {"ok": True, "state": "queued", "tag": rec.tag,
                "detail": "session is busy — it'll reconnect the moment it's idle"}

    injected = await state._inject_text(rec, "/rc", "reconnect remote control")
    if not injected:
        # picker/tool-in-flight guard, or an unreachable window -> hold and retry when clear
        state._rc_pending[session_id] = {"queued": time.time()}
        return {"ok": True, "state": "queued", "tag": rec.tag,
                "detail": "couldn't reach it right now — will retry when it's clear"}
    state._rc_pending.pop(session_id, None)
    return {"ok": True, "state": "sent", "tag": rec.tag,
            "detail": "sent /rc — the badge turns 'connected' once it bridges"}


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
    return state._resources_payload()


@app.get("/api/resources/{name}/card")
async def get_resource_card(name: str, request: Request) -> dict[str, Any]:
    """The full asset card for one resource — access / setup / gotchas / docs.

    Split out of the periodic payload because the card body is 99% of it and is
    read only when the card modal actually opens (see ``_resources_payload``).
    Served from the scan-cached resources, so it costs no extra disk read.
    """
    state: AppState = request.app.state.cond
    entry = next((r for r in state.resources.get("resources", []) if r.get("name") == name), None)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"no such resource: {name}")
    card = entry.get("card")
    if not isinstance(card, dict):
        raise HTTPException(status_code=404, detail=f"{name} has no asset card")
    return card


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
    state: AppState = request.app.state.cond
    if not _known_request_key(key, state.coord_root / "push-requests"):
        raise HTTPException(status_code=400, detail="bad request key")
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

    ``nudge`` = "go serve your queue": the manual twin of ``_wake_stale_service_heads``.
    A service's serve-wake is one-shot (posted by the requester at request time), and it
    can be lost — Conductor down when the job landed, or the service busy and never back.
    This is the phone control for exactly the case Kyle hit: a service idle on a queued
    job he can SEE but had no way to start. It injects one /msg-check into the service's
    live session and clears the auto-wake dedup so the two paths agree.
    """
    if action not in ("hold", "resume", "nudge"):
        raise HTTPException(status_code=404, detail="unknown action")
    if not name or not all(c.isalnum() or c in "._-" for c in name):
        raise HTTPException(status_code=400, detail="bad service name")
    state: AppState = request.app.state.cond

    if action == "nudge":
        rec = state._live_session_for_service(name)
        if rec is None:
            # No live session — a nudge has nowhere to land. Say so plainly rather than
            # reporting a hollow success (the failure class this whole session was about).
            return {"ok": False, "result": f"{name} has no live session to nudge — relaunch it first."}
        if rec.status in _BUSY_STATUSES:
            # Already working (very possibly this very job). A second /msg-check would only
            # queue behind its current turn and stack — one check drains the backlog anyway.
            return {"ok": True, "result": f"{name} is already working — it'll reach the queue on its own."}
        await state._inject_msg_check(rec, "manual service nudge (phone)")
        # Let the auto-path re-fire too if it's still stale next scan, and don't double-count.
        state._svc_woken = {k for k in state._svc_woken if not k.startswith(f"{name}\x00")}
        log.info("service %s nudged (phone) -> %s", name, rec.tag)
        return {"ok": True, "result": f"Nudged {name} to check its queue."}

    args = [str(state.settings.bus.script_path_resolved), "svc", action, name]
    if action == "hold":
        args.append("Kyle claimed the next opening from the dashboard")
    proc = await asyncio.to_thread(subprocess.run, args, capture_output=True, text=True, timeout=15)
    state.services = await asyncio.to_thread(read_services, state.coord_root)
    await state.hub.broadcast("services", state.services)
    log.info("service %s %s: %s", name, action, (proc.stdout or "").strip() or proc.returncode)
    return {"ok": proc.returncode == 0, "result": (proc.stdout or "").strip()}


@app.get("/api/projects")
async def get_projects(request: Request) -> dict[str, Any]:
    """Project Layer state — lead-owned multi-session work. ``needs_operator`` is the subset
    blocked on Kyle (a plan awaiting approval, an empty lead seat); ``admission`` is the current
    fleet-global throttle meter (in-flight jobs vs cap)."""
    state: AppState = request.app.state.cond
    _, _, meter = state._dispatch_admission()
    return {"projects": state.projects,
            "needs_operator": projects_needing_operator(state.projects),
            "escalations": open_escalations(state.projects, target=None),   # all open, for the desktop
            "admission": meter}


class NewProject(BaseModel):
    id: str
    goal: str = ""
    lead: str | None = None        # a session tag to nominate as lead (optional)


@app.post("/api/projects")
async def create_project(payload: NewProject, request: Request) -> dict[str, Any]:
    """Start a project from the UI — no terminal (Kyle's ask). Runs ``project new`` and, if a lead
    was picked, ``project nominate`` (which now wakes the nominee). Everything after — the lead's
    plan, your approval — flows through the surfaces already built."""
    pid = (payload.id or "").strip()
    if not pid or not all(c.isalnum() or c in "._-" for c in pid):
        raise HTTPException(status_code=400, detail="bad project id (letters, digits, . _ - only)")
    state: AppState = request.app.state.cond
    bus = str(state.settings.bus.script_path_resolved)
    new = await asyncio.to_thread(
        subprocess.run, [bus, "project", "new", pid, payload.goal or ""],
        capture_output=True, text=True, timeout=15, env=_project_subenv())
    if new.returncode != 0:
        return {"ok": False, "result": (new.stdout or new.stderr or "").strip()}
    nominated = ""
    if payload.lead:
        nom = await asyncio.to_thread(
            subprocess.run, [bus, "project", "nominate", pid, payload.lead],
            capture_output=True, text=True, timeout=15, env=_project_subenv())
        nominated = (nom.stdout or nom.stderr or "").strip()
    state.projects = await asyncio.to_thread(read_projects, state.coord_root)
    await state.hub.broadcast("projects", {"projects": state.projects})
    log.info("project created: %s (lead=%s)", pid, payload.lead or "-")
    return {"ok": True, "id": pid, "result": (new.stdout or "").strip(), "nominated": nominated}


class ProjectAction(BaseModel):
    notes: str | None = None       # for revise: what the lead should change


@app.post("/api/projects/{pid}/{action}")
async def project_action(pid: str, action: str, request: Request,
                         body: ProjectAction | None = None) -> dict[str, Any]:
    """Operator's plan-gate decision (Gate #1), made from the dashboard instead of a terminal.

    ``approve`` → the project goes ACTIVE (jobs may fan out — next slice). ``revise`` → the plan
    goes back to the lead with notes. Both shell to the same ``bus.sh project`` one-writer the
    fleet uses; Conductor never mutates the record directly.
    """
    if action not in ("approve", "revise"):
        raise HTTPException(status_code=404, detail="unknown action")
    if not pid or not all(c.isalnum() or c in "._-" for c in pid):
        raise HTTPException(status_code=400, detail="bad project id")
    state: AppState = request.app.state.cond
    args = [str(state.settings.bus.script_path_resolved), "project", action, pid]
    if action == "revise":
        args.append((body.notes if body else None) or "please revise")
    proc = await asyncio.to_thread(subprocess.run, args, capture_output=True, text=True,
                                   timeout=15, env=_project_subenv())
    # Re-read + broadcast so every open console reflects the decision immediately.
    state.projects = await asyncio.to_thread(read_projects, state.coord_root)
    await state.hub.broadcast("projects", {"projects": state.projects})
    log.info("project %s %s: %s", pid, action, (proc.stdout or "").strip() or proc.returncode)
    return {"ok": proc.returncode == 0,
            "result": (proc.stdout or "").strip() or (proc.stderr or "").strip()}


@app.post("/api/projects/{pid}/jobs/{jobid}/dispatch")
async def dispatch_job(pid: str, jobid: str, request: Request) -> dict[str, Any]:
    """Admission-controlled job dispatch (§5b). The lead REQUESTS; Conductor ADMITS by fleet-global
    load — this is the fox/henhouse control, so the throttle lives here and not in the lead's own
    hands. If admitted, it shells ``bus.sh project dispatch`` (which enforces the DAG: a job can't go
    until its deps are CONFIRMED). Placing the order is the bus layer's job; gating concurrency is
    ours."""
    for v, label in ((pid, "project id"), (jobid, "job id")):
        if not v or not all(c.isalnum() or c in "._-" for c in v):
            raise HTTPException(status_code=400, detail=f"bad {label}")
    state: AppState = request.app.state.cond
    # Per-project budget cap (§5c) first — a project at its ceiling holds new dispatch even if the
    # fleet has concurrency to spare. Measured spend, not an estimate.
    proj = next((p for p in state.projects if p["id"] == pid), None)
    if proj is not None:
        over_budget, why = state._spend_meter.would_exceed(proj)
        if over_budget:
            return {"ok": False, "admitted": False, "result": why,
                    "admission": state._dispatch_admission()[2]}
    ok, reason, meter = state._dispatch_admission()
    if not ok:
        # 429: not an error in the request, the fleet is just at capacity. Say why + the meter.
        return {"ok": False, "admitted": False, "result": reason, "admission": meter}
    proc = await asyncio.to_thread(
        subprocess.run,
        [str(state.settings.bus.script_path_resolved), "project", "dispatch", pid, jobid],
        capture_output=True, text=True, timeout=20, env=_project_subenv())
    state.projects = await asyncio.to_thread(read_projects, state.coord_root)
    await state.hub.broadcast("projects", {"projects": state.projects})
    log.info("project %s dispatch %s: %s", pid, jobid, (proc.stdout or "").strip() or proc.returncode)
    return {"ok": proc.returncode == 0, "admitted": True,
            "result": (proc.stdout or "").strip() or (proc.stderr or "").strip(),
            "admission": meter}


class EscalationAnswer(BaseModel):
    answer: str


@app.post("/api/projects/{pid}/escalations/{eid}/answer")
async def answer_escalation(pid: str, eid: str, payload: EscalationAnswer,
                            request: Request) -> dict[str, Any]:
    """Kyle answers a project escalation from his phone (the decision shield, slice 3). Shells
    ``bus.sh project answer`` — Conductor runs as its own (non-lead) tag, so the bus guard admits it
    for a Kyle-bound escalation and refuses were the answer routed wrongly. Unlike a decision, this
    isn't a keystroke into a picker — it's a recorded answer on the project the lead/worker reads."""
    for v, label in ((pid, "project id"), (eid, "escalation id")):
        if not v or not all(c.isalnum() or c in "._-" for c in v):
            raise HTTPException(status_code=400, detail=f"bad {label}")
    ans = (payload.answer or "").strip()
    if not ans:
        raise HTTPException(status_code=400, detail="answer is empty")
    state: AppState = request.app.state.cond
    proc = await asyncio.to_thread(
        subprocess.run,
        [str(state.settings.bus.script_path_resolved), "project", "answer", pid, eid, ans],
        capture_output=True, text=True, timeout=15, env=_project_subenv())
    state.projects = await asyncio.to_thread(read_projects, state.coord_root)
    await state.hub.broadcast("projects", {"projects": state.projects})
    log.info("escalation %s/%s answered: %s", pid, eid, (proc.stdout or "").strip() or proc.returncode)
    return {"ok": proc.returncode == 0,
            "result": (proc.stdout or "").strip() or (proc.stderr or "").strip()}


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
    # "None of the above" — typed into the picker's own free-text Other field. One entry
    # per question; None means "use answers[i]". Carried as text, never as a label,
    # because a label must match a captured option and this deliberately does not.
    free_text: list[str | None] | None = None


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
        raise HTTPException(status_code=409, detail={
            "code": "already_answered",
            "message": "that question is no longer pending — it was already answered",
        })

    session = state._session_for_decision(rec_dec)
    if session is None:
        # The asking session died while its picker was up. Answering would type into the
        # void — so don't; tell the user it isn't running and hand back the parked project
        # so the UI can offer a one-tap relaunch instead of a dead end (#4).
        proj = None
        cwd = rec_dec.get("cwd")
        if cwd:
            rp = os.path.realpath(cwd)
            for p in state.parked:
                if os.path.realpath(getattr(p, "project_dir", "") or "") == rp:
                    proj = p.project
                    break
        raise HTTPException(status_code=409, detail={
            "code": "session_not_running",
            "message": "the session that asked isn't running — relaunch it, then answer",
            "project": proj,
        })

    answers = [list(a) for a in payload.answers]
    if payload.free_text:
        if len(payload.free_text) != len(answers):
            raise HTTPException(status_code=400,
                                detail="free_text must have one entry per question")
        for i, txt in enumerate(payload.free_text):
            if txt is not None and txt.strip():
                # Replaces the selection for that question — the picker's Other field is
                # a choice, not an addition to one.
                answers[i] = [OTHER_TEXT + txt]
    try:
        keys = plan_keystrokes(rec_dec["questions"], answers)
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
        text=f"[picker] {answers}", why=f"answered via {client}",
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
    log.info("answered [%s]: %s -> keys %s", session.tag, answers, keys)
    return {"ok": True, "keys": keys}


@app.post("/api/decisions/{session_id}/decline")
async def decline_decision(session_id: str, request: Request) -> dict[str, Any]:
    """Decline to answer — a REAL answer, not a UI dismissal.

    ``Escape`` on the picker is measured (docs/DECISION_QUEUE.md) to produce
    *"User declined to answer questions"* in the session's transcript. So the Claude
    LEARNS it was declined and can proceed, re-ask, or take a default — which is the
    whole difference between this and quietly hiding the card. Hiding it would leave a
    session blocked forever on a question nobody ever told it had been passed on: a
    silent no-op, and a lie of omission.

    Sends ONE bare Escape via ``send_key_to_session`` and never
    ``send_keys_to_session``, which appends a Return — and Return on a picker SELECTS
    whatever the cursor happens to be sitting on, one option being "Disconnect".
    """
    state: AppState = request.app.state.cond
    rec_dec = next((d for d in state.decisions if d["session_id"] == session_id), None)
    if rec_dec is None:
        raise HTTPException(status_code=409, detail={
            "code": "already_answered",
            "message": "that question is no longer pending — it was already answered",
        })
    session = state._session_for_decision(rec_dec)
    if session is None:
        raise HTTPException(status_code=409, detail={
            "code": "session_not_running",
            "message": "the session that asked isn't running — nothing to decline",
        })

    client = request.client.host if request.client else "?"
    await asyncio.to_thread(
        attest, state.settings.bus.state_dir_resolved,
        target_pid=session.pid, target_tag=session.tag,
        text="[picker] DECLINED (Escape)", why=f"declined via {client}",
        source="conductor:decline_decision", actor=f"human:{client}",
    )
    ok = await asyncio.to_thread(
        send_key_to_session, key="Escape", pid=session.pid,
        terminal_pid=session.terminal_pid, title=session.title,
        window_title=session.window_title,
    )
    if not ok:
        raise HTTPException(
            status_code=502,
            detail="couldn't reach that session's window — decline it at the keyboard")
    await asyncio.to_thread(reap_decision, state.coord_root, session_id)
    state.decisions = [d for d in state.decisions if d["session_id"] != session_id]
    await state.hub.broadcast("decisions", {"decisions": state.decisions})
    log.info("declined [%s] — Escape sent", session.tag)
    return {"ok": True, "declined": True}


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
# ---- Fleet wind-down (the ordered shutdown; mirror of ⟳ Fleet recovery) ------
@app.post("/api/shutdown")
async def shutdown_begin(request: Request) -> dict[str, Any]:
    """Call a fleet wind-down: broadcast the ordered protocol + wake the sessions that can
    safely act on it. Sessions persist themselves and post a VERIFIED ack; none is closed here.
    Busy and question-open sessions are never woken (they get it when they pause)."""
    state: AppState = request.app.state.cond
    return await state.begin_winddown()


@app.post("/api/shutdown/clear")
async def shutdown_clear(request: Request) -> dict[str, Any]:
    """Cancel an in-progress wind-down and tell the fleet to resume normal work."""
    state: AppState = request.app.state.cond
    return await state.clear_winddown()


@app.post("/api/shutdown/close")
async def shutdown_close(request: Request) -> dict[str, Any]:
    """Close every session that has a VERIFIED wound-down ack (inject ``/exit``), then refresh
    the DR roster. Refuses to touch anything not acked — a session that has not provably
    persisted is left open and waited for. User-triggered only, from the shutdown panel."""
    state: AppState = request.app.state.cond
    return await state.close_wound_down()


@app.post("/api/shutdown/close-idle")
async def shutdown_close_idle(request: Request) -> dict[str, Any]:
    """Close the passive tail: un-acked IDLE ('flushing') sessions that never self-acked. Deliberate
    and eyes-open — these are NOT verified-clean (the UI warns). Still never touches busy or asking
    sessions. /exit ends them without deleting their working tree; the DR snapshot captures state."""
    state: AppState = request.app.state.cond
    return await state.close_idle_stragglers()


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
    state: AppState = request.app.state.cond
    if not _known_request_key(key, state.coord_root / "persist-requests"):
        raise HTTPException(status_code=400, detail="bad request key")
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
        "stale_cursors": state._stale_cursors,   # live but not reading its mail (image_gen)
        "collisions": state._collisions,
        "lost_rc": state._lost_rc,        # live-but-lost-/RC alarm (§3.4.1, rt1180)
        # If this is not ok, every button on this phone that types at a session is dead — the
        # wake, the answer, the wind-down close. Say so here rather than letting taps no-op.
        "x11": state._x11,                # can Conductor reach a display? (2026-08-05)
        "services": state.services.get("services", []),
        # Slim (card bodies deferred to /api/resources/<name>/card). This is the
        # phone's aggregate call over Tailscale, so it is the payload that benefits
        # most from not shipping 53.5 KB of static card text on every poll.
        "resources": state._resources_payload().get("resources", []),
        # Project Layer: only the operator-actionable subset (a plan awaiting approval, an empty
        # lead seat) — the phone is a needs-you console, not the full DAG view (slice 4).
        "projects": projects_needing_operator(state.projects),
        # Decision shield (slice 3): escalations that are Kyle's to decide — the denylist + severity
        # hatch + any the lead-timeout auto-escalated. Lead-framed, project-tagged, phone-answerable.
        "escalations": open_escalations(state.projects, target="kyle"),
        # A compact glance at EVERY project (slice 4b) — the phone's read-only Projects tab. Not the
        # full DAG (that's the desktop workbench); just enough to check in: state, progress, spend.
        "all_projects": [{
            "id": p["id"], "goal": p.get("goal", ""), "state": p.get("state"),
            "lead": p.get("lead"), "lead_offline": p.get("lead_offline", False),
            "job_counts": p.get("job_counts", {}), "spend": p.get("spend", 0),
            "ceiling": p.get("ceiling", 0), "spend_pct": p.get("spend_pct"),
            "over_budget": p.get("over_budget", False), "budget_warn": p.get("budget_warn", False),
            "open_kyle": p.get("open_kyle_escalations", 0), "needs": p.get("needs"),
        } for p in state.projects],
        "webpush": state._webpush_status(),   # can we actually page this phone? (2026-07-22)
        "winddown": state._winddown_payload(),  # fleet shutdown state (the 🛑 phone overlay)
        "counts": {
            "needs_you": (len(state.decisions) + len(state._push_requests)
                          + len(state._push_proposals) + len(state._persist_requests)
                          # ⚠️ COUNT EVERY PROJECT THE INBOX RENDERS, not just the plan gate.
                          # This counted approve-plan only, while the inbox showed a card for any
                          # project with a `needs` — so Kyle's phone read "nothing needs you" in
                          # green directly above an ieee-paper card. A green summary is a stronger
                          # signal than a card, so the disagreement resolves the wrong way: he
                          # trusts the header and the card becomes furniture he stops seeing.
                          + sum(1 for p in projects_needing_operator(state.projects))
                          + len(open_escalations(state.projects, target="kyle"))),
            "blocked": state.waiting.get("blocked_count", 0),
            "dead": sum(1 for s in state._silent if s.get("dead")),
            "collisions": len(state._collisions),
            "lost_rc": len(state._lost_rc),
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
        # Dead/closed sessions the phone can relaunch (Kyle's "reawaken a disconnected one").
        # `project` is the encoded dir the relaunch API takes; relaunch passes rc=true so a
        # revived session comes back remote-controlled in one tap.
        "parked": [
            {"project": p.project, "name": Path(p.project_dir).name, "tag": p.tag,
             "title": p.title, "last_activity_at": p.last_activity_at}
            for p in sorted(state.parked, key=lambda p: -p.last_activity_at)
        ],
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
        # Remote-control: the phone shows "on your phone" vs "reconnect", and needs the
        # session_id to call /check and /reconnect.
        "session_id": getattr(r, "session_id", "") or "",
        "bridged": read_bridge(r.pid)["bridged"],
        "rc_pending": (getattr(r, "session_id", "") or "") in state._rc_pending,
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
    live = next((r for r in state.sessions.values()
                 if r.status != Status.ENDED and os.path.realpath(r.project_dir) == real), None)
    if live is not None:
        # Name the live session, and if it merely LOST its /RC say so — that's the rt1180 case
        # (§3.4.1): it only LOOKS crashed, so the fix is reconnect, not a duplicate-making relaunch.
        member = _bare_tag(live.tag)
        try:
            bridged = read_bridge(live.pid)["bridged"]
        except Exception:
            bridged = True
        hint = ("" if bridged else
                " — it's ALIVE but lost its /RC (that's why it looks gone from the phone). Reconnect it, don't relaunch.")
        raise HTTPException(status_code=409, detail=f"[{member}] is already running in that folder{hint}")
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


# --- Reconstitute (DR capstone): rebuild the fleet from a roster on a new machine --------
def _reconstitute_roster(state: AppState, roster_path: str | None) -> dict:
    """Load the roster to plan from: an explicit path, else the restored fleet-backup's
    fleet-roster.json, else generate one live. On a fresh box the fleet-backup copy is the
    real one; on the live box a fresh generation matches the current fleet."""
    candidates = []
    if roster_path:
        candidates.append(Path(os.path.expanduser(roster_path)))
    candidates.append(Path(os.path.expanduser("~/Documents/GitHub/fleet-backup/fleet-roster.json")))
    for c in candidates:
        try:
            if c.is_file():
                return json.loads(c.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
    # Fall back to a live-generated roster (the current machine's fleet).
    projects_root = state.settings.scanner.claude_home_path / "projects"
    return build_roster(projects_root, state.settings.bus.tags)


def _live_cwds(state: AppState) -> set[str]:
    return {os.path.realpath(r.project_dir) for r in state.sessions.values()
            if r.status != Status.ENDED}


@app.get("/api/reconstitute")
async def reconstitute_plan(request: Request, roster: str | None = None) -> dict[str, Any]:
    """The fleet-rebuild plan: per roster session, what it takes to bring it back
    (live / present / clone / transcript-only / blocked) + blockers. Read-only."""
    state: AppState = request.app.state.cond
    r = await asyncio.to_thread(_reconstitute_roster, state, roster)
    return build_plan(r, _live_cwds(state))


class ReconstituteRequest(BaseModel):
    cwd: str                     # the roster session's cwd (the join key)
    roster: str | None = None    # optional explicit roster path


@app.post("/api/reconstitute/execute")
async def reconstitute_execute(payload: ReconstituteRequest, request: Request) -> dict[str, Any]:
    """Bring ONE session back: clone its repo if the cwd is absent, then relaunch
    ``claude --continue`` in a tracked window with ``/rc``. Refuses if a session is
    already live there, or if there's nothing to restore into.

    Transcript PLACEMENT is a prerequisite (extract the fleet-transcripts asset first, per
    RESTORE.md) — the plan flags a missing transcript; we don't silently launch a blank.
    """
    state: AppState = request.app.state.cond
    r = await asyncio.to_thread(_reconstitute_roster, state, payload.roster)
    target = os.path.realpath(payload.cwd)
    entry = next((e for e in r.get("sessions", [])
                  if os.path.realpath(e.get("cwd") or "") == target), None)
    if entry is None:
        raise HTTPException(status_code=404, detail="that cwd is not in the roster")
    from .reconstitute import plan_for
    plan = plan_for(entry, _live_cwds(state))

    if plan["status"] == "live":
        raise HTTPException(status_code=409, detail="a session is already running there")
    if plan["status"] == "blocked":
        raise HTTPException(status_code=409,
                            detail="nothing to restore into (no repo, no cwd, no transcript)")

    cwd = payload.cwd
    cloned = False
    if plan["status"] == "clone":
        if os.path.exists(cwd):
            raise HTTPException(status_code=409, detail="cwd already exists — not cloning over it")
        remote = entry.get("git_remote")
        args = ["git", "clone", remote, cwd]
        proc = await asyncio.to_thread(
            lambda: subprocess.run(args, capture_output=True, text=True, timeout=600))
        if proc.returncode != 0:
            raise HTTPException(status_code=500, detail=f"git clone failed: {proc.stderr.strip()[:300]}")
        cloned = True
        branch = entry.get("git_branch")
        if branch:
            await asyncio.to_thread(
                lambda: subprocess.run(["git", "-C", cwd, "checkout", branch],
                                       capture_output=True, text=True, timeout=60))
    elif plan["status"] == "transcript-only":
        os.makedirs(cwd, exist_ok=True)

    name = (entry.get("member") or os.path.basename(cwd.rstrip("/")) or "session")
    ok, detail = state.relaunch_parked(cwd, name, rc=True, rename=False)
    if not ok:
        raise HTTPException(status_code=500, detail=detail)
    return {"launched": True, "cwd": cwd, "name": name, "cloned": cloned,
            "status": plan["status"], "blockers": plan["blockers"], "detail": detail}


class PromptRoute(BaseModel):
    tag: str        # target session tag (bare/bracketed/@-prefixed all accepted)
    message: str    # delivered into that session's terminal AS A PROMPT (your words, verbatim)


@app.post("/api/prompt-route")
async def prompt_route(payload: PromptRoute, request: Request) -> dict[str, Any]:
    """Deliver an operator-composed message to a session as a live prompt (the `@tag message`
    feature). It's queued and injected once the target is quiet — never silently into a busy
    session — and recorded in the provenance ledger as human-driven, since you actually typed it.
    """
    state: AppState = request.app.state.cond
    tag = payload.tag.strip().lstrip("@").strip().strip("[]")
    message = payload.message.strip()
    if not tag or not message:
        raise HTTPException(status_code=400, detail="tag and message are required")
    rec = state._resolve_live_by_name(tag)
    if rec is None:
        raise HTTPException(status_code=404, detail=f"no live session for '{tag}'")
    actor = f"human:{request.client.host}" if request.client else "human"
    state._remote_prompt_seq += 1
    key = f"{tag}:{state._remote_prompt_seq}"
    state._remote_prompts[key] = {
        "tag": tag, "message": message, "queued": time.time(), "source": actor, "actor": actor,
    }
    busy = rec.status in _BUSY_STATUSES
    return {"queued": True, "tag": rec.tag,
            "delivery": "waiting for it to go idle" if busy else "on the next scan"}


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
        await ws.send_text(json.dumps({"kind": "resources", "payload": state._resources_payload()}))
        await ws.send_text(json.dumps({"kind": "push", "payload": {
            "requests": state._push_requests, "grants": state._push_grants,
            "proposals": state._push_proposals}}))
        await ws.send_text(json.dumps({"kind": "autonomy", "payload": {"windows": state._autonomy}}))
        await ws.send_text(json.dumps({"kind": "services", "payload": state.services}))
        await ws.send_text(json.dumps({"kind": "waiting", "payload": state.waiting}))
        await ws.send_text(json.dumps({"kind": "silent", "payload": {"silent": state._silent}}))
        await ws.send_text(json.dumps({"kind": "stale_cursors",
                                       "payload": {"stale_cursors": state._stale_cursors}}))
        await ws.send_text(json.dumps({"kind": "collisions", "payload": {"collisions": state._collisions}}))
        await ws.send_text(json.dumps({"kind": "lost_rc", "payload": {"lost_rc": state._lost_rc}}))
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
