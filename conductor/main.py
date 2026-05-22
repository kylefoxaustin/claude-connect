"""FastAPI app + uvicorn entry for Conductor.

Wires the SessionScanner, ActivityWatcher, BusAdapter, and WebSocket hub.
Serves the vanilla-JS frontend at `/`.
"""

from __future__ import annotations

import asyncio
import logging
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
    compute_pending,
    list_known_tags,
    list_sender_tags,
    read_active_tags,
    read_pending,
    set_active_tag,
    snapshot_history,
)
from .models import BusEvent, BusTopology, SessionRecord, Status
from .scanner import SessionScanner, encode_cwd, extract_preview, newest_jsonl
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

        # Sync inotify watch set.
        projects_root = self.settings.scanner.claude_home_path / "projects"
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

    # --- payloads ------------------------------------------------------------

    def _sessions_payload(self) -> dict[str, Any]:
        return {
            "sessions": [r.to_dict() for r in self.sessions.values()],
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
