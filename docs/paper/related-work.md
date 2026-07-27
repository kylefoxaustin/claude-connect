# Related Work and the Wedge

*Deliverable for the `relwork` job of the `ieee-paper` project. Governed by `relwork-brief.md`.
Status: DRAFT v2 by the lead (claude-connect) — revised after a web citation-verification pass
(`related-work-verification.md`), which reclassified Mixture-of-Agents, added the 2025
memory-augmented-MAS line (G-Memory et al.) that bounds our novelty, added MAPE-K, and softened the
compounding-competence claim to its ablation-tested form. Every ⚠VERIFY citation (arXiv IDs included)
is a single-pass lead, NOT a warrant — all must be confirmed against primary sources before
camera-ready (esp. MoA 2406.04692, flagged UNCONFIRMED).*

## The question this section answers

> Do existing agentic workflows *know* what their agents are good at — and inexperienced at — and
> decompose tasks to the agents that will benefit most (and whom the task will most improve)?

The honest answer is: **capability-aware routing is common, but it is almost always keyed on a
*declared* role or a *predicted* fit, applied to *stateless-by-default, same-model* agents.** Two
things differ in our method — routing on *accumulated, lived* experience across *long-lived,
heterogeneous* peers, and a substrate whose competence *compounds* across tasks — but we are careful
**not to claim the compounding idea itself is novel**: a **2025 memory-augmented multi-agent line
(G-Memory, RCR-Router, MasRouter — §below) already pursues cross-task team competence.** What is
under-explored, and where we position our contribution, is the *combination* — **long-lived
human-in-the-loop session identities that literally *lived* the work, routed by a lead's grounded
judgment over real artifacts, studied as a running-deployment trajectory** rather than a benchmark
evaluation of a memory mechanism.

We survey the field by *how it routes*, then draw the two distinctions that constitute our claim.

## A taxonomy of task-to-agent routing

**(1) Role-assignment frameworks.** AutoGen [⚠VERIFY: Wu et al., 2023], CrewAI, MetaGPT [⚠VERIFY:
Hong et al., 2023], and ChatDev [⚠VERIFY: Qian et al., 2023] assign agents *roles* — "researcher,"
"architect," "reviewer," "product manager" — and route tasks to those roles. The decisive property
is that the roles are **personas assigned up front via system prompts**, and the agents are
typically **one base model wearing different hats**. The "coder" is not experienced at coding; it is
*instructed to behave like a coder*. Routing here is persona-to-task template matching, and the
"expertise" has no history behind it.

**(2) Router / supervisor patterns.** A supervisor LLM or a learned router selects a sub-agent,
tool, or model from **declared descriptions** or **predicted difficulty/cost** — LangGraph's
supervisor graphs, **MasRouter** [⚠VERIFY: 2502.11133, ACL 2025] (a learned controller allocating
collaboration mode + roles + model per query), and query/model routers such as **RouteLLM**
[⚠VERIFY: 2406.18665] (strong-vs-weak *different* models by predicted difficulty) and **FrugalGPT**
[⚠VERIFY: Chen et al., 2305.05176, 2023]. This *is* capability-aware, but the capability is *asserted
in a description* or *inferred from difficulty*, not earned by doing. **(Note: Mixture-of-Agents**
[⚠VERIFY: Wang et al., 2406.04692 — ID UNCONFIRMED, ICLR 2025] **is *not* a router — it runs all
proposers in parallel and *aggregates* their outputs; it belongs with ensembling, not fit-based
selection, and we reclassify it accordingly.)**

**(3) Dynamic agent selection — the nearest neighbour to our work.** DyLAN [⚠VERIFY: Liu et al.,
2023] ranks agents by an inference-time "importance" score; AutoGen's Captain Agent / AutoBuild and
AutoAgents [⚠VERIFY] *build a team* by selecting or generating agents for a task from a library.
These systems genuinely *score or select* agents per task — the closest anyone comes to "who is best
for this." But the selection is still, in the main, **benchmark-optimized choice among
prompt-differentiated agents**: "which generated persona fits this task," not "which of these
sessions has actually done this kind of work before."

**(4) Model-level and skill-library mechanisms.** Mixture-of-Experts routes *tokens* to expert
subnetworks — learned routing, but at the neural level, not the agent/task level. Voyager [⚠VERIFY:
Wang et al., 2023] accumulates and reuses a *skill library* in Minecraft — the closest prior work to
"accumulated competence," but it is a *single* agent reusing its *own* skills, not a division of
labour among peers with divergent histories.

**(5) Automated agent design.** ADAS (Automated Design of Agentic Systems) [⚠VERIFY: Hu et al.,
2408.08435, 2024] searches the space of agent programs; the Darwin Gödel Machine [⚠VERIFY:
2505.22954, 2025] evolves a **population/archive of self-modifying coding agents** (not a single
agent). These operate at *design-search* time, not at *runtime* over a standing team, and they
optimize an agent *program*, not the allocation of work to experienced peers. The classical
self-adaptive-systems analogue is **MAPE-K** (Monitor–Analyze–Plan–Execute over shared Knowledge;
[⚠VERIFY: Kephart & Chess, *The Vision of Autonomic Computing*, IEEE Computer 36(1), 2003]).

**(6) Memory-augmented multi-agent systems — the *nearest* neighbour, and the reason we do not claim
compounding as our novelty.** A 2025 line gives multi-agent systems persistent cross-task memory:
**G-Memory** [⚠VERIFY: 2506.07398, NeurIPS 2025] maintains a hierarchical memory (insight / query /
interaction graphs) that stores cross-task insights and prior collaboration trajectories, so the
team's success *improves over successive tasks* — task *N+1* better because of 1…*N*, across a team.
That is our Distinction 2 almost verbatim, and it must be cited and distinguished, not written around.
**RCR-Router** [⚠VERIFY: 2508.04903, 2025] routes *structured memory to agents within a task*
(context-to-agent, not task-to-peer). The broader framing is **transactive memory** ("who knows
what") for agent teams. The distinction that survives (§Distinction 2) is *what kind of memory and
whose*: these are **retrieval over a shared memory store by ephemeral agents**, benchmarked; ours is
a **standing set of long-lived session identities that lived the work**, observed as a deployment.

## The wedge: two distinctions

**Distinction 1 — routing on LIVED experience, not DECLARED role.** In our method the lead routes
work to peers by their *accumulated history from real work*, read from a shared, append-only bus, a
fleet registry of asset cards, and each session's own long-lived context. When the lead assigned the
"case studies" job to the image-generation session, it did so because that session had *lived* the
cost blow-up it was asked to document — not because it had been prompted with a "case-study-writer"
persona. The reason this is rare is **structural**: most frameworks deliberately instantiate
**stateless, fresh agents per task** (for reproducibility, cost, and simplicity), which *precludes*
lived-experience routing by construction. This is the "context-heavy sessions vs. start-from-scratch
agents" axis.

**Distinction 2 — compounding competence, *and an honest boundary on its novelty*.** The substrate
*accumulates* expertise the way a human team does: as sessions become good at particular tasks — and
as shared context, conventions, and a division of labour accrue on the bus — the network grows
stronger on the N+1 task; a brand-new fleet is a valid starting point. **We do not claim this idea is
new** — G-Memory [§(6)] pursues exactly cross-task team competence. What we contribute is *its
particular realization and a test of it*: the "memory" is **not a retrieval store but the lived
context of long-lived, human-in-the-loop session identities**, and — critically — **we put the
compounding claim to an ablation test and report that its naive form did not survive** (§RQ4): what
actually compounds is the *committed carrier* (code, comments, `CLAUDE.md`) that any fresh session
re-reads, while lived session-memory buys *efficiency and recognition*, not raw capability, and most
so on open searches a fresh agent cannot cheaply bisect. That measured, partly-negative result — not
a novelty assertion — is the contribution here.

The contrast is sharp and, we argue, definitional:

| | Stateless orchestrated agents | Peer substrate (ours) |
|---|---|---|
| State across tasks | none — reset each task | persistent per session + shared bus |
| Position on the learning curve | **permanently at task 1** | advances with each task |
| Expertise signal for routing | declared role / predicted fit | demonstrated, lived history |
| Value model | per-task capability | a **trajectory** of compounding competence |

Because stateless agents reset every task, they pay full cost with no transfer — they are
*permanently at task 1*. A persistent, heterogeneous peer network instead forms a *team*, and the
value it delivers is a **trajectory**, not a starting condition. This reframing yields the paper's
falsifiable core: **does measured per-task cost fall, and quality rise, as the fleet matures — and if
so, *because of what*?** We operationalize and test this as RQ4 (six A/B ablations + a pre-registered
baseline). **The answer is nuanced and we report it as such:** the naive "session-memory makes N+1
dramatically cheaper" is *refuted*; what compounds is the committed carrier, with lived context
buying efficiency/recognition on open-ended tasks — sharpening the distinction from G-Memory-style
retrieval rather than resting on an untested slogan. *(The "trajectory" row of the table above is
therefore a **hypothesis the deployment tested and refined**, not an asserted property.)*

## An honest limitation of the present system

The "knowing" in our current implementation is the **lead's contextual judgment**, informed by the
shared bus history, the fleet registry / asset cards, and each session's `CLAUDE.md` — it is *not*
yet a formal, queryable capability index. This is at once a strength (the signal is rich, grounded
in real artifacts, and human-legible) and a limitation (it is not systematized or automatically
maintained). A capability registry, or expertise inferred directly from the bus corpus, is clear
future work — and it is precisely a **transactive memory system** ("who knows what") for an agent
team; naming it that way situates the caveat in an existing literature rather than concealing it.
