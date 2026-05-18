"""FastAPI app + uvicorn entry for Conductor.

Wires the SessionScanner, ActivityWatcher, BusAdapter, SkippyAdapter, and
WebSocket hub. Serves the vanilla-JS frontend at `/`.
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

from .activity import ActivityWatcher
from .bus import (
    BusAdapter,
    FakeBusAdapter,
    JSONLBusAdapter,
    MarkdownBusAdapter,
    list_known_tags,
    read_pending,
)
from .models import BusEvent, BusTopology, SessionRecord, Status
from .scanner import SessionScanner, encode_cwd, extract_preview, newest_jsonl
from .settings import Settings, load_settings
from .skippy import SkippyAdapter
from .windows import focus_session, wmctrl_available
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
        self.scanner = SessionScanner(settings.scanner)
        self.activity = ActivityWatcher()
        self.bus: BusAdapter = _build_bus_adapter(settings)
        self.skippy = SkippyAdapter(enabled=settings.skippy.enabled)
        self.hub = WSHub()

        self.sessions: dict[str, SessionRecord] = {}        # keyed by project_dir
        self.recent_events: deque[BusEvent] = deque(maxlen=RECENT_EVENTS_MAX)
        self.bus_total = 0

        self._scan_task: asyncio.Task | None = None
        self._activity_task: asyncio.Task | None = None
        self._bus_task: asyncio.Task | None = None

    async def start(self) -> None:
        await self.activity.start()
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

        # Mark missing sessions ENDED and start fade timer.
        for key, rec in list(self.sessions.items()):
            if key not in new_map and rec.status != Status.ENDED:
                rec.status = Status.ENDED
                rec.ended_at = now

        # Fold in new/updated sessions.
        for key, rec in new_map.items():
            self.sessions[key] = rec

        # Drop ended sessions whose fade window expired.
        expire = self.settings.ui.end_fadeout_seconds
        for key in list(self.sessions):
            r = self.sessions[key]
            if r.status == Status.ENDED and r.ended_at is not None and now - r.ended_at > expire:
                self.sessions.pop(key, None)

        # Hydrate per-session bus pending counts from ~/.claude/bus-state/<tag>.pending.
        state_dir = self.settings.bus.state_dir_resolved
        for r in self.sessions.values():
            if r.tag:
                r.pending_count = read_pending(state_dir, r.tag)

        # Topology for the markdown bus is implicit: every active tagged
        # session is a subscriber. Push it onto the adapter so /api/bus and
        # the connection-line drawing both see the same view.
        if isinstance(self.bus, MarkdownBusAdapter):
            subs: dict[str, list[str]] = {}
            for r in self.sessions.values():
                if r.status != Status.ENDED and r.tag:
                    subs.setdefault(r.tag, [])
            # Also surface tags seen by the bus that don't currently have a tile.
            for tag in list_known_tags(state_dir):
                subs.setdefault(tag, [])
            self.bus.set_topology(BusTopology(subscribers=subs))

        # Sync inotify watch set.
        projects_root = self.settings.scanner.claude_home_path / "projects"
        watch_dirs = []
        for r in self.sessions.values():
            if r.status == Status.ENDED:
                continue
            d = projects_root / encode_cwd(r.project_dir)
            if d.is_dir():
                watch_dirs.append(d)
        self.activity.sync_watched_dirs(watch_dirs)

        await self.hub.broadcast("sessions", self._sessions_payload())

    async def _activity_loop(self) -> None:
        queue = await self.activity.events()
        projects_root = self.settings.scanner.claude_home_path / "projects"
        while True:
            try:
                jsonl_path, preview = await queue.get()
            except asyncio.CancelledError:
                return
            # Find the session this jsonl belongs to.
            rec = None
            for r in self.sessions.values():
                if newest_jsonl(projects_root / encode_cwd(r.project_dir)) == jsonl_path:
                    rec = r
                    break
            if rec is None:
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

    # --- payloads ------------------------------------------------------------

    def _sessions_payload(self) -> dict[str, Any]:
        return {
            "sessions": [r.to_dict() for r in self.sessions.values()],
            "skippy": [t.to_dict() for t in self.skippy.tiles()],
            "fadeout_seconds": self.settings.ui.end_fadeout_seconds,
            "wmctrl_available": wmctrl_available(),
        }

    def _bus_payload(self) -> dict[str, Any]:
        # Per-tag pending counts pulled fresh so the bus tile badge stays accurate.
        state_dir = self.settings.bus.state_dir_resolved
        topology = self.bus.get_topology()
        pending_by_tag = {tag: read_pending(state_dir, tag) for tag in topology.subscribers}
        return {
            "total": self.bus_total,
            "recent": [e.to_dict() for e in list(self.recent_events)[-20:]],
            "topology": topology.to_dict(),
            "pending_by_tag": pending_by_tag,
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
    return {"ok": True, "version": "0.1.0"}


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
        focus_session, terminal_pid=rec.terminal_pid, title_hint=rec.title,
    )
    return {"focused": ok, "wmctrl_available": wmctrl_available()}


@app.post("/api/sessions/{session_id}/check")
async def check_bus(session_id: str, request: Request) -> dict[str, Any]:
    """Run `bus.sh check` for a session's tag: reads last 80 lines + clears pending."""
    state: AppState = request.app.state.cond
    rec = next((r for r in state.sessions.values() if r.session_id == session_id), None)
    if rec is None:
        raise HTTPException(status_code=404, detail="session not found")
    script = state.settings.bus.script_path_resolved
    if not script.exists():
        raise HTTPException(status_code=503, detail=f"bus script not found at {script}")
    proc = await asyncio.create_subprocess_exec(
        str(script), "check",
        cwd=rec.project_dir,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=5.0)
    except asyncio.TimeoutError:
        proc.kill()
        raise HTTPException(status_code=504, detail="bus.sh check timed out")
    # Refresh pending count immediately after check.
    rec.pending_count = read_pending(state.settings.bus.state_dir_resolved, rec.tag)
    await state.hub.broadcast("session", rec.to_dict())
    return {
        "ok": proc.returncode == 0,
        "tag": rec.tag,
        "pending_after": rec.pending_count,
        "stdout": (stdout_b or b"").decode("utf-8", errors="replace")[-4096:],
        "stderr": (stderr_b or b"").decode("utf-8", errors="replace")[-1024:],
    }


@app.get("/api/bus")
async def get_bus(request: Request) -> dict[str, Any]:
    state: AppState = request.app.state.cond
    return state._bus_payload()


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
