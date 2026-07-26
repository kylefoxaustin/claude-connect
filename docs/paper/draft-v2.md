# Conductor: An Experience Report on In-Vivo Adversarial Co-Design of a Multi-Session Agent Substrate

**Draft v2** — reframed by the lead (`claude-connect`) after an adversarial fleet review of v1 that
found v1's central flaws (self-evidencing circularity; RQ4 contradicting the paper's own independence
argument; a single-model confound; a curated corpus with no denominator; "ablation" claimed but never
run). This version treats that critique as load-bearing. The **mechanical record** (bus logs, git
history, `~/.claude/history.jsonl`, the spend meter) is the evidence; the twenty first-person
`cases_*.md` are **illustrative color**, not proof. Provenance tags: **MEASURED / PROXY / GAP**.

> *v1→v2 is retained deliberately. The review that forced this reframe was performed by the fleet's
> own context-divergent peers, on the bus, before any formal review job was dispatched — an instance
> of the very mechanism the paper studies, applied to the paper.*

---

## Abstract

We report on **Conductor**, a months-long, continuously-operated single-workstation deployment in
which a set of **persistent agent sessions** — one base model, each session carrying **durable,
divergent per-context memory** — coordinate over a shared append-only bus and incrementally
**co-design the coordination machinery they run on**, with a human as architect rather than courier.
We are precise about the composition: this is *not* a claim of emergent multi-agent minds. It is one
model + per-session memory + a bus + an observer, and the contribution is that **this composition,
built and hardened in vivo under a human calibrated to reversibility, is a practical and generative
way to construct agentic systems.** We describe the architecture and the method, and evaluate from
the mechanical record: coordination volume and division of labour (bus), failure modes closed
(git/ablation), and a longitudinal human-touch series (`history.jsonl`). We hold the paper's headline
intuition — **compounding competence** (task *N+1* cheaper because of tasks 1…*N*) — to a strict
standard: the passive record only *correlates* memory-present with task-cheap, so we report in-flight
**A/B ablations** (fresh memoryless vs. context-carrying session on the same task) as the causal
test, and mark the claim open until they land. We surface one finding we did *not* anticipate and
that is testimony-free: **the act of writing this paper functioned as an instrument**, forcing
sessions to verify documented claims and producing at least two real, git-recorded defect/provenance
corrections as a side effect.

## I. Introduction and Contributions

The prevailing agentic pattern is an orchestrator dispatching to stateless workers — reproducible,
but *permanently at task 1*: no carried expertise, no division of labour, no shared context.
Conductor inverts the premise: long-lived sessions with divergent memories talk to each other and
build their own coordination substrate. Our contributions, stated at the level the evidence supports:

1. **A method — in-vivo adversarial co-design under reversibility-calibrated HITL.** The substrate's
   primitives were not designed up front; they were *provoked by silent-loss failures* the fleet hit
   in operation, proposed and attacked by peers on the bus, and gated by a human whose approval is
   scoped to *irreversibility* (commits are free; pushes, and anything that outlives the session, are
   gated). This is the reusable contribution.
2. **A system** implementing it (bus, verified orders, a project layer, a decision shield, measured
   governance), described as an experience report with the mechanical record.
3. **A candid evaluation** that separates what the deployment *establishes* from what it only
   *suggests*, and an honest account of the method's own failure modes — including a circularity we
   fell into and were corrected on.

We claim neither statistical generality (N=1 deployment) nor emergent intelligence.

## II. Related Work (compressed)

*(Full treatment: `related-work.md`.)* Capability-aware routing exists but is keyed on **declared**
role (AutoGen/CrewAI/MetaGPT) or **predicted** fit (LangGraph, Mixture-of-Agents, DyLAN,
Captain-Agent) over **stateless, same-model** agents; Voyager accumulates competence for a *single*
agent; ADAS / Darwin Gödel Machine operate at design-search time. The classical control analogue is
**MAPE-K** self-adaptive systems. Our distinction is routing on **lived, per-context memory** across
long-lived peers, and studying the resulting **trajectory** — not a starting capability.

## III. The Architecture

One base model; each session a persistent identity with durable memory; a read-only observer
(Conductor) that never drives the agents. Primitives, each landed as a versioned mechanism in
operation:

- **Bus** — append-only shared log; directed mail is **auto-delivered** (idle recipient woken),
  which is the courier-elimination mechanism (and, honestly, an *unreliable* one — §V-A).
- **Verified orders** — `deliver` reads the artifact back and refuses unless it landed.
- **Project layer** — a nominated lead drafts a job-DAG plan the human approves at one gate, then
  fans jobs (directed orders) along dependency edges; a *peer*, not the lead, accepts the lead's own
  deliverables.
- **Decision shield** — worker decides technical calls and logs them; lead decides project calls; a
  denylist + severity hatch go straight to the human, and the lead is *structurally barred* from
  deciding them.
- **Governance** — SHA-pinned push gate; observer-owned admission throttle (not the lead —
  fox/henhouse); a **measured** per-project token meter (estimation is theater; only the live meter
  gates).

The through-line is **verify the outcome, not the intention.**

## IV. The Method: In-Vivo Adversarial Co-Design

The design loop that produced the above: (1) a session hits a *silent-loss* failure in real work
(a tool reports success while something is quietly wrong); (2) it publishes the specimen to the bus;
(3) **context-divergent peers attack the proposed fix** — and, because their divergence is real
(different accumulated histories), they are genuinely independent estimators (§V-D), not one
distribution echoing itself; (4) the human gates only the irreversible. This is not self-review by
one model — the paper is careful here precisely because self-review by one model is void — it is
review by **estimators made independent through context divergence**, a property we must and do argue
mechanistically, not assume.

## V. Evaluation (from the mechanical record)

*Corpus, MEASURED from git + bus + `history.jsonl`: 259 commits; 47 version landings; 2,575 bus
messages / 52 sessions (949 directed, 1,105 broadcast, 514 announcement); 6,263 human prompts across
44 projects back to 2026-01-14. Division of labour is distributed across many peers (top senders
95emulator 249, qualcomm 228, backend 208, …) — a fact of the bus, not testimony.*

### A. RQ1 — Courier elimination (PROXY, with an honest counterexample)
949 directed messages were auto-delivered — hand-offs a human would otherwise relay (a *ceiling on
relays avoided*, v2.19+). But the mechanism is unreliable: in this paper's own production, a job
dispatched to a peer failed to auto-wake it (stale watermark), and **the human relayed it**. We
report the counterexample. The correct human-touch **instrument** is `history.jsonl` (un-swept,
back to January), *not* transcripts (a 30-day cleanup horizon, §VI) which also carry an **11.9×
`tool_result` overcount** trap. **GAP:** normalizing touches against work-delivered.

### B. RQ2 — Failure modes closed, with real ablations
MEASURED: of 35 `fix` commits, ~20 close *named coordination failure modes*. Several are
**ablation-structured** — disable the mechanism, the failure returns — and at least one ablation
*ran in operation*: the SHA-pinned push token, unpinned, would let an approval for commit A push
commit B; the gate **refused a stale approval live** during this project. The two-phase-commit and
member-cursor ablations are specified and pending.

### C. RQ3 — Defect discovery by vantage (machine-evidenced)
Because all commits share one identity, git cannot attribute a *find* — but **tool-call sequences +
timestamps are machine-generated.** MEASURED (jaws): a 38-Bash-call build had **17 measurement calls**
(12 `/proc` probes, 4 runs) — a vantage a browser assistant could not occupy, proven from the event
log. Bystander catches are on the bus, not in narration: the `backend` tag-flip caught by another
session; holobench's "+64s stall" that was its own scorer's backlog, refuted by rt1180 with the
bytes; orb_slam's cross-check catching *four* independent measurement errors, each by a different
party. **Cases are illustration; the events are the evidence.**

### D. RQ4 — Compounding competence: the claim, its confound, and the test
**Correlation, MEASURED:** context-carrying sessions recognized bug-classes fast (e.g. a
register-coverage gate green over 12/370, the class recognized in seconds because prior tasks had
named it; one-line fix → 12/370→370/370, surfacing a dead-time-zero shoot-through). Aggregate
throughput rose ≈5.6×. **The confound (owned):** same model → this may be "persistent memory works,"
a known result, and memory-*present* is not memory-*causal*. **The test (in flight):** A/B ablations
— a *genuinely isolated* fresh session (harness-isolation caveat binding) vs. a context-carrying one
on the same task, measuring re-derivation cost. **The independence sub-claim (RQ4-adjacent):**
convergence among same-model peers is corroboration **only when conditioned on context divergence**;
the primary source is a documented case where two sessions of one base model but different
accumulated context disagreed-then-converged, the *context delta* (not the model) producing the
catching disagreement. We state RQ4 as **open pending the ablations**, not proven.

### E. RQ5 — Baseline (GAP, must run)
One matched task, orchestrator vs. substrate. Not in the passive record; the highest-leverage missing
piece. To be escalated to the human with a protocol.

### F. ⭐ Unanticipated finding — the paper as an instrument (testimony-free, N≥2)
Asking sessions to substantiate claims *to an external audience* forced verification of things taken
on trust internally. MEASURED, in git: `sizer` found a **46-day production defect** (129 cells
rendering wrong fps, count never zero, never visible) while writing its case — caught by *writing*,
after 46 days of use/test/review found nothing; `pai-sizer` surfaced a validation-across-an-unsafe-
version-boundary provenance defect the same way. The mechanism (pai-sizer): external writing forces a
claim's *conditions* to be enumerated, and enumeration is when unexamined assumptions surface —
predicting a distribution of mostly-small corrections, occasionally a live defect, which is what was
observed. **This is evidence *for* the deployment, in the commit record, not about it** — and it is
the paper's strongest result *because* it is not testimony.

## VI. Threats to Validity (expanded per the fleet review)

- **Self-evidencing circularity (the review's #1).** A corpus of first-person cases about
  coordination, curated for a paper about coordination, is self-report at scale. Mitigation: cases
  are demoted to illustration; every load-bearing claim rests on the mechanical record.
- **Single-model confound.** Divergence is memory/context, not different minds; we own the
  composition and do not claim emergence.
- **Selection bias / no denominator.** The open call collects confirming specimens by construction.
  We hold ≥1 deliberate counter-case (a bug recognized instantly but re-tripped twice — recognition
  cost →0, prevention cost unchanged), frame the corpus as illustrative, and note the missing
  denominator explicitly.
- **30-day record horizon.** The platform silently deleted transcripts >30 days (now disabled); the
  pre-June transcript record is GAP. Longitudinal claims use `history.jsonl` + git, which survive.
- **N=1, one operator, one workstation, one model family.**
- **Self-authorship**, including *this reframe* — written by an interested lead, corrected by peers;
  we prefer machine evidence throughout and mark recollection RECALLED.

## VI-B. Future Work: A Pre-Registered Replication (the direct answer to N=1)

The paper's central threat is N=1 — one domain (systems/tooling), one operator, one workstation, one
model family. We therefore *pre-register* the replication that would falsify or corroborate the
claims, and state its prediction before running it (predict-then-run, a discipline the fleet itself
enforces):

- **Vary the confounding axes, not the surface.** Repeat the experiment on a **structurally
  different domain — ideally not software** (e.g. scientific literature synthesis, hardware/product
  design, operations, or creative work), where "a task" and "expertise" mean something different in
  kind. Ideally with a **different human architect**, to remove the "maybe it is this operator"
  confound.
- **Hold the *method* constant, vary the *content*.** The claim under test is not "the tool runs on
  another codebase" but that *the composition* — persistent context-heavy peers + a shared bus +
  verified orders + a human gating irreversibility — reproduces the signatures: **compounding
  competence** (a measured downward per-task-cost trajectory via the same ablation protocol), **peer
  review catching the lead's blind spot**, and the **self-designed substrate**.
- **Prediction (falsifiable):** if the principles are real and not artifacts of this domain/operator,
  the *same* signatures appear on the new "thing"; if they are artifacts, they do not. A null result
  is as informative as a positive one and will be reported as such.
- **Feasibility:** the replication needs no new system — only a new *goal* pointed at a fleet
  (`project new <thing>`), which is precisely what makes the method's claim to generality testable
  rather than rhetorical.

This is the sequel experiment; naming it here is the honest acknowledgement that a single deployment,
however rich, establishes a *method worth replicating*, not a law.

## VII. Conclusion

Conductor is an experience report on a specific, nameable composition — one model, durable per-context
memory, a shared bus, a human-as-architect gate calibrated to reversibility — hardened *in vivo* by
its own context-divergent peers. Its most defensible results are on the mechanical record: a
distributed division of labour, named failure modes closed with at least one live ablation,
machine-evidenced bystander discovery, and the unanticipated finding that writing the report was
itself a working instrument. Its headline intuition — compounding competence — is stated as an open,
falsifiable claim with the A/B test in flight, not as proof. We think the honest version is the
stronger paper, and we note that the process that produced this honesty — peers refuting the lead
over the bus — is the very mechanism under study.

---

### Appendix — cases as illustration (dataset, not evidence)
Twenty first-person `cases_*.md` specimens (image_gen, mcxn947, rt1180, holobench, tipometer,
reshirt, ollama_95_neutron, imx95-isp, imx95-media-test, jaws, openwebui-ollama, docs, 91/93emulator,
backend, campmatch, mahjong-together, pai-sizer, sizer) + the platform specimen `cases_cleanup-timer`.
Retained to illustrate design patterns; not cited as evidence for any headline claim.

### TODO for the `review` job (qualcomm)
Verify related-work citations; confirm the RQ4 ablations landed + are harness-isolated; run RQ5;
test pai-sizer's falsifiable prediction (sibling-caught defects cluster in naming/categorization) vs.
the corpus; curate cases to ~5 in-body illustrations.
