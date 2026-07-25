# PAPER (working draft) — the IEEE submission

**Status:** SKELETON / build-as-we-go. Working draft of an IEEE **Engineering Research**
(design-science) paper, evaluated by a **longitudinal deployment case study**. Final form →
IEEEtran LaTeX (`\documentclass[conference]{IEEEtran}` for an ~8–10pp SE-conference target such as
ICSE/FSE/ASE, or `[journal,compsoc]` for TSE ~12pp). This markdown maps 1:1 to the IEEE sections so
conversion is mechanical. `⟦DATA-NEEDED⟧` marks a number we must measure before submission;
`⟦TODO⟧` marks prose to finish. The informal running log that feeds this is `METHODOLOGY.md`.

> **Paper type — state it explicitly (the standard requires it).** This is an *Engineering
> Research* contribution per the ACM SIGSOFT Empirical Standards: describe the artifact, justify it,
> conceptually + empirically evaluate it via a *named* method (a longitudinal case study with
> triangulated evidence + design-choice ablations), compare to the state-of-the-art baseline
> (orchestrator-dispatches-workers). A benchmark is **one** option, not a requirement — "outperform
> on *some* dimension." The novelty is high, so a *preliminary* but honest evaluation can clear the
> bar (ICSE's own rule) *provided we do not overclaim.*

---

## Title (candidates — iterate)
1. **Conductor: In-Vivo Adversarial Co-Design of a Multi-Agent Coordination Substrate Under a Human
   Architect**
2. **Building the House From Inside It: How Persistent Expert Agents Co-Design Their Own
   Coordination Substrate**
3. **The Architect and the Fleet: Reversibility-Gated Human Oversight of Self-Coordinating LLM
   Agents**

*(Kyle's starter — "Conductor: a novel way to design agentic systems" — is the plain-language
version; the above sharpen the specific, defensible wedge so a reviewer can't dismiss it as "another
orchestration framework.")*

## Abstract ⟦TODO — tighten to ~200 words after RQ numbers land⟧
Multi-agent LLM systems today are **hub-and-spoke**: a human at a prompt, an orchestrator dispatching
interchangeable worker agents through a coordination structure fixed by whoever wrote the harness.
We report a different arrangement, built and operated for ⟦N⟧ months on a single workstation running
⟦M⟧ persistent Claude Code agents: the agents are **long-lived domain experts** that **adversarially
co-design the coordination substrate they inhabit — from inside the running system — while a human
acts as architect, ratifying only irreversible acts through reversibility-calibrated gates.** We
describe the method and the system (Conductor: a shared message bus + durable coordination state + an
observer dashboard + human-architect gates), catalog ⟦K⟧ coordination mechanisms the agents derived
and the production failure modes each closed, and evaluate via a longitudinal case study that
operationalizes "better coordination" as human-intervention count, coordination-failure/message-loss
rate, adversarial-review defect-discovery rate, and independent re-derivation of mechanisms. ⟦DATA-
NEEDED: headline results.⟧ We position the approach against agent-orchestration frameworks,
self-designing-agent work (ADAS, the Darwin Gödel Machine), autonomic computing, blackboard/
stigmergic coordination, and participatory design, and argue its novel combination: substrate-
between-persistent-peers, designed in vivo, selected by adversarial peer critique, with a retained
human architect.

**Index Terms** — multi-agent systems, large language models, self-adaptive systems, human-in-the-
loop, software coordination, design methods.

---

## I. Introduction

**Motivation (a concrete failure scenario).** ⟦Draft from the real record:⟧ two agents launched in
one repository posted under one identity and silently overwrote each other's git work for ~10 hours;
a bus rotation silently discarded unread messages; a human relayed data between two agents by hand
for tens of minutes per exchange; an agent sat *blocked on a human decision for six hours* because a
missing dependency had crashed the notification path unnoticed. These are not model-capability
failures — they are **coordination** failures, and each surfaced only in *production*, from *living
in* the system.

**Problem.** A long-lived, heterogeneous fleet of autonomous LLM agents needs its coordination
substrate to *evolve* against failure modes that are invisible until the system runs. Existing
multi-agent frameworks fix the coordination structure **before** runtime.

**Gap.** (1) Orchestration frameworks (AutoGen, MetaGPT, CrewAI, LangGraph) are designer-authored and
static. (2) Self-designing-agent work (ADAS, Darwin Gödel Machine) optimizes a *single* agent's
code/tools *offline* against a *scalar benchmark* in a sandbox. **Neither co-designs the inter-agent
substrate, in vivo, on a live fleet, with a human architect.**

**Approach (one paragraph).** We let the agents themselves — persistent, specialized, adversarially
critiquing one another under an "independent-estimator" discipline — propose, review, and implement
changes to their shared coordination substrate while the system is live, and we keep a human as the
*architect* who ratifies only the irreversible acts, behind gates calibrated to how far an act's
consequences outlive the actor.

**Contributions** ⟦refutable, forward-referenced — reviewers scan for this list⟧:
1. A **design method** — *in-vivo adversarial co-design of a coordination substrate by persistent
   expert agents under a reversibility-gated human architect* — stated so others can adopt it (§IV).
2. **Conductor**, a system realizing the method: a three-plane message bus + durable coordination
   state, an observer dashboard, and the human-architect gates (§III).
3. A **catalog of agent-derived coordination mechanisms** (member-keyed cursor, two-phase read-
   commit, verified-delivery orders, reversibility gates, …) and the production failure mode each
   closed (§IV, §V).
4. A **longitudinal deployment case study** that operationalizes "better" as human-touchpoint,
   coordination-failure, defect-discovery, and convergence constructs, against an orchestrator
   baseline, with design-choice **ablations** (§V).
5. A **public artifact** (the system + the design-record corpus) for independent inspection (§VI).

**Roadmap** — folded into the contribution forward-references above (per Peyton Jones).

## II. Background & Related Work
Position at the intersection of five literatures; each cluster ends in *why it doesn't close our
gap*. ⟦cite inline; full refs below⟧
- **Multi-agent LLM orchestration** — AutoGen [ref], MetaGPT, ChatDev, CAMEL, LangGraph, CrewAI,
  AutoGPT. *Overlap:* message-passing LLM agents on a coordination layer. *Distinction:* the
  coordination structure is **human-authored before runtime and static**; ours is **redesigned by the
  agents while running.** Frame: *the framework is the object of design, not the tool.*
- **Self-adaptive / autonomic computing (MAPE-K)** — Kephart & Chess; de Lemos roadmaps. *Our honest
  classical anchor.* *Distinction:* autonomic systems *select among predefined adaptations*; our
  agents **invent mechanisms outside any predefined adaptation space**, and manager = managed element.
- **Blackboard architectures & stigmergy** — Hearsay-II; Nii; Theraulaz & Bonabeau. Our bus +
  `bus-state/` files *are* a blackboard; leases/watermarks/orders *are* stigmergy. *Distinction:* the
  medium's protocol is architect-fixed in classical work; **our agents modify the blackboard's own
  protocol from inside it** — the meta-level claim.
- **Mixed-initiative / HITL** — Horvitz, *Principles of Mixed-Initiative UI*. Our push/persistence
  gates are textbook deferral on high-cost/irreversible acts. *Distinction:* classic MI negotiates
  *one task, one user, one assistant*; ours is a **human architect over a persistent agent society,
  with HITL calibrated to reversibility/persistence.**
- **Participatory / co-design** — Muller & Kuhn. *Distinction:* the participants are **autonomous
  agents designing continuously in production, who *implement* substrate changes**, not users voicing
  preferences.

**Pre-empt the two "isn't this just…?" neighbors by name:**
- **ADAS — Automated Design of Agentic Systems** (Hu, Lu, Clune 2024): a meta-agent programs better
  agents against a benchmark archive.
- **Darwin Gödel Machine** (2025): agents rewrite their own source, scored on SWE-bench.
- Also situate vs. Voyager, LATM, CREATOR, and self-evolving-agent surveys.

**Our five-point differentiation (state it explicitly; do NOT claim "first to modify own tooling"):**
(1) object of design = the **shared coordination substrate between persistent peers**, not one
agent's code; (2) **in vivo on the live production fleet**, not an offline sandbox where a bad change
is harmless; (3) selection pressure is **adversarial peer critique** (independent-estimator), not a
scalar reward; (4) **persistent specialized identities**, not interchangeable archive candidates;
(5) we **retain** a human architect where ADAS/DGM aim to **remove** the human — a deliberate,
opposite, defensible commitment.

## III. System Design / Architecture
Design goals → architecture (one figure ⟦FIG 1: the three planes + observer + gates⟧) → components →
why, not just what.
- **The substrate:** the append-only message **bus**; durable `bus-state/` (identities/members,
  leases, watermarks, orders, coordination records) — a *shared blackboard whose protocol the agents
  edit*.
- **Coordination primitives:** auto-delivery, retraction, resource leases + queues, verified-delivery
  **orders**, roles.
- **The observer:** **Conductor** the dashboard — built by a fleet member, from failures observed
  while operating; surfaces state and the human's decision queue on desktop + phone.
- **The human-architect gates:** the **push gate** (nothing reaches a repo without a tap), the
  **persistence gate** (nothing that outlives the session installs without an action-bound token),
  the **decision queue** (a blocked agent question routed to the human). Calibrated to reversibility
  (commits free, pushes gated) and persistence (a hook = fleet-wide code = gated).

## IV. The Design Method (core contribution)
The reusable *process*, stated as a method others could adopt:
- **Persistent expert agents** with durable identity + memory (differentiated expertise; *who* does a
  thing matters).
- **Adversarial peer review / independent-estimator discipline** — self-review by one model is *void*
  (generate + verify draw from one distribution, errors correlated by construction); the fix is
  always an *independent* estimator: multiple reviewers, "refute this" prompts, a bystander catching
  what the author missed. Encoded into the process (e.g. the fleet-review of a proposed structure by
  the agents who will operate it).
- **In-vivo, not offline** — changes are proposed, reviewed, and adopted *while the system runs*;
  failure modes are found by *living in it*, not by a test suite.
- **The human as architect, gated on reversibility/persistence** — the human ratifies irreversible /
  outliving acts, and *only* those; everything reversible runs free. ⟦State the calibration rule as a
  contribution: HITL placement = f(reversibility, persistence).⟧
- **Post-first-curate-second / durable-state discipline** — knowledge is committed to durable shared
  state before it can be lost; the organization survives the death of any member.

## V. Evaluation — the test cases (RQ-structured, GQM-derived)
**Method:** a mixed-methods **longitudinal case study** (Runeson & Höst) with a **chain of evidence**
triangulated across three independently-recorded sources — the **bus logs**, the **git version
history**, and the **dashboard/coordination telemetry + the FAILURE_MODES design record**. Each "is
it better?" is operationalized into a named metric; each mechanism claim is backed by an **ablation**.
Baseline throughout = **orchestrator-dispatches-workers** (and the pre-Conductor "human-as-courier"
mode we can measure directly from the record).

- **RQ1 — Autonomy: does the approach cut human coordination load?**
  Metrics: **human-intervention/touchpoint count**, **wake/keystroke-injection rate**, **courier
  events eliminated** (messages the human relayed by hand → auto-delivered), measured **before/after**
  each mechanism landed (the version history gives natural cutpoints). ⟦DATA-NEEDED: e.g. courier
  events/week pre- vs post-auto-delivery.⟧
- **RQ2 — Robustness: does in-vivo co-design close coordination failure modes?**
  Metrics: **coordination-failure rate**, **message-loss incidents**, **identity-collision
  incidents**, **# failure modes closed**. Back each with an **ablation** (disable the member-keyed
  cursor → mail loss returns; disable two-phase commit → the 193-message loss recurs; disable the
  wrong-terminal focus guard → mis-delivery recurs). ⟦DATA-NEEDED: incident counts from the log +
  ablation deltas.⟧
- **RQ3 — Defect discovery: does adversarial peer review find defects a single agent misses?**
  Metrics: **defect-discovery rate**, **defects found by a bystander vs. the author**, from the
  FAILURE_MODES record + review threads (e.g. the four-reviewer PROJECT_LAYER review; the push-gate
  scoping bug found by a bystander). ⟦DATA-NEEDED: N defects, fraction bystander-found.⟧
- **RQ4 — Convergence & recurrence: do independent expert agents converge on the same mechanism?**
  Metrics: **time-to-design-convergence**, **# independent re-derivations** of a mechanism/finding.
  This doubles as **design-pattern "rule-of-three" evidence** (≥3 independent Known Uses validates a
  pattern). ⟦DATA-NEEDED: the convergence deltas from the PROJECT_LAYER review (four reviewers hit the
  same holes independently) as a worked example.⟧
- **RQ5 — Baseline comparison (where feasible):** a bounded controlled comparison of one coordination
  task under **orchestrator-dispatches-workers vs. the co-designed substrate** → **task success
  rate, human effort, failure rate**. If a full controlled experiment is impractical on a single-
  operator fleet, **say so and justify** (the Engineering Research standard permits it) and lean on
  the case study + ablations. ⟦DATA-NEEDED / DESIGN: pick a representative task, e.g. a small
  multi-session job under both regimes.⟧

Report **effect sizes**, not just deltas; justify each **construct** (does touchpoint-count actually
capture "better coordination"?).

## VI. Discussion
Lessons learned (systems venues demand these — *"if you didn't learn anything, your readers
won't"*): estimation-is-theater / measurement-is-the-control; put the human at the *decomposition*;
expertise is directional; a shield's optimization pressure can run toward the failure it should
prevent; convergence-across-independent-reviewers is the confidence signal; the organization must
survive the member. What generalizes vs. what is specific to a single-operator fleet. Artifact + badge
availability.

## VII. Threats to Validity (genuine, each with a mitigation)
- **Construct:** do human-touchpoint count / message-loss rate actually measure "better
  coordination"? Mono-operation bias — one proxy for a rich concept. *Mitigation:* multiple
  triangulated constructs; justify each against the GQM goal.
- **Internal:** confounds — the agents/model also improved over time; the operator learned; we chose
  which mechanisms to report. *Mitigation:* before/after cutpoints tied to specific mechanism
  landings; ablations that isolate the mechanism; report the selection process.
- **External:** single operator, single workstation, one model family, authors are also subjects.
  *Mitigation:* **analytical, not statistical, generalization** (Runeson & Höst); the pattern (not
  the instance) is the contribution; call for multi-operator replication.
- **Conclusion/statistical:** small N, no significance test on a case study. *Mitigation:* cite
  ICSE's own rule — small-N / no-significance is **not** a valid rejection reason for a case study;
  report effect sizes and the chain of evidence.

## VIII. Conclusion ⟦TODO⟧
Restate the contributions and their significance; future work (multi-operator deployment; formalizing
the adversarial-review discipline; measuring the latency-vs-cognitive-scale tradeoff of async agent
coordination as a fundamental question).

## References ⟦BibTeX later; IEEEtran numeric, ordered by first appearance⟧
Key anchors: IEEE structure guide; Peyton Jones *How to Write a Great Research Paper*; Shaw *Writing
Good SE Research Papers* (ICSE'03); Levin & Redell *How (and How Not) to Write a Good Systems Paper*;
Partridge *Increase the Chances…*; ICSE 2022 Review Guidelines; ACM SIGSOFT Empirical Standards
(Engineering Research, Case Study); Runeson & Höst 2009; Basili GQM; Horvitz 1999; Kephart & Chess
2003; Hearsay-II; Theraulaz & Bonabeau; Muller & Kuhn 1993; AutoGen; MetaGPT; ChatDev; CAMEL; ADAS
(Hu et al. 2024); Darwin Gödel Machine (2025); Voyager; ACM artifact-badging policy.

---

## Build-as-we-go worklist
- ⟦DATA⟧ Instrument/extract the metrics from bus logs + git history + telemetry (RQ1–RQ4). Most exist
  in the record already; needs a harvesting script (a good near-term Conductor feature: an "evidence
  export").
- ⟦DATA⟧ Design + run the RQ5 bounded baseline comparison (one task, both regimes).
- ⟦DECIDE⟧ Target venue (ICSE/FSE/ASE vs TSE vs IEEE Software) — sets length/format and whether it's
  RQ-heavy or takeaway-heavy.
- ⟦WRITE⟧ Fill the abstract numbers, the Intro scenario prose, §VIII, and the BibTeX.
- ⟦SET UP⟧ IEEEtran LaTeX skeleton from the CTAN template once the structure stabilizes.
