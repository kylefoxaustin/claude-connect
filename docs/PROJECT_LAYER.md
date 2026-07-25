# The Project Layer — lead-owned, multi-session coordinated work

**Status:** DESIGN / for fleet review. Not built. Author: claude-connect, from Kyle's ask
(2026-07-24). Extends the existing coordination primitives (orders, services, bus, roles).

---

## 1. The problem

Some work needs several Claudes on different aspects of **one** goal. The live example:
enabling **Neutron support in 95qemu** needed inputs from other sessions — a measurement here,
a converted model there, a parity check elsewhere. It got done, but **Kyle was the project
manager**: relaying "did you get 95's message?", chasing data, confirming each session ran its
part, carrying results back. That's the couriering the bus was built to abolish — one layer up.

"Let them talk amongst themselves" (auto-delivery + autonomy windows) gets us *part* of the way:
sessions can reach each other without Kyle. But freeform chat has no **goal**, no **owner**, no
**structure**, and no **bounded human touchpoints** — so Kyle still has to hold the whole thing in
his head and step in constantly.

## 2. What we're adding — a *project*

A **project** is a bounded unit of coordinated work with:

- a **goal** (what "done" means),
- one accountable **lead** session (decomposes, delegates, aggregates — the PM role, moved off
  Kyle and onto a Claude),
- a **plan** the lead drafts and **Kyle approves** before any work fans out,
- a set of **jobs** the lead delegates to other sessions (each job is an **order** — we already
  have verified point-to-point delivery),
- **issues** the lead escalates to Kyle — and *only* those,
- a live **status** Kyle watches in Conductor instead of assembling in his head.

The value over freeform chat is exactly the four things chat lacks: **a scope, an owner,
structured/verified jobs, and two — only two — human gates.** It turns Kyle from the fleet's
courier into its architect.

### Non-goals (deliberately)
- Not a general agent framework. The fleet already decided (PRIOR_ART_REVIEW.md) *not* to
  brain-transplant onto LangGraph/CrewAI/AutoGen — those **drive** agents; this fleet is
  autonomous interactive peers + a bus + an observer. We **extend our primitives.**
- Not autonomous project *creation*. Kyle starts a project and names its lead. A Claude does not
  spin up projects and conscript the fleet on its own.
- Not two-way human relay. The lead reports; Kyle decides. Kyle does not become the message bus.

## 3. The lifecycle

```
Kyle: project new "neutron-support" --lead 95emulator --goal "…"
   ↓
LEAD drafts a PLAN (decomposition: the jobs, who does each, the acceptance test for each)
   ↓
━━━ HUMAN GATE #1: Kyle reviews/approves the PLAN ━━━  ← the load-bearing gate (see §4)
   ↓  (approve / revise / reject)
LEAD fans out JOBS as ORDERS to the chosen sessions (they CLAIM — opt-in, never force-assigned)
   ↓
WORKERS do the work, DELIVER (verified-landing: can't say done until it's actually on disk)
   ↓
LEAD aggregates; on a blocker it can't resolve → escalates an ISSUE
   ↓
━━━ HUMAN GATE #2: Kyle answers the ISSUE (a decision, a datum, an arch change) ━━━
   ↓
LEAD closes the project when the goal's acceptance test passes → reports to Kyle
```

Conductor observes the whole thing and surfaces the two gates (plan-approval, issues) the way
the **decision queue** already surfaces a blocked question — desktop + phone.

## 3a. Naming the lead — a nomination handshake (per Kyle, 2026-07-24)

Kyle picks a lead from **what he's seen a session do**. But the *fleet* knows things Kyle can't
fully see: who has the deepest hands-on with a given block, who's mid-something-critical, who's
overloaded, who quietly knows a peer is the real expert. So naming a lead is **not a unilateral
assignment — it's a short handshake** that combines Kyle's judgment with the fleet's self-knowledge:

- Kyle **nominates** a session as lead of the project.
- The nominee responds:
  - **ACCEPT** — takes the lead, proceeds to draft the plan.
  - **DECLINE** (with a reason) — "wrong expertise, this is an ISP thing, not emulation," or
    "mid a two-day benchmark, can't lead this now." Returns to Kyle.
  - **SUGGEST `<other>`** (with a why) — "93emulator did the MICFIL/XCVR gate work and knows the
    QOM device model better than I do." A *suggestion*, not a reassignment.
- **Kyle stays the decider.** A decline or a suggestion comes back to Kyle, who nominates the next
  candidate (possibly the suggested one, who then accepts/declines/suggests in turn). This keeps
  the human-names-the-lead property (§2 non-goals): the fleet **advises**, Kyle **confirms**.

Why it earns the ceremony: it's the same reason the fleet catches bugs no single view does —
**Kyle's knowledge + the fleet's self-knowledge beats either alone.** The nominee also gets agency
(leadership is opt-in, not conscription — the order-*claim* principle applied to leadership), and a
better-suited lead is surfaced *before* a wrong one starts planning and burning tokens.

Mechanically it's a tiny directed bus exchange + a `lead_status: {nominated|accepted|declined}` +
`suggestions[]` on the project record — and Conductor shows Kyle the nomination + any suggestion so
he confirms from desktop or phone.

## 4. The crux: the plan-review gate (Human Gate #1)

**This is what makes the whole thing safe.** Letting a lead Claude *decompose and delegate
autonomously* is real authority — more than peers chatting. The plan gate is where Kyle catches a
bad decomposition **before** it becomes ten wrong jobs burning tokens across the fleet.

It's the **same philosophy as the push-gate**: put the human decision at the *right point* — the
plan — then let execution run without couriering. Design properties:

- The plan is a concrete artifact: **goal + acceptance test**, and per job: *what*, *which
  session*, *its acceptance test*, and an **estimated cost** (see §5).
- Kyle can **approve / revise (send back with notes) / reject**. Approval is bound to *that plan*
  (an amended plan needs re-approval — the SHA-pin lesson from the push-gate: authorize the
  specific thing, not "whatever the lead does next").
- A lead **cannot dispatch a job that isn't in an approved plan.** New jobs mid-project = a plan
  amendment = a (lightweight) re-approval. This is the bound against runaway.

## 4a. Question routing — the lead is a decision-shield (per Kyle, 2026-07-24)

A project doesn't just produce *issues* — it produces **questions**, lots of them, and the subtle
ones come from **workers mid-job**, not the lead. If those all hit Kyle raw, the flood is worse
than the couriering we're removing. The rule that prevents it: **questions flow UP the hierarchy —
worker → lead → (only if needed) Kyle. Never worker → Kyle directly.**

- A **worker** that hits a decision on a job does **NOT** block on its own AskUserQuestion picker
  — that freezes the worker and re-introduces couriering. It asks the **lead** through the job/
  order channel: a **"needs-decision"** state on the order (*"to proceed I need: `<question>`,
  options A/B"*). The order system already has the reject/revise loop; this is a sibling state.
- The **lead answers everything it can.** It holds the project context a worker lacks, so most
  low-level calls ("int8 vs fp16 for this conversion?") it simply decides and replies down the
  channel; the worker continues. **Kyle never sees these.** This is the filter — the whole reason
  the project doesn't flood him.
- The lead **escalates only what genuinely needs Kyle**, and — exactly as Kyle framed it — it must
  **describe the decision, its project impact, and the options.** Concretely the lead escalates in
  the shape of a good multiple-choice question:
  - **the decision** (one line),
  - **why it matters** (project impact / what's blocked),
  - **the options** (2–4), and
  - **the lead's recommendation** (it's the closest informed estimator; Kyle overrides freely —
    the lead recommends, it never pressures).

  That *is* an `AskUserQuestion` — so it lands in the **decision queue Kyle already answers from his
  phone**. No new channel. The lead is composing the question *for* Kyle, on the worker's behalf,
  translated from low-level to project-level.

Two escalation sources converge on Kyle's decision queue, both **lead-framed** and **project-
tagged**: the lead's *own* project questions, and worker questions the lead couldn't answer. So
what reaches Kyle is *few* and *pre-digested* — the opposite of a flood.

**Open question:** an escape hatch — may a worker escalate DIRECTLY to Kyle, bypassing the lead,
for something urgent/safety-critical it believes the lead would sit on? Default is via-the-lead
(unflooded + contextualized); a direct path is a bigger gun, so probably reserved or off by
default. And: does the lead's answer to a worker get logged on the project (an audit of decisions
the lead made on Kyle's behalf), so Kyle can spot-check what he was shielded from?

## 5. ⭐ Token / cost governance (first-class, per Kyle)

A project **multiplies token burn**: every job is another Claude doing real work. Left unbounded
this can (a) **swamp the API** — many sessions hammering concurrently → rate-limit/`overloaded`
errors and long waits — or (b) **exhaust the monthly budget**. So cost is not a footnote; it's a
design pillar with three parts:

**(a) Estimate — at the gate.** The plan Kyle approves carries a **cost estimate per job** and a
**project total** (rough — token bands, or "small/medium/large"). Kyle approves a *budget*, not a
blank check. Conductor already has the per-session token accountant (`conductor/tokens.py`); the
estimate can be informed by each session's historical burn rate.

**(b) Throttle — at dispatch.** The lead does **not** fire all jobs at once. Options to weigh:
   - a **concurrency cap** (≤ N jobs in flight fleet-wide at a time — the rest queue),
   - **serialize by default**, parallelize only jobs the plan marks independent,
   - respect a global "the fleet is busy" backpressure signal (Conductor knows how many sessions
     are ACTIVE/WARM right now).
   This directly attacks the "swamp → API error waiting on servers" failure.

**(c) Meter + cap — during the run.** Conductor **tracks live token spend against the approved
budget** (it already sums per-session tokens) and:
   - shows spend/budget on the project view,
   - **pages Kyle when a project crosses a threshold** (e.g. 80% of budget) — a real page, like a
     blocked question,
   - a **hard cap**: at 100% the lead is told to **stop dispatching and escalate**, not silently
     blow through. (Mirrors the workflow token-budget discipline: the target is a ceiling.)

Open question for the fleet: whose tokens? Each worker spends its *own* session's tokens against
the *same* Anthropic account — so the project total is what matters for the monthly budget, and
the concurrency cap is what matters for rate-limits. Both need surfacing.

## 6. How it reuses what exists (so this is an extension, not a rewrite)

- **Jobs = orders.** The v2.36 `order` primitive already gives verified point-to-point delegation:
  PLACED→CLAIMED→(COOKING)→DELIVERED→CONFIRMED, the **requester owns the acceptance test**, a
  worker **can't self-grade**, reject bumps a revision. A project's jobs are orders tagged with the
  project id. Almost nothing new at the job layer.
- **Lead = a role.** The member registry (v4 §3.4) already has roles (observer/peer/service/
  trusted). Add **`lead`** as a per-project attribute (a session is lead *of a project*, not
  globally). One lead per project — the "named owner" rule from FAILURE_MODES (coordination fails
  by diffusion when no one owns it).
- **Coordination = the bus.** Job hand-offs and status ride the bus with auto-delivery; the lead
  never couriers.
- **State = `coord/projects/<id>.json`.** A durable record (goal, lead, plan, jobs[], issues[],
  budget, spent, status), atomic under flock, exactly like orders/leases live today.
- **Human gates = the approver queue.** The plan-approval and issues surface through the same
  Conductor inbox / phone `/m` decision-queue machinery that already pages Kyle for blocked
  questions and gated pushes.

New surface area is small: a `project` state machine in `bus.sh` (+ `/project` command), a
project id on orders, a `lead` attribute, the budget/throttle logic, and the **Conductor project
view**.

## 7. Conductor's role (the observer half — claude-connect owns this)

Kyle explicitly wants **a phone UI and a local-PC view of the project and its members.** So:

- **A project view** — desktop board + phone `/m`: the goal, the lead, the **job graph** (out /
  claimed / delivered / blocked), the **members** working it, live **token spend vs budget**, and
  the open **issues**.
- **The two gates surfaced**: plan-approval and issues appear in the existing inbox / decision
  queue (desktop + phone), so Kyle approves a plan or answers an issue from wherever he is.
- **Members view**: who's on the project, each one's current job + status + token burn — the
  "which Claude is doing what" that Kyle holds in his head today.
- **Budget alarms**: the 80%/100% pages ride the existing Web Push (the two-things-page rule
  becomes three, opt-in — or folds under "a decision that needs you").

## 8. Open questions (for the fleet review)

1. **Plan format.** How structured must the plan be for the gate to be meaningful but not
   bureaucratic? (Freeform markdown Kyle reads, vs a structured job list Conductor renders.)
2. **Cost estimation.** Can a lead estimate a job's tokens usefully *before* it runs? Or do we
   estimate from the worker's historical burn + a size hint, and rely on the live meter + cap as
   the real control?
3. **Throttle policy.** Concurrency cap N? Serialize-by-default? Who enforces — the lead, or
   Conductor as backpressure? (A lead enforcing its own limit is one estimator; Conductor is the
   independent one.)
4. **Worker refusal.** A worker can decline/park a job (orders are opt-in). How does the lead
   handle a job no one claims — escalate as an issue? Reassign?
5. **Lead failure.** If the lead session dies mid-project, what happens? (Orphan-reap analog:
   Conductor sees the lead has no live session → surfaces it → Kyle reassigns lead.)
6. **Scope of Gate #1.** Does *every* job need pre-approval, or does Kyle approve the plan once and
   the lead executes within it, only re-gating on amendments? (Leaning: approve the plan; amend =
   re-gate.)
7. **When is a project overkill?** Two sessions and one hand-off is just an order. What's the
   threshold where the project wrapper earns its weight vs. adding ceremony?
8. **Direct worker escalation (§4a).** Should a worker ever bypass the lead and escalate straight
   to Kyle (urgent/safety), or is via-the-lead absolute? If allowed, how is it bounded so it
   doesn't become the flood-avoidance hole?
9. **Auditing the shield (§4a).** The lead answers worker questions on Kyle's behalf. Log those on
   the project so Kyle can spot-check what he was shielded from? (Transparency vs. noise — the
   whole point was to *not* show him everything.)
10. **Nomination loop (§3a).** Bound the suggest→suggest→suggest chain (Kyle can always cut it
    with "no, you do it") — and allow **accept-with-caveat** ("I'll lead it, but Y has more depth
    if you'd rather")? Does a nominee see the project goal/plan-sketch before accepting, or accept
    blind on the one-line ask?

---

## Build slices (once the design settles)

1. **Project object + plan gate** — `bus.sh project {new|plan|approve|revise|status}`, plan
   stored, Kyle approves via Conductor. (Gate #1 — the highest-value piece.)
2. **Jobs as tagged orders + throttle** — the lead dispatches within the approved plan, honouring
   a concurrency cap. (Auto-delegation, cost-aware.)
3. **Conductor project view** — desktop + phone: goal, job graph, members, spend/budget, issues.
4. **Budget meter + alarms** — live token spend, threshold page, hard-cap stop.
5. **Issue escalation + lead-death handling** — the second gate + the orphan-lead case.
