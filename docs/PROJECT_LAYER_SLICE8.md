# Project Layer — Slice 8: Pre-Authorization & the Question Funnel

**Provoked by a live failure (2026-07-26):** the `ieee-paper` panel stalled because a reviewer
(`holobench`) sat waiting for Kyle's *personal* approval to claim a job that was **already inside an
approved project, dispatched to it, inside an autonomy window.** Its own "ask Kyle before I claim
fleet work" policy double-gated already-authorized work, and chained the synthesizer (`qualcomm`)
behind it. Meanwhile the observer (Conductor) *mis-diagnosed* the delay as a lost keystroke. Two
distinct gaps — this slice closes both. It is itself a specimen of the paper's method (a coordination
failure surfaced by *living* the layer, fixed by the fleet).

## Gap 1 — approved project work gets double-gated
**Root cause:** plan-gate approval (Gate #1) and the autonomy window are authorizations that live in
the *coordination layer*, but a worker's caution policy lives *in the session* and does not consult
them. There is no signal on a dispatched job that says *"a human already approved this — do not
re-ask."* So caution correct for *ad-hoc* work misfires on *pre-approved* work.

**Fork A (Kyle, 2026-07-26): dispatch-into-an-approved-project IS the authorization.** The worker's
*claim* is its own logged consent (it may decline on the bus), but it MUST NOT human-gate a
pre-authorized job. Authorization travels **with the job** (the push-gate pattern: bound to the
action, machine-checkable, not prose), not as a habit in each session.

### Mechanism
1. **`bus.sh project authorized <id> <job>`** (new, worker-facing) — the machine-checkable signal.
   Returns **PRE-AUTHORIZED (exit 0)** iff: the project is `active` with `plan_status == approved`
   (Kyle passed Gate #1) **and** the job is dispatched to the *querying member*. Else exit 1 with the
   reason. A cautious session's rule becomes: *before asking the human, run `project authorized` — if
   it says yes, claim without asking.* The prose habit is replaced by a checkable fact.
2. **The dispatch wake message states the authorization + the routing** (so the worker learns it at
   the moment of assignment, without having to know the rule in advance): a `✅ PRE-AUTHORIZED …
   claim without asking the operator; decline on the bus if you can't — do not go silent` line, and a
   `❓ questions → the project lead on the bus, never the operator's prompt` line.

## Gap 2 — questions reaching the human through the terminal prompt
**Root cause:** no enforced *funnel*. A worker asking the human directly (a prompt, or a silent wait)
bypasses the shield, the lead, and Conductor's decision queue — and makes the human the courier
again. The pieces exist (shield `escalate`, the decision queue); the missing part is the **norm** that
project workers route through them.

**Fork B (lead recommendation, adopted): convention + least-resistance, not a hard block** (you cannot
forbid a model from typing a question). Two parts:
1. **A binding standing order** (fleet standing orders / onboarding): *In project work, a question or
   gate you'd raise to the human goes to the LEAD on the bus — never to the human's prompt, never a
   direct ping. The lead answers project calls (shield: lead-decides) or escalates to Kyle via
   `bus.sh project escalate` (which surfaces in Conductor's decision queue — the one place he looks).
   The human's project-interface is exactly two things: the plan gate and the decision queue. A
   question in your terminal is the bug.*
2. **The dispatch message teaches the routing** (mechanism half — see Gap 1 #2), so the norm reaches
   even a session that never read the standing order.

## The single invariant
> **A human should only ever be touched by a project through TWO surfaces: the plan gate (once,
> up front) and the decision queue (for the denylist/severity items the shield sends him). Every
> other project question resolves at the worker (technical), the lead (project), or not at all
> (it was pre-authorized). A per-session human-gate on approved work, and a question in a terminal
> prompt, are both violations of this invariant.**

## Build
- `project authorized <id> <job>` verb (python, after the id-load guard). Pure function of the
  project record; no writes.
- Augment the dispatch wake message (shell `project_dispatch`) with the PRE-AUTHORIZED + funnel lines.
- Standing-order text: added to this doc + `bus/README.md`; the LIVE fleet standing-orders hook is
  persist-gated, so Kyle installs that line from a plain terminal (documented).
- Tests: `authorized` yes/no/dispatched/wrong-member/plan-not-approved; the wake-message content.
- **Live install (persist-gated):** `cp bus/project.sh ~/.claude/bin/` (Kyle), + the standing-order
  line into the SessionStart hook.
