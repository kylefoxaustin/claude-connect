# Conductor

Local browser-based dashboard for monitoring concurrent Claude Code sessions on a single workstation.

![status: alpha](https://img.shields.io/badge/status-alpha-orange)

```
┌─ ●  keyhole-yolo ──────────────┐  ┌─ ●  api-refactor ─────────────┐
│ /home/kyle/code/keyhole         │  │ /home/kyle/code/api            │
│ ┌──────────────────────────┐   │  │ ┌──────────────────────────┐  │
│ │ ...running yolo training │   │  │ │ ...waiting on user input │  │
│ └──────────────────────────┘   │  │ └──────────────────────────┘  │
│  msgs: 47   ⏱ 2s ago           │  │  msgs: 12   ⏱ 1m ago          │
└────────────────────────────────┘  └────────────────────────────────┘
```

## Install

```bash
pip install -e ".[dev]"
sudo apt install wmctrl xdotool          # for terminal focus (Phase 5)
cp settings.example.toml settings.toml   # then edit if needed
```

## Run

```bash
make dev    # http://127.0.0.1:8765, auto-reload
```

Open the URL in a browser. Tiles appear as Conductor discovers running `claude` processes.

## How it works

1. **SessionScanner** enumerates processes via `psutil` matching the Claude Code CLI binary, then for each PID resolves `/proc/<pid>/cwd` and walks `~/.claude/projects/<encoded>/` to find the session's `*.jsonl`.
2. **ActivityWatcher** uses `watchdog` (inotify on Linux) to react to jsonl writes without polling.
3. **WebSocket hub** (`/ws`) pushes diffs to the browser at most once every 250ms.
4. The frontend renders one tile per session with a status dot (active/warm/idle/dormant/waiting/ended) and a squashed live preview of the most recent message.
5. **BusAdapter** tails a JSONL log of message-bus events; the **Bus tile** shows recent traffic and SVG connection lines fan out to subscribed sessions.
6. **claude-tracked** (in `scripts/`) is an optional wrapper that gives each Claude its own Tilix window with a unique X11 title — Conductor uses that title to focus the right window on tile click.

## Reliable terminal focus

Without `claude-tracked`, focus is best-effort: Conductor will raise the terminal window owning the Claude PID, but if you've packed several Claudes into tabs of one window, it can't switch tabs.

```bash
sudo install -m755 scripts/claude-tracked /usr/local/bin/
claude-tracked keyhole-yolo --resume
```

Each invocation opens a fresh Tilix window titled `claude:keyhole-yolo` that Conductor can target precisely.

## Configuration

`settings.toml` (copy from `settings.example.toml`). Key knobs:

- `scanner.interval_seconds` — full rescan cadence (default 3s)
- `bus.jsonl_path` — path to your message bus log file (one event per line)
- `ui.end_fadeout_seconds` — how long ended-session tiles linger (default 30s)

## Phases

See `CONDUCTOR_SPEC.md`. All phases 0–5 implemented.
