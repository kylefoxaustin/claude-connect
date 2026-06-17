"""SessionScanner — discover live Claude Code processes and their session jsonl files."""

from __future__ import annotations

import json
import logging
import os
import re
import time
from collections.abc import Iterable
from datetime import datetime
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
    """Mirror Claude Code's project-dir encoding.

    Claude sanitizes the absolute cwd into a single dir name under
    ``~/.claude/projects/`` by replacing every non-alphanumeric character with
    ``-`` (so the leading ``/`` becomes the leading dash, and ``/``, ``_``, ``.``,
    spaces, etc. all become ``-``). Older Claude versions only replaced ``/`` and
    left ``_``/``.`` intact, which is why stale dirs like ``…elm7_engine`` can
    coexist with current ``…elm7-engine`` dirs — we follow the current rule.
    """
    p = os.path.realpath(os.fspath(path))
    return re.sub(r"[^A-Za-z0-9]", "-", p)


def derive_tag(
    project_dir: str | os.PathLike[str],
    tag_map: dict[str, str] | None = None,
) -> str:
    """Return the claude-bus tag for a project dir.

    ``tag_map`` maps a directory path (``~`` allowed) to a bare tag name, e.g.
    ``{"~/code/my-api": "api"}`` — it should mirror the case-table in your
    ``bus.sh`` so Conductor labels tiles with the same tag the bus uses. It
    lives in ``settings.toml`` (local, gitignored), so no project-specific names
    are baked into the code. Anything unmapped falls back to
    ``[other:<basename>]``.
    """
    target = os.path.realpath(os.fspath(project_dir))
    for path, tag in (tag_map or {}).items():
        if os.path.realpath(os.path.expanduser(path)) == target:
            return tag if tag.startswith("[") else f"[{tag}]"
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


def last_recorded_cwd(jsonl_path: Path) -> str | None:
    """Return the most recent ``cwd`` recorded in a session jsonl, or None.

    Claude writes a ``cwd`` field on each record reflecting the session's
    *current* working directory. The jsonl itself stays in the project dir
    derived from the *launch* cwd — so when a session cd's elsewhere, reading
    this lets us still match it to its process by current cwd.
    """
    cwd: str | None = None
    for line in _tail_lines(jsonl_path):
        try:
            obj = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(obj, dict) and isinstance(obj.get("cwd"), str):
            cwd = obj["cwd"]
    return cwd


def build_cwd_index(projects_root: Path) -> dict[str, Path]:
    """Map ``realpath(recorded_cwd) -> newest jsonl`` across all project dirs.

    Used as a fallback when a process's current cwd doesn't resolve to an
    existing project dir (the session cd'd away from its launch dir, or the
    encoding differs). On collision keep the most recently modified jsonl.
    """
    index: dict[str, Path] = {}
    try:
        dirs = list(projects_root.iterdir())
    except OSError:
        return index
    for d in dirs:
        jsonl = newest_jsonl(d)
        if jsonl is None:
            continue
        cwd = last_recorded_cwd(jsonl)
        if not cwd:
            continue
        key = os.path.realpath(cwd)
        prev = index.get(key)
        try:
            if prev is None or jsonl.stat().st_mtime > prev.stat().st_mtime:
                index[key] = jsonl
        except OSError:
            index.setdefault(key, jsonl)
    return index


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


# --- human<->Claude turn extraction (🕸 History "human turns" layer) --------

YOU_TAG = "[you]"


def _iso_to_epoch(s: object) -> float | None:
    """Parse Claude's ISO-8601 record timestamp (``...Z``) to a float epoch."""
    if not isinstance(s, str) or not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _user_text_len(msg: object) -> int:
    """Length of genuine human-typed text in a ``user`` record's message, or
    ``-1`` if it isn't a real prompt (a tool_result payload, empty, etc.).

    ``type:user`` records cover BOTH human prompts and the synthetic user
    messages that carry tool results back to the model; only the former is a
    human turn. The discriminator: real prompts are plain text (string content,
    or ``text`` blocks) with no ``tool_result`` block.
    """
    if not isinstance(msg, dict):
        return -1
    content = msg.get("content")
    if isinstance(content, str):
        t = content.strip()
        return len(t) if t else -1
    if isinstance(content, list):
        has_text = False
        has_tool_result = False
        total = 0
        for block in content:
            if not isinstance(block, dict):
                continue
            bt = block.get("type")
            if bt == "tool_result":
                has_tool_result = True
            elif bt == "text":
                txt = str(block.get("text", ""))
                if txt.strip():
                    has_text = True
                    total += len(txt)
        return total if (has_text and not has_tool_result) else -1
    return -1


def _assistant_text_len(msg: object) -> int:
    """Length of the assistant's visible text (drives reply pulse size)."""
    if not isinstance(msg, dict):
        return 0
    content = msg.get("content")
    if isinstance(content, str):
        return len(content)
    total = 0
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                total += len(str(block.get("text", "")))
    return total


def extract_turn_events(jsonl_path: Path) -> list[tuple[float, str, int]]:
    """Turn-level human↔Claude events from one transcript.

    Returns ``[(ts, kind, size), ...]`` where kind is ``"prompt"`` (a genuine
    human message) or ``"reply"`` (the assistant's response, collapsed to ONE
    event at the moment it *starts* replying — so a whole exchange is one prompt
    + one reply, not the thousands of streaming / tool sub-records). Skips
    sidechain (subagent) and meta records.
    """
    out: list[tuple[float, str, int]] = []
    awaiting = False
    try:
        fh = jsonl_path.open("r", encoding="utf-8", errors="replace")
    except OSError:
        return out
    with fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
            if not isinstance(rec, dict) or rec.get("isSidechain") or rec.get("isMeta"):
                continue
            rt = rec.get("type")
            if rt == "user":
                n = _user_text_len(rec.get("message"))
                if n < 0:
                    continue  # tool_result or empty — not a human turn
                ts = _iso_to_epoch(rec.get("timestamp"))
                if ts is not None:
                    out.append((ts, "prompt", n))
                    awaiting = True
            elif rt == "assistant" and awaiting:
                ts = _iso_to_epoch(rec.get("timestamp"))
                if ts is not None:
                    out.append((ts, "reply", _assistant_text_len(rec.get("message"))))
                    awaiting = False
    return out


def collect_human_events(
    projects_root: Path,
    tag_map: dict[str, str] | None = None,
    cap: int = 8000,
) -> dict:
    """Merge human↔Claude turns across every transcript under ``projects_root``.

    Each event has the SAME shape as a bus event so the frontend renders it with
    no special path: a prompt is ``[you] → session``, a reply is
    ``session → [you]``. Sessions are keyed to their bus tag (via
    :func:`derive_tag` on the recorded cwd) so human edges land on the same nodes
    as the bus mention graph.

    Returns ``{"events": [...], "tags": [bracketed...], "dropped": int}`` —
    ``dropped`` counts oldest events trimmed past ``cap`` (surfaced so the UI can
    be honest about truncation rather than silently capping).
    """
    events: list[dict] = []
    tags_seen: list[str] = []
    seen_tag: set[str] = set()
    try:
        dirs = [d for d in projects_root.iterdir() if d.is_dir()]
    except OSError:
        dirs = []
    for d in dirs:
        try:
            jsonls = list(d.glob("*.jsonl"))
        except OSError:
            continue
        if not jsonls:
            continue
        cwd = None
        for jp in sorted(jsonls, key=lambda p: p.stat().st_mtime, reverse=True):
            cwd = last_recorded_cwd(jp)
            if cwd:
                break
        tag = derive_tag(cwd, tag_map) if cwd else f"[other:{d.name.rsplit('-', 1)[-1]}]"
        if tag not in seen_tag:
            seen_tag.add(tag)
            tags_seen.append(tag)
        for jp in jsonls:
            for ts, kind, size in extract_turn_events(jp):
                src, dst = (YOU_TAG, tag) if kind == "prompt" else (tag, YOU_TAG)
                events.append({"ts": ts, "source": src, "mentions": [dst], "size": size, "kind": kind})
    events.sort(key=lambda e: e["ts"])
    dropped = 0
    if len(events) > cap:
        dropped = len(events) - cap
        events = events[-cap:]  # keep the most recent
    return {"events": events, "tags": tags_seen, "dropped": dropped}


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

    def __init__(self, settings: ScannerSettings, tag_map: dict[str, str] | None = None):
        self.settings = settings
        self._tag_map = tag_map or {}
        self._cpu_samples: dict[int, float] = {}

    def scan(self) -> dict[str, SessionRecord]:
        projects_root = self.settings.claude_home_path / "projects"
        out: dict[str, SessionRecord] = {}
        cwd_index: dict[str, Path] | None = None  # built lazily on first miss

        for proc in self._iter_claude_processes():
            try:
                pid = proc.pid
                cwd = proc.cwd()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

            # Fast path: current cwd -> encoded project dir.
            session_dir = projects_root / encode_cwd(cwd)
            jsonl = newest_jsonl(session_dir)
            if jsonl is None:
                # Fallback: the session cd'd away from its launch dir (the jsonl
                # stays in the launch-dir folder), so match by the cwd recorded
                # inside each project's newest jsonl. Built once per scan.
                if cwd_index is None:
                    cwd_index = build_cwd_index(projects_root)
                jsonl = cwd_index.get(os.path.realpath(cwd))
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
                tag=derive_tag(cwd, self._tag_map),
                window_title=parse_custom_title(jsonl),
                jsonl_path=str(jsonl),
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
