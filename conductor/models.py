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

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        return d


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


@dataclass
class SkippyTile:
    """Placeholder tile for Skippy framework components (Mixtral, ChromaDB, ...)."""
    component_id: str
    label: str
    status: Status
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        return d
