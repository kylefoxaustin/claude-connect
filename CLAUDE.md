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
- ✅ v2.5.0: 🔬 Drill-down — watch a session explode outward in work. In the
  History human layer, **clicking a session node** opens the whole **you↔session
  working relationship** replayed on a playhead: a `[you]` node fires each prompt
  into the central session node, which detonates outward into the **files** it
  touched (deduped halo, read=blue/edit=orange, grow with touches), **sub-agents**
  spawned (Agent/Task), and every **tool call** (pulse + live counter tape). A
  **🔍 Focus prompt** selector isolates one exchange at a time (✕ returns to the
  whole relationship). Backend: `extract_session_detail(jsonl_paths)` in
  `scanner.py` walks every transcript in the project dir via `_walk_exchanges`,
  returns time-ordered `{prompts, events, summary, dropped}` with each event
  tagged by its prompt index `ex` (so focus-one is a client-side filter);
  `_classify_tool` maps tool_use → file/agent/tool nodes; tool_result `is_error`
  tints failures. `GET /api/session-detail?project=` (path-validated, off-thread).
  Cap 12000 events; when trimmed, orphaned prompts are dropped so the replay has
  no dead prompts-only prefix (keep prompts that own retained events or are
  in-window — the bug Kyle caught where 95 showed prompts for half the run before
  work appeared). Also a single-exchange `extract_exchange` + `/api/exchange`
  exist. Frontend `drilldown.js` (lazy-imported, pure SVG, deterministic-`f`).
  **Folds in v2.4.1**: the human layer now counts only GENUINE typed prompts —
  `_human_prompt_text` strips `<system-reminder>` / `<command-*>` /
  `<local-command-*>` wrappers and rejects pure injections, auto-compact
  continuations, and bare slash-commands (~5% of prior "prompts" were harness
  noise). Idea + event-schema collaboration came from 95emulator via the bus.
  Both editions.
- ✅ v2.4.0: 🕸 History — human↔Claude layer. A `👤 Human` toggle in the
  History overlay weaves the human turns into the same time-lapse. Backend:
  `/api/bus/heatmap?human=1` merges `build_mention_history` (bus) with
  `collect_human_events` (`scanner.py`), which walks `~/.claude/projects/*/*.jsonl`
  and emits **turn-level** events — one `prompt` (`[you]`→session) + one collapsed
  `reply` (session→`[you]`) per exchange, NOT every streaming/tool sub-record.
  Real human prompts are told apart from tool-result user-messages by content
  shape (`_user_text_len`: text blocks, no `tool_result`); sidechain/meta records
  skipped; ISO timestamps → epoch. Sessions key to the **same bus tags** via
  `derive_tag(recorded_cwd, settings.bus.tags)`, so human edges land on the bus
  nodes. Each event carries `kind` (bus|prompt|reply); merged stream re-sorted by
  ts; nodes recomputed (adds `[you]` with `is_you`, `first_seen`, source-count).
  Capped at 8000 most-recent events with a surfaced `dropped` count (no silent
  truncation; ~1.7s parse, off-thread, on-demand). `human=off` is byte-for-byte
  the old bus-only graph. Frontend: `heatmap.js` restructured so controls + the
  rAF loop wire once and `rebuild(data)` swaps graph state — the toggle just
  re-fetches and rebuilds in place (preserving layout/speed). `[you]` renders
  gold, labeled with the OS username (`_human_label`, capitalized; "You" if
  unavailable — NOT hardcoded); human edges gold + dashed (`hm-edge-human`, keyed off either
  endpoint being `[you]`). Toggle persists (`localStorage` `conductor.heatmapHuman`).
  Aligns to 95emulator's proposed `{ts,src,dst,kind,sessionId}` schema (the idea
  came in via the bus). Frontend + backend, both editions.
- ✅ v2.3.0: 🕸 History time-lapse. A `🕸 History` topbar button replays the
  **entire** bus (live `messages.md` + every `messages-*.md` archive) as an
  animated graph. Backend `GET /api/bus/heatmap` (`build_mention_history` in
  `bus.py`) sweeps all logs and returns `{nodes, events}` time-ordered; since
  the bus is broadcast-only (0 `@to` in practice), edges are **inferred from
  mentions** — a message naming another session — using a longest-first regex
  alternation so `pai-sizer` ≠ `sizer`. `[system]` rotation notices are
  excluded. Each event carries `size` (body length). Frontend `heatmap.js` is
  **lazily imported** like `scene3d.js` (pure SVG, no deps — a failure can't
  touch the 2D board): a full-screen overlay where nodes fade in as each session
  first speaks (and persist dimmed when quiet), undirected mention-lines thicken
  with cumulative traffic, and a pulse-dot flies each wire on use, **sized by
  message length** (fat report vs. speck hello). Everything is a pure function
  of one progress scalar `f∈[0,1]` (glow/pulse recency = `f - lastTouch`, no
  timers), so scrubbing back is just a cheap replay. Play/pause + scrubber +
  0.25×–5× speeds, idle-gap-clamped virtual timeline. **Three layouts** via a
  switcher (persisted to `localStorage` `conductor.heatmapLayout`): **clusters**
  (default; live force-directed sim — mention-edges are springs, frequent
  partners drift together as weights grow during playback), **ring** (arrival
  order), **orbit** (radial by volume, loudest centered). Modes morph smoothly
  (everything seeds as a ring, then eases/springs into place). Force constants
  tuned by a stability stress-test (3000 steps, worst-case dense graph: no
  NaN/explosion, converges, no overlap) since the sandbox can't run a live
  browser. Frontend + one backend field; ships in both editions.
- ✅ v2.2.0: 3D view (fork ②). A `🧊 3D` topbar toggle swaps the 2D board for
  a WebGL scene rendered with Three.js + `CSS3DRenderer` (loaded via import map,
  no build step). `frontend/scene3d.js` is **dynamically imported only on first
  toggle**, so a CDN miss can never break the 2D default. Session cards are real
  DOM (crisp text, reusing the `requestFocus`/`toggleBusActive`/`requestCheck`
  globals), **billboarded** to always face the camera — the lesson from the
  rejected CSS-tilt prototype (never angle the content you read; depth lives in
  the space between tiles). OrbitControls (drag-orbit / scroll-zoom), a glowing
  bus core, and bus wires drawn on an SVG overlay by projecting each card's 3D
  position to screen (flow animation on message). Three layouts via a floating
  switcher — **carousel** (default; ring you spin, front card enlarged),
  **orbital** (fibonacci sphere around the core), **gallery** (reuses the v1.5
  saved positions, depth by status). **Groups** carry into 3D: group color
  (border+glow) + spatial clustering (contiguous ordering → adjacent placement
  for orbital/carousel; centroid-pull for gallery), reading the same
  `conductor.groups.v2` store (assignment still happens via the 2D ▦ menu).
  Prefs `view3d` (default false → 2D) + `layout3d` (default "carousel") persist
  in localStorage. Two bugs caught during the build, both verified via headless
  screenshots: (1) cards inherited `.tile` which forced `position:absolute` w/o
  `top/left` → mis-anchored in the CSS3D transform; fixed with a self-contained
  `.card3d`. (2) A `.scene3d > div` rule also matched the controls bar, blowing
  it to a full-screen opaque panel that hid everything; removed (the renderer
  sizes its own host). Frontend only, ships in both editions.
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
