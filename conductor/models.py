"""Data models shared between scanner, watcher, bus, and WebSocket hub."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class Status(str, Enum):
    ACTIVE = "active"      # mtime < 3s
    WARM = "warm"          # 3s – 30s
    IDLE = "idle"          # 30s – 5m
    DORMANT = "dormant"    # > 5m
    WAITING = "waiting"    # alive, low CPU, jsonl quiet
    ENDED = "ended"        # process gone; tile fading


@dataclass
class SessionRecord:
    session_id: str
    pid: int
    terminal_pid: int | None
    project_dir: str
    title: str
    status: Status
    last_activity_at: float        # unix seconds
    message_count: int
    preview: str = ""
    ended_at: float | None = None  # set when status flips to ENDED
    tag: str = ""                  # claude-bus tag, e.g. "[backend]"
    pending_count: int = 0         # unread bus messages for this tag
    window_title: str | None = None  # session's customTitle (/rename); matches the X11 window title
    jsonl_path: str = ""           # resolved session jsonl (backend-only; for activity matching)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        d.pop("jsonl_path", None)  # internal; not needed by the frontend
        return d


@dataclass
class ParkedSession:
    """A previously-run session with on-disk history but no live process — a
    candidate the dormant dock can relaunch (``claude --continue``) in its folder.

    ``project`` is the encoded ``~/.claude/projects`` dir name (the path segment
    the relaunch API takes); ``project_dir`` is the real cwd to launch into.
    """
    project: str                 # encoded project-dir name (API path segment)
    project_dir: str             # real cwd to relaunch into
    title: str
    tag: str
    session_id: str
    last_activity_at: float      # unix seconds (newest transcript mtime)
    message_count: int
    # The transcript `--continue` will resume. Used to tally this session's token
    # usage (so the relaunch picker can sort by it) — stripped from the payload.
    jsonl_path: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class BusEvent:
    timestamp: float
    source_session: str
    destination_session: str   # session_id or "broadcast"
    topic: str
    payload_summary: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class BusTopology:
    """session_id -> list of topics it subscribes to."""
    subscribers: dict[str, list[str]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"subscribers": self.subscribers}
