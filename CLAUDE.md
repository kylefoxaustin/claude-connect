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

## Identity & absence — three rules, earned the hard way

Five failures in one session (2026-09-14) shared one shape: **something was looked up by a PROXY for
its identity, and the proxy had drifted from the thing.** `comm` vs the exe path; a bus tag vs its
directory; file mtime vs "was produced". **Every one returned a confident, plausible answer and none
errored** — and each wrong answer looked like a finding about the fleet ("that session is dead", "104
new results") rather than a fault in the instrument.

1. **An absence is a claim about your instrument until a positive control passes.** Before believing
   *not running* / *no results* / *nothing advanced*, show the SAME instrument finding a case you know
   is present. (lostchild: *"an absence claim needs an instrument that could not have produced the
   absence."*)
2. **Identify by stable identity, never by name.** Process → `/proc/<pid>/exe` + cwd, never `comm`
   (it is the exe basename and truncates at 15 bytes). Session → cwd + session_id, never the bus tag
   (`keyhole` posts as `backend`). "New results" → content, never mtime. ⚠️ Rule 1 does not cover
   this case: a positive control passes while the KEY is still wrong.
3. **When you fix an identity bug, grep the whole tree for the same predicate.** `comm == "claude"`
   was fixed in `conductor/scanner.py` on 2026-08-31 and left standing in `bus/pid-join.sh`, where it
   silently froze a session's read cursor for two weeks. A lesson recorded in a commit message and
   not swept for only ever fixes one site.

## Conventions
- Single-host only, listens on 127.0.0.1.
- No persistence; in-memory state, restart-clean.
- `psutil` + `watchdog` for discovery + activity. No terminal scraping.
- Frontend is plain JS — no build step. Edit `frontend/*.js` and reload.
- Settings live in `settings.toml` (copy from `settings.example.toml`).

## Phase status
Current: **v2.41.0**. Full per-version history — the why, the bugs, the measurements — lives in
**`docs/CHANGELOG.md`** (newest first). Read the relevant entry before changing a subsystem; most
of them record a failure that the obvious fix would reintroduce.

Arcs, oldest → newest: dashboard core (v1.0–v2.8) · shared-resource reservation + watchdog
(v2.9–2.18) · fleet coordination, retraction, push gate (v2.19–2.21) · mobile/PWA, ops console,
decision queue, web push (v2.22–2.27) · FAILURE_MODES taxonomy + bus provenance (v2.28–2.33) ·
persistence gate (v2.31/2.34) · fleet-health signals + v4 delivery plane (v2.35–2.36) · disaster
recovery (v2.37–2.38) · bound-the-unbounded scale review (v2.39) · decision-queue escapes
(v2.40) · approval loop + Windows (v2.41).

See `CONDUCTOR_SPEC.md` for full design.
