"""Token history — every session's token spend, by day and project, for as long as Conductor has seen it.

The tile badge and the topbar sum (``tokens.py``) only ever covered LIVE sessions: close one and its
tokens left the total, restart Conductor and everything began at zero. Kyle (2026-10-29) wanted the
total kept, plus a history to look at and a time-lapse like the 🕸 bus one.

Every assistant record in ``~/.claude/projects/<proj>/<session>.jsonl`` (and the subagent transcripts
under it) carries a ``timestamp`` and a ``usage`` block, so the history is already on disk. This reads
it incrementally — transcripts are append-only, so each file is read from where we stopped, over
complete lines only — and buckets output/total tokens by local day and project.

⚠️ ONE REPLY IS WRITTEN AS SEVERAL RECORDS. Claude Code writes each content block of a reply
(thinking, text, each tool call) as its own line, and every one of them repeats the SAME ``usage``
under the same ``message.id``. Summing lines counted one reply up to five times: MEASURED on this
session's transcript 2026-10-29, 743 usage lines for 344 replies, 539K output tokens summed vs 225K
real. So a reply is counted once, by ``message.id``; if a later line carries larger numbers for the
same id, only the difference is added. The duplicates are adjacent, so we remember only the last few
ids per file.

PERSISTED, unlike the rest of Conductor, because the source is not permanent: Claude Code deletes
transcripts older than its cleanup period (30 days by default), and a history that forgets every
month is not a history. The cache holds only per-file offsets and per-day counts — no message
content — and it is rebuildable: delete it and the next scan re-reads whatever transcripts remain.
"""

from __future__ import annotations

import json
import os
import threading
import time
from collections import OrderedDict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

_KEYS = ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "output_tokens")
_TAIL_IDS = 8                  # duplicates of one reply are adjacent; a handful is plenty
_BLOCK = 8 << 20
# First-scan pacing. skippy's /home is a spinning disk under mq-deadline, which IGNORES io priority,
# so pacing is the only lever: an unpaced first scan of 6 GB took 145 s and pushed IO pressure to
# ~30% (avg60) — the same starvation that has recycled the desktop before. 8 MB then 0.4 s is
# ~20 MB/s: about five minutes, once, then the cache makes every later scan a stat() sweep.
FIRST_SCAN_THROTTLE = (8 << 20, 0.4)
CACHE_NAME = "token-history.json"
CACHE_VERSION = 1


def usage_records(chunk: bytes) -> Iterator[tuple[str | None, str | None, str | None, dict[str, int]]]:
    """Yield ``(message_id, timestamp, cwd, usage)`` for each complete line carrying a usage block.

    A cheap byte prefilter skips the (vast majority of) lines that cannot carry one, so a 6 GB
    projects tree costs a read, not a JSON parse of every line."""
    for line in chunk.split(b"\n"):
        if b'"usage"' not in line:
            continue
        try:
            o = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        msg = o.get("message") if isinstance(o, dict) else None
        u = msg.get("usage") if isinstance(msg, dict) else None
        if not isinstance(u, dict):
            continue
        clean = {k: (u.get(k) if isinstance(u.get(k), int) else 0) for k in _KEYS}
        mid = msg.get("id") if isinstance(msg.get("id"), str) else None
        ts = o.get("timestamp") if isinstance(o.get("timestamp"), str) else None
        cwd = o.get("cwd") if isinstance(o.get("cwd"), str) else None
        yield mid, ts, cwd, clean


class ReplyDedup:
    """Counts each reply once. ``delta(id, usage)`` returns what to ADD for this record."""

    def __init__(self, recent: dict[str, dict[str, int]] | None = None) -> None:
        self.recent: OrderedDict[str, dict[str, int]] = OrderedDict(recent or {})

    def delta(self, mid: str | None, usage: dict[str, int]) -> dict[str, int] | None:
        if mid is None:
            return usage                                  # no id: nothing to dedupe against
        prev = self.recent.get(mid)
        if prev is None:
            self.recent[mid] = dict(usage)
            if len(self.recent) > _TAIL_IDS:
                self.recent.popitem(last=False)
            return usage
        d = {k: max(0, usage[k] - prev.get(k, 0)) for k in _KEYS}
        if not any(d.values()):
            return None                                   # a repeat — already counted
        self.recent[mid] = {k: max(usage[k], prev.get(k, 0)) for k in _KEYS}
        return d


def _day(ts: str | None, fallback: float) -> str:
    if ts:
        try:
            return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone().strftime("%Y-%m-%d")
        except ValueError:
            pass
    return datetime.fromtimestamp(fallback).strftime("%Y-%m-%d")


def _project_from_dir(d: str) -> str:
    # "-home-kyle-Documents-GitHub-claude-connect" -> "claude-connect" is ambiguous (dashes are
    # both separators and name characters), so this is only the fallback when no record had a cwd.
    for marker in ("-GitHub-", "-Documents-", "-home-"):
        if marker in d:
            d = d.rsplit(marker, 1)[1]
    return d.strip("-") or "unknown"


class TokenHistory:
    """Incremental, persisted day × project token tally over a projects tree."""

    def __init__(self, projects_root: Path, cache_path: Path | None = None) -> None:
        self.projects_root = Path(projects_root)
        self.cache_path = cache_path
        self._lock = threading.Lock()
        # path -> {"ino", "off", "proj", "recent": {id: usage}, "days": {day: [out, total, replies]}}
        self.files: dict[str, dict[str, Any]] = {}
        self.scanned_at = 0.0
        self.scans = 0
        self._load()

    # --- persistence -----------------------------------------------------------------------
    def _load(self) -> None:
        if not self.cache_path:
            return
        try:
            d = json.loads(self.cache_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if not isinstance(d, dict) or d.get("version") != CACHE_VERSION or not isinstance(d.get("files"), dict):
            return
        self.files = {p: f for p, f in d["files"].items() if isinstance(f, dict) and isinstance(f.get("days"), dict)}

    def _save(self) -> None:
        if not self.cache_path:
            return
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.cache_path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps({"version": CACHE_VERSION, "files": self.files}), encoding="utf-8")
            tmp.replace(self.cache_path)
        except (OSError, TypeError, ValueError):
            pass

    # --- scanning --------------------------------------------------------------------------
    def scan(self, throttle_bytes: int = 0, pause: float = 0.0) -> bool:
        """Read whatever is new. Returns True if anything changed.

        ``throttle_bytes``/``pause``: after every that-many bytes read, sleep ``pause`` seconds, so a
        first scan of a large tree on a spinning disk yields to everything else on the box. Throttled
        reads also drop themselves from the page cache afterwards."""
        changed = False
        read_since_pause = 0
        try:
            paths = sorted(self.projects_root.glob("**/*.jsonl"))
        except OSError:
            return False
        for p in paths:
            sp = str(p)
            try:
                stt = p.stat()
            except OSError:
                continue
            with self._lock:
                f = self.files.get(sp)
            if f is not None and f.get("ino") == stt.st_ino and stt.st_size == f.get("off"):
                continue                                         # unchanged
            if f is None or f.get("ino") != stt.st_ino or stt.st_size < f.get("off", 0):
                # new, replaced, or shrunk: start this file over (its old contribution goes with it)
                f = {"ino": stt.st_ino, "off": 0, "proj": None, "recent": {}, "days": {}}
            try:
                with open(sp, "rb") as fh:
                    fh.seek(f["off"])
                    parts = []
                    while True:
                        b = fh.read(_BLOCK)
                        if not b:
                            break
                        parts.append(b)
                        read_since_pause += len(b)
                        if throttle_bytes and pause and read_since_pause >= throttle_bytes:
                            time.sleep(pause)
                            read_since_pause = 0
                    chunk = b"".join(parts)
                    if throttle_bytes:
                        # A one-off sweep of GBs must not evict what the rest of the box is using.
                        try:
                            os.posix_fadvise(fh.fileno(), 0, 0, os.POSIX_FADV_DONTNEED)
                        except (AttributeError, OSError):
                            pass
            except OSError:
                continue
            nl = chunk.rfind(b"\n")
            if nl == -1:
                continue
            complete = chunk[: nl + 1]
            dedup = ReplyDedup(f.get("recent"))
            days = {k: list(v) for k, v in f["days"].items()}
            proj = f.get("proj")
            for mid, ts, cwd, usage in usage_records(complete):
                if proj is None and cwd:
                    proj = os.path.basename(cwd.rstrip("/")) or cwd
                d = dedup.delta(mid, usage)
                if d is None:
                    continue
                b = days.setdefault(_day(ts, stt.st_mtime), [0, 0, 0])
                b[0] += d["output_tokens"]
                b[1] += sum(d.values())
                b[2] += 1 if d is usage else 0             # a new reply, not a top-up of one
            new = {"ino": stt.st_ino, "off": f["off"] + nl + 1,
                   "proj": proj or _project_from_dir(p.relative_to(self.projects_root).parts[0]),
                   "recent": dict(dedup.recent), "days": days}
            with self._lock:
                self.files[sp] = new
            changed = True
        with self._lock:
            self.scanned_at = time.time()
            self.scans += 1
        if changed:
            self._save()
        return changed

    # --- the view --------------------------------------------------------------------------
    def snapshot(self) -> dict[str, Any]:
        """``days``: sorted day list; ``projects``: totals, largest first; ``series``: day -> project ->
        [output, total, replies]; ``all_time``: grand totals. Pure counts — no content."""
        with self._lock:
            files = list(self.files.values())
            scanned_at, scans = self.scanned_at, self.scans
        series: dict[str, dict[str, list[int]]] = {}
        per_proj: dict[str, list[int]] = {}
        for f in files:
            proj = f.get("proj") or "unknown"
            for day, (o, t, r) in f["days"].items():
                b = series.setdefault(day, {}).setdefault(proj, [0, 0, 0])
                b[0] += o; b[1] += t; b[2] += r
                pp = per_proj.setdefault(proj, [0, 0, 0])
                pp[0] += o; pp[1] += t; pp[2] += r
        projects = [{"name": n, "output": v[0], "total": v[1], "replies": v[2]}
                    for n, v in sorted(per_proj.items(), key=lambda kv: -kv[1][0])]
        return {
            "days": sorted(series),
            "projects": projects,
            "series": series,
            "all_time": {"output": sum(p["output"] for p in projects),
                         "total": sum(p["total"] for p in projects),
                         "replies": sum(p["replies"] for p in projects)},
            "files": len(files),
            "scanned_at": scanned_at,
            "ready": scans > 0,
        }
