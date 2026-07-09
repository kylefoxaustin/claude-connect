# Claude Bus — reference implementation

This is the cross-session message bus that Conductor's 📬 features talk to. It's
a tiny, dependency-free shell script plus four Claude Code slash commands and two
hooks. Wiring it up is **optional** — Conductor monitors every session with or
without it (see ["What if a session isn't wired up?"](#what-if-a-session-isnt-wired-up)).

How it works: each Claude Code session is auto-tagged by its working directory
(`[backend]`, `[other:my-repo]`, …). `/msg-send` appends a tagged line to a shared
markdown log; `/msg-check` reads it. A `UserPromptSubmit` hook quietly tells a
session when new messages have arrived so it can offer to check them. Conductor
tails the same log and renders the traffic.

See [`../docs/claude-bus.md`](../docs/claude-bus.md) for the full format spec.

## Layout

| File | Install to | Purpose |
|------|-----------|---------|
| `bus.sh` | `~/.claude/bin/bus.sh` | the bus engine (send/check/all/rotate + hook outputs) |
| `commands/msg-*.md` | `~/.claude/commands/` | the `/msg-send` `/msg-check` `/msg-all` `/msg-rotate` slash commands |
| `settings.hooks.example.json` | merge into `~/.claude/settings.json` | makes sessions bus-aware automatically |

## Install

```bash
# from the repo root
install -Dm755 bus/bus.sh ~/.claude/bin/bus.sh
mkdir -p ~/.claude/commands
cp bus/commands/*.md ~/.claude/commands/
```

Then merge `bus/settings.hooks.example.json` into `~/.claude/settings.json`
(replace `/home/YOU` with your home path). If you already have `permissions` or
`hooks` keys, merge the inner arrays rather than overwriting them. Restart any
open Claude Code sessions so the hooks load.

Verify:

```bash
~/.claude/bin/bus.sh send "hello bus"
~/.claude/bin/bus.sh check
```

## Tag your projects

Out of the box every directory gets a tag of `[other:<dirname>]`. To give a
project a clean name, add a case branch near the top of `bus.sh`:

```bash
case "$CWD" in
  */my-api|*/my-api/*)   TAG="api" ;;
  */my-web|*/my-web/*)   TAG="web" ;;
  *)                     TAG="other:$(basename "$CWD")" ;;
esac
```

If you want a named tag to participate in the **automatic hooks** (SessionStart
context injection + UserPromptSubmit nudges), it must be "active." Active
membership is read from `~/.claude/bus-state/active-tags` (one bare tag per
line) when that file exists, falling back to the `BUS_WHITELIST` near the top of
`bus.sh` otherwise. Conductor's dashboard toggles this file when you flip a
tile's tag chip Active/Passive — or edit it by hand. Un-active tags can still
use the slash commands manually; they just won't get the automatic nudges. This
is what keeps the bus out of unrelated sessions.

> **Keep Conductor in sync:** when you add a named tag here, also add it to the
> `[bus.tags]` table in Conductor's `settings.toml` so it labels the tile with
> the same tag:
>
> ```toml
> [bus.tags]
> "~/code/my-api" = "api"
> ```
>
> See `settings.example.toml`. Anything unmapped falls back to `[other:<dir>]`.

## What if a session isn't wired up?

Nothing breaks. Conductor discovers sessions from OS process state, not the bus,
so an un-wired Claude appears as a full, normal tile (status dot, live preview,
message count, click-to-focus). It just has no bus state, so:

- it shows **no 📬 badge** (no pending messages tracked for it), and
- it draws **no connection line** to the Bus tile.

That's intentional: wired sessions are visually on the tunnel; un-wired ones are
monitored but silent.

## Resource reservation (shared GPU, boards, any single-holder rig)

If your sessions share a scarce resource — one GPU, a dev board (an IQ9 EVK, …),
any single-holder rig — the bus can arbitrate it so they **self-coordinate
without you in the middle**. Each resource is a **named** cooperative lease: state
lives in `~/.claude/bus-state/resources/<name>/lease`, acquire/release are atomic
(`flock`), and the current status of *every* resource is auto-injected into each
session's per-prompt context — so a session *knows* who holds what without asking.

Slash-commands (each just calls `bus.sh res …`), with the resource named:

| Command | What it does |
| --- | --- |
| `/res-status [name]` | Who holds each resource, mode, time left, any pending request. **Read-only** — sends no message. Omit the name for all resources. |
| `/reserve <name> <dur> <soft\|hard> ["job"]` | Claim it if free (e.g. `iq9-evk 2h hard`). Rejected (with guidance) if held. |
| `/release <name>` | Free your reservation. |
| `/keep <name> <dur>` | Extend your reservation before it expires — **also the heartbeat** for non-GPU resources (see the watchdog). |
| `/res-request <name>` | **Join the FIFO queue** — you'll be pinged the moment it's your turn (no polling). |
| `/res-pass <name>` | When you've been *offered* a resource, decline it → hands to the next in line. |

The GPU keeps its `/gpu-*` commands as **aliases** for the `gpu` resource
(`/gpu-reserve 30m soft` == `/reserve gpu 30m soft`), so nothing that already
uses them changes.

### Queue + grace-hold hand-off

Can't have a resource now? `/res-request <name>` puts you in a **FIFO queue**
instead of polling. When the holder `/release`s (or the lease expires, or an idle
`soft` lease is reclaimed), the head of the queue is **offered** the resource: it's
*held for them* for a grace window (`RES_GRACE_MIN`, 15m) with a `mode=offer` lease.
They `/reserve <name> …` to claim it (their offer converts to a real hold, the rest
of the queue is preserved) or `/res-pass <name>` to skip it — and if they do
nothing, the watchdog **auto-passes** to the next in line when the grace elapses.

Delivery is two-layer: a `[resource-broker]` **bus message** is always posted to
the offered session (seen on its next prompt), and — if Conductor is running — it
**injects `/msg-check`** into that session's terminal within ~3s so an idle waiter
wakes and acts on the offer in real time. Nobody polls; the *release* is the only
event, and it drives everything.

**Two hold modes** — the honest signal that makes coordination work:

- **soft** — *"I have it + code/board set up, but I'll drop it if you need it."* Preemptible; a `/res-request` nudges the holder.
- **hard** — *"Mine until my job finishes or the user says stop."* Not preemptible; requesters wait/queue.

Reservations carry a **duration** and **auto-expire** on next access (a forgotten
hold frees itself), so a resource can't get stuck. The per-prompt awareness line
is silent when everything is free — zero noise until there's contention.

### Idle watchdog (auto-nudge / auto-reclaim)

A standalone daemon, [`resource-watchdog.sh`](resource-watchdog.sh), watches every
held lease and judges *idle* per resource type:

- **GPU** — by `nvidia-smi` **utilization** (≤ threshold = models loaded but not computing).
- **Other resources** — by the **`/keep` heartbeat**: run `/keep <name> <dur>` while you're actively using a board; if no heartbeat arrives for a while, it counts as idle. (No board-specific probe needed.)

When a lease sits idle past a limit, it acts **without the human coordinating**:

- **Nudges the owner** on the bus (a `[resource-watchdog]` message their per-prompt
  hook surfaces): *"your HARD iq9-evk lease has shown no activity for 40m — /release if done, or /keep."* It re-nudges on a cadence while still idle, and names anyone who's `/res-request`ed it.
- **Auto-releases a `soft` lease** once it's idle past a longer grace (a soft
  hold yields by definition) and posts a `to:all` heads-up. **`hard` leases are
  never auto-released** — the owner or the user decides; the watchdog only checks in.
- Activity (GPU compute, or a fresh `/keep`) **resets** the idle clock (and the idle
  time shows up in the awareness line: `iq9-evk: YOU hold it (hard · ~18m left · idle 40m ⚠)`).

> **A nudge has to actually reach someone.** Bus messages surface through a session's
> *per-prompt hook* — so an idle holder (the only kind that gets nudged) never reads
> one. If Conductor is running it closes that loop: when the watchdog nudges a live
> holder, it injects `/msg-check` into that session so the nudge lands and the holder
> can `/keep` or `/release`. Once per idle *episode*, never mid-task, so it can't
> spam your focus on the re-nudge cadence.

**Orphan reaping (after a reboot).** A lease is a *file* — it outlives the session
that took it. So after a reboot you'd otherwise be left with a `hard` lease held by
a session that no longer exists, blocking the resource until its duration expires
(and the watchdog will never force-release a hard lease, so it would just nudge a
corpse). The watchdog therefore treats **`acquired_epoch` earlier than the kernel's
boot time** as *provably orphaned* — no process survives a reboot — and reaps it:
handing the resource to the next in the queue, or freeing it, and saying why on the
bus. There's a short post-boot **grace** (`RES_ORPHAN_GRACE_MIN`, 10m) first, so an
owner who relaunches promptly can re-anchor their lease with `/keep` and keep it.
This is a *certain* signal, not a heuristic like idle time.

Run it headless (once):

```bash
# systemd --user (recommended: auto-restart, starts on login)
install -m755 bus/resource-watchdog.sh ~/.claude/bin/resource-watchdog.sh
cp bus/resource-watchdog.service ~/.config/systemd/user/
systemctl --user enable --now resource-watchdog.service
#   …or simply:  nohup ~/.claude/bin/resource-watchdog.sh run &
```

Tunables via env (in the service file or your shell): `RES_POLL_SEC` (60),
`RES_IDLE_UTIL_PCT` (5, GPU only), `RES_IDLE_NUDGE_MIN` (30), `RES_IDLE_RENUDGE_MIN` (20),
`RES_SOFT_RELEASE_MIN` (60), `RES_ORPHAN_GRACE_MIN` (10).

Conductor visualizes each resource as a live tile: the holder (soft/hard), a
ticking countdown, the watchdog's idle warning, and any pending request. The
**GPU tile** additionally shows the GPU name + live `nvidia-smi` utilization bar +
memory; other resources show a plain lease.
