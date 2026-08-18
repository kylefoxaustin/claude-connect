# 🏗 Conductor — basement-up review, and what v3 should be

**Written 2026-08-16**, prompted by a new session (`kitchen_margin`) not appearing on the board.
Everything tagged ✅ was **measured on skippy against the live system**, not reasoned about. The
design half (Part 3) is judgment and is labelled as such.

---

## Part 0 — the number that frames everything

| | at design time (~v1.0) | **today, measured** |
|---|---|---|
| project dirs | a handful | ✅ **69** (43 with transcripts) |
| transcripts on disk | small | ✅ **717 files, 1.5 GB** |
| bus messages | dozens | ✅ **463** |
| bus tags | ~6 | ✅ **36** |
| live sessions | 3–5 | 4 (has been 15+) |
| codebase | — | ✅ ~20k lines; `main.py` alone **3,949** |

> ⭐ **THE THESIS.** Almost nothing here is rotten architecture or a careless bug. Conductor was
> built for **a fleet you can hold in your head**, and every one of its core structures is
> *unbounded*: recompute everything every tick, remember every project forever, count every unread
> for every tag that ever existed. Each was correct at N=5. **At N=69 each has become a defect —
> and they are all the same defect wearing different clothes.**

Three structural roots, and every finding below is one of them:

1. **Recompute-everything-every-tick** rather than event-driven or cached → F1, F5, F6
2. **Never-forget state** with no retirement policy → F2, F3
3. **One god-loop, one god-file** with no notion of "cheap and live" vs "expensive and static" → F5

---

## Part 1 — Findings, ranked

### 🔴 F1 — Conductor reads **224 MB/s, 18.5 TB/day**, to count lines

✅ **Measured on the running process** (`/proc/2034779/io`, 30 s sample):

| | |
|---|---|
| logical reads (`rchar`) | **223.9 MB/s → 18.5 TB/day** |
| actual disk reads (`read_bytes`) | **0.0 MB/s** |
| page-cache hit rate | **100.00%** |

**Cause** — `scanner.py:260`, inside `parse_session_meta`, called for every project dir by
`discover_parked_projects` every 3 s:

```python
# Message count: cheap estimate via line count of the file. For multi-MB files
# a sampled estimate would be better, but jsonl files are typically <1MB.
with jsonl_path.open("rb") as f:
    count = sum(1 for _ in f)          # ← reads the ENTIRE file
```

**The comment states the assumption, and the assumption is false.** ✅ The newest transcripts it
re-reads are up to **99.7 MB** (95emulator), 85.6 MB, 83.1 MB, 81.2 MB — **732.9 MB fully read per
tick**, to produce a decorative message count on a dormant-dock chip.

⚠️ **`limit=40` does not limit the work** — the loop reads every dir, then slices the *result*.

⚠️ **Be precise about the harm — the alarming version is wrong and the real one is worse.** This is
**not** hitting the disk today: 94 GB of RAM absorbs it at a 100% cache-hit rate, which is why
`discover_parked_projects` measures a mere ✅ **202.7 ms** and IO pressure sits at zero. The real
harm is **coupling**:

> ⭐ It pins ~733 MB of page cache permanently hot and generates continuous reclaim pressure — and
> **this is exactly the workload that converts memory pressure into IO pressure.** The 01:10 fleet
> wipe was caused by *sustained page-cache reclaim* from a checkpoint load. Under that condition the
> page cache is evicted, and Conductor's 224 MB/s stops being free and becomes **real reads on
> `/dev/sda` — a ✅ rotational 28 TB Seagate (`ST28000NT000`)**, the same spindle whose IO starvation
> historically recycled the desktop session.

**Conductor is a continuous page-cache pressure generator on the box it exists to observe.** It did
not cause the wipe. It is a contributor to the environment that produced it — and *an observability
tool must never be a load-bearing part of the failure it reports.*

---

### 🔴 F2 — a new session's tile is placed where you cannot see it (the reported bug)

`tiles.js:314`:

```js
function nextCascadeSlot() {
  const occupied = Object.values(positions);   // EVERY position ever stored
  ...first slot overlapping none of them
}
```

and 75 lines later, the deliberate v1.5 decision that makes it unbounded:

> `// No GC of offline tiles: positions/sizes/groups are keyed by project dir and`
> `// kept even when a session isn't running`

So **every project dir ever opened permanently occupies a slot in the collision map.** A new session
must clear all of them. With ~43 stored positions at 6 columns (1920 px, `TILE_W=280 GAP=16`), row 7
→ **y ≈ 1672 px**, roughly two screens down. `clampX()` clamps horizontally; **Y is clamped only by
`Math.max(0, p.y)` — there is no upper bound** — and `updateGridExtent()` obligingly grows the board
to cover it.

**The tile is perfectly reachable and completely invisible.** Mechanism ✅ measured from source; the
exact offset is DERIVED (localStorage is browser-side).

*Immediate non-destructive workaround: **⊞ Tidy** — a pure CSS view-mode (`app.js:202`) that never
writes positions.*

---

### 🟠 F3 — the Bus tile's unread count is ~20× the messages that exist

✅ Measured: the tile sums per-tag unread across **all 36 tags** → **9,208**, over a bus containing
**463 messages**. Every top backlog is a **dormant** tag:

```
441  [isa-lab]                 441  [docs]
441  [other:isr-loop-visualizer]  441  [frontend]
441  [imagegen]                441  [other:orb_slam]
```

`isa-lab`'s directory ✅ no longer exists. These sessions are not running and will never read
anything. The number is arithmetically correct and **communicates something false** — it reads as
"9,208 messages await you." It is the v2.35 lesson again: *an unread count cannot distinguish
deliberating from dead* — here it is dominated **entirely** by the dead.

---

### ~~🟠 F4 — `bus.sh catchup` reports success and does nothing~~ · ❌ **RETRACTED 2026-08-16**

**This finding was WRONG, and the error was mine.** Retracted in place rather than deleted, because
how it happened is more useful than the claim was.

What I published: `catchup` printed *"162 message(s) digested. Now current."* while the watermark
stayed at `2026-08-03 21:58:12`, so I called it a silent no-op.

**What is actually true.** ✅ `bus-state/two-phase` has existed since 2026-07-19 and the `Stop` hook
`bus.sh stop-commit` is wired. Under v2.36's **two-phase commit** the read point deliberately does
NOT advance `.last-seen`; it writes a pending `.delivered` record, and the turn's OWN `Stop` hook
commits it — proof the turn ran to completion and the model actually consumed the emission. That
mechanism exists precisely so a cursor can never advance over output nobody received (91emulator
lost 193 messages exactly that way).

**I measured the watermark inside the same turn as the action** — before the `Stop` hook could
possibly have fired. The test could not have observed success. ✅ The cursor has since advanced on
its own to **`2026-08-13 00:59:23`**, and no `.delivered` record is left pending.

> ⭐ **The lesson, which is the reusable part:** I ran a *tool that defers its commit to end-of-turn*
> and then checked the result *inside that turn*. A verification that cannot observe success is not
> evidence of failure — it is a broken test. This is the same shape as the failures catalogued
> throughout this codebase, aimed at me: **a check that could not fire, and its silence read as a
> result.**

**Residual, stated honestly and much smaller:** the wording *"Now current."* is printed *before* the
commit is guaranteed. If the turn dies before `Stop`, the messages are re-delivered — correct and
by design, but the message is optimistic about a thing that has not happened yet. *"Digested — will
mark read when this turn completes"* would be true at the moment it is printed. Cosmetic, not a
defect, and **not worth spending a persist-gate approval on.**

### 🟡 F5 — `_do_scan` is a 280-line god-function running ~30 subsystems at one rate

`main.py:489–768`, every **3.0 s**, unconditionally: `scanner.scan` → `_sync_members` (writes a
file) → `directed_unread_all` → `list_known_tags` + `list_sender_tags` → `discover_parked_projects`
→ inotify sync → 3 broadcasts → `resources_state` (+`nvidia-smi`) → `attach_cards` →
`_refresh_active_leases` → `_annotate_orphans` → **five** coord reads → `read_services` →
`read_projects` (**up to three times**) → spend meter → 3 annotators → budget alarms → **nine** wake/
delivery passes → `_notify`.

**The defect is not the length — it is that everything shares one clock.** These have wildly
different natural rates: session activity genuinely needs 3 s; the parked list changes only when a
session starts or stops; **asset cards are essentially static**. Running static things at the live
rate is the direct cause of F1.

---

### 🟡 F6 — the three largest payloads are broadcast unconditionally

✅ Measured: `sessions` 21.7 KB + `bus` 6.8 KB + `resources` 52.6 KB ≈ **81 KB pushed every 3 s
whether or not anything changed** = **2.3 GB/day per connected client** — including the phone over
Tailscale. (`/api/ops`, the phone's aggregate, is **61.3 KB** per poll.)

`push`, `services` and `projects` *are* change-gated (`main.py:608, 618, 645`) — so **the pattern is
already in the file, just not applied to the big three.**

---

### ⚪ What is genuinely good — keep and propagate these

Not everything needs changing, and v3 should spread these rather than replace them:

- **`directed_unread_all` is mtime-cached** — ✅ **1.0 ms**, the one hot path that *is* bounded. This
  is the pattern F1 needs.
- **`TokenAccountant` is incremental by design** — seeks past bytes already counted. **The exact fix
  for F1 already exists in the codebase**, two modules away.
- **`reconstitute.py`** — a plan as a pure function of its inputs, testable off-box. The right shape.
- **The honesty discipline is the best thing here** and it *worked*: the fleet-health banner caught
  Conductor's own display blindness instead of silently no-op'ing; the two-pages-only rule has held;
  provenance tags are load-bearing. **Do not trade any of this for tidiness.**

---

## Part 2 — the pattern behind the findings

> Four separate escape hatches exist from the default board view — **⊟ Compact, ⊞ Tidy, minimize-to-
> dock, and groups.** Kyle built each because the board became unusable at scale. **Four escape
> hatches from a default is the default being wrong**, and F2 is what it costs.

---

## Part 3 — what v3 should be *(judgment, not measurement)*

### D1. Split the scan by change frequency — highest leverage, lowest risk

Replace one 3 s loop with a **step registry**, each step declaring its cadence and whether it is
change-gated:

| step | today | proposed |
|---|---|---|
| session status/activity | 3 s | **3 s** (this is the live signal) |
| parked projects | 3 s | **event-driven** — invalidate when a session starts/stops |
| resources / leases | 3 s | 3–10 s |
| asset cards | 3 s | **once + inotify** (they are static) |
| coord dirs (×5), projects | 3 s | **inotify** (they change on write) |

Conductor **already runs an inotify layer** (`activity.py`, `sync_watched_dirs`). This is wiring
existing machinery to existing state, not new infrastructure. **On its own this removes ~80% of
per-tick cost.**

### D2. Never read a file to count its lines

Three fixes, cheapest first:

1. **Cache on `(path, mtime, size)`** — the parked list changes rarely; the count never changes for
   an inactive transcript. One dict, and F1 mostly evaporates.
2. **Reuse `TokenAccountant`'s incremental seek** for anything that must stay current.
3. **Question the field.** `message_count` decorates a dormant chip. A count nobody acts on is not
   worth 733 MB every three seconds — *and the honest option is to drop it.*

### D3. Give every accumulating structure a retirement policy — at birth

The general rule, stated so it generalises past these three:

> ⭐ **Any structure keyed by "every X that has ever existed" needs a retirement policy defined when
> it is created — otherwise it is a leak with a slow fuse.**

- **positions** — GC keys with no live session and no transcript activity in N days; and **clamp Y
  into the viewport, because a tile must never be placed where it cannot be seen** (F2 dies even
  with a stale map).
- **unread / watermarks** — a tag with no process and no activity for N days is **retired** and
  leaves the fleet sum. Show *live* unread; put dormant backlog behind a disclosure.
- **bus log** — 463 messages read 20 at a time is not a reader, it is an archive. Retire by
  rotation with a working catch-up (F4).

### D4. Invert the default view: console first, workbench opt-in

The v2.24 reasoning was right — a desktop board is a **workbench** (spatial, you arranged it, the
arrangement means something); a phone is a **console** (episodic, ranked by what needs you). But
**the workbench premise fails at 40+ tiles**: you cannot meaningfully arrange 40 tiles, and the four
escape hatches are the evidence that nobody tried.

**v3: make the ranked console the default on desktop too, and the spatial board an explicit mode**
for the handful of sessions you are actively arranging. This is the inverse of today.

⭐ **It also makes F2 structurally impossible: a ranked list has no off-screen.** The `/m` console
already proves the pattern and its ranking rule ("needs attention first") is the right one.

### D5. Finish the identity migration and delete the old path

Identity is answered **three** ways today: cwd-derived tag → tag-map override → member registry
(`session_id → member`, bound once, never re-derived). The member registry is correct and already
built; the cwd path is the documented source of years of bugs (tag drift on `cd`, the
`keyhole`/`backend` silent rename, dual-session collisions). **v3 completes the migration and
deletes the derived path.** Three mechanisms for one question is how they disagree.

### D6. Extract the scan pipeline from `main.py`

3,949 lines is not itself the bug, but it is what makes D1 unenforceable — there is no seam at which
a step could declare a cadence. Extract the registry; the god-file shrinks as a side effect rather
than as a goal.

---

## Part 4 — order of work

| # | change | effort | payoff |
|---|---|---|---|
| **1** | **Clamp tile Y into the viewport** | ~10 lines | **fixes the reported bug outright** |
| **2** | Cache `parse_session_meta` on `(path, mtime, size)` | small | kills most of 18.5 TB/day |
| **3** | Change-gate the three big broadcasts | small | −2 GB/day per client |
| **4** | Retire dormant tags from the unread sum | small | the tile stops lying |
| **5** | GC / bound the `positions` map | medium | F2 cannot regrow |
| ~~**6**~~ | ~~Fix `bus.sh catchup`~~ | — | **WITHDRAWN — F4 retracted, the tool was correct** |
| **7** | Scan-step registry with per-step cadence | medium | removes the whole class |
| **8** | Console-default view | large, product call | removes the class *above* it |
| **9** | Finish identity migration | large | retires a bug family |

**1–4 are a single afternoon and address every user-visible symptom.** 7–9 are the actual v3.

> ⚠️ **What I would not do:** rewrite. Nothing found here is rotten — the honesty discipline, the
> incremental accountant, the pure-function planners and the fail-loud instincts are genuinely good
> and hard-won. **This is a scaling problem in structures that were right when they were written**,
> and it is fixed by bounding them, not by starting over.

---

## Part 5 — what shipped (2026-08-16)

Items 1–4 of Part 4, plus **F7**, which only surfaced while verifying F6.

### 🔴 F7 (new) — the `projects` gate existed and never held

Found by measuring real WebSocket traffic after fixing F6. `_annotate_assignee_status`
stamps each job with its assignee's **live session status**, which flips `active` ⇄ `warm`
as a session works — so `projs != self.projects` was true on ~9 of every 10 ticks.
✅ **14.4 KB × ~9 per 30 s = ~414 MB/day per client**, for a payload that had not
meaningfully changed.

> ⭐ This is *exactly* the trap the push-grant gate documents 60 lines earlier —
> *"compare on identity, not the live countdown"* — written down, then not applied one
> function later. **A gate keyed on a value that ticks is not a gate; it is a comparison
> that always returns true.**

Fixed with `_projects_gate_key()`, a pure digest that strips the volatile annotations.

### Measured before → after

| | before | after | |
|---|---|---|---|
| **F1** logical reads | **223.9 MB/s** (18.5 TB/day) | **3.14 MB/s** (0.26 TB/day) | **−98.6%** |
| **F6** `/api/resources` | 52.6 KB | **0.7 KB** | −98.7% |
| **F6** `/api/ops` (phone) | 61.3 KB | **9.2 KB** | −84.9% |
| **F6/F7** WS traffic per client | ~944 KB/30 s (2.59 GB/day) | **271 KB/30 s (0.75 GB/day)** | **−71%** |
| `projects` frames / 30 s | 9 | **0** | gate holds |
| `bus` frames / 30 s | 10 | **1** | 60 s safety resend |

### How each was fixed

- **F2** — `nextCascadeSlot()` now collides only against tiles **actually on the board**,
  and the row search is bounded by the viewport. A one-time rescue drops stored positions
  that are *both* off-screen *and* exactly on the cascade grid — the discriminator that
  separates "the cascade put this here" from "Kyle put this here", so a hand-built layout
  is never touched. Board full ⇒ small diagonal near the origin: **overlapping-and-visible
  beats tidy-and-unreachable.**
- **F1** — `parse_session_meta` memoizes on `(mtime, size)` and counts lines
  **incrementally** over an append-only file, advancing only over complete lines so the
  trailing partial record (Claude transcripts usually lack a final newline) is counted but
  not double-counted. Verified equal to a full read on real transcripts.
- **F6** — asset cards (99% of the resources payload) are stubbed on the wire and fetched
  from the new `GET /api/resources/{name}/card` when the modal opens. Both frontends
  updated; a fetch failure reports the **fetch** failure rather than rendering an empty
  card, which would be a confident lie about a resource you are about to go and touch.
- **F3** — the Bus tile leads with live-session unread and reports dormant backlog
  separately, named as backlog.
- **F7** — durable-content digest, with a 60 s forced resend bounding staleness.

### Deliberately NOT done, with the reason

- **`sessions` is not gated.** ✅ Measured 9/9 ticks genuinely changed (live previews,
  token tallies). A gate there would never fire and would only add a way to go stale. It is
  now 93% of remaining traffic; the real fix is **splitting the static `parked` list
  (13.4 KB) out of the volatile payload** — the same shape as the card split, and the next
  obvious slice.
- **Test-suite note:** `test_x11_health::test_a_moved_display_self_heals_without_a_restart`
  fails on a clean tree (confirmed by stashing) and
  `test_windows_focus::test_focus_ok_when_focus_moves_to_target` is flaky — both consult
  the **real** X server rather than being hermetic. Pre-existing; worth fixing separately.

### Round 2 (same day) — the sessions payload split, and a retraction

| | before | after | |
|---|---|---|---|
| WS traffic per client | **944 KB/30 s** (2.59 GB/day) | **61.5 KB/30 s (0.169 GB/day)** | **−93.5%** |
| `sessions` frame | 23.2 KB every tick | **3.9 KB** (23.4 KB snapshot + 60 s full resend) | −83% |
| `discover_parked_projects()` | 202.7 ms | **13.4 ms** | −93.4% |
| `scanner.scan()` | 47.3 ms | **16.0 ms** | −66% |
| hot path per 3 s tick | 251.1 ms (8.4% duty) | **30.5 ms (1.0% duty)** | −87.9% |

✅ **Delta protocol verified on the live wire:** connect snapshot 23.4 KB carrying `parked` +
`members`; 22 following frames at 3.9 KB with them omitted; the forced full resend observed at
frame 16 (~48 s). Absence means *unchanged*, and both sides say so in comments.

⚠️ **F4 RETRACTED** — see the struck-through section in Part 1. My verification ran inside the same
turn as the command it was verifying, against a tool that deliberately commits at end-of-turn.

### Where this leaves Part 4

Items **1, 2, 3, 4, 5** shipped; **6 withdrawn** (F4 was wrong); **7 (scan-step registry) is now much
less urgent** — the hot path it targets is down to **1.0% of the tick budget**. It remains the right
*structural* fix, because it stops the class from regrowing, but it is no longer buying back real
time. **8 (console-default view) is now the highest-value remaining item**, and it is a product call,
not a performance one.
