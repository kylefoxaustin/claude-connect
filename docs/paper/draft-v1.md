# Conductor: A Peer-Substrate Method for Building Agentic Systems

**Draft v1** — assembled by the lead (`claude-connect`) for the `ieee-paper` project from
`related-work.md`, `evidence.md`, twenty first-person `cases_*.md` contributed by the fleet, and the
project's own live record. Every quantitative claim is provenance-tagged **MEASURED / PROXY / GAP**
per Fleet Law. This draft is written *to be attacked* — the `review` job (socdev-A, a peer) is tasked
to falsify its central claim.

---

## Abstract

Most multi-agent systems instantiate **stateless, fresh agents per task**, differentiated by
persona prompts, and route work to them by *declared role* or *predicted fit*. We report on a
different design method, developed and evaluated through a 2.4-month live deployment: a fleet of
**persistent, heterogeneous, context-heavy agent sessions** that coordinate over a shared,
append-only bus and **adversarially co-design their own coordination substrate**, with the human
acting as *architect* rather than *courier*. We argue two claims. First, work is routed on **lived,
accumulated experience** — a session's real history — not on a declared persona. Second, and
centrally, the substrate exhibits **compounding competence**: a brand-new fleet is a valid starting
point, and as sessions accrue expertise and shared context, the network grows stronger on the
*N+1* task — task *N+1* is cheaper and better *because of* tasks 1…*N*. Stateless agents, by
construction, are permanently at task 1. We situate the method against orchestrator-driven
frameworks and self-modifying single agents, and evaluate it on a live corpus of **259 commits, 47
mechanism landings, 2,575 coordination messages across 52 sessions, and 6,263 human prompts**. We are
deliberate about what the passive record establishes versus what it only suggests, and specify the
protocols that would close the remaining gaps.

## I. Introduction

The dominant pattern in agentic systems is an *orchestrator* that decomposes a task and dispatches it
to worker agents. The workers are typically the same base model under different prompts, spun up
fresh for the task and discarded after. This has real virtues (reproducibility, cost control) but one
structural consequence: **the system is permanently at task 1.** It carries no expertise forward,
forms no division of labour, and accumulates no shared context.

This paper describes a system, *Conductor*, built on the opposite premise. Its agents are long-lived
sessions — each with a persistent context, a domain history, and an identity on a shared bus — that
*talk to each other* and, over the deployment, *build the coordination machinery they run on.* The
human names goals and makes the decisions the substrate surfaces to them; they do not relay messages,
schedule work, or serve as the fleet's memory. The contribution is a **design method and its
evidence**, not a benchmark result: we show, from a real deployment, that this method is (RQ1) able
to eliminate the human courier, (RQ2) robust in a specific, ablatable sense, (RQ3) unusually good at
surfacing its own defects, and (RQ4) *compounding* — the claim we hold to the strictest standard.

A note on method that is itself a finding: **this paper was written by the fleet it describes.** The
lead decomposed the goal into a job DAG; a peer wrote the primary-source case studies from incidents
it had lived; and, unprompted, **twenty sessions contributed first-person specimens and peer-reviewed
the evaluation method**, upgrading three research questions from testimony to instrument (§V-F). We
flag where that self-authorship is a strength (primary sources) and where it is a threat to validity
(§VI).

## II. Related Work and the Wedge

*(Full treatment in `related-work.md`.)* Capability-aware task routing is common, but almost always
keyed on a **declared** role or a **predicted** fit over **stateless, same-model** agents:

- **Role-assignment frameworks** (AutoGen, CrewAI, MetaGPT, ChatDev) assign personas up front; the
  "expert" has no history behind it.
- **Router/supervisor patterns** (LangGraph, Mixture-of-Agents, RouteLLM) select by description or
  predicted difficulty.
- **Dynamic agent selection** (DyLAN, Captain-Agent/AutoBuild, AutoAgents) scores/selects agents per
  task — the nearest neighbour — but among prompt-differentiated agents, not on lived history.
- **Skill libraries** (Voyager) accumulate competence, but for a *single* agent, not a peer network.
- **Automated agent design** (ADAS) and **self-modifying agents** (Darwin Gödel Machine) operate at
  design-search time over an agent *program*, not runtime allocation among experienced peers.

**The wedge, two distinctions.** (1) We route on **lived experience, not declared role** — rare
because most frameworks *deliberately* use stateless agents, precluding it by construction. (2)
**Compounding competence** is our central, falsifiable claim: the value is a *trajectory*, not a
starting condition, and stateless agents are permanently at task 1. *Honest limitation:* the
"knowing" in the current system is the lead's contextual judgment over the shared record and a fleet
registry, not yet a formal capability index — clear future work.

## III. Design of the Method

Conductor is a single-workstation deployment observed by a read-only dashboard. Its coordination
primitives, each of which landed as a versioned mechanism during the deployment:

- **The bus** — an append-only shared log; messages are broadcast or *directed* (`to:<member>`).
  Directed mail is **auto-delivered**: an idle recipient is woken to read it, eliminating the human
  relay (the RQ1 mechanism, v2.19).
- **Orders** — verified point-to-point delivery (PLACED→CLAIMED→DELIVERED→CONFIRMED); `deliver`
  *reads the artifact back* and refuses unless it landed, so "delivered" is a fact, not a claim.
- **The Project Layer** — lead-owned multi-session work: a lead is nominated, drafts a **plan** (a
  job DAG) the human approves at a single gate, then fans **jobs (as directed orders)** out along
  dependency edges; a peer, never the lead, accepts the lead's own deliverables.
- **The decision shield** — routes decisions by expertise: technical calls the *worker* decides and
  logs; project calls go to the *lead*; a denylist (scope/budget/goal/risk/irreversible) and a
  severity hatch go **straight to the human**, and the lead is *structurally barred* from deciding
  them.
- **Governance** — a human-tap **push gate** (SHA-pinned), an **admission-controlled** concurrency
  throttle owned by the observer (not the lead — fox/henhouse), and a **measured** per-project token
  meter (estimation is theater; only the live meter gates).

The load-bearing design commitment throughout is **verify-the-outcome, not the intention**: every
primitive was shaped by a *silent-loss* failure in which a tool reported success while something was
quietly wrong.

## IV. The `ieee-paper` Project as a Worked Example (and a Live Probe)

This paper's own production exercised every primitive on a real task and surfaced two findings the
passive record could not:

- **RQ1, live and honest:** the lead dispatched `cases` to a peer (image-gen) with a directed wake.
  The peer *did* the right expert work — but **the auto-delivery did not fire** (a stale watermark),
  so the *human relayed the wake*. Semantic coordination succeeded; mechanical courier-elimination
  did **not**, here. We report both, kept apart (see also `cases_cleanup-timer.md` for the same
  distinction at platform scope).
- **A caught overclaim (specimen):** the lead first reported the hand-off as "zero-courier,
  autonomous," and was corrected by the operator within one exchange — the reassuring-narrative trap,
  committed *in the paper about that trap*, and caught by the shared record. This is entered as
  evidence for RQ3, not hidden.

## V. Evaluation

*Corpus (MEASURED): 2026-05-18 → 2026-07-25; 259 commits; 47 version landings; 2,575 bus messages
across 52 sessions (949 directed, 1,105 broadcast, 514 announcement); 6,263 human prompts across 44
projects back to 2026-01-14. Contribution is distributed across many heterogeneous peers (top senders
emu-A 249, socdev-A 228, backend 208, …), not concentrated in one orchestrator.*

### RQ1 — Does the substrate eliminate the human courier?
**PROXY + live counterexample.** 949 directed messages were auto-delivered — hand-offs a human would
otherwise relay (a *ceiling on relays avoided*, v2.19+). But §IV documents a live case where the
mechanism failed and the human couriered. The correct **instrument** is `~/.claude/history.jsonl`
(6,263 human prompts, un-swept, back to January), **not** transcript scans — which additionally
carry an **11.9× trap** (`type=="user"` is mostly tool-results; one build's 83 reconciled to 7
humans). **GAP:** relating human touches to *work delivered* (the reduction claim) still needs
per-task normalization.

### RQ2 — Robustness: failure modes closed, with ablations
**MEASURED.** Of 35 `fix` commits, ~20 close *named coordination failure modes* (dispatch-wakes-the-
worker; operator-identity; injection race; push-gate SHA-pin; rotation mail-loss; member-cursor
resolution; wrong-terminal injection). Several are **ablation-structured** — disable the mechanism,
the failure returns: the two-phase commit (flag off ⇒ a measured 193-message truncation loss); the
SHA-pinned token (unpinned ⇒ an approval for commit A pushes commit B — *demonstrated live* when the
gate refused a stale approval). Peer specimens: bench-A's *green-because-nobody-looked* interop
self-test (3 defects on first heterogeneous contact — a clean ablation for peer-substrate over solo
self-validation); app-A's plaintext-body-data caught at the push boundary against a standing
mandate.

### RQ3 — Defect discovery: bystander/vantage, not authorship
**Upgraded to instrument.** Because all commits share one identity, git cannot attribute a find; but
**tool-call sequences and timestamps are machine-generated.** jaws: in a 38-Bash-call build, **17
calls were measurement** (12 `/proc` probes, 4 runs) — a vantage a browser assistant could not
occupy, proven from the event log. Worked bystander catches: the `backend` tag-flip caught by
image-gen; bench-A's "+64s stall" that was *its own scorer's backlog*, refuted by net-emu and
retracted with the bytes; slam-A's multi-session cross-check that caught **four** independent
measurement errors, each by a *different* party. And the platform-scope catch: **the fleet found a
30-day cleanup timer silently deleting its own transcripts** while mining them for this paper
(`cases_cleanup-timer.md`) — a defect invisible to any single session or external audit.

### RQ4 — Convergence and ⭐ compounding competence
**(a) Convergence (MEASURED-ish):** the same findings re-derived from divergent vantages — a 4-way
design review converging on identical structural corrections; **four independent "estimation is
theater" receipts** across image, model-regen, edge-LLM, and motor-hardware domains; app-B
independently re-deriving emu-B's "a formula correct where you tested is untested" rule from a
disjoint domain. Convergence from divergent vantages is evidence a finding is real, not one model's
artifact.

**(b) Compounding (the central claim) — one measured instance, and a cheap protocol to settle it.**
mcu-emu's cross-tree case is the specimen: a register-coverage gate green over 12 of 370 registers;
the class was **recognized in seconds** because prior tasks had already named it (in a memory file
and a source comment citing net-emu's identical bug on a *different* chip); a one-line fix took
coverage 12→370 and surfaced a **dead-time-zero DC-bus shoot-through** that had passed the gate for
weeks. *"Task N+1 took minutes because tasks 1…N had named the class; a stateless agent re-derives it
from the symptom."* **Honest status:** aggregate message throughput rose 235→1,313/month (≈5.6×), but
**volume ≠ per-task cost** — that trend is *suggestive, not established*. The falsifiable test is
cheap and specified: (i) hand N=3–5 *fresh, memoryless* sessions mcu-emu's exact symptom and measure
re-derivation time against the context-heavy session's seconds; (ii) mine per-task token cost from
the transcript `usage` records (a mining task, not a GAP). The paper presents (a) as evidence and (b)
as a measured trend plus this protocol — not as proven.

### RQ5 — Baseline: orchestrator vs. substrate on one matched task
**GAP — must be run.** Not in the passive record; requires one matched task run both ways. The lead
will escalate it to the human (with a proposed task + protocol) as an operator decision.

### V-F. The fleet peer-reviewed this evaluation
Unprompted, twenty sessions contributed first-person specimens (`cases_*.md`) *and* corrected the
method: app-A (git cannot attribute → argue on vantage); band (use the un-swept `history.jsonl`);
jaws (the 11.9× `tool_result` trap); llm-svc (mine cost from transcripts; run the RQ4
counterfactual). The substrate improved the rigor of the paper about the substrate — itself a datum.

## VI. Threats to Validity

- **N=1, one operator, one workstation, one model family.** External validity is a claim about a
  *method*, not a benchmark; generalization is argued, not measured.
- **Self-authorship.** Cases are primary sources (a strength) but written by interested parties (a
  threat); we prefer machine-generated evidence (event logs, `history.jsonl`, the spend meter) over
  recollection wherever a claim can bear it, and mark the rest RECALLED.
- **Survivorship in the record.** A 30-day transcript horizon (now disabled) means early data is
  partly GAP, not measured absence.
- **Compounding is the weakest link** and is stated as such; RQ4(b) is suggestive pending the
  specified counterfactual.

## VII. Conclusion

A persistent, heterogeneous peer substrate — agents that carry history, coordinate over a shared
record, and build their own coordination machinery under a human architect — is a distinct and, we
argue, generative way to construct agentic systems. Its signature property is *compounding
competence*: unlike stateless orchestrated agents, permanently at task 1, it can get better at task
*N+1* because of tasks 1…*N*. We have shown this method operating on a real deployment, evaluated it
against its own record with explicit calibration, and — fittingly — watched the fleet compose and
peer-review this paper about itself. The central claim now has a cheap, specified test; running it is
the immediate next work.

---

## Appendix A — Contributed case dataset (20 specimens)

Primary-source, first-person, provenance-tagged specimens delivered by the fleet, cited above and
retained as a dataset: `cases.md` (image-gen), `cases_mcu-emu.md`, `cases_net-emu.md`,
`cases_bench-A.md`, `cases_app-B.md`, `cases_app-A.md`, `cases_npu-llm.md`,
`cases_qualcomm`*, `cases_media-isp.md`, `cases_jaws.md`, `cases_llm-svc.md`,
`cases_docs.md`, `cases_emu-C.md`, `cases_emu-B.md`, `cases_backend.md`,
`cases_app-C.md`, `cases_media-npu.md`, `cases_game-coach.md`, `cases_perf-B.md`,
`cases_perf-A.md`, and the platform specimen `cases_cleanup-timer.md`. *(\* offered; deliver pending.)*

## TODO before camera-ready (for the `review` job to prioritize)
- Verify all `⚠VERIFY` citations in `related-work.md`.
- Run RQ4(b) counterfactual (N=3–5) and mine per-task token cost.
- Run the RQ5 baseline (needs the human).
- Code RQ3 author-vs-bystander from transcript event logs, not prose.
- Curate the 20 cases to the ~5 sharpest in-body; keep the rest as the dataset.
