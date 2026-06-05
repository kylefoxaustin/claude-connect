# CLAUDE.md — Conductor

Local browser dashboard for monitoring active Claude Code sessions on a single workstation. Observes read-only and never modifies Claude itself; the only outbound actions are bus-mediated — appending a composed message to the bus log (v1.1) and injecting `/msg-check` keystrokes into a session's terminal on request.

## Run
- `make dev` — uvicorn with --reload on http://127.0.0.1:8765
- `make run` — production-ish (no reload)
- `make test` — pytest
- `make native` — Native App Edition: same app in a pywebview/WebKitGTK window
  (run `make install-native` once first; `make install-desktop` adds a launcher)

## Layout
- `conductor/` — FastAPI backend (scanner, activity watcher, bus adapter, ws hub)
- `frontend/` — vanilla JS SPA served at `/`
- `scripts/claude-tracked` — wrapper that opens each Claude session in its own Tilix window with a unique X11 title; required for reliable tile→focus
- `docs/claude-storage.md` — empirically documented `~/.claude/` format

## Conventions
- Single-host only, listens on 127.0.0.1.
- No persistence; in-memory state, restart-clean.
- `psutil` + `watchdog` for discovery + activity. No terminal scraping.
- Frontend is plain JS — no build step. Edit `frontend/*.js` and reload.
- Settings live in `settings.toml` (copy from `settings.example.toml`).

## Phase status
- ✅ Phase 0: skeleton, FastAPI hello, frontend served at `/`
- ✅ Phase 1: SessionScanner + tile grid + status dots + WS auto-refresh
- ✅ Phase 2: jsonl tail → live activity preview
- ✅ Phase 3: BusAdapter + Bus tile + notification badge
- ✅ Phase 4: SVG connection lines + flow animation
- ✅ Phase 5: claude-tracked + WindowMapper + focus action
- ✅ v1.0: 📬 bubble injects /msg-check into the live Claude (guarded by a
  per-user busy policy); un-wired sessions render without a bus line; bus
  reference impl shipped in `bus/`.
- ✅ v1.1: Compose button → `POST /api/bus/send`. Send a bus message as
  `[operator]` (configurable `bus.sender_tag`) to all sessions or specific
  ones (soft-addressed via a leading `@to [tag]…` line), with an optional
  ping that injects /msg-check into the chosen sessions.
- ✅ v2.1.2: Tilix-exact tile focus. `focus_session`/`send_keys_to_session`
  now resolve a session's tilix tile by `TILIX_ID` (read from
  `/proc/<pid>/environ`) and call the `activate-terminal` gaction over the
  `com.gexperts.Tilix` D-Bus name — raising the window *and* selecting the exact
  tile. This runs before the old wmctrl title matching and falls back to it for
  non-tilix terminals / when `gdbus` or `TILIX_ID` is absent. Fixes the
  combined-window corner case: title matching only sees the *active* tile's
  title, so a backgrounded tile lost focus to a stray same-named terminal (e.g.
  a shell `cd`'d into the project dir); the exact PID→tile handle sidesteps X11
  titles entirely. Backend only, ships in both editions. **Scope: tilix only.**
  Tested exclusively with tilix; other multi-window terminals (terminator,
  kitty, gnome-terminal tabs, …) are out of scope and untested — they simply
  fall through to the wmctrl title path, no regression. No plans to support
  other tiling terminals.
- ✅ v2.1.1: Stop the multi-session tile blink. `renderGrid` now reconciles
  tiles (reuse the outer node per key + refresh content in place) instead of
  `innerHTML=""` teardown every WS update. Preserving node identity means an
  ended tile's opacity fade runs once to 0 instead of restarting on each of the
  ~10 updates that arrive while several sessions tear down at once (the v1.5.3
  fix only stopped the backend ENDED↔ACTIVE flap; this is the frontend layer).
  Drag handlers + the resize observer now attach once, not per-render. Frontend
  only, so it ships in both editions.
- ✅ v2.1: Native App Edition. `app.py` launches the same FastAPI app in a
  pywebview/WebKitGTK window — uvicorn runs in a daemon thread, window-close
  stops it, and it attaches to an already-running instance instead of spawning
  a duplicate. Makefile `install-native` (separate `.venv-native` with
  `--system-site-packages`) / `native` / `install-desktop`; `.desktop` template
  + SVG icon. Release scheme (as of v2.1.2): a **single release per version**
  from the bare tag (`vX.Y.Z`), covering both editions — it's one commit, the
  edition is just `make run` vs `make native`. The old `-native` split-release
  scheme is retired; legacy `-native` tags/releases (≤ v2.1.0-native) stay as
  history.
- ✅ v2.0: Web Browser Edition milestone — clean baseline for the dual-edition
  era (functionally same as v1.5.3).
- ✅ v1.5: Durable layout. Tiles keyed by project dir (not the ephemeral
  session UUID), and offline tiles' layout/groups are no longer GC'd — so
  positions/sizes/groups survive reboots and fresh sessions. localStorage keys
  bumped to v2 (positions/minimized/groups). README documents what's stored where.
- ✅ v1.4: Color-coded groups. Per-tile ▦ menu assigns membership (no canvas
  multi-select — a popup that closes before re-render, avoiding drag/click
  conflicts). Minimize a whole group to one dock chip w/ rollup; ▦ Groups
  panel manages rename/recolor/minimize/ungroup. Logical (color-only), in
  localStorage (`conductor.groups.v1`).
- ✅ v1.3: Minimize tiles to a bottom dock (live status, click to restore;
  state persisted); "Lines behind tiles" appearance toggle (overlay z-index).
- ✅ v1.2: Tile resize (corner grip, size persisted) + full-title tooltip.
  Active⇄Passive per-tile toggle (click the tag chip) → `POST /api/bus/active`
  writes `~/.claude/bus-state/active-tags`, the data-file whitelist that the
  migrated `bus.sh` reads (falls back to defaults when absent). Connection
  lines: solid = active (auto-notified), dashed = passive; legend bottom-left.

See `CONDUCTOR_SPEC.md` for full design.
