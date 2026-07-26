# relwork job — brief (governs the `relwork` job of the `ieee-paper` project)

This is the authoritative brief for the **related-work + wedge** section. The job's one-line label
is short; THIS is what to actually build. Verify every external claim with a real citation before it
enters the paper — the characterizations below are from the lead's training knowledge (cutoff
2026-01) and must be checked, not trusted.

## The research question, in Kyle's framing (put this front-and-centre)

> **Do any existing agentic workflows *know* what their agents are good at — and inexperienced at —
> and decompose tasks to the agents they believe will benefit the most (and whom the task will make
> most competent)?**

The section must answer this precisely and honestly, drawing the boundary between what exists and
what we claim is new.

## The landscape to survey (categorize by HOW they route — verify + cite each)

1. **Role-assignment frameworks** — AutoGen, CrewAI, MetaGPT, ChatDev. Route tasks to roles
   ("researcher", "architect", "reviewer"), but the roles are **personas assigned up front via
   system prompts**, and the agents are typically **the same base model wearing different hats**.
   No learned competence — persona-to-task template matching.
2. **Router / supervisor patterns** — LangGraph supervisor, Mixture-of-Agents, RouteLLM / FrugalGPT.
   A dispatcher (or learned router) picks a sub-agent / tool / model from **declared descriptions**
   or **predicted difficulty/cost**. Capability-aware, but the capability is *declared or cost-
   predicted*, not earned.
3. **Dynamic agent selection — the nearest neighbour.** DyLAN (inference-time agent-importance
   ranking), AutoGen Captain Agent / AutoBuild (build a team by selecting/generating agents from a
   library), AutoAgents. These *score or select* agents per task — but still mostly
   **benchmark-optimized selection among prompt-differentiated agents**, i.e. "which generated
   persona fits," not "which of these sessions has actually done this before."
4. **Model-level & skill-library** — Mixture-of-Experts (learned token routing, neural-level, not
   agent-level); Voyager (a single agent accumulating + reusing its own skill library — closest to
   "accumulated competence," but one agent, not routing among peers).
5. **Automated agent design** — ADAS (Automated Design of Agentic Systems), Darwin Gödel Machine
   (self-modifying single agent). Meta-level design search, not runtime expertise-routing.

## The wedge (our two distinctions — this is the paper's core)

**Distinction 1 — routing on LIVED experience, not DECLARED role.** We route to peers by their
*accumulated, demonstrated history from real work* (image_gen wrote the tipometer case study because
it *lived* the cost blow-up), not by a persona prompt. The reason this is rare is **structural**:
most frameworks deliberately spin up **stateless, fresh agents per task** (reproducibility, cost),
which *precludes* lived-expertise routing by construction. This is the "context-heavy sessions vs.
start-from-scratch agents" axis.

**Distinction 2 — COMPOUNDING COMPETENCE (Kyle's reframe — make this a headline claim).**
The novelty is **not** "we start with expert agents." **A brand-new fleet is a valid starting
point.** The claim is that the substrate *accumulates* expertise the way a human team does: as
sessions become good at specific tasks, **the network gets stronger on the N+1 task** — task N+1 is
cheaper and better *because of* tasks 1…N.
- **Stateless agents are permanently at task 1** — no compounding, every task pays full cost with
  no transfer. That is the baseline our method is measured against.
- Persistent heterogeneous peers form a **learning network / team**: competence, shared context,
  and division-of-labour accrue over the deployment.
- This makes the value a **trajectory**, not a starting condition — and it is **testable**: does
  measured per-task cost fall / quality rise as the fleet matures? (ties to RQ4 convergence and the
  longitudinal evidence.) The section should frame this as the falsifiable version of the thesis.

## What the section must deliver

- A crisp taxonomy of routing mechanisms (declared-role / router / dynamic-selection / skill-library
  / auto-design) with citations.
- The explicit statement that **capability-aware routing exists, but keyed on declared role or
  predicted fit over stateless same-model agents** — and that **routing on accumulated lived
  experience across long-lived heterogeneous peers, with compounding competence over N tasks, is the
  gap we fill.**
- Honest limitation of *our* current system: the "knowing" is the **lead's contextual judgment**,
  informed by the shared bus history + fleet registry/asset cards + each session's CLAUDE.md — not
  yet a formal, queryable capability index. Name a capability registry / bus-corpus-inferred
  expertise as future work. State it as a caveat, not a hidden weakness.
