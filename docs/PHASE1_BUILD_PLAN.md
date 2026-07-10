# Phase 1 Build Plan — "Never Be the Courier" + Retraction

> Concrete, implementation-ready spec for the first coordination phase (see
> `FLEET_COORDINATION_PLAN.md` for the why). Two parts. **Part A** is the daily-pain relief and is
> mostly *generalizing machinery that already ships* (the v2.17 wake, the 📬 unread computation,
> the busy guard). **Part B** is the safety net and reuses the same wake. Target: **v2.19.0**.
>
> Nothing here is built yet — this is the plan to approve.

---

## Part A — Auto-deliver (stop being the fleet's message courier)

**Pain it kills:** Kyle manually prodding sessions to check the bus, and explaining to a Claude
that another Claude *did* send it something. After this, an idle session that has a message aimed
at it is woken automatically, and Kyle can *see* which sessions have asks waiting.

**Scope boundary (honest):** Phase 1 solves *delivery* — "B has an unread message addressed to it →
wake B." The full "who is waiting on a *reply* from whom" graph needs the structured `/need`
intents and lands in Phase 3. This phase nails the actual daily chore.

### A1 — Backend: compute *directed* unread per session
- **File:** `conductor/bus.py`.
- **New:** `directed_unread(messages, tag, since) -> {"count": int, "senders": [tag], "latest_ts": float}`
  — counts unread messages whose `to:` header list contains the bare tag `T`, excluding messages
  `T` itself sent. Reuses the existing message parsing + the v2.5.1 never-checked-baseline logic
  that `compute_pending` already applies.
- **"Directed at T"** = the `to:qualcomm to:all — [sender] …` soft-address convention already in
  use. Trigger is `to:<bareT>` **explicit** addressing only. `to:all` broadcasts are counted for
  the badge but **do not** trigger auto-wake (waking every idle session on every broadcast = spam).
- **Wire:** `AppState._sessions_payload` attaches `pending_directed` (int) and
  `pending_directed_from` (list) per session record, alongside the existing `pending_count`.

### A2 — Backend: auto-wake idle recipients
- **File:** `conductor/main.py`. New `AppState._wake_unread_recipients()`, called in `_do_scan`
  after the payload is computed (it needs the directed counts), next to `_wake_nudged_owners()`.
- **Logic**, per live session `rec`:
  - skip unless `rec.status in _WAKEABLE_STATUSES` — **new constant `{Status.IDLE, Status.DORMANT}`**.
    Deliberately excludes `ACTIVE`/`WARM` (busy) *and* `WAITING` (Kyle may be actively at that
    prompt — don't inject under his cursor).
  - skip if `pending_directed == 0`.
  - **once per episode:** key `f"{tag}\x00{latest_ts}"` in a new `self._unread_woken: set`. A newer
    directed message advances `latest_ts` → wakes again; the same batch never re-wakes. Pruned to
    currently-unread keys each scan (same pattern as `_nudge_woken`).
  - `await self._inject_msg_check(rec, f"{pending_directed} unread addressed to it")`.
- **Reuses:** `_inject_msg_check`, `_live_session_for`, the busy-guard philosophy — all shipped.
- **Settings:** `[bus] autodeliver = true`, `autodeliver_statuses = ["idle","dormant"]` so Kyle can
  tune or disable.

### A3 — Frontend: make the waiting visible
- **Tiles:** when `pending_directed > 0`, the 📬 badge gains a distinct **"N for you"** styling
  (e.g. amber vs the neutral broadcast count) so an at-a-glance scan shows which sessions have
  *directed* asks pending. The existing click-to-nudge (📬 → inject `/msg-check`) already gives a
  manual override.
- **Topbar:** a small indicator `📨 N waiting` (sessions with `pending_directed > 0`), hover =
  the list (`session ← from …`), each with a nudge button (reuses `requestCheck`).
- No new heavy view in Phase 1; the dependency DAG is Phase 3.

---

## Part B — Retraction (the safety net)

**Pain it kills:** A tells B "do X," realizes it's wrong, and needs B to *not* act — before B runs a
destructive step. Delivery must be **immediate** and **loud**, and this is the one case where
interrupting a *busy* B is correct (B may be mid-action).

### B1 — bus.sh: `retract` / `supersede`
- **Both `bus.sh` copies** (live `~/.claude/bin/bus.sh` + sanitized repo `bus/bus.sh`), spliced via
  the established scratch-test-then-migrate pattern.
- `bus.sh retract <to-tag> "<what-was-wrong>"`:
  - posts a bus message `to:<tag> — [<sender>] 🛑 RETRACTION — <what-was-wrong>. Do NOT act on my
    earlier instruction.`
  - writes a record `~/.claude/bus-state/coord/retractions/<tag>-<epoch>` (sender, target, text,
    epoch).
- `supersede <to-tag> "<ignore X, do Y instead>"` — same mechanism, correction framing.
- Slash-commands `bus/commands/{retract,supersede}.md` → installed to `~/.claude/commands/`.

### B2 — prompt-check hook: surface retractions at the top, loudly
- In the per-prompt hook (`prompt-check`), before the pending/resource lines, check for retraction
  records targeting my tag whose epoch is newer than my `last-seen`. If any, **prepend**:
  `🛑🛑 RETRACTION from [sender]: <text> — STOP and re-evaluate before acting.`
- Guarantees the retraction surfaces on the recipient's very next prompt even with Conductor off.

### B3 — Conductor: immediate, *unconditional* wake
- **File:** `conductor/main.py`. `_wake_retractions()` in `_do_scan`. On a **new** retraction record
  targeting tag `T`, inject `/msg-check` into `T`'s session **overriding the busy guard** — the one
  intentional exception, because B might be actively executing the bad step. Track `self._retraction_woken`
  to wake once per record; log distinctly (`retraction wake [T] (busy-guard overridden)`).
- **Frontend:** a red retraction banner on the target tile + a bus alert.

### B4 — Lifecycle
- Retraction records TTL (default 1h) so `coord/` stays small. Once the recipient's `last-seen`
  passes the record's epoch (it checked), the hook stops surfacing it and Conductor won't re-wake.
  No explicit `/ack-retract` in v1 (can add later).

---

## Data model (new)
- `~/.claude/bus-state/coord/retractions/<tag>-<epoch>` — retraction records (the only `coord/`
  content in Phase 1; `/need`-style asks come in Phase 3).
- Per-session payload: `pending_directed: int`, `pending_directed_from: list[str]`.
- `AppState`: `_unread_woken: set`, `_retraction_woken: set`.
- New constant `_WAKEABLE_STATUSES = {Status.IDLE, Status.DORMANT}`.

## Tests (`tests/test_coord.py`, new)
- `directed_unread`: to:T counts; to:other doesn't; to:all counted-but-not-trigger; own msgs
  excluded; never-checked baseline.
- `_wake_unread_recipients`: idle+directed → wake once; re-wake on newer ts; busy/waiting → no wake;
  none directed → no wake; ended → no wake; `_unread_woken` pruned.
- retraction: record parsed; `_wake_retractions` wakes **even a WARM/ACTIVE** owner (busy override);
  wake-once; TTL/last-seen suppression.
- Target: green + the existing 108 stay green.

## Live verification
- Directed-unread badge renders; auto-wake fires for an idle session with a `to:<tag>` message
  (log line + the session actually running `/msg-check`); a `/retract` wakes even a busy recipient
  and shows the loud hook banner. (X11/terminal-level — hand-verified, per the sandbox constraint.)

## Rollout order (recommend building Part A first — biggest relief, lowest risk)
1. **A1 + A2 + A3** → ship as the courier-killer. Backend-heavy, reuses shipped wake, no bus.sh
   change. Fastest path to relief.
2. **B1–B4** → retraction. Touches both `bus.sh` copies (scratch-test-then-migrate) + the hook +
   Conductor.
3. Version bump **v2.19.0** ("🚦 Fleet coordination I: auto-delivery + retraction"), docs, both
   editions, announce the new `/retract` `/supersede` to the fleet.

## Risks & mitigations
- **Auto-wake stealing focus / spam** → conservative wakeable set (IDLE/DORMANT only), directed-only
  trigger, once-per-episode keying, `[bus] autodeliver` off-switch. This is the main thing to watch
  in live use; easy to dial back.
- **Retraction overrides the busy guard** → intentional and rare (only on explicit `/retract`);
  logged; it's the one case where interrupting is the *right* call.
- **Directed detection depends on the `to:` convention** → broadcasts intentionally don't auto-wake;
  documented. If the fleet under-uses `to:<tag>`, coverage is lower — acceptable for v1, and Phase 3
  `/need` makes intent explicit.
- **A session Kyle is actively at** → excluded (`WAITING` not wakeable; `ACTIVE`/`WARM` not wakeable).
