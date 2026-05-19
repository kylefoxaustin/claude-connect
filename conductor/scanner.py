"""SessionScanner — discover live Claude Code processes and their session jsonl files."""

from __future__ import annotations

import json
import logging
import os
import time
from collections.abc import Iterable
from pathlib import Path

import psutil

from .models import SessionRecord, Status
from .settings import ScannerSettings

log = logging.getLogger(__name__)

# Terminal emulators we recognise when walking parent chains.
TERMINAL_NAMES = {
    "tilix", "gnome-terminal-server", "gnome-terminal", "alacritty",
    "kitty", "wezterm-gui", "wezterm", "xterm", "konsole", "terminator",
    "tmux", "screen",
}


def encode_cwd(path: str | os.PathLike[str]) -> str:
    """Mirror Claude Code's project-dir hashing: replace / with -, leading dash."""
    p = os.path.realpath(os.fspath(path))
    return "-" + p.lstrip("/").replace("/", "-")


# Claude-bus tag mapping (mirrors ~/.claude/bin/bus.sh case-table). Keys are
# absolute paths; expanded against $HOME at call time.
_BUS_TAG_TABLE: list[tuple[str, str]] = [
    ("~/Documents/GitHub/keyhole",                      "[backend]"),
    ("~/Documents/GitHub/keyhole-UI",                   "[frontend]"),
    ("~/Documents/GitHub/keyhole-sizer",                "[sizer]"),
    ("~/Documents/GitHub/personal-ai-framework",        "[docs]"),
    ("~/Documents/GitHub/personal-ai-assistant-sizer",  "[pai-sizer]"),
]


def derive_tag(project_dir: str | os.PathLike[str]) -> str:
    """Return the claude-bus tag for a project dir per the spec's case-table.

    Falls back to ``[other:<basename>]`` when no whitelisted dir matches.
    """
    target = os.path.realpath(os.fspath(project_dir))
    for path, tag in _BUS_TAG_TABLE:
        if os.path.realpath(os.path.expanduser(path)) == target:
            return tag
    return f"[other:{os.path.basename(target.rstrip('/'))}]"


def tag_to_state_basename(tag: str) -> str:
    """Return the unbracketed form of a tag (e.g. ``[backend]`` → ``backend``).

    Per the spec, bus-state files use the bracketed tag verbatim
    (``[backend].last-seen``), but ``bus.py``'s ``read_pending`` /
    ``list_known_tags`` also accept the unbracketed form as a fallback.
    """
    return tag.strip("[]")


def is_claude_process(proc: psutil.Process) -> bool:
    """Lenient match: cmdline mentions @anthropic-ai/claude-code or a `claude` script."""
    try:
        cmdline = proc.cmdline()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return False
    if not cmdline:
        return False
    joined = " ".join(cmdline)
    if "@anthropic-ai/claude-code" in joined:
        return True
    # Fallback: a node process whose argv[1] basename is `claude` or `cli.js` under claude-code.
    if cmdline[0].endswith(("node", "node.exe")):
        for arg in cmdline[1:]:
            if "claude-code" in arg or os.path.basename(arg) == "claude":
                return True
    # Direct invocation of a `claude` shim script.
    if os.path.basename(cmdline[0]) == "claude":
        return True
    return False


def find_terminal_pid(pid: int) -> int | None:
    """Walk parents until we hit a recognised terminal emulator. Return its PID, else None."""
    try:
        proc = psutil.Process(pid)
    except psutil.NoSuchProcess:
        return None
    for ancestor in proc.parents():
        try:
            name = ancestor.name()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        if name in TERMINAL_NAMES:
            return ancestor.pid
    return None


def newest_jsonl(session_dir: Path) -> Path | None:
    if not session_dir.is_dir():
        return None
    candidates = list(session_dir.glob("*.jsonl"))
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def _tail_lines(path: Path, max_bytes: int = 65536) -> list[str]:
    try:
        size = path.stat().st_size
    except OSError:
        return []
    with path.open("rb") as f:
        if size > max_bytes:
            f.seek(-max_bytes, os.SEEK_END)
            f.readline()  # discard partial line
        chunk = f.read()
    try:
        text = chunk.decode("utf-8", errors="replace")
    except Exception:
        return []
    return [line for line in text.splitlines() if line.strip()]


def parse_session_meta(jsonl_path: Path) -> tuple[str, str | None, int]:
    """Return (session_id, title_or_None, message_count_estimate).

    session_id = filename stem; title from newest `summary` record; count = total lines.
    """
    session_id = jsonl_path.stem
    title: str | None = None
    # Title: scan the tail for type=='summary'; full file scan would be wasteful.
    for line in reversed(_tail_lines(jsonl_path, max_bytes=131072)):
        try:
            rec = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if rec.get("type") == "summary" and isinstance(rec.get("summary"), str):
            title = rec["summary"]
            break
    # Message count: cheap estimate via line count of the file. For multi-MB files
    # a sampled estimate would be better, but jsonl files are typically <1MB.
    try:
        with jsonl_path.open("rb") as f:
            count = sum(1 for _ in f)
    except OSError:
        count = 0
    return session_id, title, count


def _head_lines(path: Path, max_bytes: int = 65536) -> list[str]:
    try:
        with path.open("rb") as f:
            data = f.read(max_bytes)
    except OSError:
        return []
    return [line for line in data.decode("utf-8", errors="replace").splitlines() if line.strip()]


def parse_custom_title(jsonl_path: Path) -> str | None:
    """Return the session's ``customTitle`` (set via /rename), newest wins, or None.

    Claude Code writes this same string to the terminal/window title, so it's the
    reliable hint for matching a session to its X11 window. The record is usually
    near the head (rename at session start) but a later /rename appends a fresh
    one near the tail — so we check the tail first, then fall back to the head.
    """
    def _find(lines: list[str]) -> str | None:
        for line in reversed(lines):
            try:
                rec = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
            ct = rec.get("customTitle")
            if isinstance(ct, str) and ct.strip():
                return ct.strip()
        return None

    return _find(_tail_lines(jsonl_path, max_bytes=131072)) or _find(_head_lines(jsonl_path))


def extract_preview(jsonl_path: Path, max_chars: int = 200) -> str:
    """Pull the most recent text content from the jsonl as a one-line preview."""
    for line in reversed(_tail_lines(jsonl_path, max_bytes=32768)):
        try:
            rec = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        msg = rec.get("message")
        if not isinstance(msg, dict):
            continue
        content = msg.get("content")
        text = ""
        if isinstance(content, str):
            text = content
        elif isinstance(content, list):
            parts = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    parts.append(str(block.get("text", "")))
            text = " ".join(parts)
        text = " ".join(text.split())  # collapse whitespace
        if text:
            return text[-max_chars:]
    return ""


def classify_status(mtime_age: float, *, alive: bool, low_cpu: bool) -> Status:
    if not alive:
        return Status.ENDED
    if mtime_age < 3:
        return Status.ACTIVE
    if mtime_age < 30:
        return Status.WARM
    if low_cpu and mtime_age >= 30:
        return Status.WAITING
    if mtime_age < 300:
        return Status.IDLE
    return Status.DORMANT


class SessionScanner:
    """One Claude per project dir (per project decision §12.2). Keyed by project_dir."""

    def __init__(self, settings: ScannerSettings):
        self.settings = settings
        self._cpu_samples: dict[int, float] = {}

    def scan(self) -> dict[str, SessionRecord]:
        projects_root = self.settings.claude_home_path / "projects"
        out: dict[str, SessionRecord] = {}

        for proc in self._iter_claude_processes():
            try:
                pid = proc.pid
                cwd = proc.cwd()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

            session_dir = projects_root / encode_cwd(cwd)
            jsonl = newest_jsonl(session_dir)
            if jsonl is None:
                continue

            session_id, title_from_summary, msg_count = parse_session_meta(jsonl)
            preview = extract_preview(jsonl)

            try:
                mtime = jsonl.stat().st_mtime
            except OSError:
                mtime = 0.0
            mtime_age = max(0.0, time.time() - mtime)

            cpu_pct = self._cpu_sample(proc)
            status = classify_status(mtime_age, alive=True, low_cpu=cpu_pct < 1.0)

            title = title_from_summary or Path(cwd).name

            record = SessionRecord(
                session_id=session_id,
                pid=pid,
                terminal_pid=find_terminal_pid(pid),
                project_dir=cwd,
                title=title,
                status=status,
                last_activity_at=mtime,
                message_count=msg_count,
                preview=preview,
                tag=derive_tag(cwd),
                window_title=parse_custom_title(jsonl),
            )
            # Decision §12.2: one Claude per project dir; on collision keep the most recent.
            existing = out.get(cwd)
            if existing is None or record.last_activity_at > existing.last_activity_at:
                out[cwd] = record

        return out

    def _iter_claude_processes(self) -> Iterable[psutil.Process]:
        for proc in psutil.process_iter(["pid"]):
            try:
                if is_claude_process(proc):
                    yield proc
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

    def _cpu_sample(self, proc: psutil.Process) -> float:
        """Non-blocking CPU% sample. First call seeds the counter; second returns the rate."""
        try:
            return proc.cpu_percent(interval=None)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return 0.0
