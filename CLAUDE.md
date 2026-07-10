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
- ✅ v2.18.0: 💓 Activity-as-heartbeat — Conductor heartbeats a shared board on
  behalf of a *working* holder. **Found live**: `orb_slam` held `orin-agx` (hard)
  and the watchdog nudged it **7×** over 2h with no reply. It wasn't stalled —
  `status=warm`, actively doing its a78ae rebuild. A remote board has no telemetry,
  so "idle" means *"no `/keep` heartbeat"*, and a Claude deep in a long build never
  stops to run `/keep`. Worse, the loop **defeated itself**: the sessions most
  likely to be nudged are doing long work → no heartbeat → nudged; but long work
  also means `active`/`warm` → v2.17.0's busy guard (correctly) refuses to inject →
  the nudge can *never* reach exactly the sessions it targets. Both decisions were
  right; the *heartbeat model* was the weak link. Fix: `AppState._refresh_active_leases`
  — if the lease owner's session is in `_BUSY_STATUSES`, `resources.touch_lease_activity()`
  rewrites `last_active_epoch` (throttled `_HEARTBEAT_MIN_AGE`=60s) under the **same
  `flock`** `bus.sh` uses (`fcntl.flock` on `<res>/.lock`), so it can't race
  reserve/release/promote. Excluded: the **GPU** (nvidia-smi tells the truth), offers,
  quiet owners, and **dead owners** (else an abandoned lease would look alive forever
  — the v2.16 orphan path must still see it). The broadcast payload sets `idle=0`
  immediately for a busy holder (the `idle` field mirrors the watchdog's `idle_since`,
  which lags a tick). **Watchdog**: now clears `nudged_epoch` when a lease drops below
  the nudge threshold, so a resumed heartbeat ends the idle *episode* — otherwise the
  refreshed `idle_since` would mint a new `_nudge_woken` key every scan and Conductor
  would re-wake the owner repeatedly. Honest caveat: a busy session might be working
  on something unrelated to the board — still strictly better than nudging busy
  sessions who can't hear us and never nudging anyone who can. 5 new tests (19 in
  `test_resources.py`, 108 total). Live-verified: `[docs]` was `warm` with an 828s-stale
  heartbeat → Conductor beat for it (`heartbeat for orin-agx on behalf of a working
  [docs]`), nudges stopped.
- ✅ v2.17.2: 🔧 Resource-name aliases + new-name warning (drift made impossible).
  `orin` drifted back a **second** time (and `imx95-evk` nearly did): a resource
  springs into existence on first reserve, so `/reserve orin` silently created a
  *separate* resource for the same physical Jetson — its own lease, its own queue.
  Found it holding a live `backend` soft lease **with 2 sessions queued** (`docs`,
  `orb_slam`). Migrated the whole lease (owner/mode/epochs/job/queue, order
  preserved) `orin` → `orin-agx` under both flocks, with the watchdog stopped for
  the move, then deleted the stray. Durable fix (Kyle picked "alias + warning"):
  `_res_canon()` maps known spellings to the canonical name (`orin|jetson|agx|
  orin64`→`orin-agx`, `imx95|imx95-evk|frdm-imx95`→`imx95-frdm`, `iq9|iq9075`→
  `iq9-evk`) and prints a note; `res_dispatch` canonicalizes the name arg for
  **every** verb (so `/res-request orin` joins the *orin-agx* queue — the split is
  now impossible); `res_reserve` warns loudly when creating a genuinely new name,
  listing existing resources (typo protection) while keeping the zero-registration
  property. Genuinely different hardware (Orin NX vs AGX) still gets its own name.
  Verified: alias on reserve/keep/release/status/request/promote, `/gpu-*`
  back-compat, no-arg status, hook lines, queue unification, send/check — all pass;
  live lease untouched.
- ✅ v2.17.1: 🪪 Stable session identity — `bus.sh` tags no longer drift with `cd`.
  **Found live** while verifying v2.17.0: `imx95-frdm` was held by `other:bench_data`,
  a tag matching no live session, so Conductor was ~10 min from flagging it as an
  orphan and offering a **reclaim button for a board actively running a GenAI
  benchmark**. Root cause: `bus.sh` derived TAG from the **current cwd** —
  projects in its explicit case-table matched subdirs (`*/keyhole/*`), but anything
  falling through to `other:$(basename "$CWD")` became a *new identity* whenever a
  session `cd`'d (`.../qualcomm/results/bench_data` → `other:bench_data`). Conductor
  meanwhile derives a tag from the session's stable **project dir** — so the two
  disagreed the moment a session changed directory. This also (a) made offer/nudge
  wakes unreachable for such leases, (b) fragmented bus identity (qualcomm's msgs
  arrived as `[other:bench_data]`), and (c) drew one session as two nodes in the
  History graph. Fix: new `_proj_root()` — a dir directly under `BUS_PROJECTS_ROOT`
  (default `~/Documents/GitHub`, env-overridable) resolves to **that project dir**;
  else the enclosing **git root**; else the cwd. Note git-root alone was NOT enough
  (Kyle's `qualcomm/` isn't a repo) — the first patch passed for `claude-connect`
  and failed for `bench_data`; the test caught it. Spliced into live + repo bus.sh
  (backed up). Verified: both `qualcomm/` and `qualcomm/results/bench_data` → 
  `other:qualcomm`; `claude-connect/conductor` → `other:claude-connect`; non-git dirs
  unchanged; explicit table still wins; send/check no regression. Migrated the live
  `imx95-frdm` lease owner `bench_data`→`qualcomm` under flock (otherwise qualcomm
  could no longer `/release` its own board). False orphan confirmed cleared.
- ✅ v2.17.0: 🔔 Wake an idle holder when the watchdog nudges it — closes the
  idle-detection loop. **Found live**: qualcomm held `iq9-evk` (hard) idle for
  75m; the watchdog nudged 3× (30m/50m/1h10m) and qualcomm *never saw a single
  one* — its session was alive but `status=idle`, and bus messages only surface
  through a session's **per-prompt hook**, which an unprompted session never
  fires. So the watchdog was talking into the void and the board stayed locked
  until expiry. Same class of problem the offer-wake solved (an idle session is
  only reachable by a keystroke, not a message) — we'd just never wired nudges to
  it. `read_lease` now exposes `nudged_epoch` + `idle_since_epoch`;
  `AppState._wake_nudged_owners` injects `/msg-check` into a nudged holder **once
  per idle episode** (keyed on `idle_since_epoch`, which the watchdog clears on
  activity — so a *new* idle spell wakes again, but the 20m re-nudge cadence does
  not spam focus). Refactored the two wake paths onto shared `_live_session_for`
  + `_inject_msg_check` helpers, and added a **busy guard** (`_BUSY_STATUSES` =
  active/warm, mirroring the frontend's ping guard) to *both* — never inject
  keystrokes into a Claude mid-task; skip without marking so it retries once
  quiet. Dead owner → left to the v2.16 orphan path. 5 new tests (14 in
  `test_resources.py`, 103 total). Kyle also had me wake qualcomm by hand first.
- ✅ v2.16.0: 👻 Orphan-lease surfacing + 1-click reclaim ("tier 2" of the reboot
  finding) — **and a serious tag-matching bugfix uncovered while building it.**
  Conductor knows which sessions are live, so a lease whose owner has no live
  session is *strong* (not certain — a session can be closed + relaunched)
  evidence of abandonment: `AppState._annotate_orphans` debounces (owner missing
  ≥ `bus.orphan_flag_seconds`, default **600s**, Kyle picked 10m to match
  `RES_ORPHAN_GRACE_MIN`) then marks the lease `orphan_suspect` +
  `owner_offline_seconds`; offers are skipped (they auto-pass). Tile shows
  `⚠ owner offline Xm` + a **reclaim** button → `POST /api/resources/{name}/reclaim`,
  which **refuses (409) unless the backend itself flagged the lease** (a live
  holder's lease can never be yanked from the UI) and then shells out to the same
  race-safe `bus.sh res promote` the watchdog uses (→ offers to the queue head,
  else frees). Conductor never reclaims autonomously — always Kyle's click, always
  confirmed. **THE BUG**: Conductor stores tags bracketed (`[other:qualcomm]`),
  `bus.sh` writes lease owners bare (`other:qualcomm`), so `s.tag == owner` NEVER
  matched. That (a) would have flagged *every* live owner as an orphan, and (b)
  meant **v2.15.0's real-time offer wake never actually fired** — it always fell
  through to the bus-message fallback (I'd misread the `rec is None` as "that
  session isn't live"). Fixed with a shared `_bare_tag()` used by both
  `_annotate_orphans` and `_wake_offered_sessions`; caught only by live-testing
  against the real fleet. Also fixed: `GET /api/resources` recomputed fresh state
  and so silently dropped the orphan flags — it now serves the same scan-cached,
  annotated payload the WS broadcasts. New `tests/test_resources.py` (9 tests,
  regression-guards the bracket/bare mismatch); 98 tests pass. Live-verified:
  live owner NOT flagged, ghost owner flagged, tile + button render.
- ✅ v2.15.1: ♻️ Boot-orphan lease reaping. **Found in production by a reboot**:
  a lease is a *file*, so it outlives the session that took it — after Kyle
  rebooted Skippy, qualcomm's **HARD** `iq9-evk` lease survived with ~3h left
  while its session was dead, and by design the watchdog *never* force-releases a
  hard lease, so it would have nudged a corpse every 20m for three hours while
  the board stayed blocked. Idle-time can't distinguish "owner quiet" from "owner
  dead". Fix uses a **certain** signal, not a heuristic: `acquired_epoch` earlier
  than the kernel's **boot time** (`/proc/stat` `btime`) ⇒ the owning process
  provably cannot exist. `resource-watchdog.sh` gains `_reap_orphan` — promotes
  the lease (hands it to the **next in the queue**, else frees) and posts a
  `[resource-watchdog]` explanation naming the old owner. A post-boot grace
  (`RES_ORPHAN_GRACE_MIN`, 10m) lets an owner who relaunches promptly re-anchor
  with `/keep` (which rewrites `acquired_epoch`) and keep it. `_promote` now
  echoes its outcome (`freed` / `offered:<tag>`) so the reap message states what
  happened; existing call sites silenced. Tested: orphan+no-queue→FREE,
  orphan+queue→offered to next, within-grace→untouched, post-boot lease→
  untouched, `/keep`-re-anchored→untouched. Freed the real orphaned lease live.
  (Possible follow-on "tier 2": Conductor knows which sessions are *live*, so it
  could surface an orphan even without a reboot — but only surface, never
  auto-reclaim a hard lease, since a session may be closed and relaunched.)
- ✅ v2.15.0: 🎟️ Reservation QUEUE + grace-hold hand-off + real-time wake.
  Kyle: "add a queue — a claude waits, gets a ping the moment the board opens,
  decides to use it or not; don't have 20 claudes polling." Design
  (AskUserQuestion): **grace-hold** (board is HELD for the next-in-line ~15m to
  claim/pass, else auto-passes) + **Conductor-inject wake with bus fallback** +
  **full build**. Key reframe pushed back to Kyle: no per-requester watchdogs —
  the *release* is one event; hook promotion there + reuse Conductor's existing
  /msg-check injection for the real-time wake. **bus.sh**: single `requested_by`
  → a FIFO `queue=` field; `/res-request` now JOINS the queue (deduped, reports
  position); on release/expiry/reclaim `_res_promote_locked` pops the head and
  writes an **offer** lease (mode=offer, owner=head, ~15m expiry, queue=rest) +
  posts a `[resource-broker]` "🎉 you're up" msg; new `/res-pass` declines →
  next; `res promote <name> <owner>` is a race-safe (owner-guarded) entry the
  watchdog calls; `_res_write` preserves the queue. Migrated into live+repo
  bus.sh via a tested splice (queue lifecycle, dedup, offer, pass, claim,
  promote paths, race-guard all scratch-tested first). **Watchdog**:
  resource-watchdog.sh now DRIVES the queue — offer-timeout / lease-expiry /
  idle-soft-reclaim all call `bus.sh res promote` (never holds a lock across the
  call; the idle block's fd-9 redirect had to wrap the whole `( … ) 9>lock`
  subshell, caught in test). **Conductor**: `read_lease` parses `queue`+`offered`;
  `AppState._wake_offered_sessions` injects `/msg-check` into the offered
  session the moment it's offered (once per offer, `_pinged_offers` set, bounded;
  untracked/not-live session → bus fallback, no error). Frontend: resource tile
  shows the **queue** (`⏳ N queued (X next)`) and a distinct **OFFER** state
  (blue pulsing dot + OFFER badge + "~Xm to claim"). Live-verified: offer tile
  renders; real fleet already using it (qualcomm reserved iq9-evk hard, watchdog
  nudging an idle Orin lease). Both editions.
- ✅ v2.14.0: 🎛️ Named-resource reservation — generalized the whole GPU
  reservation system to **any shared resource** (the GPU + dev boards like the
  Qualcomm IQ9 EVK). Driven by Kyle: "the IQ9 EVK is owned by qualcomm-claude but
  others want it." Design (AskUserQuestion): **generalize + add EVK** (not a
  one-off) + **heartbeat** idle-detection for non-GPU resources. **bus.sh**: the
  `gpu_*` block became generic `res_*` (lease at `bus-state/resources/<name>/`,
  parameterized by name via `_res_setup`); new `res)` case + `gpu)` kept as a
  back-compat alias (`/gpu-*` → resource `gpu`); the per-prompt hook now shows a
  line **per held resource** (`res_hook_lines`). Spliced into live + repo bus.sh
  via a tested migration (the generic core was scratch-tested first: multi-
  resource lifecycle, correct labels, 8-way race → 1 winner, heartbeat). New
  slash-commands `/reserve /release /keep /res-request /res-status` (+ kept
  `/gpu-*`). **Watchdog**: `gpu-watchdog.sh` → `resource-watchdog.sh` — loops all
  resources, idle = nvidia-smi util (gpu) OR time-since-`/keep` (others); soft
  auto-release, hard check-in only; systemd unit swapped
  (`gpu-watchdog.service` → `resource-watchdog.service`). **Conductor**:
  `conductor/resources.py` (`resources_state` reads all leases + nvidia-smi for
  gpu) replaces the single-GPU `gpu_state`; `"gpu"` WS msg → `"resources"`;
  `/api/gpu` → `/api/resources`; frontend renders a **tile per resource**
  (`fillResourceTile` generalizes `fillGpuTile` — util bar/mem only for the GPU;
  boards get a plain 🔧 lease tile). Path migrated `bus-state/gpu` →
  `bus-state/resources/gpu` (was free, clean). Live-verified: both tiles render
  (GPU free + iq9-evk hard/qualcomm/drone-sizer-waiting via a demo lease). 89
  tests pass. Backend + frontend + bus infra + live services; both editions.
- ✅ v2.13.0: `scripts/token-usage.py` CLI + README fresh-eyes pass. **CLI**: a
  standalone one-shot analyzer (self-contained, no `conductor` import) that sums
  transcript `usage` blocks per session/project/all — `python
  scripts/token-usage.py [path]`, `--json`, clean exit codes. Tested across a
  single session, a project dir, all-projects (Kyle's fleet: 67 sessions / 89K
  turns / 40.1B total), JSON, and bad-path. **README fresh-eyes pass** (cold
  newcomer agent read): version badge 2.8→2.13 (was 4 minors stale); gave the
  GPU system its **own "🎛️ Shared-GPU coordination" section** in Using-the-Dashboard
  (was one dense run-on bullet + an external link — the agent's #2 issue);
  documented the previously-unmentioned **global topbar token sum** + added the
  token line to the "what a tile shows" list + a "🪙 Token usage" section (with
  the out-vs-total explanation + the CLI); added the **NVIDIA/`nvidia-smi`**
  requirement (optional, GPU features only); tightened the swollen GPU/token
  Features bullets to one-liners pointing at the sections; unified 🎛️ (system) vs
  🎮 (tile). Docs + one script; no app-code change.
- ✅ v2.12.1: Token usage polish. Tile badge now literal `tokens: X out · Y total`
  (dropped the 🪙 coin — read as money; no universal token glyph). Added a
  **global token sum next to the "Conductor" title** (topbar-left group): sums
  every session's output + total (`tokens: 41.7M out · 12.5B total`), hover for
  turns + breakdown (`updateTokenTotal` in `tiles.js`, called from `renderGrid`).
  The out↔total delta is all input-side (new input + cache creation + cache
  reads), ~entirely cache reads (whole context re-read each turn — cheap), which
  is why total dwarfs out.
- ✅ v2.12.0: 🪙 Per-session token usage on each tile. Every session tile shows
  a badge (`🪙 617.3K out · 102.6M total`, humanized K/M/B) read from that
  session's transcript `usage` blocks; hover for the full breakdown (output /
  new-input / cache-creation / cache-read / turns / total). Kyle's ask ("record
  how many tokens a Claude has used"). `conductor/tokens.py` `TokenAccountant` is
  **incremental** — transcripts are append-only, so each poll seeks past bytes
  already counted and parses only new *complete* lines (a half-written trailing
  record is deferred, not lost/double-counted), making the per-scan cost O(new
  bytes) even for multi-MB, thousand-turn transcripts. Wired via
  `AppState.token_accountant`; `_sessions_payload` attaches `tokens` per record
  (uses `jsonl_path` before `to_dict` drops it). Frontend: `humanTok` +
  `tokenTooltip` + a `.tile-tokens` line in `fillSessionTile`. Note the honest
  framing — `cache_read` dominates the "total" (the whole context is re-read each
  turn; cheap, ~10% rate) so the tile shows **output** (real work) alongside
  **total** (raw processed). Verified: incremental == full-parse, partial-line
  safe, live screenshot. Frontend + backend, both editions.
- ✅ v2.11.0: 🎮 GPU tile (Phase 3 — Conductor now *visualizes* the GPU system).
  A live tile: GPU name + `nvidia-smi` utilization bar (cool/warm/hot), the
  current lease (soft=amber / hard=red dot, owner, **client-side ticking
  countdown** from `expires_epoch`), the watchdog's idle warning (`⚠ idle 40m`),
  and any pending request (`⏳ [orb_slam] waiting`) + the job note + mem
  used/total. Backend `conductor/gpu.py` (`query_nvidia_smi` + `read_lease` with
  the same lazy-expiry as bus.sh) → `AppState.gpu` polled each scan off-thread,
  broadcast as a `"gpu"` WS message (+ sent on connect) + `GET /api/gpu`. Tile
  only appears when `nvidia-smi` is present (`available`); renders like the Bus
  tile (`GPU_KEY`, `createGpuShell`/`fillGpuTile` in `tiles.js`, a 1s
  `updateGpuCountdowns` ticker). Live-verified via ffmpeg screenshot with a demo
  lease (util%, RTX 5090, HARD/95emulator/~24m, idle-40m, orb_slam-waiting all
  render). Completes the GPU arc: reserve (v2.9) → watchdog (v2.10) → visualize
  (v2.11). Frontend + backend, both editions. (Minor: on a very crowded board
  the tile cascades to a low slot — draggable, persists.)
- ✅ v2.10.0: 🐕 GPU idle watchdog (Phase 2 of the GPU-reservation system). A
  standalone daemon `bus/gpu-watchdog.sh` polls `nvidia-smi` and, when the held
  lease sits idle (utilization ≤ `GPU_IDLE_UTIL_PCT`, default 5% — "models loaded
  but not computing"), acts without the human: **nudges the owner** on the bus
  (a `[gpu-watchdog]` message their prompt-hook surfaces; re-nudges on a cadence,
  names any `/gpu-request`er) after `GPU_IDLE_NUDGE_MIN` (30m); **auto-releases a
  `soft` lease** past `GPU_SOFT_RELEASE_MIN` (60m) with a `to:all` heads-up; a
  **`hard` lease is never auto-released** (owner/user decides — watchdog only
  checks in). Real activity resets the idle clock (writes `last_active_epoch`);
  idle is surfaced in the awareness line too (`… · idle 40m ⚠`) via a
  `_gpu_held_line` update (both bus.sh copies). Shares the lease `flock`, so it
  never races reserve/release. Ships headless via a `systemd --user` unit
  (`bus/gpu-watchdog.service`, `%h`-relative, auto-restart, starts on login) —
  installed + enabled live. Tick logic verified with a mock `nvidia-smi`:
  active-reset, nudge, re-nudge cadence, soft auto-release, hard-preserve all
  correct. **Phase 3** (planned): a Conductor GPU tile. Bus-layer; no dashboard
  needed.
- ✅ v2.9.0: 🎛️ GPU reservation — sessions self-coordinate a shared GPU without
  Kyle arbitrating (MVP; his ask). The bus grows from message-passing to
  shared-*resource* coordination: a cooperative **lease** in
  `~/.claude/bus-state/gpu/lease` (flat key=value; owner/mode/acquired/expires/
  job/requested_by), acquire/release **atomic via `flock`** (stress-tested: 8-way
  race → exactly 1 winner). New `bus.sh gpu {reserve|release|keep|request|status|
  line}` subcommands + `/gpu-*` slash-commands (`bus/commands/`). **soft** =
  "I'll drop it if you need it" (preemptible); **hard** = "mine until my job's
  done or the user stops me". Duration + **lazy auto-expiry** (checked on access;
  a forgotten hold frees itself — no daemon needed). **Auto-awareness**: the
  existing per-prompt `prompt-check` hook appends a GPU line (`GPU: held by
  [95emulator] (hard · ~18m left)` / `YOU hold it — ⚠ [orb_slam] REQUESTED it`)
  **only when held** — silent when free, so zero added noise; nobody has to ask
  anyone. `/gpu-request` flags the owner (surfaced via their hook, no message
  needed). Added to the **live** `~/.claude/bin/bus.sh` + the sanitized repo
  `bus/bus.sh` (additively — `send`/`check`/etc. untouched, verified no
  regression) + `bus/README.md`. **Phase 2** (planned): a standalone `nvidia-smi`
  watchdog that auto-nudges idle holders (models loaded, ~0% util for a long
  time). **Phase 3**: a Conductor GPU tile. Bus-layer feature (works with or
  without the dashboard).
- ✅ v2.8.1: 🎨 Visual identity — logo + hero banner. A hand-built **Radiant
  Bus-Core** SVG logo (`assets/conductor.svg`, also `frontend/logo.svg`): a
  glowing violet bus core (`#bc8cff`, the app's `--bus-color`), six session nodes
  on an orbit ring in the tile/group palette, wires to each, one amber wire
  carrying a message pulse — the app's signature view distilled to a mark. Wired
  in everywhere: the install `.desktop` icon (already pointed at
  `assets/conductor.svg`), the topbar `<h1>`, the Settings header, and the
  favicon (`<link rel=icon>` — also kills the old `/favicon.ico` 404). Concept
  picked by Kyle from three (Radiant Bus-Core / Conductor's Baton / CC
  constellation); rendered + QC'd via librsvg (no rasterizer installed — used
  `gi.repository.Rsvg` + cairo). **README hero banner** (`assets/hero.png`,
  1280×640) — "mission control for AI agents," **commissioned over the bus from
  the `imagegen` fleet node** (its local RTX 5090 + ComfyUI rig): violet bus-core
  ringed by session panels with terminal snippets + status dots, violet cables,
  one amber cable with a pulse mid-flight, title + tagline. Matched to the logo
  palette; plus a 512² square crop (`assets/logo-square.png`). Fun full-circle:
  the dashboard that *visualizes* the bus commissioned its own art *over* that
  bus. Docs + frontend + assets, both editions.
- ✅ v2.8.0: 🧊 Rotate the History graph in 3D. A `🧊 3D` toggle in the History
  overlay spins the whole mention graph in space (Kyle's idea — "fun to rotate
  the ring to see how the clusters are set up"). Deliberately **not** the
  rejected whole-board *tilt* and **not** Three.js: a hand-rolled **SVG 3D
  projection** keeps `heatmap.js` pure-SVG/dependency-free. Each node gains a real
  `z`; a `project()` applies yaw (spin) + pitch (tilt) + weak perspective
  (`CAM_D`) and returns screen `sx,sy,scale,depth`. **project() is identity when
  3D is off AND at rest with a flat layout**, so the 2D graph is byte-for-byte
  unchanged (verified). Per-layout depth: **ring** stays flat (spin/tilt reveals
  crossings), **orbit** lifts into a **dome** (`tz = √(R²−rad²)`, loud=centered=
  high), **clusters** gains a 3rd force axis in `forceStep` (3D repulsion/spring +
  z-gravity toward the z=0 slab). Drag-to-orbit (window pointer handlers, pitch
  clamped so it never flips edge-on; a moved-drag suppresses the node-click so
  orbiting doesn't drill in) + a gentle idle **auto-spin** (`SPIN_RATE`, paused
  while dragging). Depth cues: near=big/bright, far=small/dim (`depthFade`);
  radius/edge-width/pulse scale by perspective. No depth-sorting of the DOM (small
  translucent nodes read fine; a known v1 tradeoff). Toggle persists (`LS_3D`);
  2D stays the default. Frontend only, lazily-imported overlay (a throw can't
  touch the 2D board), both editions.
- ✅ v2.7.1: `/rc` on relaunch is now opt-in (default off) + README fresh-eyes
  pass. The dormant-dock relaunch auto-injected `/rc` on every session — but
  that's Claude Code's `/remote-control` (drive the session from a browser/phone;
  needs a qualifying plan + `/login`), an opinionated side effect Kyle had
  forgotten was there (it came from his original spec: "enter /rc so its remote
  controlled"). Now `[relaunch].rc` (default `false`) gates it, alongside the
  existing `rename` — with both off (the default) relaunch is a clean
  `claude --continue` with **zero keystroke injection** (`_bootstrap_relaunched`
  short-circuits when `not cmds`, and `relaunch_parked` doesn't even schedule it).
  `rc`/`rename` are settings + per-request `/api/relaunch` overrides. **README
  fresh-eyes pass** (read as a dev new to the ecosystem): version badge → 2.7,
  defined `/rc` (was undefined jargon), fixed the "read-only" contradiction
  (→ "read-only *toward Claude*"; the few actions are external + user-triggered),
  glossed "tilix", "binary"→"app", added the `install-app` feature bullet,
  "on the tunnel"→"on the bus". Backend + docs, both editions.
- ✅ v2.7.0: `make install-app` (staged desktop install) + settings polish.
  **Staged install**: `make install-app` copies the app (entry, backend, served
  frontend, icon, and the `claude-tracked` relaunch helper) into
  `~/.local/share/conductor/`, builds the WebKitGTK venv THERE, and points the
  `.desktop` launcher at that copy — so the **cloned repo becomes disposable**
  (the prior `install-desktop` runs out of the clone). `app.py` now
  `sys.path.insert(0, <its dir>)` before importing `conductor`, so the staged
  copy imports its co-located package + serves its own `frontend/` regardless of
  launch cwd or a stray clone editable — verified clone-independent (resolves to
  the staged home from a foreign cwd). Overridable `APP_HOME` / `APPLICATIONS_DIR`
  (tested against a scratch dir end-to-end: copy → `--system-site-packages` venv
  → editable `pip install` → `.desktop` gen). `make uninstall-app` removes it.
  NOT a sandboxed package (Flatpak/Snap would hide host processes from `psutil`
  and break session discovery — Conductor is a host-automation tool) nor a
  single-file binary; it's a self-contained local install. Design fork chosen by
  Kyle over AppImage (staged = 90% of the benefit, ~zero new tooling). README
  "Two ways to install it" table added. **Settings polish**: the settings
  dropdowns showed their value in WebKitGTK's dim native-control color (looked
  like unset placeholder) — `appearance: none` + custom caret so the current
  choice renders in bright `--text`; and a **version label** in the settings
  header (`#settings-version`, fetched from `/api/health`, matches the release
  tag). Backend untouched for settings; both editions.
- ✅ v2.6.1: Dormant-dock drawer no longer fights the cursor. When parked chips
  overflowed, the bottom dock's `overflow-x: auto` drew a **fade-in overlay
  scrollbar** (WebKitGTK native edition) right on top of the chips' ✕ buttons —
  so reaching for a dismiss ✕ summoned the scroll thumb under the cursor (Kyle
  caught it live). Fix in `style.css`: styled `::-webkit-scrollbar` (thin, 8px,
  always-present in a reserved gutter — opting out of the overlay), added bottom
  padding (`8px 12px 14px`) to lift the chip row clear of that gutter, and gave
  `.parked-dismiss` a bigger/taller hit area + hover highlight. CSS-only, both
  editions. Verified by Kyle in the live native window (sandbox can't render
  WebKitGTK — see the no-live-HTTP constraint).
- ✅ v2.6.0: 💤 Dormant dock — relaunch a closed session in one click. Sessions
  Kyle closes don't vanish: every project dir with on-disk history but no live
  process now surfaces as a chip in the bottom dock (a "💤 Dormant" group after
  the minimized tiles). **Clicking it relaunches that session** — opens
  `claude --continue` in its original folder in a tracked Tilix window, then,
  once the new session appears and its TUI settles, **injects `/rc`** (and
  optionally `/rename`) so it comes back remote-controlled with its identity
  intact. Backend: `discover_parked_projects(projects_root, tag_map, live_cwds)`
  (`scanner.py`) walks each project dir, resolves the cwd its newest transcript
  last ran in, and skips cwds that are currently live, folders deleted off disk,
  or unreadable transcripts (dedups multiple encoded dirs → same cwd, newest
  wins, capped 40). Surfaced as `ParkedSession` on the `sessions` payload.
  `POST /api/relaunch {project}` (path-validated to the projects root, refuses if
  a session is already live there) → `AppState.relaunch_parked` spawns
  `claude-tracked <name> --dir <cwd> --continue` detached, then schedules
  `_bootstrap_relaunched`, which **polls the scanner for the new live session**
  before injecting (the flaky part — keystrokes only land once the TUI is up;
  timing knobs in `[relaunch]` settings: `settle_seconds`, `between_seconds`,
  `appear_timeout_seconds`, `rename`). `scripts/claude-tracked` gained `--dir`
  (cd's first so `--continue` resolves to the right folder; legacy callers
  unaffected) and — caught during Kyle's live test — switched its tilix launch
  from `-- <cmd>` to `-e <cmd>`: when a tilix server is already running (always,
  if you have other windows open) the single-instance invocation **silently
  drops** a `--`-style command and opens a bare shell, so claude never launched
  and there was nothing to inject `/rc` into; `-e` is honored by the running
  server. Frontend: `parkedChip` in `tiles.js` (dashed dock chip, 💤 + name
  + tag + last-active age, click→relaunch with optimistic "launching…", trailing
  ✕ to dismiss); dismissals persist (`conductor.parkedDismissed.v1`) and
  **auto-clear when that folder goes live again** ("auto + dismiss"). New live
  session removes the chip on the next scan. **Note:** spawn + keystroke
  injection are X11/terminal-level and can't run in the sandbox — pure logic
  (`discover_parked_projects`, dedup, limit, exclusions) is unit-tested; the live
  click path is hand-verified. Backend + frontend, both editions. **Scope: tilix
  only** (same as v2.1.2 focus).
- ✅ v2.5.1: 📬 Honest unread badge for never-checked sessions.
  `compute_pending` (`bus.py`) returned 0 for any tag with no `<tag>.last-seen`
  file, so a prolific sender that had never run `prompt-check` (never
  self-checked, never pinged) showed an empty 📬 badge while real messages piled
  up — the `95emulator` blind spot Kyle caught (chatty on the bus, badge stuck
  at 0). **Fix A**: when no `last-seen` exists, infer the baseline from the tag's
  own *latest sent message* — a session that just posted has demonstrably caught
  up to that moment, so only later messages from others count as unread. A tag
  that never sent AND never read still yields 0 (no basis for "unread"; don't
  dump all bus history on a brand-new session's first contact). A real
  `last-seen`, once written by that session's first check, supersedes the
  estimate. Also adds `scripts/bus-backlog` — a read-only diagnostic that prints
  the real backlog per tag and *why* each badge reads what it does
  (`read` / `inferred` / `NEVER`), for when a tile looks suspiciously quiet.
  Backend-only computation shared by both editions, so no frontend change.
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
