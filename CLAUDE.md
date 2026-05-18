# CLAUDE.md — Conductor

Local browser dashboard for monitoring active Claude Code sessions on a single workstation. Read-only observer; never modifies Claude itself.

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
- 🟡 Skippy adapter — stubbed (placeholder tiles only)

See `CONDUCTOR_SPEC.md` for full design.
