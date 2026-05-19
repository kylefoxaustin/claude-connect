# Conductor — Claude Code Multi-Session Dashboard

> A local browser-based dashboard for monitoring and controlling concurrent Claude Code sessions on a single workstation.

## Project name
Working name: **Conductor**. Other candidates: FlightDeck, Hivemind, Choir, Watchtower. Rename freely.

## Owner
Kyle Fox · Skippy (Ubuntu 22.04, RTX 5090) · personal-tools repo

---

## 1. Goals (priority order)

| # | Capability | Phase |
|---|---|---|
| 1 | Auto-discover active Claude Code sessions on the local machine | MVP |
| 2 | Render each session as a tile with the title from `/rename` | MVP |
| 3 | Active vs. idle indicator per tile (traffic-light style) | MVP |
| 4 | Auto-rescan on a configurable interval (default 3s) with manual refresh | MVP |
| 5 | Live activity preview — squashed scrolling text inside each tile | Phase 2 |
| 6 | "Bus" tile showing message bus state with new-message notification badge | Phase 2 |
| 7 | SVG connection lines from Bus tile to participating Claude tiles | Phase 3 |
| 8 | Double-click a tile → focus the underlying terminal window | Phase 3 |

## 2. Non-goals

- Cross-machine / cross-host monitoring (single workstation only).
- Modifying or proxying Claude Code itself. Conductor is read-only / observation-side.
- Persistent metrics database. In-memory state only; restart-clean is fine.
- Authentication. Listens on `127.0.0.1` only.

---

## 3. Architecture

```
┌─────────────────────────── Browser (localhost:8765) ──────────────────────────┐
│                                                                                │
│   React / vanilla-JS frontend                                                  │
│   ├─ Tile grid (Claude sessions + Bus tile)                                    │
│   ├─ SVG overlay for connection lines                                          │
│   └─ WebSocket client → live updates                                           │
│                                                                                │
└──────────────────────────────────┬─────────────────────────────────────────────┘
                                   │ WebSocket + REST
┌──────────────────────────────────┴─────────────────────────────────────────────┐
│                                                                                │
│   FastAPI backend (Python, uvicorn)                                            │
│   ├─ /api/sessions       GET — current session inventory                       │
│   ├─ /api/sessions/{id}  POST {action: "focus"} — bring terminal forward       │
│   ├─ /api/bus            GET — bus state + recent events                       │
│   ├─ /ws                 WebSocket — push session/bus updates                  │
│   │                                                                            │
│   ├─ SessionScanner      psutil-driven, discovers Claude PIDs every N seconds  │
│   ├─ ActivityWatcher     watchdog/inotify on session jsonl files               │
│   ├─ WindowMapper        wmctrl-based PID→window resolution                    │
│   └─ BusBridge           subscribes to Kyle's existing message bus             │
│                                                                                │
└────────────────────────────────────────────────────────────────────────────────┘
```

## 4. Stack

- **Backend:** Python 3.11+, FastAPI, uvicorn, `psutil`, `watchdog`, `websockets`. Same shape as Kyle's video-transcription system; no new muscle to learn.
- **Frontend:** Plain HTML + vanilla JS + a tiny CSS framework (Pico.css or similar). React is acceptable but overkill — the UI is ~6 components.
- **Build/run:** `uv` or `pip` for Python; static frontend served by FastAPI itself. Single `make run` invocation, single port. No Docker needed for v1.
- **System deps:** `wmctrl`, `xdotool`. Both are `apt install` one-liners.

---

## 5. Session discovery — the meat of MVP

### 5.1 Discovery algorithm

```
every SCAN_INTERVAL seconds:
    1. enumerate processes via psutil where cmdline contains "claude" and the
       binary path resolves to the Claude Code CLI (filter out greps, editors).
    2. for each candidate PID:
         a. cwd = /proc/<pid>/cwd
         b. encoded_cwd = Claude Code's directory-hashing scheme
            (discover empirically: `ls ~/.claude/projects/` and inspect)
         c. session_dir = ~/.claude/projects/<encoded_cwd>/
         d. active_jsonl = most-recently-modified *.jsonl in session_dir
         e. parse jsonl for: session_id, rename_title, created_at,
            last_message_at, message_count
    3. walk parent chain (PPid in /proc/<pid>/status) until we hit a known
       terminal emulator (tilix, gnome-terminal, alacritty, kitty, wezterm).
       Capture (terminal_pid, terminal_cmd) for window mapping.
    4. emit SessionRecord {
         session_id, pid, terminal_pid, project_dir, title,
         status, last_activity_at, message_count
       }
```

### 5.2 Title resolution

`/rename` is an internal Claude Code command. The renamed title is persisted in session state. **Discovery task for Claude Code at build time:**

1. Run `/rename foo` in a test Claude session.
2. `find ~/.claude -newer /tmp/.timestamp -type f` to find what was written.
3. Parse the file. Document the format in `docs/claude-storage.md`.

Likely candidates: `~/.claude/projects/<hash>/<session-id>.jsonl` containing rename events as message records, OR a sidecar `metadata.json`. Detect at runtime; fall back to project dir name if title not found.

### 5.3 Activity / idle classification

```
status = case file_mtime_age:
    < 3s        → "active"  (green, animated)
    3s – 30s    → "warm"    (yellow)
    30s – 5min  → "idle"    (gray)
    > 5min      → "dormant" (dim gray)

if process is running AND CPU% < 1% AND no jsonl writes in 30s:
    → "waiting" (blue, "awaiting user input")
```

Watcher uses inotify (`watchdog` library) — no polling on the file content itself, just `mtime` events.

---

## 6. Live activity preview (Phase 2)

The terminal output is not directly accessible from another process. **Use the jsonl stream instead:**

- Tail the active session's jsonl.
- For each new message record, extract its text content.
- Push the last ~200 chars over WebSocket.
- Frontend renders inside the tile at ~50% font size with `overflow: hidden`, auto-scrolling.

Result: a "ghost preview" of recent conversation without any terminal-scraping shenanigans. Squashed but legible-enough to confirm activity is happening.

---

## 7. Bus tile (Phase 2) — wired to claude-bus

The default adapter is `MarkdownBusAdapter`, which integrates with Kyle's
existing **claude-bus** (full spec in `docs/claude-bus.md`):

- **Log:** append-only markdown at `~/Documents/claude-bus/messages.md`,
  one block per message: `## YYYY-MM-DD HH:MM [tag]\n\n<body>`.
- **Tags** are auto-derived from each session's CWD per `bus.sh`'s case-table.
  `BusEvent.source_session` carries the bracketed tag (e.g. `"[backend]"`);
  `destination_session` is always `"broadcast"`; `topic` is empty.
- **Pending counts** come from `~/.claude/bus-state/<basename>.pending`. Conductor
  reads these directly and shows a 📬 badge on each session tile (sum across
  all tags drives the bus-tile badge).
- **Topology** is implicit: every active session whose tag is recognised is a
  subscriber. Connection lines are drawn from the bus tile to each tile by tag.
- **Click** the 📬 badge on a tile → Conductor invokes `bus.sh check` from that
  session's project_dir (which clears its `<tag>.pending` and marks seen).

`JSONLBusAdapter` and `FakeBusAdapter` remain for non-claude-bus deployments;
select via `[bus] adapter = "markdown" | "jsonl" | "fake"` in `settings.toml`.

```python
class BusAdapter(Protocol):
    async def stream_events(self) -> AsyncIterator[BusEvent]: ...
    def get_topology(self) -> BusTopology: ...

@dataclass
class BusEvent:
    timestamp: float
    source_session: str        # tag (markdown bus) or session_id (jsonl bus)
    destination_session: str   # always "broadcast" for markdown bus
    topic: str                 # always "" for markdown bus
    payload_summary: str       # first ~80 chars of body

@dataclass
class BusTopology:
    subscribers: dict[str, list[str]]   # tag -> topics (topics empty for md bus)
```

The Bus tile renders:
- Total messages observed since startup
- Aggregate-pending badge (sum of all `<tag>.pending` files)
- Last 5 events as a feed (`HH:MM:SS [tag]: <body...>`)
- Click → expands into a modal with full event log

---

## 8. Connection lines (Phase 3)

- SVG overlay on the tile grid.
- For each session subscribed to the bus, draw a thin line from the bus tile center to the session tile center.
- Animate with a flowing-dash effect when an event flows along that line.
- Use `BusTopology.subscribers` to determine connectivity.
- Recompute line endpoints on window resize (use `ResizeObserver`).

---

## 9. Terminal focus (Phase 3) — the gotcha

### Problem
`wmctrl -a` focuses windows, not tabs within windows. If five Claudes live in five tabs of one Tilix window, focus only tells you which window — not which tab.

### Solution: tracked launcher
Provide a `claude-tracked` wrapper that opens each session in its **own Tilix window** with a unique X11 window title:

```bash
#!/usr/bin/env bash
# /usr/local/bin/claude-tracked
NAME="${1:?usage: claude-tracked <name> [claude-args...]}"; shift
exec tilix \
  --title "claude:${NAME}" \
  -- bash -c "claude $*; exec bash"
```

Then:
- `WindowMapper` shells out to `wmctrl -lp` and matches windows by title pattern `claude:*` cross-referenced with PID.
- Focus action: `wmctrl -a "claude:${name}"`.
- Document this in the README — using Conductor without `claude-tracked` means tile→focus is best-effort.

### Fallback
If `claude-tracked` wasn't used: walk PID tree to find the terminal emulator PID, find any window owned by that PID via `wmctrl -lp`, focus it. Won't switch tabs, but at least raises the right window.

---

## 10. UI — tile spec

Each tile is ~280×200 px, grid-tiled with CSS grid (auto-fill, gap 16px). Contents:

```
┌────────────────────────────────┐
│ ●  keyhole-yolo            ⏵   │  ← status dot, title from /rename, focus icon
│ /home/kyle/code/keyhole         │  ← project dir, dimmed
│                                │
│ ┌────────────────────────────┐ │
│ │ ...running yolo training   │ │  ← squashed activity preview
│ │ at epoch 4/12, loss 0.341  │ │
│ │ ...                        │ │
│ └────────────────────────────┘ │
│                                │
│  msgs: 47   ⏱ 2s ago           │  ← message count, last activity
└────────────────────────────────┘
```

Status dot colors map to states from §5.3. Pulsing animation on `active`. Tile border tints to match status.

The Bus tile uses a distinct visual treatment (different shape/color) to read as "infrastructure" rather than a peer Claude.

---

## 11. Implementation phases

| Phase | Deliverable | Effort |
|---|---|---|
| 0 | Project skeleton, FastAPI hello, frontend served at `/` | 1 hr |
| 1 | Session scanner + tile grid + status colors + auto-rescan | 1 evening |
| 2 | Live activity preview + jsonl tail + WebSocket push | 1 evening |
| 3 | Bus adapter interface + Bus tile + notification badge | 1 evening |
| 4 | Connection lines + flow animation | half evening |
| 5 | `claude-tracked` wrapper + window mapper + focus action | half evening |
| 6 | Polish: settings panel (rescan interval, display options), dark theme | as desired |

Total realistic budget: ~2–3 evenings of Claude-Code-assisted coding for phases 0–5.

---

## 12. Open questions for Kyle — RESOLVED

1. **Bus implementation** — JSONL log file watcher. Path configurable via `settings.toml`.
2. **Multiple Claudes in one project dir** — assumed one Claude per project dir (tile keyed by project_dir).
3. **Skippy framework activity** — considered but removed; Conductor monitors Claude Code sessions + the bus only.
4. **Tile order** — manual drag + pin, localStorage-persisted.
5. **Session-end behavior** — fade out, remove after 30s.

---

## 13. Repo layout

```
claude-connect/                   # repo root
├── README.md
├── CONDUCTOR_SPEC.md
├── CLAUDE.md
├── pyproject.toml
├── Makefile
├── settings.example.toml
├── .gitignore
├── conductor/                    # Python package (kept named "conductor")
│   ├── __init__.py
│   ├── main.py
│   ├── scanner.py
│   ├── activity.py
│   ├── windows.py
│   ├── bus.py
│   ├── models.py
│   ├── settings.py
│   └── ws.py
├── frontend/
│   ├── index.html
│   ├── app.js
│   ├── tiles.js
│   ├── lines.js
│   └── style.css
├── scripts/
│   └── claude-tracked
├── docs/
│   ├── claude-storage.md
│   └── claude-bus.md
└── tests/
    ├── test_scanner.py
    ├── test_bus.py
    ├── test_markdown_bus.py
    └── test_settings.py
```

---

## 14. First-session prompt for Claude Code

> Read CONDUCTOR_SPEC.md. Implement Phase 0 and Phase 1: a FastAPI backend that scans for active Claude Code processes and serves a static frontend at `/` rendering one tile per session with title, project directory, status dot, and last-activity timestamp. Auto-refresh via WebSocket every 3 seconds. Document any discoveries about Claude Code's `~/.claude` storage format in `docs/claude-storage.md`. Do not implement the bus, connection lines, or window focus yet — those are later phases.

---

*TTA.*
