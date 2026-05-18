"""WebSocket hub — fans out scanner/bus updates to all connected browser clients."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import WebSocket

log = logging.getLogger(__name__)


class WSHub:
    def __init__(self) -> None:
        self._clients: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._clients.add(ws)

    async def disconnect(self, ws: WebSocket) -> None:
        async with self._lock:
            self._clients.discard(ws)

    async def broadcast(self, kind: str, payload: Any) -> None:
        msg = json.dumps({"kind": kind, "payload": payload})
        async with self._lock:
            stale: list[WebSocket] = []
            for ws in self._clients:
                try:
                    await ws.send_text(msg)
                except Exception:  # noqa: BLE001 — connection-level failures
                    stale.append(ws)
            for ws in stale:
                self._clients.discard(ws)
