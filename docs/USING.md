# Using Conductor

The full tour of the dashboard. For install and first run, see the [README](../README.md); for the
native app and phone setup, [INSTALL.md](INSTALL.md).

- [Using the dashboard](#using-the-dashboard)
- [Reliable terminal focus](#reliable-terminal-focus)
- [What's stored, and where](#whats-stored-and-where)
- [Disaster recovery](#disaster-recovery)
- [How it works](#how-it-works)

## Using the dashboard

### Tiles

Each tile is one live Claude session. It shows:

- **Status dot** — `active` (writing now), `warm` (recent), `idle`, `dormant`, `waiting` (on user input), `ended`
- **Squashed live preview** of the latest message
- **Message count + time since last activity**
- **📬 bubble** — appears when this session has unread bus messages (only if the [bus](../README.md#wire-up-the-bus-optional) is wired up)
- **Tag chip** (e.g. `[backend]`) — its bus identity, and a click-toggle for [Active/Passive](#active--passive) membership
- **Token line** (`tokens: 617K out · 103M total`) — this session's usage from its transcript; hover for the breakdown (see [Token usage](#-token-usage))

**Drag** a tile to move it; **drag the bottom-right corner** to resize it; the **`–`** button minimizes it to the bottom dock. Hover a truncated title to see it in full. Position, size, and minimized state persist across restarts.

### Minimize / dock

Click a tile's **`–`** to tuck it into a thin **dock** along the bottom — a tiny chip with its status dot, name, and 📬 badge. It's still monitored (the dot keeps updating; a new message still lights the badge), just out of the way. Hover for the full name; **click the chip to restore** it to its previous position and size. Minimized tiles' bus wires are hidden to keep the board clean.

### 🪙 Token usage

Every session tile shows its token usage, read straight from that session's transcript (the same numbers Claude Code shows per command):

```
tokens: 617K out · 103M total
```

- **`out`** = tokens the model *generated* (the real "work done").
- **`total`** = everything *processed* = `out` + all input. The gap is almost entirely **cache reads** — the whole conversation is re-read as input every turn (cheap: cached input bills at ~10% of fresh), which is why `total` dwarfs `out`.
- **Hover** the line for the full breakdown (output / new input / cache creation / cache reads / turn count).
- A **global sum sits next to the "Conductor" title** in the top bar — every session added up (`tokens: 41.7M out · 12.5B total`).

Prefer the terminal? [`scripts/token-usage.py`](../scripts/token-usage.py) reports the same, for any scope:

```bash
python scripts/token-usage.py                    # every project under ~/.claude/projects
python scripts/token-usage.py <project-dir>      # one project's sessions
python scripts/token-usage.py <session.jsonl>    # a single session
python scripts/token-usage.py --json             # machine-readable
```

### 🚀 Session launcher — find and relaunch a closed session

Any project folder Conductor has seen — one with transcript history but **no live process right now** — is *dormant*. The bottom dock shows one button, **💤 N dormant `Ctrl+K`**; it, the header's **⟳ Relaunch**, **Ctrl+K**, or **/** (anywhere that isn't a text field) opens the **launcher**: a search box with focus, and below it every dormant session grouped **★ Pinned / Today / This week / Older**, plus the live ones in their own group.

![The session launcher — search box, pinned sessions, then Today and This week groups, each row with its folder, age and tokens](../assets/screenshot-launcher.png)

- **Type to filter** over name, bus tag and folder — a few letters is enough. **Enter** acts on the highlighted match: relaunch a dormant session, or *focus* a live one. **↑/↓** move, **Esc** closes.
- **Relaunch** opens **`claude --continue` in the session's original folder** (in a tracked terminal via `scripts/claude-tracked`) — a clean resume, not a blank session. The row shows "launching…" until the live tile takes its place.
- **Bring a fleet back after a reboot:** tick several rows and **Relaunch selected** (or `Ctrl+Enter`). They launch one at a time, so twenty sessions don't stampede the box. Sort by tokens to see which heavy sessions may auto-compact on resume.
- **★ Pin** what you come back to; **✕ Hide** what you won't. Hidden sessions move to a *Hidden* section rather than vanishing, a search still finds them, and a hidden folder un-hides itself the next time you actually run a session there.
- **Synced everywhere.** Pins and hides are stored by Conductor (`coord/launcher-prefs.json`, `GET/POST /api/launcher-prefs`), so the desktop board, the native app and the phone agree.
- **Auto-discovered** — no list to maintain; the 40 most-recently-active folders.

| Search finds dormant *and* live sessions | On the phone (`/m` → Fleet) |
| :---: | :---: |
| ![Typing "fw" finds a dormant session to relaunch and a live one to focus](../assets/screenshot-launcher-search.png) | ![The phone launcher — pinned sessions, each with Hide and Relaunch buttons](../assets/screenshot-phone-launcher.png) |

On the phone, the Fleet tab shows a single **💤 N dormant** row that opens the same launcher full-screen; **Relaunch** there also runs `/rc`, so the session comes back visible in the Claude app.

- **Keystrokes after relaunch** (in the `[relaunch]` block of `settings.toml`): `rc` auto-runs **`/rc`** — Claude Code's `/remote-control`, which makes the resumed session drivable from a browser/phone (needs a qualifying plan + `/login`) — and is **on by default**, so a relaunched session comes back remote-controllable and visible in the phone app instead of looking crashed. `rename` re-issues `/rename` and is **off by default** (its injection is timing-flaky and it overwrites a session's own title with the derived tag; `--continue` keeps the prior name anyway). `/rc` opens a **Remote Control menu** that blocks the session until answered, so Conductor presses **Esc** to dismiss it *(2.39)* — never Return, which would *select* an option, one of which is "Disconnect this session". Injection also **retries while you're at the keyboard** (Conductor won't type into a session while a human is active, and a relaunch is started by your click). Timing knobs: `settle_seconds` (wait for the TUI before typing), `appear_timeout_seconds`, `between_seconds`.

> When `rc`/`rename` are enabled, keystroke injection is **best on tilix** (like [click-to-focus](#reliable-terminal-focus)) and needs `xdotool` — it briefly **steals focus** while typing. Relaunch itself (the spawn) works anywhere: it goes through `scripts/claude-tracked` — found on your `PATH` or used straight from the repo — which uses `tilix -e` so the command runs even when a tilix server is already open.
### Groups

For a crowded board, organize sessions into **named, color-coded groups**. Each tile has a **▦** button that opens a small menu:

- **▦ → New group from this** (prompts for a name) — or **Add to ▸ {group}** to join an existing one. A tile belongs to one group; members get a colored top accent.
- On a grouped tile: **Rename group**, **Move to ▸ {other}**, **Remove from group**, or **Minimize group** — which folds the *whole* group into a single dock chip (swatch + name + member count + active dot + total 📬). Click the chip to expand it back.
- The **▦ Groups** panel (top bar) lists every group to rename, recolor, minimize/restore, or ungroup.

Groups are *logical* (members keep their own positions — they aren't auto-arranged) and persist across restarts.

### 🧊 3D view

Click **🧊 3D** in the top bar to lift the board into a 3D scene; click **🗔 2D** to come back. **2D is the default** and stays untouched — 3D is an optional view, and your choice (plus the last layout) is remembered.

- **Navigate** — *drag* to orbit the camera, *scroll* to zoom. Click a card's **▶** to focus its terminal, or its tag chip to toggle Active/Passive, just like 2D.
- **Cards always face you.** No matter how you orbit, every card is billboarded toward the camera so the text stays readable — depth and motion live in the *space between* sessions, never in the angle of the content.
- **Groups become places.** Cards carry their group color (border + glow), and group members physically **cluster together** in the scene. The glowing **bus core** sits at the center with wires fanning out (solid = active, dashed = passive), pulsing on each message.
- **Three layouts** (switcher floats at the bottom):
  - **Carousel** *(default)* — sessions on a ring you spin through; the front card is enlarged and in focus.
  - **Orbital** — sessions orbit the bus core on a sphere; each group shares an arc.
  - **Gallery** — your saved 2D positions lifted into depth (active sessions float forward, idle recede), with groups pulled into tight clumps.

> The 3D view loads Three.js from a CDN the first time you open it (no build step). Offline or CDN blocked? It cleanly falls back to 2D with a notice — the 2D board never depends on it. Assign/rename/recolor groups from the 2D **▦** menu; 3D visualizes whatever's set.

### 🕸 History (time-lapse)

Click **🕸 History** in the top bar to replay your whole cross-session bus as an animated graph — *who talked to whom, and when*. It sweeps the live log **and every monthly archive**, so it's the full story, not just what's on screen now.

- **Sessions are nodes** that fade in the moment each one first speaks, and stay (dimmed) once they go quiet — so you watch the network *populate* over weeks.
- **Lines are mentions.** The bus is broadcast-only, so an edge means *one session named another* in its message — the real "who's addressing whom" signal. Line thickness = how *often* that pair talks; a **pulse-dot** flies the wire on each message, sized by the message's **length** (a fat packet for a multi-KB status report, a speck for a quick "hi").
- **Three layouts** (switcher at the bottom-left):
  - **Clusters** *(default)* — a live force layout. Mention-edges act like springs, so **frequent partners drift together** and clusters tighten as traffic accumulates during playback.
  - **Ring** — every session on a circle in arrival order; stable and fully labeled.
  - **Orbit** — radial by volume: the loudest sessions pulled to the center, quiet ones on the rim.
- **👤 Human turns** *(2.4)* — toggle this to weave in the **human↔Claude** layer: a **you** node (labeled with your username) plus *your* prompts and each session's replies, read turn-by-turn from the `~/.claude/projects` transcripts and merged onto the same timeline. Human edges are **gold/dashed** to set them apart from the inter-Claude mention lines, so you can watch a day of work flow — *a prompt fires to a session, it posts to the bus, another replies*. In **Clusters** layout the sessions you talk to most drift in toward you. (Turn-level: each exchange is one prompt + one reply, not every streaming chunk. Only *genuine* typed prompts count — harness injections like system-reminders, slash-commands, and auto-compact summaries are filtered out.)
- **🔬 Drill-down** *(2.5)* — with Human turns on, **click a session node** and watch the whole **you↔session working relationship** replay: a **you** node fires each of your prompts into the central session node, which **explodes outward** into the work it did — the **files** it touched (a deduped halo, read = blue / edited = orange, growing with each touch), the **sub-agents** it spawned (Agent/Task, labeled by type), and every **tool call** firing a pulse + ticking a live counter (`Bash ×N · Grep ×N · …`). `tool_result` failures tint red. Hit **🔍 Focus prompt** to isolate a single exchange at a time (the `● focused ✕` chip returns you to the whole relationship). Its own play/scrub/speed controls; **← Back** to the timeline.
- **🧊 3D** *(2.8)* — toggle to **rotate the whole graph in space**: drag to orbit, and it idles with a gentle spin. Each layout gains real depth — **ring** tilts and spins, **orbit** lifts into a **dome** (loud sessions centered/high), **clusters** spreads into a 3D cloud — so you can see a tangle of links from any angle. Still pure SVG (a hand-rolled projection, no WebGL); 2D stays the default.
- **Drive it** — play/pause, drag the **scrubber** anywhere, and pick a speed (**0.25× / 0.5× / 1× / 2× / 5×**). A live clock shows the date as history unspools.

> Pure SVG, no dependencies — `heatmap.js` (and `drilldown.js`) are lazily loaded on first open, so (like 3D) they can never affect the 2D board. Read-only: it just visualizes the bus log + transcripts you already have. The human layer reads the same `*.jsonl` Conductor already tails for live previews; older turns past a cap are trimmed (the count is shown, never silently dropped).

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

> Requires the data-file-aware `bus.sh` (the shipped [`bus/bus.sh`](../bus/bus.sh) reads `active-tags`, falling back to its built-in `BUS_WHITELIST` when the file is absent). If you wired up the bus before this, re-copy `bus/bus.sh`.

### 🎛 Shared-resource coordination

If several of your Claudes share a scarce resource — one GPU, a dev board (an
IQ9 EVK, …), any single-holder rig — the bus can arbitrate it so they
**coordinate themselves and you never have to be the middleman.** Each resource
is a named cooperative *lease* (state in `~/.claude/bus-state/resources/<name>/`,
atomic via `flock`), and it has four parts:

1. **Reserve / release, from any session** — slash-commands the Claudes run, with
   the resource named: `/reserve <name> <dur> <soft|hard> ["job"]`, `/res-status`
   (read-only — all resources at once), `/release <name>`, `/keep <name> <dur>`,
   `/res-request <name>`, `/res-pass <name>`. (`/gpu-*` still works as an alias for
   the `gpu` resource.) Nobody has to ask anyone: the current holder of every
   resource is **injected into each session's per-prompt context** automatically.
2. **Two honest hold modes** — the signal that makes it work:
   - **soft** — *"I've got it + code/board set up, but I'll drop it if you need it."* Preemptible; `/res-request` nudges the holder.
   - **hard** — *"mine until my job's done or you stop me."* Not preemptible; requesters queue. Leases carry a duration and **auto-expire**, so a forgotten hold frees itself.
3. **A queue with a grace-hold hand-off** *(new in 2.15)* — can't have it now? `/res-request` puts you in a **FIFO queue** instead of polling. When the holder releases (or the lease expires, or an idle soft lease is reclaimed), the **next in line is automatically offered** the resource — it's *held for them* for a grace window (~15m) to `/reserve` (claim) or `/res-pass` (skip → next); if they don't respond it auto-passes. And the moment it's offered, **Conductor injects `/msg-check` into that session** so it wakes and sees "🎉 you're up" in real time (a bus message is always posted too, so an untracked session still learns on its next prompt). No polling, no you-in-the-middle.
4. **An idle watchdog** — a small headless daemon ([`bus/resource-watchdog.sh`](../bus/resource-watchdog.sh), run via `systemd --user`) watches every held lease. It judges *idle* by **`nvidia-smi` utilization** for the GPU, and by the **`/keep` heartbeat** for other resources (run `/keep` while you're actively using a board). Past a threshold it **auto-nudges the owner** (naming who's next in the queue) and **auto-reclaims an idle `soft` lease** — handing it to the next in line — while a `hard` lease is only ever checked in on, never force-released. And because a bus message only reaches a session through its *per-prompt hook*, an
idle holder would never actually read the nudge aimed at it — so Conductor **wakes
the holder** (injects `/msg-check`) when the watchdog nudges it, once per idle spell
and never mid-task. The watchdog is also what fires the grace-hold auto-pass and expiry hand-offs above, and it **reaps orphaned leases after a reboot** — a lease is a file, so it outlives the session that took it; one acquired before the kernel's boot time has a provably dead owner, so it's handed to the next in queue (or freed) instead of blocking the resource until it expires.

Conductor also **spots abandoned leases** *(new in 2.16)*: it knows which sessions
are live, so a lease held by a session that's no longer running gets flagged on its
tile (`⚠ owner offline 12m`) with a **reclaim** button that hands the resource to
the next in queue (or frees it). It never reclaims on its own — a session can be
closed and relaunched, so the call is yours. (After a *reboot* the watchdog doesn't
need to guess: a lease older than the boot is provably orphaned, and it's reaped
automatically.)

Conductor **visualizes** each shared resource as a live tile on the board: the
holder (soft = amber / hard = red dot, offered = blue pulse), a ticking countdown,
the watchdog's idle warning, the **queue** (`⏳ N queued`), and the job note. The **🎮 GPU tile** additionally
shows the GPU name + `nvidia-smi` utilization bar + memory (it appears whenever
`nvidia-smi` is present); board tiles appear once the resource has been reserved.

> Full command reference + install (the daemon, the slash-commands, thresholds)
> is in the bus docs: [**Resource reservation**](../bus/README.md#resource-reservation-shared-gpu-boards-any-single-holder-rig).

### 🔗 Autonomy windows ("let them talk")

Auto-delivery (the 📨 wake) only fires when *you're not the one at the keyboard* —
by default a quiet session parked at its prompt is treated as **attended** (you
might be typing there), so it's left alone. That's the right call when you're
present and exactly what forces hand-clicking when you're not. An **autonomy
window** is a scoped, time-boxed way to say *"I'm away from these keyboards — let
them wake each other"*:

- Click **🔗 Let them talk** in the top bar, click the tiles to include (a pulsing
  ring → a green ✓), pick a duration, and go. On the phone, tick the members from a
  list. Green connectors show the live window on the board.
- **What it lifts, and what it never lifts:** it lifts only the *attended* guard —
  a **busy** Claude mid-task is still never interrupted. Only **directed** mail
  (`to:<tag>`) wakes anyone, so even a 30-member window can't storm itself; a
  non-member can never wake you; and the window **expires** on its own. The
  time-box is the safety property.

### 🩺 Fleet-health signals

Five fleet-health signals a plain dashboard glance misses. Three are states an
unread-message **count** cannot tell apart — *"deliberating"*, *"has nothing to say"*,
and *"isn't running"* are all the same number going up — plus one for a session that's
**alive but unreachable**. Conductor surfaces each directly (found by *running* a real
fleet, v2.35–2.36):

- **🪪 Identity collision** — the bus tag is derived from a session's directory, so
  **two** Claudes in one repo post under **one** name and become indistinguishable.
  Conductor counts live `claude` **processes** per directory (not deduped records —
  the dedup is exactly what hid it) and, on a clash, shows a card with **what each
  session is doing** (last activity + a preview), because *"one active 9m ago
  building X, one 31m ago on Y"* is a decision and a bare repeated name isn't.
- **💀 Dead-reader alarm** — a tag **others are actively addressing** that has
  **itself posted nothing for hours** is a reader that may no longer exist, with
  mail piling up behind it. Conductor annotates it live/dead (no process + an open
  ask ⇒ a human must relaunch it) and surfaces it on the desktop and phone. *A
  watcher whose absence is silent is not a watcher.*
- **🕸 Phantom-stall fix** — the mutual-stall detector now draws a wait-for edge
  **only** when *A asked B a question B hasn't answered* (a real open ask), never
  merely because *B has unread mail*. On a fleet where a message often names 5–10
  recipients, a session that's just **cc'd** is no longer threaded into a stall it
  has no part in.
- **📵 Lost-`/RC` alarm** *(2.36)* — a session that's **alive but dropped its
  remote-control bridge** vanishes from the phone's Claude app and *looks* crashed —
  which is how you end up launching a replacement and putting **two** sessions in one
  repo. Conductor watches the *process*, so it says *"alive, lost `/RC` Nm ago —
  reconnect, don't relaunch."* Fires only on lost-it (was bridged, aged past a
  threshold), so it isn't noise; the relaunch guard's refusal also names the live one.

- **📪 Not reading its mail** *(2.41)* — a **live** session sitting on mail addressed to
  it that it hasn't read in hours. The obvious version of this alarm is a firehose, and
  that was **measured before shipping it**: raw cursor age fires on **36 of 36** cursors
  here and **17 of 17** live sessions — a lagging cursor is the *normal* state of a
  session nobody is talking to. So the trigger is **harm, not housekeeping**: mail
  *addressed to you*, unread past a threshold. On the same snapshot that fires on **7**.
  A mass-cc doesn't count — being cc'd is not a debt.

Conductor pages your phone (Web Push) on exactly **two** things — a session blocked
on a *question*, and a *gated push*. Dead-reader is a surfaced signal, not a page,
by default (a third alarm is an opt-in — `[bus].page_dead_readers`).

### 🔒 The two hard controls — push gate & persistence gate

Everything else Conductor does toward Claude is a nudge; these two are enforced
**gates**, and they guard the same property: **an act whose consequences outlive
the session that committed it.**

- **🔐 Push gate** — nothing reaches a repo without your tap. A Claude Code
  `PreToolUse` hook denies a `git push` unless a valid one-per-push approval token
  exists; the denial files a request into Conductor's inbox (desktop + phone), you
  approve in one click, and the token is consumed on use. Commits stay free — only
  pushes are gated — and it's an instant no-op for any non-push command. A session
  can also `/push-propose` (*"ready, or keep digging?"*) so you decide **with** the
  commits and its reasoning in front of you.

  **The three steps** *(2.41)* — printed by the gate itself at the moment it stops a
  session, so nobody has to be told and nobody improvises:

  1. **Finish committing, then attempt.** Being denied *is* how the request reaches you.
     A commit made *after* the request invalidates the approval — correctly: you approved
     a tip, and the tip moved.
  2. **Tell you once, then wait.** *Never* ask permission first — that is the whole loop:
     you say yes, there is nothing to tap because nothing is filed, the push is denied,
     and you tap anyway. Two of your interactions where one would do.
  3. **Re-run, verify it landed, report the sha.** Approved is not pushed.

  Two accounting bugs that used to eat taps went with it: a push the remote **rejects**
  no longer spends the approval (the hook predicts a non-fast-forward from the remote sha
  and refuses *without consuming*), and a **clean rebase keeps** it — the grant is pinned
  to `git patch-id`, invariant across a rebase exactly when the diff is unchanged. A
  rebase whose conflict resolution *altered* a diff still asks again.
- **🔒 Persistence gate** — the same shape for a *capability* that outlives the
  session: writes to `~/.claude/bin`, `settings.json` (a hook there is fleet-wide
  code on every tool call), systemd units, crontabs. The grant is bound to the
  **action**, not conveyed in prose — *"the user approved this"* in a message is still a
  deny. It ships **disarmed**, and there's a **plain-terminal escape hatch** so a
  hook can never lock you out of your own machine. Full detail:
  [`docs/PERSISTENCE_GATE.md`](PERSISTENCE_GATE.md).

A related lighter-weight control is **🛑 retraction** — a session that told another
*"do X"* and realized it's wrong runs `/retract` (or `/supersede`); the recipient is
woken **immediately, even mid-task**, and sees a loud warning before it acts.

### ✉ Compose

Click **Compose** in the top bar to send your own message on the bus — like email for your sessions. You're a first-class sender (tagged `[operator]` by default; set `bus.sender_tag` in `settings.toml` to your name).

- **All sessions** (default) — a broadcast everyone sees.
- **Specific sessions** — uncheck "All" and pick recipients. The message is soft-addressed with a leading `@to [tag] …` line, so receivers (and the dashboard's connection-line animation) know who it's for. It's still on the shared log; addressing is advisory, not private.
- **Ping recipients** — also injects `/msg-check` into the chosen sessions so they read it immediately (specific recipients only — broadcast-ping would steal focus across every window). `Ctrl/⌘+Enter` sends.

> Sending makes Conductor a *writer* on the bus (it still never touches Claude's own state). Requires the markdown bus adapter.

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

## Reliable terminal focus

A single terminal server (Tilix, `gnome-terminal-server`) owns all its windows, so they share one PID — and a tiled window shows only the *active* tile's title at a time. So matching purely on **window title** is ambiguous: a backgrounded tile has no title of its own on the window, and a stray same-named terminal (e.g. a shell `cd`'d into the project dir) can win the match.

**Tilix gets an exact path.** Each tilix tile stamps its shell with a `TILIX_ID` env var, so Conductor reads that UUID from the Claude process and tells tilix (over its `com.gexperts.Tilix` D-Bus interface) to focus that precise tile — **raising the window *and* switching to the exact tile**, even inside a combined/tiled window where several Claudes share one window. No wrapper, no setup; it just works if you run Claude inside tilix.

> Scope: this exact-tile path is **tilix-only** and only tested on tilix. Other terminals fall through to the title-matching path below — no regression, just less precise.

For non-tilix terminals, focus falls back to **window-title matching**, and the optional `claude-tracked` wrapper in [`scripts/`](../scripts/) gives each Claude its own window with a unique X11 title so focus and 📬 injection target precisely:

```bash
sudo install -m755 scripts/claude-tracked /usr/local/bin/
claude-tracked api-server --resume
```

Without either the tilix path or the wrapper, focus is best-effort: Conductor raises the terminal window owning the Claude PID, but can't switch between tabs packed into one window.

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
| `conductor.heatmapLayout` | 🕸 History layout (clusters / ring / orbit) |
| `conductor.heatmapHuman` | 🕸 History — whether the 👤 Human layer is on |

Layout/minimize/group state is keyed by **project directory**, so a session re-attaches to its saved spot, size, and group whenever it runs in the same directory — across reboots and even fresh (non-resumed) sessions. Conductor doesn't prune offline tiles' layout, so it waits for them to return. Clear it with **Reset layout**, **Ungroup**, or your browser's site-data tools.

**On your machine, not the browser:** the launcher's ★ pins and hidden sessions (`<bus state>/coord/launcher-prefs.json` — shared by every device); the cross-session bus log (`~/Documents/claude-bus/messages.md`), unread state (`~/.claude/bus-state/`), and the active/passive whitelist (`~/.claude/bus-state/active-tags`). The Conductor server itself is **in-memory and restart-clean** — it holds no persistent state of its own.

---

## Disaster recovery

*Optional.* The Conductor **server** is restart-clean, but the fleet you've built up — the bus tooling, coordination state, per-session memory, and each session's conversation — lives in `~/.claude` and would be lost if the machine died. Disaster recovery backs that up off-box and gives you a one-screen rebuild on a new machine.

**What's backed up, and how often:**

| What | Where | Cadence |
| --- | --- | --- |
| The `~/.claude` **coordination layer** — bus tooling, `bus-state/` (tags, members, leases, watermarks), per-session memory, hooks, systemd units | a **private `fleet-backup` GitHub repo** | **hourly** |
| Your session **transcripts** (the `claude --continue` fuel, ~1 GB) | a compressed **release asset** on that repo | **daily** |
| A **roster** (`fleet-roster.json`) — every session's cwd, git remote/branch, tokens, transcript | the same repo | with each snapshot |

Backups run as `systemd --user` timers, so they're automatic and survive reboots. Big model files are captured as a re-download **manifest**, not blobs.

**Restoring on a new machine** (same home path, e.g. `/home/<you>`):

1. **The backup repo is one you create** (private). This repo provides the pieces: `scripts/fleet-roster.py` (the roster), `scripts/backup-transcripts.{sh,service,timer}` (the daily transcript upload), and the Reconstitute screen. Restore `~/.claude` from your backup, then start Conductor; the steps you can't automate are `claude /login` and `tailscale up`.
2. Open Conductor and use the **🧯 Reconstitute** screen (on the desktop *or* your phone at `/m`) to pick which sessions to bring back. For each, it clones the repo (if needed) and resumes the conversation with `claude --continue`.

Note DR backs up the **bus/coordination state and transcripts** — not the in-memory Conductor server (which needs no backup; it rebuilds itself from what it observes).

---

## How it works

For the curious:

1. **SessionScanner** enumerates Claude Code processes via `psutil`, resolves `/proc/<pid>/cwd`, and walks `~/.claude/projects/<encoded>/` to find each session's `*.jsonl`.
2. **ActivityWatcher** uses `watchdog` (inotify on Linux) to react to jsonl writes without polling.
3. A **WebSocket hub** at `/ws` fans updates out to the browser: a session + bus update every `scanner.interval_seconds` (3 s by default), plus an immediate per-session push whenever a jsonl write fires (inotify), and a bus event as each message arrives. Each client gets a **full snapshot on connect**; after that the periodic frame carries only what moved — sub-keys that hadn't changed (`parked`, `members`, the fleet-health rows) are omitted, and **absent means "unchanged, keep yours"**, never "empty". A full frame is re-sent every 60 s so a client can never diverge for long, and asset-card bodies — 99% of the resources payload, and static — are fetched on demand from `GET /api/resources/{name}/card` when you open a card rather than riding every tick *(2.39)*.
4. The **frontend** renders one tile per session — plain JS, no build step.
5. **BusAdapter** tails the message-bus log; the Bus tile shows recent traffic and SVG lines fan out to sessions on the bus.
6. **WindowMapper** raises the right terminal window on click and types `/msg-check` into a session when you click its 📬 — focusing the exact tilix tile via `gdbus` + `TILIX_ID` when available, else falling back to `wmctrl`/`xdotool` title matching.
7. **Relaunch** (the 🚀 session launcher) discovers closed-but-known folders (`discover_parked_projects` — history on disk, no live process), and `POST /api/relaunch` spawns `claude --continue` there via `claude-tracked`, then polls the scanner for the new session — and, **when `[relaunch].rc` is on** (the default), types `/rc` into it once its terminal is up so it comes back remote-controllable, then presses **Esc** to close the Remote Control menu `/rc` opens *(2.39 — without that the resumed session sits blocked on a modal until a human answers it)*. Both keystrokes **retry until you stop typing**: Conductor refuses to inject while a human is active at the machine (tilix panes share one X11 window, so a racing focus splits keystrokes across tiles), and a relaunch is triggered *by* you clicking a button — so the first attempt lands inside that refusal window almost every time. (`rename` injection is off by default — it's timing-flaky and clobbers a session's own title.)
8. **🕸 History** is served on demand: `GET /api/bus/heatmap` parses the bus log + archives into a time-ordered mention graph; `?human=1` merges in turn-level prompt/reply events from the transcripts; `GET /api/exchange` extracts one prompt's tool/file/agent fan-out for the 🔬 drill-down. All read-only, parsed off-thread.

Full design doc: [`CONDUCTOR_SPEC.md`](../CONDUCTOR_SPEC.md)
