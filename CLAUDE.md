# CLAUDE.md — Conductor

Local browser dashboard for monitoring active Claude Code sessions on a single workstation. Observes read-only and never modifies Claude itself; the only outbound actions are bus-mediated — appending a composed message to the bus log (v1.1) and injecting `/msg-check` keystrokes into a session's terminal on request.

## Run
- `make dev` — uvicorn with --reload on http://127.0.0.1:8765
- `make run` — production-ish (no reload)
- `make test` — pytest

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
- ✅ v1.3: Minimize tiles to a bottom dock (live status, click to restore;
  state persisted); "Lines behind tiles" appearance toggle (overlay z-index).
- ✅ v1.2: Tile resize (corner grip, size persisted) + full-title tooltip.
  Active⇄Passive per-tile toggle (click the tag chip) → `POST /api/bus/active`
  writes `~/.claude/bus-state/active-tags`, the data-file whitelist that the
  migrated `bus.sh` reads (falls back to defaults when absent). Connection
  lines: solid = active (auto-notified), dashed = passive; legend bottom-left.

See `CONDUCTOR_SPEC.md` for full design.
