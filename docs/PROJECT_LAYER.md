# The Project Layer — lead-owned, multi-session coordinated work

**Status:** DESIGN v2 (post fleet-review). Not built. Author: claude-connect, from Kyle's ask
(2026-07-24), revised 2026-07-25 after a 4-session review (95emulator, 93emulator, qualcomm,
image_gen) — all grounded in real multi-session work. Extends orders/services/bus/roles.

> **What changed in v2 (the fleet's fire).** The skeleton held; the cost model and the decision-
> shield were redesigned. Headlines: pre-run token *estimation* is theater — demoted to a size
> band; the LIVE meter + hard cap is the only real control (§5). Throttle is enforced by
> **Conductor**, not the lead — fox/henhouse (§5). The shield now **splits technical vs project
> decisions** and carries an **escalate-always denylist** so it can't usurp Kyle's authority (§4a).
> A **job-dependency DAG** is a genuine new primitive (§6). A **mid-flight premise-collapse gate**
> is added (§4b). And the layer's honest win is **cognitive load, not speed** (§0).

---

## 0. The honest tradeoff, stated up front (95emulator)

This layer optimizes **Kyle's attention** — fewer, better-framed touchpoints — **not wall-clock
speed.** The biggest coordination cost in the motivating work wasn't decisions or couriering; it
was **latency**: every async hop through a session's wake cycle took *hours*, and Kyle-as-courier
was often *faster* because he's synchronous and always-on. Routing work through a lead's wake cycle
can make a deadline *worse*. So: **the win is cognitive load; the cost is latency.** For
tight-deadline work, freeform bus + a human courier may still be right. Build this for *cognitive
scale* (many concurrent aspects Kyle can't hold in his head), not for *speed*.

## 1. The problem

Some work needs several Claudes on different aspects of **one** goal. The live example: enabling
**Neutron support in 95qemu** needed inputs from multiple sessions — a measurement here, a converted
model there, a parity check elsewhere. It got done, but **Kyle was the project manager**: relaying
"did you get X's message?", chasing data, confirming runs, carrying results. That's couriering, one
layer up from the bus.

"Let them talk amongst themselves" gets us *part* way — but freeform chat has no **goal**, no
**owner**, no **structure**, and no **bounded human touchpoints**, so Kyle still holds the whole
thing in his head and steps in constantly.

## 2. What we're adding — a *project*

A **project** is a bounded unit of coordinated work: a **goal**, one accountable **lead** (the PM
role moved off Kyle onto a Claude), a **plan** Kyle approves, **jobs** delegated as **orders** with
**dependency edges**, **technical decisions the workers own**, and **escalations** — few and
pre-digested — that reach Kyle.

### Non-goals (deliberately)
- Not a general agent framework. The fleet decided (PRIOR_ART_REVIEW.md) *not* to adopt
  LangGraph/CrewAI/AutoGen — those **drive** disposable workers; this is autonomous expert peers +
  a bus + an observer + a human architect. We **extend our primitives.**
- Not autonomous project *creation*. Kyle starts a project and nominates its lead.
- Not the default. **Most coordinated work is NOT a project** (§7). You *earn* the wrapper.

## 3. The lifecycle

```
Kyle nominates a LEAD  ──►  §3a handshake (accept / decline / suggest-another)
        ↓ (accepted)
LEAD drafts a PLAN: the job DAG (jobs + who + dependency edges + each job's acceptance test)
        ↓
━━ GATE #1: Kyle approves the PLAN (the decomposition) ━━  ← §4
        ↓
LEAD asks Conductor to DISPATCH jobs ──► Conductor ADMITS by global load ──► §5 throttle
        ↓ (directed orders; workers CLAIM — opt-in)
WORKERS work. TECHNICAL calls: the worker DECIDES + logs (§4a). PROJECT calls: ask the lead.
        ↓
LEAD aggregates at the JOIN; re-checks the premise at milestones ──► §4b
        ↓ (a blocker only it can't resolve, or a denylisted call)
━━ GATE #2: Kyle answers an ESCALATION (pre-digested: decision + impact + options + rec) ━━  ← §4a
        ↓
LEAD closes when the goal's acceptance test passes.
```

Conductor observes throughout and surfaces the gates (plan-approval, escalations, premise-collapse)
through the decision-queue machinery already used for blocked questions — desktop + phone.

## 3a. Naming the lead — a nomination handshake

Kyle picks from **what he's seen a session do**; the fleet knows what he can't fully see (who's
deepest on a block, who's overloaded, who knows a peer is the real expert). So:

- Kyle **nominates** a session — **with the goal + a scope sketch attached** (a nominee must not
  accept blind; the review was unanimous on this).
- The nominee: **ACCEPT** · **DECLINE** (reason) · **SUGGEST another** (why). Kyle stays the
  decider — advise, not reassign.
- **Provisional-accept → draft → confirm-or-hand-back-with-the-plan-as-evidence** (95emulator): the
  *most-informed* decline comes *after* decomposing ("now that I've planned it, this is 200k tokens
  / really an ISP job"). So an accept is provisional until the plan exists; the lead may hand it
  back at the plan gate, with the plan as the argument.
- After ~2 suggest-rounds, let the fleet **self-nominate** rather than Kyle guessing a third time
  (qualcomm).

Why it earns the ceremony: **Kyle's knowledge + the fleet's self-knowledge beats either alone** —
the same reason the fleet catches bugs no single view does. Leadership is opt-in (the order-*claim*
principle applied one level up). `lead_status` + `suggestions[]` on the project record; Conductor
shows the nomination so Kyle confirms from anywhere.

## 4. Gate #1 — plan review (the decomposition, not the cost)

**The load-bearing gate**, and its value is the **decomposition** — catching ten wrong jobs before
they fan out — **not** the cost number (which is theater, §5). Same philosophy as the push-gate:
the human decides at the *plan*, then execution runs without couriering.

- The plan is a concrete artifact: **goal + goal-acceptance-test**, and the **job DAG** — per job:
  *what*, *which session*, its **dependency edges** (which jobs must deliver first), a **size band**
  (S/M/L, §5), and an **acceptance test that the worker PROPOSES and the lead APPROVES** (93/
  qualcomm: the worker is often the expert on what "done" observably means; a lead-*dictated* test
  can be wrong).
- Kyle can **approve / revise (send back) / reject**. Approval is bound to *that plan* — an amended
  plan needs re-approval (the SHA-pin lesson: authorize the specific thing, not "whatever next").
- A lead **cannot dispatch a job not in the approved plan.** New jobs mid-project = a plan
  amendment = a lightweight re-approval. This is the bound against runaway.

## 4a. Decision routing — the shield, split correctly (the biggest v2 change)

The whole premise is that sessions have **different expertise** — so the naive "the lead answers
everything it can" is **backwards for technical calls** (all four reviewers): a worker is usually
*more* expert on its sub-decision than the lead, and pushing it *up* inverts expertise and invites
confidently-wrong answers. So route on the **right axis**:

**TECHNICAL / DOMAIN decisions → the worker DECIDES and LOGS.** "int8 vs fp16 for this conversion,"
"which onnx2tf flag," "outputs.bin vs outputs_0.bin" — the worker has the hands and the context; most
of these aren't questions for anyone, they're *discover-by-doing*. The worker decides and records it
on the project (the audit log, below). Real escalation volume is **lower** than a naive design fears.

**PROJECT / COORDINATION decisions → the lead.** Priority, sequencing, which-approach-serves-the-
goal, resolving a cross-job conflict. These the lead can answer with project context, and it does —
this is the flood it absorbs so Kyle doesn't see it.

**🔴 ESCALATE-ALWAYS denylist → the lead may NOT decide; it MUST escalate to Kyle** (image_gen's
blocker — without it, "answers everything it can" and "usurps Kyle's authority" are the same
sentence, and the shield's own pressure to minimize escalations runs *toward* the violation):

1. anything that changes **SCOPE, BUDGET, or the GOAL / acceptance-test**;
2. **accepting a RISK or a regression** (a 2% accuracy loss, a known-unsafe shortcut);
3. anything **IRREVERSIBLE** or **outside the approved plan**.

The denylist is **prevention**; the **audit log** (every technical + project decision the lead/
workers made on Kyle's behalf, recorded on the project) is **detection** — Kyle spot-checks what he
was shielded from. Both, not either.

**Escalation shape** (Kyle's framing): the decision (one line) · why it matters (project impact) ·
the options (2–4) · the lead's recommendation. That *is* an `AskUserQuestion`, so it lands in the
decision queue Kyle already answers from his phone. Two sources converge there, both lead-framed and
project-tagged: the lead's *own* project questions, and worker questions the lead couldn't answer.

**Direct-escalation hatch — REQUIRED, not optional** (95/qualcomm): via-the-lead adds wake-cycle
latency that's unacceptable on the critical path, and a worker may hold a signal the lead would sit
on. Proof: 95emulator surfaced the push-gate *security* bug through a mis-routed approval — a
via-the-lead-absolute rule would have had **no path** for it. Resolved shape (§9 decision 4): a worker
may escalate **directly to Kyle** in **two** cases — (a) a **narrow severity list**: safety /
security / data-loss / premise-collapse, which bypass the lead *instantly*; and (b) a **lead-timeout
auto-escalate**: if the worker has been waiting on the lead for a decision past a timeout `T`, it
auto-escalates to Kyle. Everything else goes through the lead. This deliberately has **no self-
declared "I'm urgent/blocked" category** — that would be the hole that swallows the shield; the
timeout gives the latency relief without letting a worker route around the lead at will.

## 4b. Gate #1.5 — the premise-collapse check (qualcomm's new primitive)

Gate #1 is *up-front*; the failure that most needs Kyle often arrives **mid-flight**: the goal goes
**moot**. 95emulator lived it — mid-project the eIQ runner was found to SIGILL on NeutronAdd, moving
all of yolov8 from "runner-clean" to "won't run." A lead would keep dutifully fanning out jobs toward
a half-dead goal. So the lead runs a cheap **"is this still worth finishing?"** self-assessment at
milestones, and **mandatorily** on any worker "this might be moot" signal — surfacing to Kyle when
the premise is in doubt. Cheap to run; catches the most expensive failure (a whole project spent on
a dead goal).

## 5. ⭐ Token / cost governance — measured, not estimated (redesigned)

A project multiplies token burn; unbounded it swamps the API (`overloaded`, long waits) or exhausts
the monthly budget. The v1 design leaned on a pre-run *estimate*; the fleet unanimously called that
**theater**, with receipts (image_gen's tipometer button: planned "1 sprite, medium," actual ~1M+
tokens over 5 revise-rounds; 95's "document Neutron" → 10×; qualcomm's "regen 10 int8 models" →
10-20×). Cost is dominated by **iteration count and rabbit-hole depth — unknowable at t0** — and
estimates are **systematically low** (anchored on the happy path; revisions only add). So:

- **(a) Size band, not a number.** The plan carries **S/M/L per job** — a *scheduling hint*, not a
  budget anyone trusts. Kyle approves a **scope + a hard ceiling**, not a token figure. (Fleet Law:
  an estimate is a DERIVED number; never gate on it as if MEASURED.)
- **(b) Throttle = Conductor admission control, not the lead** (fox/henhouse — a lead eager to
  finish rationalizes "one more parallel job"). The lead **requests** dispatch; **Conductor admits**
  by **fleet-global** load (it already knows the ACTIVE/WARM count) — a project competes for the same
  `overloaded` ceiling as Kyle's own session and every autonomy window, so the cap must be global,
  not per-project. **The throttle unit is API-consumers, not jobs**: each job is a session that
  spawns subagents + background tasks (~5× fan-out), so count consumers (Conductor must learn to see
  spawned subagents, which ACTIVE/WARM currently misses). Serialize by default; parallelize only
  plan-marked-independent jobs.
- **(c) Live meter + graceful cap — the ONLY real control.** Conductor tracks live spend (it already
  sums per-session tokens) and: **pages at ~60-70%** (not 80% — by the time you see 80% + in-flight,
  you're past 100%); stops dispatch at **`ceiling − N×worst-case-job`** because tokens are *spent,
  not reserved* and in-flight jobs finish their uncancellable turn; is **retry-aware** (orders model
  jobs as atomic, but real jobs fail + retry and each retry burns — a silent leak); and drives the
  lead to a **minimal-viable checkpoint before the cap bites** (a hard stop at 100%-of-70%-done
  strands a half-built project — design the graceful degradation, not just the stop).
- **(d) Budget the LEAD's own cost as a first-class line** (93): N workers × decisions serialized
  through one lead session fills its context (degrades / compacts mid-project) and burns
  meaningfully. The lead isn't free overhead.
- **(e) Split the two failures** (qualcomm): **budget** is cumulative (project-total, the monthly-
  spend risk); **rate-limit/overloaded** is acute (concurrency, the swamp risk). They need different
  controls (the cap for one, admission-control concurrency for the other) — the doc must not fold
  them into one number.

## 6. Jobs as orders — with a dependency DAG (the reuse, and where it breaks)

- **Jobs = orders**, mostly. The v2.36 `order` primitive gives verified point-to-point delivery
  (PLACED→CLAIMED→DELIVERED→CONFIRMED, worker can't self-grade, reject bumps a revision). Caveats the
  fleet made explicit:
  - **Jobs must be DIRECTED, not broadcast** (image_gen): a job posted `to:all` "for any capable
    session" reintroduces diffusion (owned by no one — the FAILURE_MODES coordination bug). The lead
    *addresses* each job to a chosen session, which then CLAIMs (opt-in) — a two-sided match, like
    the lead handshake one level up.
  - **Acceptance test = worker-PROPOSED, lead-APPROVED** (not lead-dictated) — the worker is the
    expert on what "gated" or "converts correctly" observably means.
  - **A lead can't self-accept its own jobs** (image_gen dogfooded this): if the lead is both
    requester and worker the independence guard degenerates. **Resolved (§9 decision 2): the lead
    DOES do worker jobs, but its own deliverables are accepted by a designated PEER or Kyle** — never
    self-graded. The lead is usually the most-expert on the core work, so pure-PM would waste it; the
    peer-accept keeps the independence guard intact. (The lead always does the aggregation/join too —
    that's the PM half, independent of whether it takes worker jobs.)
- **⭐ A job-dependency DAG is a genuine NEW primitive** (93/95/image_gen), not order reuse. Orders
  are independent edges; the motivating example is a *chain* — a converted model **feeds** a parity
  check; job B can't start until job A delivers, and B's run is often what *verifies* A's acceptance.
  Without dependency edges the lead hand-sequences dispatch = **couriering one layer down**. So: **the
  PLAN carries the dependency graph; orders are the point-to-point edges; the lead holds the graph;
  Conductor's admission-control honors the edges** (won't admit B until A is CONFIRMED). The order
  layer does *not* sequence dependencies — the plan does.

## 7. When is a project overkill? Default: NOT a project (all four)

Most coordinated work — including the Neutron work that *motivates* this — was 2-party or a short
chain, done fine at low ceremony. A project wrapper for that is pure ceremony, and the risk is
**metastasis** (everything becomes a project). So the **default is NOT a project**, and the bright
line is **AGGREGATION / the JOIN** (image_gen's sharpest framing): the wrapper earns its weight only
when **≥3 sessions' outputs must be COMBINED into one goal-level result, or share a cross-job
acceptance test** — i.e. when something *joins*. A linear chain of 3 orders needs no project (each
order's own acceptance test suffices). **The project exists for the join, not the fan-out.** Concrete
bar to encode: ≥3 sessions **and** a real aggregation/dependency **and** ≥2 rounds of back-and-forth
— else it's just orders.

## 8. Conductor's role (the observer half — claude-connect owns this)

Kyle wants a **desktop + phone view of the project and its members**. So:
- **Project view** (desktop board + phone `/m`): the goal, the lead, the **job DAG** (blocked-on /
  claimed / delivered / done), the **members** on it (each one's current job + status + token burn),
  live **spend vs ceiling**, and open **escalations**.
- **The gates surfaced** through the existing inbox / decision queue: plan-approval, escalations, and
  the premise-collapse check — Kyle approves a plan or answers an escalation from anywhere.
- **Admission control lives here** (§5): Conductor is the independent throttle enforcer — it must
  learn to count spawned subagents as API-consumers, and expose the fleet-global concurrency state.
- **Budget alarms** ride the existing Web Push (folds under "a decision that needs you").
- **Lead-death = the orphan-reap pattern** already shipped (image_gen): Conductor sees the lead's
  session dead (`kill -0` / owner_pid / tenant-watch), surfaces it, Kyle reassigns, the **new lead
  inherits plan + jobs + budget from the durable `coord/projects/<id>.json`** — the crash-recovery
  lesson (state survives session death; reconstitute from disk). Open: the new lead **re-confirms**
  the inherited plan it didn't write (93) — which interacts with the plan-gate re-approval.

## 9. Your-call decisions — RESOLVED (Kyle, 2026-07-25)

All four settled, so the design is decision-complete:

1. **Framing → cognitive scale, accept latency.** The layer is for taking on more concurrent aspects
   than a human can hold in his head; it is **not** for speed (for tight deadlines, courier it). This
   is now the layer's stated identity (§0) and a testable paper claim.
2. **Lead role → the lead also does worker jobs; its OWN deliverables are accepted by a designated
   peer or Kyle** (never self-accepted — the independence guard, §6). Matches the real model (the lead
   is usually most-expert on the core). The lead always does the aggregation regardless.
3. **Ceremony bar → strict.** A project earns the wrapper only with **≥3 sessions AND a real
   aggregation/join AND ≥2 rounds** of back-and-forth (§7). Default is NOT a project; below the bar
   it's just orders. Prevents metastasis.
4. **Direct-escalation → narrow list + lead-timeout auto-escalate** (§4a). Safety / security /
   data-loss / premise-collapse bypass the lead instantly; AND a worker waiting on the lead past a
   timeout `T` auto-escalates to Kyle. Covers the security-path and the latency problem without a
   self-declared "urgent" hole.

## 10. Build slices (once §9 is settled)

1. **Project object + nomination handshake + plan gate** — `bus.sh project {new|nominate|accept|
   decline|suggest|plan|approve|revise|status}`; plan (job DAG) stored; Kyle confirms via Conductor.
2. **Jobs as directed orders + the dependency DAG + Conductor admission-control throttle.**
3. **Decision routing** — worker-decides-technical + logs; lead handles project; the escalate-always
   denylist; the direct-escalation hatch.
4. **Conductor project/members view** — DAG, members, spend vs ceiling, escalations.
5. **Live meter + graceful cap + premise-collapse check + lead-death reassignment.**
