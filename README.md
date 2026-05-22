# Claude Connect

**A local browser dashboard for watching all your Claude Code sessions at once — plus an optional message bus that lets them talk to each other.**

[![version: 1.5](https://img.shields.io/badge/version-1.5-blue)](https://github.com/kylefoxaustin/claude-connect/releases)
[![platform: linux](https://img.shields.io/badge/platform-linux-orange)](#requirements)
[![safety: read--only](https://img.shields.io/badge/safety-read--only-green)](#how-it-works)

```
┌─ ●  api-server ────────────────┐  ┌─ ●  web-app ───────────────────┐
│ ~/code/api                 📬3 │  │ ~/code/web                     │
│ ┌──────────────────────────┐   │  │ ┌──────────────────────────┐   │
│ │ ...running test suite    │   │  │ │ ...waiting on user input │   │
│ └──────────────────────────┘   │  │ └──────────────────────────┘   │
│  msgs: 47   ⏱ 2s ago           │  │  msgs: 12   ⏱ 1m ago           │
└────────────────────────────────┘  └────────────────────────────────┘
```

> 💡 **Heads up on names:** the repo is `claude-connect`; the dashboard binary is `conductor`. Same project — you'll see both names throughout.

---

## Why?

If you're like us, you're running 3, 4, or 8 Claude Code sessions at once across different projects. You forget which terminal is doing what. You miss when one finishes and goes quiet. You wish they could *coordinate* — "hey, the API change is in, you can start on the frontend."

**Claude Connect solves both problems:**

- **See everything at a glance.** One tile per live Claude session — status dot, live preview of what it's saying, time since last activity. Click a tile to jump to that terminal.
- **Let your Claudes talk.** Wire up the optional message bus and your sessions can `/msg-send` each other across projects. The dashboard shows the traffic with animated connection lines.

It's **read-only and local**. It watches Claude's `~/.claude/projects/*.jsonl` logs and process state — it never modifies Claude itself, and it only binds to `127.0.0.1`.

---

## Features

- 🪟 **Live tiles** for every running Claude session — auto-discovered, no config
- 🎯 **Click-to-focus** — clicking a tile raises the actual terminal window
- 📬 **Cross-session messaging** with an animated bus tile showing live traffic
- ✉️ **Compose from the dashboard** — send your own bus message to all sessions or a chosen few, with an optional "ping" that makes them read it now
- 🟢 **Status indicators** — `active` / `warm` / `idle` / `dormant` / `waiting` / `ended`
- 💾 **Persistent layout** — drag tiles to rearrange and **resize** them (corner grip); both stick
- 🗕 **Minimize to dock** — tuck rarely-touched sessions into a bottom dock (still live), restore with a click
- ▦ **Groups** — color-code sessions into named groups; minimize a whole group to one dock chip with a rollup badge
- 🔀 **Active/Passive bus control** — click a tile's tag chip to toggle whether it's auto-notified of bus traffic
- 🎨 **Themeable** — dark/light, animations, connection-line styling
- 🔒 **Local only** — `127.0.0.1`, in-memory, restart-clean

---

## Requirements

- **Linux with X11** (Wayland is best-effort)
- **Python 3.10+**
- **`wmctrl` and `xdotool`** for terminal focus and `/msg-check` injection
  - Both optional — without them, the focus and 📬 buttons just no-op

---

## Quick Start

```bash
# 1. Clone and install
git clone https://github.com/kylefoxaustin/claude-connect
cd claude-connect
pip install -e ".[dev]"

# 2. Install the OS helpers (recommended)
sudo apt install wmctrl xdotool

# 3. Copy the example settings
cp settings.example.toml settings.toml

# 4. Run it
make dev    # http://127.0.0.1:8765, auto-reload
```

Open the URL in a browser. Start a Claude Code session in another terminal — a tile appears within seconds. **No per-session registration. No config to get started.**

Other targets:

```bash
make run     # production-style, no reload
make test    # run the pytest suite
```

---

## Using the Dashboard

### Tiles

Each tile is one live Claude session. It shows:

- **Status dot** — `active` (writing now), `warm` (recent), `idle`, `dormant`, `waiting` (on user input), `ended`
- **Squashed live preview** of the latest message
- **Message count + time since last activity**
- **📬 bubble** — appears when this session has unread bus messages (only if the [bus](#cross-session-bus) is wired up)
- **Tag chip** (e.g. `[backend]`) — its bus identity, and a click-toggle for [Active/Passive](#active--passive) membership

**Drag** a tile to move it; **drag the bottom-right corner** to resize it; the **`–`** button minimizes it to the bottom dock. Hover a truncated title to see it in full. Position, size, and minimized state persist across restarts.

### Minimize / dock

Click a tile's **`–`** to tuck it into a thin **dock** along the bottom — a tiny chip with its status dot, name, and 📬 badge. It's still monitored (the dot keeps updating; a new message still lights the badge), just out of the way. Hover for the full name; **click the chip to restore** it to its previous position and size. Minimized tiles' bus wires are hidden to keep the board clean.

### Groups

For a crowded board, organize sessions into **named, color-coded groups**. Each tile has a **▦** button that opens a small menu:

- **▦ → New group from this** (prompts for a name) — or **Add to ▸ {group}** to join an existing one. A tile belongs to one group; members get a colored top accent.
- On a grouped tile: **Rename group**, **Move to ▸ {other}**, **Remove from group**, or **Minimize group** — which folds the *whole* group into a single dock chip (swatch + name + member count + active dot + total 📬). Click the chip to expand it back.
- The **▦ Groups** panel (top bar) lists every group to rename, recolor, minimize/restore, or ungroup.

Groups are *logical* (members keep their own positions — they aren't auto-arranged) and persist across restarts.

### Click a tile

Raises that session's terminal window. See [Reliable terminal focus](#reliable-terminal-focus) for the trick that makes this work cleanly when you have many sessions in one terminal app.

### Click the 📬 bubble

Runs `/msg-check` *inside that live Claude* — it raises the window and types the command for you. Behavior is configurable so you don't clobber a Claude mid-task (see below).

### Bus tile

A central tile shows recent cross-session traffic. SVG lines fan out to every session that's on the bus and animate on each message. The line style tells you *how* a session is on the bus (see the legend, bottom-left):

- **Active** (solid) — wired to the bus hooks, so it's **auto-notified** of new messages and receives broadcasts.
- **Passive** (dashed, dim) — has used the bus manually (`/msg-send` / `/msg-check`) but isn't auto-notified, so it **won't see broadcasts** unless you Ping it. (These are sessions outside `bus.sh`'s hook whitelist — a deliberate scoping so the bus doesn't pester unrelated sessions.)

### Active / Passive

Click a tile's **tag chip** to toggle that session between **Active** (auto-notified) and **Passive** (manual only) right from the dashboard. Conductor writes the membership to `~/.claude/bus-state/active-tags`, and `bus.sh` reads it — so the change takes effect on that session's **next prompt** (promote a throwaway session into the team, or stop pestering one). The list seeds from your existing active set on first toggle, so nothing changes until you click.

> Requires the data-file-aware `bus.sh` (the shipped [`bus/bus.sh`](bus/bus.sh) reads `active-tags`, falling back to its built-in `BUS_WHITELIST` when the file is absent). If you wired up the bus before this, re-copy `bus/bus.sh`.

### ✉ Compose

Click **Compose** in the top bar to send your own message on the bus — like email for your sessions. You're a first-class sender (tagged `[operator]` by default; set `bus.sender_tag` in `settings.toml` to your name).

- **All sessions** (default) — a broadcast everyone sees.
- **Specific sessions** — uncheck "All" and pick recipients. The message is soft-addressed with a leading `@to [tag] …` line, so receivers (and the dashboard's connection-line animation) know who it's for. It's still on the shared log; addressing is advisory, not private.
- **Ping recipients** — also injects `/msg-check` into the chosen sessions so they read it immediately (specific recipients only — broadcast-ping would steal focus across every window). `Ctrl/⌘+Enter` sends.

> Sending makes Claude Connect a *writer* on the bus (it still never touches Claude's own state). Requires the markdown bus adapter.

### ⚙ Settings

Theme, connection lines (incl. **Lines behind tiles** to drop the wires behind the tiles for a cleaner board — each wire still stays anchored to its own tile via a plug + stub drawn on top), animations, rescan cadence, and the **bus-bubble click policy**:

| Policy                                      | Behavior                                                                                      |
| ------------------------------------------- | --------------------------------------------------------------------------------------------- |
| **Confirm if busy, inject if idle** *(default)* | Inject silently when idle; confirm first if the session looks busy (writing in the last 30s). |
| **Always inject**                           | Type `/msg-check` immediately, regardless of state.                                           |
| **Block while busy**                        | Badge is dimmed/non-clickable while busy; injects only when idle.                             |
| **Always confirm**                          | Ask before every injection.                                                                   |

> ⚠️ "Busy" is inferred from `jsonl` activity + CPU. A Claude blocked on a long, quiet tool call can still look idle, so this guard *shrinks* the risk of clobbering rather than eliminating it. Use *Always confirm* if you want a prompt every time.

---

## Cross-Session Bus

> *Optional, but the killer feature.*

The 📬 features ride on a **shared markdown message log**. Claude sessions append to it with `/msg-send` and read it with `/msg-check`; hooks make each session aware of new messages. Claude Connect tails the same log to drive the bus tile.

### Setup

```bash
install -Dm755 bus/bus.sh ~/.claude/bin/bus.sh
cp bus/commands/*.md ~/.claude/commands/

# Then merge bus/settings.hooks.example.json into ~/.claude/settings.json
```

Point Claude Connect at the log in the `[bus]` section of `settings.toml`. Full setup docs and format spec:

- 📖 [`bus/README.md`](bus/README.md) — install + slash commands
- 📖 [`docs/claude-bus.md`](docs/claude-bus.md) — message format spec

### What if a session isn't on the bus?

Claude Connect works fully without it. Session discovery comes from OS process state, not from the bus, so:

- ✅ An un-wired Claude still appears as a normal tile — status, preview, message count, click-to-focus all work
- ❌ It just won't show a 📬 badge or a connection line to the Bus tile

This is actually useful — if you wire up some sessions and leave others out, the dashboard shows at a glance which ones are on the tunnel and which are silent.

---

## Reliable Terminal Focus

A single terminal server (Tilix, `gnome-terminal-server`) owns all its windows, so they share one PID. Claude Connect matches on **window title** to tell them apart.

The optional `claude-tracked` wrapper in [`scripts/`](scripts/) gives each Claude its own Tilix window with a unique X11 title, so focus and 📬 injection target precisely:

```bash
sudo install -m755 scripts/claude-tracked /usr/local/bin/
claude-tracked api-server --resume
```

Without the wrapper, focus is best-effort: Claude Connect raises the terminal window owning the Claude PID, but can't switch between tabs packed into one window.

---

## Configuration

Edit `settings.toml` (copied from `settings.example.toml`). Key knobs:

| Setting                       | What it does                                                  | Default |
| ----------------------------- | ------------------------------------------------------------- | ------- |
| `scanner.interval_seconds`    | Full rescan cadence                                           | `3`     |
| `bus.adapter`                 | `markdown` (the reference bus), `jsonl` (generic), or `fake`  | —       |
| `bus.markdown_path`           | Path to the bus log                                           | —       |
| `bus.state_dir`               | Where unread state lives                                      | —       |
| `bus.script_path`             | Path to `bus.sh`                                              | —       |
| `ui.end_fadeout_seconds`      | How long ended-session tiles linger after exit                | `30`    |

---

## What's stored, and where

Conductor keeps **no central database** — state lives in two clearly separated places:

**Your browser (localStorage, per-origin `127.0.0.1:8765`)** — all the visual/layout customization. Written to disk by the browser, so it survives closing the tab, restarting the browser, restarting the server, and rebooting:

| Key | Holds |
| --- | --- |
| `conductor.prefs.v1` | theme, connection-line visibility, lines-behind, flow animation, bus-bubble click policy |
| `conductor.positions.v2` | tile positions **and sizes** |
| `conductor.minimized.v2` | which tiles are minimized to the dock |
| `conductor.groups.v2` | your groups (names, colors, members, collapsed state) |

Layout/minimize/group state is keyed by **project directory**, so a session re-attaches to its saved spot, size, and group whenever it runs in the same directory — across reboots and even fresh (non-resumed) sessions. Conductor doesn't prune offline tiles' layout, so it waits for them to return. Clear it with **Reset layout**, **Ungroup**, or your browser's site-data tools.

**On your machine (the bus), not the browser:** the cross-session bus log (`~/Documents/claude-bus/messages.md`), unread state (`~/.claude/bus-state/`), and the active/passive whitelist (`~/.claude/bus-state/active-tags`). The Conductor server itself is **in-memory and restart-clean** — it holds no persistent state of its own.

---

## How It Works

For the curious:

1. **SessionScanner** enumerates Claude Code processes via `psutil`, resolves `/proc/<pid>/cwd`, and walks `~/.claude/projects/<encoded>/` to find each session's `*.jsonl`.
2. **ActivityWatcher** uses `watchdog` (inotify on Linux) to react to jsonl writes without polling.
3. A **WebSocket hub** at `/ws` pushes diffs to the browser at most once every 250 ms.
4. The **frontend** renders one tile per session — plain JS, no build step.
5. **BusAdapter** tails the message-bus log; the Bus tile shows recent traffic and SVG lines fan out to sessions on the bus.
6. **WindowMapper** uses `wmctrl`/`xdotool` to raise the right terminal window on click and to type `/msg-check` into a session when you click its 📬.

Full design doc: [`CONDUCTOR_SPEC.md`](CONDUCTOR_SPEC.md)

---

## Design Notes

- **Single-host only.** Binds to `127.0.0.1`.
- **No persistence.** State is in-memory and restart-clean.
- **No build step on the frontend.** Edit `frontend/*.js` and reload.

---

## Troubleshooting

**Tiles aren't appearing.**
Check that `claude` is actually running and that `~/.claude/projects/` has recent jsonl files. Drop `scanner.interval_seconds` to `1` temporarily to confirm discovery is happening.

**Clicking a tile doesn't focus the terminal.**
Make sure `wmctrl` is installed. If you're using Tilix or another tabbed terminal, install the `claude-tracked` wrapper so each session gets a unique window title.

**📬 bubbles never appear.**
The bus isn't wired up. See [Cross-Session Bus](#cross-session-bus). Sessions work fine without it — they just won't have bubbles or connection lines.

**`/msg-check` doesn't inject when I click 📬.**
Check that `xdotool` is installed and the session's terminal window is on the current desktop/workspace.

---

## Maintainer

Built and maintained by **Kyle Fox** ([@kylefoxaustin](https://github.com/kylefoxaustin)).

Got an idea, found a bug, or want to share how you're using it? Open an [issue](https://github.com/kylefoxaustin/claude-connect/issues) or ping me on GitHub.

## Contributing

Issues and PRs welcome. See [`CLAUDE.md`](CLAUDE.md) for the agent-friendly contributor guide.
