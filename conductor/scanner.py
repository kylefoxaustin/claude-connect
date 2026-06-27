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

from .models import ParkedSession, SessionRecord, Status
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


def discover_parked_projects(
    projects_root: Path,
    tag_map: dict[str, str] | None,
    live_cwds: set[str],
    *,
    limit: int = 40,
) -> list[ParkedSession]:
    """Project dirs with on-disk transcripts but no live Claude process — the
    relaunch candidates for the dormant dock.

    For each project dir we read its newest transcript, resolve the cwd the
    session last ran in, and skip it when (a) a session is currently live in
    that cwd, (b) the folder no longer exists (can't ``claude --continue`` into
    a deleted dir), or (c) the transcript is missing/unreadable. Multiple
    project dirs can resolve to the same cwd (re-encoded over Claude versions);
    we keep only the most-recent per cwd. Newest first, capped at ``limit``.
    """
    by_cwd: dict[str, ParkedSession] = {}
    try:
        dirs = list(projects_root.iterdir())
    except OSError:
        return []
    for d in dirs:
        if not d.is_dir():
            continue
        jsonl = newest_jsonl(d)
        if jsonl is None:
            continue
        cwd = last_recorded_cwd(jsonl)
        if not cwd:
            continue
        real = os.path.realpath(cwd)
        if real in live_cwds:
            continue                      # a session is already running there
        if not os.path.isdir(real):
            continue                      # folder gone — nothing to relaunch into
        try:
            mtime = jsonl.stat().st_mtime
        except OSError:
            mtime = 0.0
        prev = by_cwd.get(real)
        if prev is not None and prev.last_activity_at >= mtime:
            continue                      # keep the most-recent transcript per cwd
        session_id, title, msg_count = parse_session_meta(jsonl)
        by_cwd[real] = ParkedSession(
            project=d.name,
            project_dir=real,
            title=title or os.path.basename(real.rstrip("/")) or real,
            tag=derive_tag(real, tag_map),
            session_id=session_id,
            last_activity_at=mtime,
            message_count=msg_count,
        )
    parked = sorted(by_cwd.values(), key=lambda p: p.last_activity_at, reverse=True)
    return parked[:limit]


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

# Harness-injected wrappers that ride along inside a user record but aren't part
# of what the human typed: the UserPromptSubmit/SessionStart system-reminders and
# the slash-command echo blocks. Stripped before measuring a prompt so (a) pure
# injections (nothing left) are dropped, and (b) a genuine prompt that merely has
# a reminder prepended keeps its real text + real length.
_HARNESS_WRAP_RE = re.compile(
    r"<system-reminder>.*?</system-reminder>"
    r"|<command-[a-z]+>.*?</command-[a-z]+>"          # command-name/message/args echo
    r"|<local-command-[a-z]+>.*?</local-command-[a-z]+>",  # local-command-stdout/caveat
    re.DOTALL,
)
_BARE_SLASH_RE = re.compile(r"^/\S+$")
_CONTINUATION_PREFIX = "This session is being continued from a previous conversation"


def _iso_to_epoch(s: object) -> float | None:
    """Parse Claude's ISO-8601 record timestamp (``...Z``) to a float epoch."""
    if not isinstance(s, str) or not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _human_prompt_text(msg: object) -> str | None:
    """The genuine human-typed text in a ``user`` record, or ``None`` if it isn't
    a real prompt.

    ``type:user`` records cover far more than what the human typed: tool-results
    fed back to the model, harness ``<system-reminder>`` / slash-command echo
    blocks, and the auto-compact "session is being continued…" summary. We keep
    only genuine prompts and return the *typed* text (wrappers stripped, so a
    prompt that merely has a reminder prepended keeps its real text + length).

    Dropped (→ ``None``): tool_result payloads; records that are nothing but
    harness wrappers; context-continuation summaries; bare slash-commands.
    """
    if not isinstance(msg, dict):
        return None
    content = msg.get("content")
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        parts = []
        for block in content:
            if not isinstance(block, dict):
                continue
            bt = block.get("type")
            if bt == "tool_result":
                return None  # synthetic user message carrying a tool result
            if bt == "text":
                parts.append(str(block.get("text", "")))
        text = "\n".join(parts)
    else:
        return None

    stripped = _HARNESS_WRAP_RE.sub("", text).strip()
    if not stripped:
        return None  # pure harness injection — no human text
    if stripped.startswith(_CONTINUATION_PREFIX):
        return None  # auto-compact continuation summary, not a typed prompt
    if _BARE_SLASH_RE.match(stripped):
        return None  # bare slash-command (/rc, /msg-check, …)
    return stripped


def _human_prompt_len(msg: object) -> int:
    """Length of the genuine human prompt text, or ``-1`` if not a real prompt."""
    t = _human_prompt_text(msg)
    return len(t) if t is not None else -1


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


def extract_turn_events(jsonl_path: Path) -> list[tuple[float, str, int, str | None, str]]:
    """Turn-level human↔Claude events from one transcript.

    Returns ``[(ts, kind, size, uuid, snippet), ...]`` where kind is ``"prompt"``
    (a genuine human message; ``uuid`` locates the record for drill-down,
    ``snippet`` is the first ~80 chars for the picker) or ``"reply"`` (the
    assistant's response, collapsed to ONE event at the moment it *starts*
    replying — a whole exchange is one prompt + one reply, not the thousands of
    streaming / tool sub-records; uuid None, snippet ""). Skips sidechain
    (subagent) and meta records.
    """
    out: list[tuple[float, str, int, str | None, str]] = []
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
                text = _human_prompt_text(rec.get("message"))
                if text is None:
                    continue  # tool_result / harness injection — not a human turn
                ts = _iso_to_epoch(rec.get("timestamp"))
                if ts is not None:
                    out.append((ts, "prompt", len(text), rec.get("uuid"), _short(text, 80)))
                    awaiting = True
            elif rt == "assistant" and awaiting:
                ts = _iso_to_epoch(rec.get("timestamp"))
                if ts is not None:
                    out.append((ts, "reply", _assistant_text_len(rec.get("message")), None, ""))
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
            for ts, kind, size, uuid, snippet in extract_turn_events(jp):
                if kind == "prompt":
                    # carry the locator + snippet so the frontend can list and drill in
                    events.append({
                        "ts": ts, "source": YOU_TAG, "mentions": [tag], "size": size, "kind": kind,
                        "session": jp.stem, "project": d.name, "uuid": uuid, "text": snippet,
                    })
                else:
                    events.append({"ts": ts, "source": tag, "mentions": [YOU_TAG], "size": size, "kind": kind})
    events.sort(key=lambda e: e["ts"])
    dropped = 0
    if len(events) > cap:
        dropped = len(events) - cap
        events = events[-cap:]  # keep the most recent
    return {"events": events, "tags": tags_seen, "dropped": dropped}


def _short(s: object, n: int = 70) -> str:
    return " ".join(str(s or "").split())[:n]


def _classify_tool(name: str, inp: object) -> dict:
    """Map an assistant ``tool_use`` block to a drill-down node.

    kind: ``file`` (Read/Edit/Write… — carries a path), ``agent`` (Agent/Task
    sub-agent spawn), or ``tool`` (everything else). label is a short human cue.
    """
    inp = inp if isinstance(inp, dict) else {}
    if name == "Bash":
        return {"kind": "tool", "tool": "Bash", "label": _short(inp.get("command"))}
    if name == "Read":
        path = inp.get("file_path", "")
        return {"kind": "file", "tool": name, "mode": "read", "path": path, "label": os.path.basename(path) or path}
    if name in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
        path = inp.get("file_path", "") or inp.get("notebook_path", "")
        return {"kind": "file", "tool": name, "mode": "write", "path": path, "label": os.path.basename(path) or path}
    if name in ("Grep", "Glob", "LS"):
        return {"kind": "tool", "tool": name, "label": _short(inp.get("pattern") or inp.get("query") or inp.get("path") or name)}
    if name in ("Agent", "Task"):
        label = inp.get("subagent_type") or inp.get("description") or "agent"
        return {"kind": "agent", "tool": name, "label": _short(label, 40), "desc": _short(inp.get("description"), 110)}
    return {"kind": "tool", "tool": name, "label": name}


def extract_exchange(jsonl_path: Path, uuid: str) -> dict | None:
    """Fine-grained drill-down of ONE human prompt → its tool/file/agent fan-out.

    Locates the prompt record by ``uuid`` and walks its exchange (forward until
    the next genuine human prompt, main thread only — sidechain sub-agent
    internals are out of scope for now), extracting every assistant ``tool_use``
    block as a timestamped event and tagging it with the matching ``tool_result``
    status. Returns ``{prompt, events, summary, duration_s}`` or ``None`` if the
    uuid isn't found.
    """
    try:
        lines = jsonl_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    recs: list[dict] = []
    for ln in lines:
        ln = ln.strip()
        if not ln:
            continue
        try:
            r = json.loads(ln)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(r, dict):
            recs.append(r)

    start = next((i for i, r in enumerate(recs) if r.get("uuid") == uuid), None)
    if start is None:
        return None
    prompt_rec = recs[start]
    prompt_text = _human_prompt_text(prompt_rec.get("message")) or ""
    prompt_ts = _iso_to_epoch(prompt_rec.get("timestamp"))

    events: list[dict] = []
    results: dict[str, bool] = {}  # tool_use_id -> is_error
    for r in recs[start + 1:]:
        if r.get("isSidechain"):
            continue
        if r.get("type") == "user" and _human_prompt_text(r.get("message")) is not None:
            break  # next human prompt — end of this exchange
        msg = r.get("message")
        if not isinstance(msg, dict):
            continue
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        ts = _iso_to_epoch(r.get("timestamp")) or prompt_ts
        for b in content:
            if not isinstance(b, dict):
                continue
            if b.get("type") == "tool_use":
                ev = _classify_tool(str(b.get("name", "")), b.get("input"))
                ev["id"] = b.get("id")
                ev["ts"] = ts
                events.append(ev)
            elif b.get("type") == "tool_result":
                results[b.get("tool_use_id")] = bool(b.get("is_error"))

    for ev in events:
        if ev.get("id") in results:
            ev["status"] = "error" if results[ev["id"]] else "ok"

    files = {e["path"] for e in events if e["kind"] == "file" and e.get("path")}
    summary = {
        "total": len(events),
        "tools": sum(1 for e in events if e["kind"] == "tool"),
        "files": len(files),
        "edits": sum(1 for e in events if e["kind"] == "file" and e.get("mode") == "write"),
        "agents": sum(1 for e in events if e["kind"] == "agent"),
    }
    duration = round(events[-1]["ts"] - prompt_ts, 1) if events and prompt_ts else 0.0
    return {
        "prompt": {"text": prompt_text[:240], "ts": prompt_ts},
        "events": events,
        "summary": summary,
        "duration_s": duration,
    }


def _walk_exchanges(jsonl_path: Path) -> list[dict]:
    """Every human prompt in a transcript + the tool/file/agent fan-out it
    triggered, in order. ``[{prompt:{text,ts,uuid}, events:[...]}, ...]``."""
    try:
        lines = jsonl_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    exchanges: list[dict] = []
    cur: dict | None = None
    results: dict[str, bool] = {}
    for ln in lines:
        ln = ln.strip()
        if not ln:
            continue
        try:
            r = json.loads(ln)
        except (json.JSONDecodeError, ValueError):
            continue
        if not isinstance(r, dict) or r.get("isSidechain"):
            continue
        rt = r.get("type")
        if rt == "user":
            text = _human_prompt_text(r.get("message"))
            if text is not None:
                cur = {"prompt": {"text": _short(text, 120), "ts": _iso_to_epoch(r.get("timestamp")),
                                  "uuid": r.get("uuid")}, "events": []}
                exchanges.append(cur)
                continue
            msg = r.get("message")
            if isinstance(msg, dict) and isinstance(msg.get("content"), list):
                for b in msg["content"]:
                    if isinstance(b, dict) and b.get("type") == "tool_result":
                        results[b.get("tool_use_id")] = bool(b.get("is_error"))
            continue
        if rt == "assistant" and cur is not None:
            msg = r.get("message")
            if not isinstance(msg, dict) or not isinstance(msg.get("content"), list):
                continue
            ts = _iso_to_epoch(r.get("timestamp")) or cur["prompt"]["ts"]
            for b in msg["content"]:
                if isinstance(b, dict) and b.get("type") == "tool_use":
                    ev = _classify_tool(str(b.get("name", "")), b.get("input"))
                    ev["id"] = b.get("id")
                    ev["ts"] = ts
                    cur["events"].append(ev)
    for ex in exchanges:
        for ev in ex["events"]:
            if ev.get("id") in results:
                ev["status"] = "error" if results[ev["id"]] else "ok"
    return exchanges


def extract_session_detail(jsonl_paths: list[Path], cap: int = 12000) -> dict:
    """The WHOLE working relationship for a session tag: every prompt across all
    its transcripts + the tool/file/agent events each triggered, time-ordered.

    Feeds the 🔬 drill-down's "watch a session explode outward in work" view.
    Each event is tagged with ``ex`` (its prompt's index) so the frontend can
    either replay the whole relationship or focus one exchange at a time. Capped
    at the most-recent ``cap`` events with a surfaced ``dropped`` count — and when
    trimming happens, prompts whose work fell off the front are dropped too, so
    the timeline doesn't open with a long stretch of prompts before any work.
    """
    all_ex: list[dict] = []
    for p in jsonl_paths:
        all_ex.extend(_walk_exchanges(p))
    all_ex.sort(key=lambda e: e["prompt"]["ts"] or 0.0)

    prompts: list[dict] = []
    events: list[dict] = []
    for i, ex in enumerate(all_ex):
        prompts.append({"i": i, "ts": ex["prompt"]["ts"], "text": ex["prompt"]["text"], "uuid": ex["prompt"]["uuid"]})
        for ev in ex["events"]:
            events.append({**ev, "ex": i})
    events.sort(key=lambda e: e["ts"] or 0.0)
    dropped = 0
    if len(events) > cap:
        dropped = len(events) - cap
        events = events[-cap:]
        # work was trimmed off the front — drop the now-orphaned prompts (whose
        # events are gone) so the replay doesn't start with a dead prompts-only
        # run. Keep a prompt if it still owns retained events, or is an in-window
        # no-work prompt (ts at/after the first surviving event).
        earliest = events[0]["ts"]
        retained_ex = {e["ex"] for e in events}
        prompts = [
            p for p in prompts
            if p["i"] in retained_ex or (earliest is not None and p["ts"] is not None and p["ts"] >= earliest)
        ]

    files = {e["path"] for e in events if e["kind"] == "file" and e.get("path")}
    summary = {
        "prompts": len(prompts),
        "total": len(events),
        "tools": sum(1 for e in events if e["kind"] == "tool"),
        "files": len(files),
        "edits": sum(1 for e in events if e["kind"] == "file" and e.get("mode") == "write"),
        "agents": sum(1 for e in events if e["kind"] == "agent"),
    }
    return {"prompts": prompts, "events": events, "summary": summary, "dropped": dropped}


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
