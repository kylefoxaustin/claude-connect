# Conductor

Local browser dashboard for monitoring concurrent Claude Code sessions on a
single workstation. Read-only observer — it never modifies Claude itself.

![version: 1.0](https://img.shields.io/badge/version-1.0-blue)

```
┌─ ●  api-server ────────────────┐  ┌─ ●  web-app ──────────────────┐
│ ~/code/api                 📬3 │  │ ~/code/web                     │
│ ┌──────────────────────────┐   │  │ ┌──────────────────────────┐  │
│ │ ...running test suite    │   │  │ │ ...waiting on user input │  │
│ └──────────────────────────┘   │  │ └──────────────────────────┘  │
│  msgs: 47   ⏱ 2s ago           │  │  msgs: 12   ⏱ 1m ago          │
└────────────────────────────────┘  └────────────────────────────────┘
```

## Install

```bash
pip install -e ".[dev]"
sudo apt install wmctrl xdotool          # for terminal focus + 📬 bus-bubble inject
cp settings.example.toml settings.toml   # then edit if needed
```

`wmctrl`/`xdotool` are optional — without them, focus and bus-bubble injection
degrade gracefully (the buttons just no-op).

## Run

```bash
make dev    # http://127.0.0.1:8765, auto-reload
make run    # no reload
make test   # pytest
```

Open the URL in a browser. Tiles appear as Conductor discovers running `claude`
processes — no configuration needed to get started.

## Use

- **Tiles** — one per live Claude session, discovered automatically. Each shows a
  status dot (`active` / `warm` / `idle` / `dormant` / `waiting` / `ended`), a
  squashed live preview of the latest message, the message count, and time since
  last activity. Drag tiles to rearrange; the layout persists.
- **Click a tile** → raises that session's terminal window (see
  [Reliable terminal focus](#reliable-terminal-focus)).
- **📬 bubble** — appears on a tile when its session has unread cross-session bus
  messages. Click it to run `/msg-check` *in that live Claude* (it raises the
  window and types the command). Requires the [bus](#cross-session-bus-optional)
  to be wired up.
- **Bus tile** — shows recent cross-session traffic; SVG lines fan out to the
  sessions that are on the bus, animating on each message.
- **⚙ Settings** — theme, connection lines, animations, rescan cadence, and the
  **Bus bubble click** policy (below).

### Bus bubble click policy

Clicking 📬 types into a live terminal, so there's a guard against interrupting a
Claude mid-task. Choose the behavior in **Settings → Messages → Bus bubble click**:

| Policy | Behavior |
|--------|----------|
| Confirm if busy, inject if idle *(default)* | Inject silently when idle; confirm first if the session looks busy (writing in the last 30s). |
| Always inject | Type `/msg-check` immediately, any state. |
| Block while busy | Badge is dimmed/non-clickable while busy; injects only when idle. |
| Always confirm | Ask before every injection. |

> "Busy" is inferred from jsonl activity + CPU. A session blocked on a long, quiet
> tool call can still read as idle, so the guard shrinks the risk of clobbering
> rather than eliminating it. Use *Always confirm* if you want a prompt every time.

## Cross-session bus (optional)

The 📬 features ride on a small **message bus** — a shared markdown log that
Claude sessions append to via `/msg-send` and read via `/msg-check`, with hooks
that make each session aware of new messages. Conductor tails the same log.

The reference implementation (script + slash commands + hook config) ships in
[`bus/`](bus/) — see [`bus/README.md`](bus/README.md) for setup. In short:

```bash
install -Dm755 bus/bus.sh ~/.claude/bin/bus.sh
cp bus/commands/*.md ~/.claude/commands/
# then merge bus/settings.hooks.example.json into ~/.claude/settings.json
```

Point Conductor at the log in `settings.toml` (`[bus]` section). The format spec
is in [`docs/claude-bus.md`](docs/claude-bus.md).

### What if a session isn't wired up?

Conductor works fully without the bus. Discovery is driven by OS process state,
not the bus, so a Claude that's never touched the bus still appears as a normal,
fully-functional tile — status, live preview, message count, and click-to-focus
all work. The only difference: an un-wired session shows **no 📬 badge** and draws
**no connection line** to the Bus tile. So if you wire up some sessions and leave
others out, the dashboard shows at a glance who's on the tunnel and who's silent.

## How it works

1. **SessionScanner** enumerates processes via `psutil` matching the Claude Code
   CLI, resolves `/proc/<pid>/cwd`, and walks `~/.claude/projects/<encoded>/` to
   find each session's `*.jsonl`.
2. **ActivityWatcher** uses `watchdog` (inotify on Linux) to react to jsonl writes
   without polling.
3. **WebSocket hub** (`/ws`) pushes diffs to the browser at most once per 250ms.
4. The frontend renders one tile per session with a status dot and a live preview.
5. **BusAdapter** tails the message-bus log; the **Bus tile** shows recent traffic
   and SVG connection lines fan out to sessions that are on the bus.
6. **WindowMapper** uses `wmctrl`/`xdotool` to raise the right terminal window on
   tile click, and to type `/msg-check` into a session when you click its 📬.

## Reliable terminal focus

A single terminal server (Tilix, gnome-terminal-server) owns all its windows, so
they share one PID. Conductor matches on the **window title** to tell them apart.
The optional `claude-tracked` wrapper (in `scripts/`) gives each Claude its own
Tilix window with a unique X11 title so focus and 📬 injection target precisely:

```bash
sudo install -m755 scripts/claude-tracked /usr/local/bin/
claude-tracked api-server --resume
```

Without it, focus is best-effort: Conductor raises the terminal window owning the
Claude PID, but can't switch between tabs packed into one window.

## Configuration

`settings.toml` (copy from `settings.example.toml`). Key knobs:

- `scanner.interval_seconds` — full rescan cadence (default 3s)
- `bus.adapter` — `markdown` (the reference bus), `jsonl` (generic), or `fake` (demo)
- `bus.markdown_path` / `bus.state_dir` / `bus.script_path` — bus log + state + script
- `ui.end_fadeout_seconds` — how long ended-session tiles linger (default 30s)

## Design notes

- Single-host only; binds to `127.0.0.1`. No persistence — state is in-memory and
  restart-clean.
- Frontend is plain JS, no build step. Edit `frontend/*.js` and reload.
- See [`CONDUCTOR_SPEC.md`](CONDUCTOR_SPEC.md) for the full design.
