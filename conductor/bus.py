"""BusAdapter — pluggable interface.

Three adapters ship:

* ``MarkdownBusAdapter`` — Kyle's claude-bus (``~/Documents/claude-bus/messages.md``).
  Append-only markdown of ``## YYYY-MM-DD HH:MM [tag]`` blocks. CWD-derived tag is
  the source; destination is always ``"broadcast"``; topic is empty.
* ``JSONLBusAdapter`` — generic JSONL log (one event per line). See
  ``_coerce_event`` for the accepted schema.
* ``FakeBusAdapter`` — synthetic events for development/demo.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path
from typing import Protocol

from .models import BusEvent, BusTopology

log = logging.getLogger(__name__)


class BusAdapter(Protocol):
    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    def stream_events(self) -> AsyncIterator[BusEvent]: ...
    def get_topology(self) -> BusTopology: ...


class JSONLBusAdapter:
    """Tails a JSONL log file. Robust to truncation, rotation, and missing file."""

    def __init__(self, path: Path, *, poll_interval: float = 0.5):
        self._path = path
        self._poll_interval = poll_interval
        self._queue: asyncio.Queue[BusEvent] = asyncio.Queue(maxsize=1024)
        self._topology = BusTopology()
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    async def start(self) -> None:
        self._stop.clear()
        self._task = asyncio.create_task(self._tail_loop(), name="bus-tail")

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            try:
                await asyncio.wait_for(self._task, timeout=2.0)
            except asyncio.TimeoutError:
                self._task.cancel()
            self._task = None

    def get_topology(self) -> BusTopology:
        return self._topology

    async def stream_events(self) -> AsyncIterator[BusEvent]:
        while True:
            ev = await self._queue.get()
            yield ev

    async def _tail_loop(self) -> None:
        offset = 0
        inode: int | None = None
        # Start at end-of-file so we don't replay history on every restart.
        if self._path.exists():
            try:
                st = self._path.stat()
                offset = st.st_size
                inode = st.st_ino
            except OSError:
                pass

        while not self._stop.is_set():
            try:
                if not self._path.exists():
                    await asyncio.sleep(self._poll_interval)
                    continue

                st = self._path.stat()
                if inode is not None and st.st_ino != inode:
                    # Rotated.
                    offset = 0
                    inode = st.st_ino
                elif st.st_size < offset:
                    # Truncated.
                    offset = 0

                if st.st_size > offset:
                    with self._path.open("rb") as f:
                        f.seek(offset)
                        chunk = f.read()
                        offset = f.tell()
                    if inode is None:
                        inode = st.st_ino
                    await self._consume_bytes(chunk)
            except OSError as e:
                log.debug("bus tail OSError: %s", e)

            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._poll_interval)
            except asyncio.TimeoutError:
                pass

    async def _consume_bytes(self, chunk: bytes) -> None:
        text = chunk.decode("utf-8", errors="replace")
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
            if not isinstance(obj, dict):
                continue
            if isinstance(obj.get("topology"), dict):
                # Merge topology updates.
                topo = obj["topology"]
                merged = dict(self._topology.subscribers)
                for k, v in topo.items():
                    if isinstance(v, list):
                        merged[str(k)] = [str(t) for t in v]
                self._topology = BusTopology(subscribers=merged)
                continue
            ev = _coerce_event(obj)
            if ev is None:
                continue
            try:
                self._queue.put_nowait(ev)
            except asyncio.QueueFull:
                try:
                    self._queue.get_nowait()
                    self._queue.put_nowait(ev)
                except asyncio.QueueEmpty:
                    pass


def _coerce_event(obj: dict) -> BusEvent | None:
    src = obj.get("source") or obj.get("source_session")
    dst = obj.get("destination") or obj.get("destination_session") or "broadcast"
    topic = obj.get("topic")
    if src is None or topic is None:
        return None
    payload = obj.get("payload", "")
    if isinstance(payload, (dict, list)):
        try:
            payload = json.dumps(payload)
        except (TypeError, ValueError):
            payload = str(payload)
    payload = str(payload)
    summary = payload[:80]
    ts = obj.get("timestamp", time.time())
    try:
        ts = float(ts)
    except (TypeError, ValueError):
        ts = time.time()
    return BusEvent(
        timestamp=ts,
        source_session=str(src),
        destination_session=str(dst),
        topic=str(topic),
        payload_summary=summary,
    )


# --- Markdown adapter (claude-bus) -----------------------------------------

# Header line: `## 2025-05-08 14:23 [backend]`
_HEADER_RE = re.compile(r"^##\s+(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2})\s+\[([^\]]+)\]\s*$")


def parse_markdown_blocks(text: str) -> list[BusEvent]:
    """Parse all complete `## ts [tag]` blocks from a chunk of markdown.

    A block runs from one header line to the next header (or EOF). Body text is
    stripped and truncated to 80 chars for ``payload_summary``.
    """
    out: list[BusEvent] = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        m = _HEADER_RE.match(lines[i])
        if not m:
            i += 1
            continue
        date, hm, tag = m.group(1), m.group(2), m.group(3)
        body_lines: list[str] = []
        i += 1
        while i < len(lines) and not _HEADER_RE.match(lines[i]):
            body_lines.append(lines[i])
            i += 1
        body = "\n".join(body_lines).strip()
        try:
            ts = datetime.strptime(f"{date} {hm}", "%Y-%m-%d %H:%M").timestamp()
        except ValueError:
            ts = time.time()
        out.append(BusEvent(
            timestamp=ts,
            source_session=f"[{tag}]",
            destination_session="broadcast",
            topic="",
            payload_summary=body[:80],
        ))
    return out


def read_pending(state_dir: Path, tag: str) -> int:
    """Read ``<tag>.pending`` from the bus-state dir for a given tag.

    Spec uses the bracketed tag verbatim as the filename stem
    (e.g. ``[backend].pending``); we also accept the unbracketed form as a
    defensive fallback.
    """
    bare = tag.strip("[]")
    for candidate in (state_dir / f"{tag}.pending", state_dir / f"{bare}.pending"):
        try:
            txt = candidate.read_text().strip()
        except (FileNotFoundError, OSError):
            continue
        try:
            return int(txt) if txt else 0
        except ValueError:
            return 0
    return 0


def list_known_tags(state_dir: Path) -> list[str]:
    """Tags that have ever been seen by the bus (presence of ``<tag>.last-seen``).

    Filenames are the bracketed tag verbatim — e.g. ``[backend].last-seen`` —
    so we strip the ``.last-seen`` suffix and use the stem as-is. We also
    accept unbracketed stems as a fallback, wrapping them in brackets for
    callers that expect the canonical form.
    """
    out: list[str] = []
    try:
        for p in state_dir.iterdir():
            if p.suffix != ".last-seen":
                continue
            stem = p.name[: -len(".last-seen")]
            if stem.startswith("[") and stem.endswith("]"):
                out.append(stem)
            else:
                out.append(f"[{stem}]")
    except (FileNotFoundError, OSError):
        return []
    return out


class MarkdownBusAdapter:
    """Tails ~/Documents/claude-bus/messages.md and emits one BusEvent per block."""

    def __init__(self, path: Path, *, poll_interval: float = 0.5):
        self._path = path
        self._poll_interval = poll_interval
        self._queue: asyncio.Queue[BusEvent] = asyncio.Queue(maxsize=1024)
        self._topology = BusTopology()
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._buf = ""

    async def start(self) -> None:
        self._stop.clear()
        self._task = asyncio.create_task(self._tail_loop(), name="md-bus-tail")

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            try:
                await asyncio.wait_for(self._task, timeout=2.0)
            except asyncio.TimeoutError:
                self._task.cancel()
            self._task = None

    def get_topology(self) -> BusTopology:
        # Topology is set externally by main.py based on active sessions; the
        # markdown bus has no explicit subscriber list of its own.
        return self._topology

    def set_topology(self, topology: BusTopology) -> None:
        self._topology = topology

    async def stream_events(self) -> AsyncIterator[BusEvent]:
        while True:
            yield await self._queue.get()

    async def _tail_loop(self) -> None:
        offset = 0
        inode: int | None = None
        if self._path.exists():
            try:
                st = self._path.stat()
                offset = st.st_size
                inode = st.st_ino
            except OSError:
                pass

        while not self._stop.is_set():
            try:
                if not self._path.exists():
                    await asyncio.sleep(self._poll_interval)
                    continue
                st = self._path.stat()
                if inode is not None and st.st_ino != inode:
                    offset = 0
                    inode = st.st_ino
                    self._buf = ""
                elif st.st_size < offset:
                    offset = 0
                    self._buf = ""

                if st.st_size > offset:
                    with self._path.open("rb") as f:
                        f.seek(offset)
                        chunk = f.read()
                        offset = f.tell()
                    if inode is None:
                        inode = st.st_ino
                    text = self._buf + chunk.decode("utf-8", errors="replace")
                    # Split off the trailing partial block (no terminating header
                    # yet) and keep it buffered for the next poll.
                    last_header_pos = _last_header_start(text)
                    if last_header_pos is None:
                        # No headers in chunk yet; keep buffering.
                        self._buf = text
                    else:
                        complete = text[:last_header_pos]
                        self._buf = text[last_header_pos:]
                        for ev in parse_markdown_blocks(complete):
                            await self._enqueue(ev)
            except OSError as e:
                log.debug("markdown bus tail OSError: %s", e)

            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._poll_interval)
            except asyncio.TimeoutError:
                pass

    async def _enqueue(self, ev: BusEvent) -> None:
        try:
            self._queue.put_nowait(ev)
        except asyncio.QueueFull:
            try:
                self._queue.get_nowait()
                self._queue.put_nowait(ev)
            except asyncio.QueueEmpty:
                pass


def _last_header_start(text: str) -> int | None:
    """Return the offset of the last `## ts [tag]` header line in `text`, or None."""
    last = None
    pos = 0
    for line in text.splitlines(keepends=True):
        if _HEADER_RE.match(line):
            last = pos
        pos += len(line)
    return last


class FakeBusAdapter:
    """Synthetic-event adapter for development/demo when no real bus is wired up."""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[BusEvent] = asyncio.Queue()
        self._topology = BusTopology(subscribers={})
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    async def start(self) -> None:
        self._stop.clear()
        self._task = asyncio.create_task(self._loop(), name="fake-bus")

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            try:
                await asyncio.wait_for(self._task, timeout=1.0)
            except asyncio.TimeoutError:
                self._task.cancel()
            self._task = None

    def get_topology(self) -> BusTopology:
        return self._topology

    async def stream_events(self) -> AsyncIterator[BusEvent]:
        while True:
            yield await self._queue.get()

    async def _loop(self) -> None:
        i = 0
        while not self._stop.is_set():
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=4.0)
                return
            except asyncio.TimeoutError:
                pass
            i += 1
            self._queue.put_nowait(BusEvent(
                timestamp=time.time(),
                source_session="demo-session",
                destination_session="broadcast",
                topic="demo",
                payload_summary=f"synthetic event #{i}",
            ))
