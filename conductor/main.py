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
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import __version__
from .activity import ActivityWatcher
from .bus import (
    BusAdapter,
    FakeBusAdapter,
    JSONLBusAdapter,
    MarkdownBusAdapter,
    active_tags_configured,
    append_message,
    build_mention_history,
    compute_pending,
    list_known_tags,
    list_sender_tags,
    read_active_tags,
    read_pending,
    set_active_tag,
    snapshot_history,
)
from .gpu import gpu_state
from .models import BusEvent, BusTopology, ParkedSession, SessionRecord, Status
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
        self.gpu_dir = settings.bus.state_dir_resolved / "gpu"   # GPU reservation lease dir
        self.gpu: dict[str, Any] = {"available": False, "smi": None, "lease": None}
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
        # GPU tile: live nvidia-smi telemetry + the current reservation lease.
        self.gpu = await asyncio.to_thread(gpu_state, self.gpu_dir)
        await self.hub.broadcast("gpu", self.gpu)

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

    # --- payloads ------------------------------------------------------------

    def _sessions_payload(self) -> dict[str, Any]:
        sessions = []
        for r in self.sessions.values():
            d = r.to_dict()
            if r.jsonl_path:  # tally tokens from the transcript (incremental → cheap)
                d["tokens"] = self.token_accountant.usage_for(r.jsonl_path)
            sessions.append(d)
        return {
            "sessions": sessions,
            "parked": [p.to_dict() for p in self.parked],
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


@app.get("/api/health")
async def health() -> dict[str, Any]:
    return {"ok": True, "version": __version__}


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


@app.get("/api/gpu")
async def get_gpu(request: Request) -> dict[str, Any]:
    """Live GPU telemetry (nvidia-smi) + the current reservation lease, for the GPU tile."""
    state: AppState = request.app.state.cond
    return await asyncio.to_thread(gpu_state, state.gpu_dir)


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


@app.post("/api/relaunch")
async def relaunch(payload: RelaunchRequest, request: Request) -> dict[str, Any]:
    """Relaunch a parked (offline) session: open ``claude --continue`` in its
    folder in a tracked terminal. Optionally inject ``/rc`` and/or ``/rename``
    afterwards (both opt-in via ``[relaunch]`` settings; default is a clean
    resume with no injection).

    Resolves the encoded project dir → its newest transcript → the cwd that
    session last ran in, validates the dir is inside the projects root and still
    exists, and refuses if a session is already live there. Path-validated, no
    traversal. The actual spawn + post-launch keystroke injection is handled by
    ``AppState.relaunch_parked`` / ``_bootstrap_relaunched``.
    """
    state: AppState = request.app.state.cond
    projects_root = (state.settings.scanner.claude_home_path / "projects").resolve()
    pdir = (projects_root / payload.project).resolve()
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

    name = tag_to_state_basename(derive_tag(real, state.settings.bus.tags))
    rc = state.settings.relaunch.rc if payload.rc is None else payload.rc
    rename = state.settings.relaunch.rename if payload.rename is None else payload.rename
    ok, detail = state.relaunch_parked(real, name, rc, rename)
    if not ok:
        raise HTTPException(status_code=500, detail=detail)
    return {"launched": True, "name": name, "cwd": real, "rc": rc, "rename": rename, "detail": detail}


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
    await state.hub.connect(ws)
    try:
        # Send initial snapshot.
        import json
        await ws.send_text(json.dumps({"kind": "sessions", "payload": state._sessions_payload()}))
        await ws.send_text(json.dumps({"kind": "bus", "payload": state._bus_payload()}))
        await ws.send_text(json.dumps({"kind": "gpu", "payload": state.gpu}))
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
