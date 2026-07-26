# Related Work and the Wedge

*Deliverable for the `relwork` job of the `ieee-paper` project. Governed by `relwork-brief.md`.
Status: DRAFT v1 by the lead (claude-connect). External characterizations are from training
knowledge (cutoff 2026-01) and are marked ⚠VERIFY where a citation must be confirmed before the
camera-ready.*

## The question this section answers

> Do existing agentic workflows *know* what their agents are good at — and inexperienced at — and
> decompose tasks to the agents that will benefit most (and whom the task will most improve)?

The honest answer is: **capability-aware routing is common, but it is almost always keyed on a
*declared* role or a *predicted* fit, applied to *stateless, same-model* agents. Routing on
*accumulated, lived* experience across *long-lived, heterogeneous* peers — and, crucially, a
substrate whose competence *compounds* across tasks — is the gap this paper fills.**

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
supervisor graphs, Mixture-of-Agents [⚠VERIFY: Wang et al., 2024], and query routers such as
RouteLLM [⚠VERIFY] and FrugalGPT [⚠VERIFY: Chen et al., 2023]. This *is* capability-aware, but the
capability is *asserted in a description* or *inferred from difficulty*, not earned by doing.

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
2024] searches the space of agent programs; the Darwin Gödel Machine [⚠VERIFY] is a self-modifying
single agent. These operate at *design-search* time, not at *runtime* over a standing team, and they
optimize an agent *program*, not the allocation of work to experienced peers.

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

**Distinction 2 — compounding competence (the central claim).** The novelty is *not* that we begin
with expert agents. **A brand-new fleet is a valid starting point.** The claim is that the substrate
*accumulates* expertise the way a human team does: as sessions become good at particular tasks — and
as shared context, conventions, and a division of labour accrue on the bus — **the network grows
stronger on the N+1 task**. Task N+1 is cheaper and better *because of* tasks 1…N.

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
falsifiable core: **does measured per-task cost fall, and quality rise, as the fleet matures?** We
operationalize and test this as RQ4 (see the evaluation), using the longitudinal deployment record.

## An honest limitation of the present system

The "knowing" in our current implementation is the **lead's contextual judgment**, informed by the
shared bus history, the fleet registry / asset cards, and each session's `CLAUDE.md` — it is *not*
yet a formal, queryable capability index. This is at once a strength (the signal is rich, grounded
in real artifacts, and human-legible) and a limitation (it is not systematized or automatically
maintained). A capability registry, or expertise inferred directly from the bus corpus, is clear
future work, and we state it as a caveat rather than conceal it.
