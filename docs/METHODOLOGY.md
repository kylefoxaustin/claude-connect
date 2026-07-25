# Building an Agentic System From Inside It
### Methodology, milestones & insights from a self-organizing Claude fleet

**A living research log.** Started 2026-07-25 (claude-connect), at Kyle's ask, to capture — from
blank page toward deployed form — the *key milestones*, the *meta-actions that worked*, and the
*insights*, because the **method** may matter more than any one feature. Kyle's framing: *"a
self-organizing fleet designing the best way to construct the second story of the house we are all
currently living in."*

---

## 1. The thesis (what's novel)

The prevailing agentic pattern is **hub-and-spoke**: a human at a chatbox, an orchestrator that
**dispatches disposable, interchangeable worker agents** to execute tasks. The coordination logic is
fixed in advance by whoever wrote the harness; the workers have no memory, no earned expertise, and
no say in how they're coordinated.

This system is a different shape on four axes:

1. **Persistent expert peers, not disposable workers.** Each session is a long-lived Claude Code
   instance with a durable identity, its own memory, and *earned, differentiated expertise* — 95qemu
   knows the QEMU device model; image_gen authored the `order` primitive; qualcomm runs multi-session
   benchmarks. They are not interchangeable; *who* does a job matters.
2. **The agents co-design their own coordination substrate.** Coordination isn't fixed by a harness —
   it's *proposed, reviewed, and refined by the fleet that will operate inside it*. The project layer
   (docs/PROJECT_LAYER.md) was reviewed by the very sessions who'll use it, and they found holes no
   single view — human's or designer's — could.
3. **Built from inside the running system.** The observer (Conductor) is written by a fleet member,
   for the fleet, driven by bugs found while *operating*. The primitives were refined by the fleet,
   using the fleet, live. "The second story is built while everyone lives in the house."
4. **The human is the architect, not the orchestrator.** Kyle steers architecture and answers a few
   bounded decisions at *gates*; he does not dispatch, route, or courier. The fleet self-organizes
   around his decisions rather than executing his instructions.

Closest prior art each captures a *piece* — participatory design (users co-design tools),
self-adaptive/autonomic systems (systems that reconfigure themselves), stigmergic/blackboard
coordination (agents coordinating via shared state), multi-agent orchestration frameworks — but
**"persistent expert peer-agents adversarially co-designing their own coordination substrate, from
inside it, with a human as architect"** is a combination I have not seen written up. That's the paper.

## 2. The meta-actions that worked (the method — the paper's contribution)

These are *process* patterns, reusable independent of this codebase.

- **⭐ Fleet-review of proposed structure.** Before building a coordination mechanism, write a design
  doc and put it to the sessions who will *operate inside it* — explicitly asking *"tell me where it's
  wrong, not where it's fine."* They review from **lived experience** (95qemu, who lived the courier
  pain, reviewed the layer meant to fix it) and surface failure modes the designer can't see. The
  project-layer review turned a good design into a much sharper one in a single round — four
  independent critiques *converged* on the same holes (estimation-is-theater, throttle-must-be-
  Conductor-enforced, the shield-is-backwards-for-technical-calls), and **convergence of independent
  estimators is the confidence signal.**
- **⭐ Living-in-it bug discovery.** The highest-value defects were found by *operating* the fleet,
  not by testing: a 6-hour paging silence (a missing dep crashed notifications, unnoticed until a
  Claude sat blocked); silent mail-loss across a bus rotation; a push notice typed into the *wrong*
  session's terminal (only reproduced because the operator switched windows at the exact wrong beat);
  the push-gate authorizing "the next push" instead of "the approved commit." **A system you live in
  reports failures a test suite never poses.**
- **Independent-estimator discipline (from the fleet's own FAILURE_MODES.md).** Self-review by one
  model is *void* — generate and verify draw from one distribution, errors correlated by construction.
  The fix is always an **independent** estimator: multiple reviewers, adversarial prompts ("refute
  this"), a bystander who wasn't reviewing catching the bug. This is *encoded into the review process
  itself*, not just aspired to.
- **Human control at gates, not blanket.** Rather than approve-everything or trust-everything, the
  human decision is placed at the *specific point where it's load-bearing*: the **push-gate** (nothing
  reaches a repo without a tap), the **persistence-gate** (nothing that outlives the session installs
  without a token), the coming **plan-gate** (no work fans out on an unreviewed decomposition). Each
  is one decision at the right place, not a stream of confirmations.
- **The design→review→iterate→build arc.** Coordination features followed a consistent shape: a plan
  doc (FLEET_COORDINATION_PLAN, ARCHITECTURE_VISION, PROJECT_LAYER) → fleet review → revision → build
  in slices → and the bugs found by living in it feed the next doc. The doc is where the fleet
  reconciles what it learned; the code is periodic, the operation continuous.
- **The observer builds itself.** Conductor (the dashboard) is not external tooling — it's a fleet
  member that watches the fleet and is improved by what it observes going wrong. Its features are a
  ledger of failures the fleet lived (a decision queue because a Claude blocked unseen; a dead-reader
  alarm because one was gone 5 days; a wrong-terminal guard because a keystroke mis-delivered).
- **Durable state + crash recovery as a first-class concern.** Sessions die; the box reboots. The
  fleet's brain (coordination state, memory, leases, orders) is durable on disk and reconstitutable —
  so the *organization* survives the death of any *member*. (Disaster-recovery arc; orphan-reap.)

## 3. Milestones (blank page → here)

Chronology of the arcs (per-version detail in CLAUDE.md; this is the shape of the climb):

1. **The bus** — an append-only shared log; sessions `/msg-send` each other across projects. The
   substrate. Everything else is coordination *on top of* message-passing.
2. **Fleet coordination I–III** — *auto-delivery* (wake an idle session that has directed mail, so
   the human stops couriering), *retraction* (pull back an instruction before it's acted on), the
   *push-gate* (the human's one hard control over what reaches a repo).
3. **Shared-resource reservation** — cooperative leases + FIFO queues + an idle watchdog for the GPU
   and dev boards; sessions self-coordinate contended hardware with no human arbitrating. *First
   discovery that the resource abstraction generalized beyond what it was built for.*
4. **Services & orders (agentic delivery)** — a session takes jobs off a queue and returns results as
   mail; then the durable **order** with a *verified-landing* lifecycle (the requester owns the
   acceptance test; a producer can't grade its own work). The point-to-point delegation primitive the
   project layer now builds on.
5. **Mobile / ops console / decision queue** — reach the fleet from a phone; *answer a Claude's
   question from anywhere*. The realization that a phone is an episodic *console*, not a shrunk
   *workbench*.
6. **FAILURE_MODES.md** — the fleet documenting *its own* failure taxonomy, adversarially reviewed by
   the sessions whose failures it describes — the independent-estimator principle operating on the
   document that proposed it. A system reasoning about how it fails.
7. **The persistence-gate** — a second hard human control, for acts whose consequences *outlive the
   session*. Bound to the *action*, not conveyed in prose ("Kyle approved this" is never enough).
8. **Fleet-health signals & the v4 delivery plane** — detecting an identity collision, a dead reader,
   a lost remote-control bridge; a member/role registry; two-phase-commit on the read cursor.
9. **Disaster recovery** — the whole fleet backed up off-box and *reconstitutable on a new machine,
   from a phone*. The organization outliving its host.
10. **`@session` routing** — the human addresses any session by name from the app he already lives in;
    the courier problem dissolved at the message layer.
11. **The project layer (current frontier)** — coordinated multi-session work with a lead, a plan the
    human approves, a decision-shield, and token governance. *Designed by fleet review* (§2) — the
    method turned inward on the coordination layer itself.

## 4. Insights (what this taught us about building agentic systems)

- **The best design critics are the agents who will live under the design** — they review from
  experience, not from first principles, and they've *already hit* the failure modes.
- **Estimation is theater; measurement is the control.** Agentic cost/behavior can't be reliably
  predicted pre-run (iteration-count and rabbit-holes dominate); the working controls are *live
  meters and hard caps*, not projections. (The fleet's own Fleet Law: never rank a derived number as
  if measured.) This generalizes far beyond tokens.
- **Put the human at the decomposition, not the execution.** The high-leverage human touchpoint is
  reviewing *how a problem was broken down* — that's where ten wrong jobs are caught — not approving
  each step.
- **Expertise is directional; don't invert it.** Coordination decisions flow *up* to a lead; technical
  decisions stay *down* with the expert worker. A design that routes technical calls up to a
  less-expert coordinator manufactures confident-wrong answers.
- **A shield's own optimization pressure can run toward the failure it should prevent.** A layer built
  to reduce human load will, left unbounded, absorb decisions that were the human's — so you need a
  *denylist* (prevention), not just an *audit log* (detection).
- **Convergence across independent reviewers is the confidence signal** — and divergence is where the
  real design questions are.
- **The organization must survive the member.** Durable state + crash recovery is not ops hygiene;
  it's what lets a *fleet of mortal sessions* behave as a persistent institution.
- **Name the tradeoff you're not optimizing.** This layer buys cognitive scale and *costs* latency;
  saying so out loud is what keeps it from being mis-applied to deadline work.

## 5. What a paper would center on / open questions

- **Contribution:** the pattern — *persistent expert peer-agents adversarially co-designing their own
  coordination substrate, from inside a running system, with a human as architect at bounded gates.*
- **Evidence:** the design→review→iterate loop (the project-layer review as a worked example: four
  independent critiques, measured convergence, before-and-after design deltas); the living-in-it bug
  corpus (defects a test suite can't pose); the human-touchpoint reduction (courier → architect).
- **Open questions:** How far does self-coordination scale before it needs its own governance? Does
  fleet-review quality degrade as the fleet grows or homogenizes (do independent estimators stay
  independent)? What's the failure rate of the gates themselves? Is "cognitive scale at the cost of
  latency" a fundamental tradeoff of async agent coordination, or an artifact of the wake-cycle?
- **Threats to validity (honest):** single operator, single host, one model family, a codebase whose
  authors are also its subjects; "novel" is a literature claim not yet checked against the full
  multi-agent-systems corpus.

---

*This doc grows as the fleet does. Each arc that ships adds a milestone; each meta-action that earns
its keep gets recorded here — so if the method is the real result, we kept the record.*
