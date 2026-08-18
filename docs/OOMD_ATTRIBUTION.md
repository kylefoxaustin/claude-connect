# 💀 Death Attribution — "why did this session vanish?"

**Status: SPEC, not built.** Written 2026-08-14, the morning after `systemd-oomd` killed
`dbus.service` and took the fleet with it. Grounded against the live box — every empirical claim
marked ✅ was verified on skippy, not reasoned about.

> **Originally titled "OOMD Attribution."** Renamed in Amendment 1: `systemd-oomd` is no longer the
> reaper on this box, and a spec named after a mechanism that has been switched off would be a
> document lying in its own title.

---

## AMENDMENT 1 — 2026-08-14, same day, pre-build

**Nothing had been built when this landed, so nothing is retracted — but the premise moved and two
of the three decisions are gone.** Recorded here rather than silently patched, per the v2.32
discipline (*publish the correction IN the section*).

**What changed:** `qualcomm` replied at 16:11 with the fix already applied and the root cause I
could not close.

### ① The oomd fix is APPLIED and VERIFIED — broader than what this doc proposed

```
/etc/systemd/system/user@.service.d/oomd.conf   →   [Service] ManagedOOMMemoryPressure=auto
```

Applied by qualcomm at Kyle's instruction. ✅ **Independently verified from this session**, not
taken on qualcomm's word:

- `oomctl` → **`Memory Pressure Monitored CGroups:` is EMPTY** (it previously listed
  `/user.slice/user-1000.slice/user@1000.service` at a 50% limit)
- `systemctl show user@1000.service -p ManagedOOMMemoryPressure` → **`auto`**
- the drop-in appears in `DropInPaths` alongside Ubuntu's `10-oomd-user-service-defaults.conf`

This is **broader than §A11's dbus exemption.** Mine would have protected one cgroup; this removes
the entire user session from pressure monitoring, so oomd cannot select *any* victim in it.

⚠️ **Verification gotcha worth keeping** (qualcomm's, and it generalises): after hand-creating a
drop-in, `NeedDaemonReload` still reports **no** — systemd only mtime-compares units it already
knows, so a brand-new drop-in *directory* does not trip it, and `DropInPaths` omits it until reload.
**Trust `oomctl` and `DropInPaths`; never the file's existence.** Same shape as this codebase's
recurring lesson: *a check that did not run looks exactly like a check that found nothing.*

### ② The root cause is CLOSED — the half this doc could not reach

**Qwen2.5-VL-7B genie compile.** `transformers` "Loading checkpoint shards" pulling the fp
Qwen2.5-VL-7B into host RAM to generate vision preprocessing tensors.

- `~/genie_bundles/qwen25vl_247/compile.log` — last write **01:10**, final line
  `Loading checkpoint shards: 1/5 [00:28<01:53]`. It died mid-load at exactly **01:10:41**.
- **Re-run of the identical step post-fix: completed in 73.8 s, peak RSS 34.78 GB, min
  MemAvailable 56.51 GB.** The "hog" never came within **56 GB** of exhausting the box.

⇒ A large sequential checkpoint read generating **sustained page-cache reclaim → PSI pressure →
oomd**. The 9 GB swap churn observed from this side is the same phenomenon seen from another angle.
**Three independent estimators converged** (this session from journald/Conductor, qualcomm from the
compile log, and the re-run as a controlled repro).

### ③ ⭐ THE REAPER MOVED — and the feature must follow it

With oomd off the user session, **a true exhaustion now falls to the KERNEL OOM-killer, which
targets the largest process** (a python export job) **instead of `dbus`.** The failure mode becomes
*"lose one job"* rather than *"lose the fleet"* — that is the real win, and it is already
load-tested: today's Llama-3.1-8B export peaked at **75.5 GB RSS with 14 GB available**, comfortably
over the old 50%/20 s trigger, and **did not** wipe the fleet.

**Consequence for this spec: `systemd-oomd` will produce no further kills to attribute.** The
post-mortem's live subject is now the **kernel OOM-killer**. The design survives intact — the field
was named **`death_cause`**, not `oomd`, precisely to leave this room — and §4 below anticipated it.

### ④ Live risk this introduces, worth watching

✅ **Swap is at 157 MB free of 32 GB (99.5% consumed)**, on the NVMe (`/mnt/ssd/swapfile`), not the
HDD — so this is *not* the old IO-starvation freeze. Pressure is currently flat zero and 74 GB of
RAM is available, so it is **not an emergency**. But the Llama export peaked at 75.5 GB RSS when it
had 25 GB of swap free; a repeat now has effectively none, and the backstop is the kernel killer.

---

## 1. The problem: a dormant chip is a lie of omission

Conductor renders four causally different events **identically**:

| what happened | what Conductor shows |
|---|---|
| Kyle deliberately closed the window | dashed chip in the dormant dock + age |
| `claude` exited or crashed on its own | dashed chip in the dormant dock + age |
| **a reaper killed that one session** | dashed chip in the dormant dock + age |
| **a reaper killed the session bus → 187 procs** | dashed chip in the dormant dock + age |

The chip invites a relaunch and says **nothing** about whether the session was destroyed against
your will in the middle of work. Same defect class as the v2.37 arc — *a silent no-op is a lie of
omission* — except here it is a silent *death*.

### The invariant this feature buys

> ⭐ **An involuntary death must never render identically to a deliberate close.**

### Evidence the gap is load-bearing

✅ measured on skippy, 2026-08-14: **46 `systemd-oomd` kills across 10 separate days** — Jun 17
(six in two minutes), Jun 18, Jun 27 ×3, Jul 04, Jul 08, Jul 17, Jul 18, Aug 14. By victim:

| victim | count | meaning |
|---|---|---|
| `vte-spawn-*.scope` | **~25** | **individual Claude sessions, killed one at a time** |
| `dbus.service` | 6 | whole-session wipe |
| `tracker-miner-fs-3` | 4 | since masked |
| `firefox` | 3 | — |
| `org.gnome.Shell@x11` | 2 | shell death |
| **`app-gnome-conductor-*.scope`** | **2** | **Conductor itself** |

⇒ roughly **25 individual Claude sessions killed one at a time over months.** Every one was
attributable all along, and nothing ever attributed them — they simply appeared as "went dormant."

> **Post-Amendment-1 status of this evidence:** it is now **historical**. It remains the motivating
> case and the payload of the retro-scan (§A9), but it is no longer a prediction about future
> events.

---

## 2. Component A — the post-mortem

### A1. The join key must be captured while the session is alive

A reaper names its victim and nothing else — no project, no cwd, no tag, no `session_id`. Once the
kill lands `/proc/<pid>` is gone, so **the mapping is unrecoverable after death** and must be
recorded before.

**Two reapers, two join keys — and the live one is the cheaper:**

| reaper | what the journal names | join key | status |
|---|---|---|---|
| `systemd-oomd` | a **cgroup path** (`…/vte-spawn-<uuid>.scope`) | cgroup → session | ✅ verified, now **dormant** |
| **kernel OOM-killer** | **`Killed process <pid> (<comm>)`** — the **PID directly** | pid → session | **the live target** |

✅ **Verified:** a live `claude` process's `/proc/<pid>/cgroup` *is* exactly the
`vte-spawn-<uuid>.scope` string oomd names, so the harder join works. **And the kernel path needs no
new field at all** — `proc_groups` already carries `pid`.

**Hook point:** `SessionScanner.scan()` already builds `proc_groups` per *process*, pre-dedup
(`conductor/scanner.py:762`), with `{pid, cwd, name, tag}`. Add `cgroup` if the oomd path is ever
wanted; the kernel path is already covered by `pid`.

> Same shape as the v2.36 PID-JOIN bridge and v2.30 provenance: the join is recorded by the party
> that can observe it, *before* the event, because the event destroys the evidence. Not a new
> pattern — the established one.

### A2. The table must be persisted — because Conductor is itself a victim

**2 of the 46 kills were `app-gnome-conductor-*.scope`.** An in-memory join table dies in exactly
the event it exists to explain — the v2.22 wake-state lesson, which is why
`coord/wake-state.json` exists at all.

⚠️ **Tension, named honestly.** `CLAUDE.md` says *"no persistence; in-memory state, restart-clean."*
The precedent that resolves it: `coord/wake-state.json` and `coord/autonomy.json` already persist.
The rule means no persistence of **observed session state**, which scanning rebuilds. A forensic
join that **cannot** be rebuilt is the other category.

Proposed: `coord/death-join.json`, written on change, bounded — cap entries, prune those whose
process no longer exists and predate journald's retention window.

### A3. Provenance tags on every attribution

Two paths of different epistemic strength, and LAW 1 makes labelling them mandatory:

| tag | how it is established | when |
|---|---|---|
| **MEASURED** | the journal named a pid/scope **present in the join table**, and the kill timestamp falls inside that entry's observed window | kills while this feature runs |
| **DERIVED** | a kill landed within N s of a session's last transcript write, identifier unknown | historical kills; kills while Conductor was down |

> ⭐ **A DERIVED attribution may never be rendered as a MEASURED one.** Measured reads *"the kernel
> killed this session at 01:10:41."* Derived reads *"a kill at 01:10:41 is within 12 s of this
> session's last write — likely, unconfirmed."*

### A4. Explicitly rejected: a bare time-window as the primary mechanism

v2.30 already paid for this — **"a queue, never a timestamp window"** — where a ±5 s instinct met a
real latency of 6–13 minutes. The failure here is different but just as fatal: a session-bus kill
takes **187 processes in the same second**, so a time window cannot distinguish

- *the reaper killed this session*, from
- *this session died because the bus it depended on was killed*, from
- *Kyle closed it three seconds earlier.*

For single-session kills, naming the **wrong** session is strictly worse than saying nothing.

### A5. The identifier-reuse trap — the bug that would ship

Both join keys are **reused over time**: `vte-spawn-<uuid>.scope` is minted per terminal spawn, and
**PIDs recycle**. Either way a stale entry can be matched by a kill of a *different* process.

**Guard:** each entry carries `first_seen`/`last_seen`, and a kill attributes **only if its
timestamp falls inside that window.** Without it the feature confidently names innocent sessions —
the exact plausible-and-silent class the fleet has spent months cataloguing.

### A6. A mass kill is one event, not 187 findings

A session-bus kill has a **blast radius**, not a cardinality. Render it as a single fleet-wipe event
naming the sessions live at that instant — never as N per-session alarms. 187 identical cards is the
v2.29 mass-cc failure rebuilt: volume where one fact was wanted.

### A7. ⭐ It must fail loud, never empty — the highest-stakes property

The feature's whole subject is **silent death**. If the journal query fails — permissions, rotation,
missing binary, unparseable output — and returns an empty list, the UI reads **"nothing killed
anything"**: a confident false negative on precisely the question being asked.

Three precedents, all from this codebase:

- the **NUL-byte binary grep** (v2.30) — `grep` searched nothing, returned empty, and the silence
  was read as evidence, producing a false statement about Kyle's own consent;
- the **webpush `ModuleNotFoundError`** (v2.37) — paging silently dead for hours;
- the **card validator** (v2.28) — returned 1 under `set -e` and silenced the very thing it existed
  to shout about.

⇒ **Distinguish "queried successfully, zero kills" from "could not query."** The latter is a
fleet-health degradation banner, never an empty list.

✅ Verified: `journalctl _COMM=systemd-oomd -o json` works and exits 0, and `kyle` ∈ `adm` grants
system-journal read (the kernel path reads the same journal). **But this must be a runtime check,
not an assumption baked in at build time** — the entire point is that it can break quietly later.

### A8. Bounded reads

`journalctl -o json --since <cursor>`, filtered to the reaper's own records. **Never** an unbounded
whole-journal read per scan tick. ✅ The JSON carries `__CURSOR` — resume from it, the same watermark
idiom the bus already uses. Off-thread, like every other scan-adjacent read.

### A9. The retro-scan, honest about its limits

Sweep history into a **kill log** — 46 events, victim classes, dates. This is how the finding was
made, and post-Amendment-1 it is the component whose value is *unchanged*, because its subject was
always the past.

But historical kills **cannot** be measured-attributed: no join table existed then. The retro view
reports the **pattern**, and per-session attribution only as derived-or-nothing.
⚠️ **It must not invent attributions in order to look complete.**

### A10. What the user sees

- **Dormant chip** gains a cause badge — `💀 killed 01:10` (measured) or `💀 killed? 01:10`
  (derived) — versus a plain age for an ordinary close. The chip already invites relaunch; now it
  also says whether that relaunch resumes work that was *interrupted* rather than *finished*.
- **Fleet-health row**: a fifth signal beside lost-`/RC`, dead-reader, collision and
  display-unreachable. Fires on a *new* kill since last seen.
- **Fleet-wipe card**: one card, the session list, and the reason the reaper cited.
- **Phone `/m`**: the same signal in the Fleet bar. Desktop-only was already the v2.37 reclaim
  mistake — don't repeat it.

### A11. Paging — recommendation: no, off by default

Conductor pages on exactly **two** things: a Claude blocked on a question, and a gated push — both
meaning work has stopped dead and a human is the only unblocker.

**The case for** paging a fleet-wipe is genuinely stronger than the squatter case it sits beside:
work *has* stopped dead, and a human *is* the only unblocker. **The case against, which wins:** the
fleet was already dead for eight hours, and learning at 09:07 instead of 01:10 cost about zero — the
sessions were gone before any page could fire. **A page you cannot usefully act on is one you learn
to swipe away, and that is exactly what would make the other two pages untrustworthy.**

Precedent: `page_dead_readers` exists and defaults off — *"a third alarm is a deliberate choice."*
Proposed: `[bus] page_session_killed = false`.

> **Post-Amendment-1:** with oomd disarmed, this is close to moot — but the kernel path can still
> fire, so keep the flag and keep it off.

---

## 3. Component B — the pressure gauge · ⬇ DEPRIORITIZED

### B1. Read the cgroup the reaper reads, not the system-wide file

✅ **Measured, and it is why this distinction is real:** at 01:10:24 io-watch logged **`mem=51.2`**
while oomd cited **`65.63%`**. Different numbers — io-watch reads system-wide
`/proc/pressure/memory`; oomd read **`user@1000.service`'s cgroup `memory.pressure`**. A gauge
calibrated on the wrong file under-reports and gives false reassurance right up to the kill.
✅ Verified world-readable:
`/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/memory.pressure`

### B2. ⚠️ Unverified — and now unlikely to be settled

Which field oomd thresholds on (`some` vs `full`, `avg10` vs `avg60`) was never confirmed, and
guessing it is not acceptable. The acceptance test was to match the gauge against a real kill —
**which oomd will no longer produce.** *A gauge that has never matched a real event is unvalidated,
and this one now has no event to match against.*

### B3. Its main justification is spent

This component was justified primarily as **the instrument that finds the unknown driver.** Per
Amendment 1 ② **the driver is known** — Qwen2.5-VL-7B checkpoint-shard loading. That justification is
gone.

**What remains, and it is weaker:** confirming the fix holds, and watching the swap/kernel-OOM path
(§Amendment 1 ④ — 157 MB of swap headroom). Real, but not worth building ahead of Component A.
**Recommendation: deprioritize below slices 1–3.**

### B4. It does not replace io-watch

io-watch's log is the existing forensic trail and it *worked* — its `mem=` column plus the `avail`
jump (70→90 GB) and swap collapse (9.2→3.4 GB) are how the mass death was dated.

---

## 4. What this feature does not do

- **It does not fix the kill.** That lives in `/etc` — persist-gated, outlives the session, Kyle's
  call from a plain terminal. ✅ **Already done** (Amendment 1 ①) — by qualcomm, not by this feature.
  *An observability feature must never quietly become a system-config mutator.*
- **It does not auto-relaunch.** A killed session's repo may be dirty; that's a Reconstitute/DR
  decision with its own guards, already built. This feature informs that screen; it never acts.
- **It does not claim to explain every death.** Absence of a kill record means "not killed," not
  "deliberate close." The field is `death_cause`, not `oomd` — which is exactly why Amendment 1 ③
  is a retarget rather than a rewrite.

---

## 5. Test plan

Pure functions, same idiom as `reconstitute.py` — fully testable without the machine that produced
the inputs.

1. **`parse_kill_records(journal_json_lines)` → events**, covering both reapers (oomd's cgroup form
   and the kernel's `Killed process <pid> (<comm>)` form). ⚠️ **Fixtures must be real captured
   journal output**, including the verbatim 01:10:41 `dbus.service` line with `187 process(es)` —
   not hand-written strings. The v2.33 mirror lesson: *a test that gets its data from my own
   description of the format is not a test, it is a mirror, and mutation testing is blind to it by
   construction.*
2. **`attribute_kills(events, join_table, parked, now)` → attributions carrying `provenance`.**
   Cases: exact identifier hit ⇒ measured; identifier absent ⇒ derived-or-none; mass kill collapses
   to one event; **and the reuse guard — a kill outside an entry's `first_seen…last_seen` window
   must not attribute to it** (PID recycling makes this sharper than the cgroup case, not softer).
3. **Fail-loud:** unreadable / garbage / permission-denied / empty journal ⇒ degraded status, never
   an empty list presented as success.
4. **Retro-scan** reports the pattern without inventing per-session attribution.

---

## 6. Slicing

| slice | content | note |
|---|---|---|
| **1** | persist `coord/death-join.json` from `proc_groups` (pid; + cgroup only if the oomd path is wanted) | small; **kernel path needs no new field** |
| **2** | parse + attribute + fleet-health signal + dormant badge + phone | the visible feature |
| **3** | retro-scan view (the 46-kill log) | **value unchanged by Amendment 1** |
| **4** | pressure gauge | ⬇ deprioritized — §B3 |

> ⚠️ **The original sequencing argument is WITHDRAWN.** This doc argued slice 1 must land first
> because *"every day without it is another day of unattributable deaths."* That held while oomd was
> live. **It is not true any more** — oomd cannot kill in this session. Slice 1 is now justified only
> to the extent the **kernel** path is considered a live risk, which §Amendment 1 ④ suggests it is,
> but the urgency is gone. Stating this plainly rather than letting a stale argument carry a build
> decision.

---

## 7. Open questions for Kyle

1. **Paging** — off by default (§A11)? *Near-moot post-Amendment 1; recommend keeping the flag, off.*
2. **Retarget at the kernel OOM-killer, and build slice 1?** The kernel is the live reaper now, it
   names the **pid** directly, and `proc_groups` already carries pid — so this is *cheaper* than the
   oomd design, not dearer.
3. ~~Prepare the `/etc` drop-in~~ — **WITHDRAWN. Already applied and independently verified**
   (Amendment 1 ①), and broader than what was proposed here.
