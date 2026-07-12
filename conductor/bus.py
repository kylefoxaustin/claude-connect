"""BusAdapter — pluggable interface.

Three adapters ship:

* ``MarkdownBusAdapter`` — the reference claude-bus (``~/Documents/claude-bus/messages.md``).
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
from typing import Any, Protocol

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


def _bare_name(tag: str) -> str:
    """Reduce a bracketed tag to the bare name people type when mentioning it.

    ``[backend]`` -> ``backend``; ``[other:95emulator]`` -> ``95emulator``.
    The ``other:`` prefix is Conductor/bus.sh bookkeeping (any cwd outside the
    hardcoded whitelist), but in prose a session refers to itself by its plain
    name, so that's what we match on.
    """
    t = tag.strip().strip("[]")
    if t.startswith("other:"):
        t = t[len("other:"):]
    return t


def _iter_full_blocks(text: str):
    """Yield ``(ts_float, bracketed_tag, full_body)`` for each header block.

    Like ``parse_markdown_blocks`` but keeps the *entire* body (not truncated to
    80 chars) because mention detection has to scan the whole message.
    """
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
        try:
            ts = datetime.strptime(f"{date} {hm}", "%Y-%m-%d %H:%M").timestamp()
        except ValueError:
            continue
        yield ts, f"[{tag}]", "\n".join(body_lines).strip()


def build_mention_history(messages_path: Path) -> dict:
    """Sweep the live bus + every monthly archive and build a mention graph over time.

    The bus is broadcast-only (no ``@to`` addressing in practice), so a "who
    talks to whom" edge is *inferred*: an edge ``A -> B`` exists for a message
    sent by A whose body names session B. We count each message once per distinct
    mentioned session (a message that says "sizer" five times is one act of
    addressing sizer).

    Returns ``{"nodes": [...], "events": [...]}`` ordered by time:
      * ``nodes``  — ``{"tag", "first_seen", "count"}`` (count = messages sent)
      * ``events`` — ``{"ts", "source", "mentions": [tags]}`` in chronological
        order. The frontend replays these to grow the graph over time; a message
        with no mentions still reveals its source node (the session "came online").
    """
    bus_dir = messages_path.parent
    try:
        files = sorted(bus_dir.glob("messages*.md"))
    except OSError:
        files = []
    if messages_path.exists() and messages_path not in files:
        files.append(messages_path)

    raw: list[tuple[float, str, str]] = []
    for f in files:
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        raw.extend(_iter_full_blocks(text))
    raw.sort(key=lambda r: r[0])

    # Distinct sessions, in first-appearance order. [system] is bus bookkeeping
    # (rotation notices), not a participant — exclude it as a node and a mention.
    tags: list[str] = []
    seen: set[str] = set()
    for _ts, tag, _body in raw:
        if tag == "[system]" or tag in seen:
            continue
        seen.add(tag)
        tags.append(tag)

    name_map: dict[str, str] = {_bare_name(t).lower(): t for t in tags}
    names = sorted((n for n in name_map if n), key=len, reverse=True)
    pat = (
        re.compile(r"\b(" + "|".join(re.escape(n) for n in names) + r")\b", re.IGNORECASE)
        if names
        else None
    )

    events: list[dict] = []
    first_seen: dict[str, float] = {}
    counts: dict[str, int] = {}
    for ts, tag, body in raw:
        if tag == "[system]":
            continue
        mentions: list[str] = []
        if pat:
            found: set[str] = set()
            for m in pat.finditer(body):
                canon = name_map.get(m.group(1).lower())
                if canon and canon != tag:
                    found.add(canon)
            mentions = sorted(found)
        first_seen.setdefault(tag, ts)
        counts[tag] = counts.get(tag, 0) + 1
        for mt in mentions:
            first_seen.setdefault(mt, ts)
        # ``size`` (body char length) lets the frontend tell a terse "hello"
        # from a multi-KB bulk report and scale the pulse accordingly.
        events.append({"ts": ts, "source": tag, "mentions": mentions, "size": len(body)})

    nodes = [
        {"tag": t, "first_seen": first_seen.get(t, raw[0][0] if raw else 0.0), "count": counts.get(t, 0)}
        for t in tags
    ]
    return {"nodes": nodes, "events": events}


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


# Cache parsed bus headers keyed by (path, mtime) so compute_pending across
# many tags in one scan loop doesn't re-read the log file each time.
_HEADERS_CACHE: dict[Path, tuple[float, list[tuple[str, str]]]] = {}


def _read_log_headers(messages_path: Path) -> list[tuple[str, str]]:
    """Return ``[(ts_str, bracketed_tag), ...]`` for every header in the log.

    Cached by mtime so repeated calls within one scan are cheap.
    """
    if not messages_path.exists():
        return []
    try:
        mtime = messages_path.stat().st_mtime
    except OSError:
        return []
    cached = _HEADERS_CACHE.get(messages_path)
    if cached and cached[0] == mtime:
        return cached[1]
    try:
        text = messages_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    headers: list[tuple[str, str]] = []
    for line in text.splitlines():
        m = _HEADER_RE.match(line)
        if m:
            headers.append((f"{m.group(1)} {m.group(2)}", f"[{m.group(3)}]"))
    _HEADERS_CACHE[messages_path] = (mtime, headers)
    return headers


def _read_last_seen(state_dir: Path, tag: str) -> str | None:
    bare = tag.strip("[]")
    for name in (f"{tag}.last-seen", f"{bare}.last-seen"):
        try:
            return (state_dir / name).read_text().strip() or None
        except (FileNotFoundError, OSError):
            continue
    return None


def compute_pending(messages_path: Path, state_dir: Path, tag: str) -> int:
    """Compute pending message count for a tag without waiting for the destination
    session's ``bus.sh prompt-check`` to run.

    Mirrors ``bus.sh prompt-check``: counts headers with ``ts > <tag>.last-seen``
    and ``header_tag != [tag]``.

    When no ``<tag>.last-seen`` exists yet, we don't have a real read-baseline.
    Rather than return 0 — which silently hides a genuine backlog for a session
    that has never run ``prompt-check`` (never self-checked, never been pinged),
    the blind spot Kyle hit where prolific senders like ``95emulator`` showed no
    badge — we *infer* a baseline from the tag's own most recent SENT message: a
    session that just posted has demonstrably caught up to that moment, so only
    messages after it are genuinely unread. This gives an honest badge without
    dumping all historical traffic as "pending" on a brand-new session's first
    contact (a never-seen, never-sent tag still yields 0). The real ``last-seen``
    written by that session's first ``check`` supersedes this estimate.
    """
    me = tag if tag.startswith("[") else f"[{tag}]"
    headers = _read_log_headers(messages_path)
    last_seen = _read_last_seen(state_dir, tag)
    if not last_seen:
        # Implicit baseline = the tag's own latest sent-message timestamp.
        own = [ts for ts, ttag in headers if ttag == me]
        if not own:
            return 0  # never read, never sent — no basis to call anything unread
        last_seen = max(own)
    return sum(1 for ts, ttag in headers if ts > last_seen and ttag != me)


_TO_TOKEN_RE = re.compile(r"\bto:(\S+)")
_DIRECTED_BLOCKS_CACHE: dict[Path, tuple[float, list[tuple[str, str, frozenset[str]]]]] = {}


def _plain_name(tag: str) -> str:
    """Normalize a tag or a ``to:`` token to the plain name for matching.

    ``[other:qualcomm]`` / ``other:qualcomm`` / ``qualcomm`` all -> ``qualcomm``;
    ``[backend]`` -> ``backend``. So a message ``to:qualcomm`` matches the session
    whose tag is ``[other:qualcomm]``.
    """
    t = tag.strip().strip("[]")
    if t.lower().startswith("other:"):
        t = t[6:]
    return t.lower()


def _address_targets(first_body_line: str) -> frozenset[str]:
    """Plain names a message is explicitly addressed to (its leading ``to:x to:y —``
    list). Empty for an untargeted broadcast; ``all`` is kept but never matches a
    session name, so broadcasts don't count as *directed*."""
    head = first_body_line.split("—", 1)[0]
    if "to:" not in head:
        return frozenset()
    return frozenset(_plain_name(m) for m in _TO_TOKEN_RE.findall(head))


def _directed_blocks(messages_path: Path) -> list[tuple[str, str, frozenset[str]]]:
    """``[(ts_str, sender_bracket, address_targets), ...]`` for each message. mtime-cached."""
    if not messages_path.exists():
        return []
    try:
        mtime = messages_path.stat().st_mtime
    except OSError:
        return []
    cached = _DIRECTED_BLOCKS_CACHE.get(messages_path)
    if cached and cached[0] == mtime:
        return cached[1]
    try:
        lines = messages_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    blocks: list[tuple[str, str, frozenset[str]]] = []
    i = 0
    while i < len(lines):
        m = _HEADER_RE.match(lines[i])
        if not m:
            i += 1
            continue
        ts_str, sender = f"{m.group(1)} {m.group(2)}", f"[{m.group(3)}]"
        i += 1
        first_body = ""
        while i < len(lines) and not _HEADER_RE.match(lines[i]):
            if not first_body and lines[i].strip():
                first_body = lines[i]
            i += 1
        blocks.append((ts_str, sender, _address_targets(first_body)))
    _DIRECTED_BLOCKS_CACHE[messages_path] = (mtime, blocks)
    return blocks


# Above this many named recipients, a message is an ANNOUNCEMENT, not a question. 1-3 people
# is a conversation; 8 is a mailing list. Measured on the real bus: a quarter of all
# "directed" messages name 5+ recipients, and those are what were storming the fleet.
_WAKE_MAX_RECIPIENTS = 4


def directed_unread_all(
    messages_path: Path, state_dir: Path, tags: list[str]
) -> dict[str, dict[str, Any]]:
    """Per tag, the UNREAD messages *explicitly addressed to it* (``to:<tag>``).

    Distinct from ``compute_pending`` (all unread): this is the signal for
    auto-delivery — a message aimed at a specific session that the session hasn't
    read. Pure broadcasts (``to:all`` / no address line) and the tag's own messages
    are excluded, so waking on this can't spam every idle session on every broadcast.
    Same never-checked baseline as ``compute_pending``. One log parse for all tags.

    Returns ``{tag: {"count": int, "senders": [name], "latest_ts": str}}``.
    """
    out = {t: {"count": 0, "senders": [], "latest_ts": ""} for t in tags}
    if not tags:
        return out
    blocks = _directed_blocks(messages_path)
    if not blocks:
        return out
    for tag in tags:
        me = tag if tag.startswith("[") else f"[{tag}]"
        plain = _plain_name(tag)
        last_seen = _read_last_seen(state_dir, tag)
        if not last_seen:
            own = [ts for ts, snd, _ in blocks if snd == me]
            if not own:
                continue  # never read, never sent — no unread basis
            last_seen = max(own)
        count, latest, senders, wakeable = 0, "", set(), 0
        for ts, snd, targets in blocks:
            if ts <= last_seen or snd == me:
                continue
            if plain in targets:
                count += 1
                senders.add(_bare_name(snd))
                if ts > latest:
                    latest = ts
                # A message cc'd to half the fleet is an ANNOUNCEMENT wearing directed-mail
                # clothes. `to:a to:b to:c to:d to:e to:f` is not six people each blocking on
                # you — it's one person telling everyone something. Waking on it treats an
                # FYI as an interruption.
                #
                # This is why `docs` asked THREE TIMES to be exempted and why qualcomm got 12
                # keystroke injections in an hour: the fleet tag-ccs everyone on nearly every
                # broadcast, which defeats the directed/broadcast distinction entirely — and
                # exempting sessions one at a time treats the symptom.
                if len(targets - {"all"}) <= _WAKE_MAX_RECIPIENTS:
                    wakeable += 1
        out[tag] = {"count": count, "senders": sorted(senders), "latest_ts": latest,
                    # What auto-delivery may act on. `count` is what the badge shows —
                    # the human should still SEE the cc; they just shouldn't be woken for it.
                    "wakeable": wakeable}
    return out


def snapshot_history(messages_path: Path) -> tuple[list[BusEvent], int]:
    """Parse the full bus log once. Returns ``(all_events, count)``.

    Used by main.py at startup to seed ``bus_total`` and ``recent_events`` so
    the Bus tile reflects historical activity instead of starting at zero.
    """
    if not messages_path.exists():
        return [], 0
    try:
        text = messages_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return [], 0
    events = parse_markdown_blocks(text)
    return events, len(events)


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


def _active_tags_path(state_dir: Path) -> Path:
    return state_dir / "active-tags"


def active_tags_configured(state_dir: Path) -> bool:
    """True once the data-file whitelist exists (i.e. bus.sh has been migrated)."""
    return _active_tags_path(state_dir).exists()


def read_active_tags(state_dir: Path) -> list[str]:
    """Bracketed tags listed in the ``active-tags`` data file (one bare tag per
    line; blanks and ``#`` comments ignored). Empty if the file is absent."""
    try:
        lines = _active_tags_path(state_dir).read_text().splitlines()
    except OSError:
        return []
    out: list[str] = []
    for ln in lines:
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        out.append(ln if ln.startswith("[") else f"[{ln}]")
    return out


def set_active_tag(state_dir: Path, tag: str, active: bool, *, seed: list[str]) -> list[str]:
    """Add/remove ``tag`` in the active-tags data file; return the new bracketed
    list. Seeds from ``seed`` (the current active set) when the file is created,
    so migrating from the hardcoded whitelist preserves existing membership."""
    base = read_active_tags(state_dir) if active_tags_configured(state_dir) else list(seed)
    bare = tag.strip("[]")
    ordered: list[str] = []
    seen: set[str] = set()
    for t in (x.strip("[]") for x in base):
        if t and t not in seen:
            seen.add(t)
            ordered.append(t)
    if active and bare not in seen:
        ordered.append(bare)
    elif not active:
        ordered = [t for t in ordered if t != bare]
    state_dir.mkdir(parents=True, exist_ok=True)
    _active_tags_path(state_dir).write_text("\n".join(ordered) + "\n")
    return [f"[{t}]" for t in ordered]


def append_message(messages_path: Path, sender_tag: str, body: str) -> str:
    """Append a message to the markdown bus in bus.sh's exact format.

    Returns the timestamp written. Mirrors ``bus.sh send``: a blank line, the
    ``## YYYY-MM-DD HH:MM [tag]`` header, a blank line, then the body — so the
    MarkdownBusAdapter tails and emits it like any other message.
    """
    tag = sender_tag.strip().strip("[]") or "operator"
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    messages_path.parent.mkdir(parents=True, exist_ok=True)
    with messages_path.open("a", encoding="utf-8") as f:
        f.write(f"\n## {ts} [{tag}]\n\n{body.rstrip()}\n")
    return ts


def list_sender_tags(messages_path: Path) -> list[str]:
    """Distinct bracketed sender tags that have appeared in the bus log.

    A session that has *sent* a message is on the bus even if it has no
    ``<tag>.last-seen`` file — e.g. an ``[other:*]`` tag that isn't in bus.sh's
    auto-hook whitelist (so ``mark_seen`` never ran for it). Pairing this with
    ``list_known_tags`` lets such sessions still get a connection line.
    """
    seen: dict[str, None] = {}
    for _ts, tag in _read_log_headers(messages_path):
        seen.setdefault(tag, None)
    return list(seen)


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
                    # Emit every block whose end is bounded by a following header.
                    # The trailing block stays buffered because its body may still
                    # be mid-write (bus.sh emits header + body in separate echos).
                    last_header_pos = _last_header_start(text)
                    if last_header_pos is None:
                        self._buf = text
                    else:
                        complete = text[:last_header_pos]
                        self._buf = text[last_header_pos:]
                        for ev in parse_markdown_blocks(complete):
                            await self._enqueue(ev)
                elif self._buf and _last_header_start(self._buf) is not None:
                    # File stopped growing and a complete header sits in the
                    # buffer — the write has settled, so flush the final block
                    # instead of waiting for a future message to bound it.
                    for ev in parse_markdown_blocks(self._buf):
                        await self._enqueue(ev)
                    self._buf = ""
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
