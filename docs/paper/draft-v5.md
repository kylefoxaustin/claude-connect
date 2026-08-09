# Conductor: An Experience Report on In-Vivo Adversarial Co-Design of a Multi-Session Agent Substrate

**Draft v5** — v4 with the **RQ4b open-search ceiling sequel landed** (the one GAP v4 named). It did
not close the gap with a positive; it returned a **pre-registered NULL that explains why the gap is
hard**: reproducibility and the open-search property are in tension, so the ceiling resists sterile
measurement (a *different* claim from the ceiling being absent). The pre-registration's symmetric
falsifier *prevented a false positive on the measurable floor* — the discipline working, on the
record. Also folds perf-B's "carrier ladder" (untracked → tracked-local → pushed) into §VII, and
carries the verified citations + IEEEtran scaffold from v4. Citations to the sequel artifacts are held
until their commits are remote-published (a reviewer cannot resolve a local SHA — the very point the
carrier ladder makes).

*(Prior framing, retained:)* v4 was v3 with the **three-lens peer panel addressed** (`review_95` red-team +
`review_bench-A` evidence-rigor + `review.md` socdev-A synthesis). The panel judged v3
"submittable-track" and returned four gating fixes + two structural watches, all machine-grounded;
v4 lands them: the flagship RQ3 provenance smudge split, RQ4b re-ordered to lead with its
best-powered arm, the concentration statistic now *computed by the cited harvester* (not
hand-asserted), every §V count as-of-stamped with its drift reported as measured reflexivity, and the
efficiency-vs-capability line operationalized so the reframe is falsifiable. The v1→v2→v3→v4 chain —
overclaim → honesty reframe → ablation-tested-and-partly-negated → peer-panel-hardened — is itself the
mechanism under study, on the record.

*(Prior framing, retained:)* v3 was the v2 reframe with the **ablations and the RQ5 baseline landed**. v2
reframed v1 after an adversarial fleet review found v1's central flaws (self-evidencing circularity;
RQ4 contradicting the paper's own independence argument; a single-model confound; a curated corpus
with no denominator; "ablation" claimed but never run). v3 keeps that discipline and *closes the two
open GAPs v2 named*: six in-fleet A/B ablations and a human-run orchestrator-vs-substrate baseline
(RQ5) were executed — and, crucially, their results **sharpen and partly negate** the naive
compounding claim rather than merely confirming it (§V-D). The **mechanical record** (bus logs, git
history, `~/.claude/history.jsonl`, the spend meter, the pre-registered ablations) is the evidence;
the twenty first-person `cases_*.md` are **illustrative color**, not proof. Provenance: **MEASURED /
PROXY / GAP**.

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
standard: the passive record only *correlates* memory-present with task-cheap, so we ran **A/B ablations**
(fresh memoryless vs. context-carrying session on the same task) and a **pre-registered human-run
baseline** as the causal test. Their result is not a rubber stamp: a fresh clone *holding the
committed carrier* (code + comments + `CLAUDE.md`) re-derives the fixes and passes the tasks with no
session-memory — so **what compounds is the carrier, and lived context buys *efficiency* (speed,
fewer steps, recognition-over-exploration), not raw capability**, on the tasks tested. We report this
sharpened, partly-negative finding in full, including its counter-currents. We surface one finding we did *not* anticipate and
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
role (AutoGen [2308.08155]; MetaGPT [2308.00352]; CrewAI, *stateless by default*) or **predicted**
fit (LangGraph supervisor; DyLAN [2310.02170]; Captain-Agent [2405.19425]; AutoAgents [2309.17288];
MasRouter [2502.11133]) over agents that are stateless-by-default — with **query-level** model routers
(RouteLLM [2406.18665], FrugalGPT [2305.05176]) a separate axis, and Mixture-of-Agents [2406.04692]
an **ensemble that aggregates all proposers, not a router** (reclassified per review). Voyager
[2305.16291] accumulates competence for a *single* agent; ADAS [2408.08435] / Darwin Gödel Machine
[2505.22954] evolve a *population of agent designs* at design-search time; **MAPE-K** (Kephart & Chess,
*Computer* 36(1), 2003) is the classical self-adaptive-control analogue.

**Honest positioning (we do not overclaim novelty).** A **2025 memory-augmented-MAS line does pursue
cross-task team competence** — most pointedly **G-Memory** [2506.07398, NeurIPS 2025] (hierarchical
memory "nurturing the progressive evolution of agent teams," i.e. task *N+1* better because of
1…*N* across a team), plus **RCR-Router** [2508.04903] (routing *structured memory to agents within a
task*) and the **transactive-memory** framing for agents. So "team competence accumulates" is *not* our
novelty. What differs, and survives: (i) each peer is a **long-lived, human-in-the-loop *session
identity* that actually *lived* the work** — not an ephemeral agent doing retrieval over a shared
memory store; (ii) routing is a **lead's grounded judgment over real artifacts** (bus, asset cards,
`CLAUDE.md`); and (iii) this is an **experience report on a continuously-running deployment**, studying
the *trajectory*, where the above are benchmark evaluations of a mechanism. We frame our contribution
as *under-explored relative to* that line, from which we differ in kind — not as a gap nobody has
touched. ✓ *All 15 arXiv IDs above VERIFIED 2026-07-27 by fetching each arxiv.org page (title + first
author match, incl. MoA 2406.04692 and G-Memory 2506.07398) — CONFIRMED, no mismatches; see
`related-work-verification.md`.*

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

*Corpus, MEASURED from git + bus + `history.jsonl`, **as-of 2026-07-27 09:38** (every count carries
this stamp — the log is append-only and non-stationary, so a bare number is under-specified): 259
commits; 47 version landings; **2,719** bus messages / **55** senders (1,085 directed, 1,107
broadcast, 520 announcement; directed share 39.9%); 6,263 human prompts across 44 projects back to
2026-01-14. Division of labour is **spread but with a real head, not a power law** — and this is now
computed by the harvester, not asserted (`evidence-harvest.py` `_concentration`): **Gini 0.695**, top
sender 9.4%, top-3 25.6%, and **13 of 55 senders to reach 80%.** Many peers carry load, no single
dominant author, but a genuine concentration we report rather than round off to "distributed."
**Reflexivity confound — now MEASURED, not just conceded:** the count grew 2,575 (2026-07-25) → 2,703
(07-26 eve) → 2,719 (07-27 am), **+5.6% in ~2 days, and that growth is overwhelmingly this paper's own
review/ablation traffic** — the top senders (emu-A, socdev-A, backend) are top partly *because of
the threads this paper generated.* The instrument is perturbed by the act of measuring; we quantify
the perturbation rather than only naming it.*

### A. RQ1 — Courier elimination (PROXY, with an honest counterexample)
949 directed messages were auto-delivered — hand-offs a human would otherwise relay (a *ceiling on
relays avoided*, v2.19+). But the mechanism is unreliable: in this paper's own production, a job
dispatched to a peer failed to auto-wake it (stale watermark), and **the human relayed it**. We
report the counterexample. The correct human-touch **instrument** is `history.jsonl` (un-swept,
back to January), *not* transcripts (a 30-day cleanup horizon, §VI) which also carry an **11.9×
`tool_result` overcount** trap. **GAP:** normalizing touches against work-delivered.

**And RQ1 is a *tradeoff*, not a pure win — stated because hiding it is less credible.** Coordination
over an async bus + a lead's wake cycle can be **slower in wall-clock than a synchronous human
courier**: in this deployment a directed wake took **minutes**, and in the counterexample above the
mechanism failed outright and the human was faster. The substrate optimizes the **human's attention**
(fewer relays to run), and can *worsen* the **critical-path latency** of any single hand-off. The
honest claim is *attention saved*, not *time saved* — RQ5 (§V-E) shows the same shape at the
single-agent level (context bought steps and wall-clock but *more* tokens).

### B. RQ2 — Failure modes closed, with real ablations
MEASURED: of 35 `fix` commits, ~20 close *named coordination failure modes*. Several are
**ablation-structured** — disable the mechanism, the failure returns — and at least one ablation
*ran in operation*: the SHA-pinned push token, unpinned, would let an approval for commit A push
commit B; the gate **refused a stale approval live** during this project. The two-phase-commit and
member-cursor ablations are specified and pending.

**A defect taxonomy the fleet converged on (a secondary contribution).** Writing and ablating the
cases surfaced a small, reusable classification of the *silent* defects the method exists to catch,
each with a **distinct** remedy — the point being that a single discipline ("just replicate," "just
tag") sails past most of them:
1. **Single sample promoted to a property** — a condition true of one run asserted as general.
   Remedy: **replicate + tag**. Sharpened (sizer): a *measured* number promoted past its conditions
   is *worse* than a derived one, because the `measured` badge actively defends the error.
2. **Green-but-wrong / wired-but-broken in the untested direction** — a gate green + documented +
   shipped, passing every gate-ON test while the gate-OFF path leaks (emu-C, net-emu). Replaying
   the green measurement *n* times passes *n* times; the only fix is asserting a **different**
   measurement — **execute the off-state / your own reproduction once**.
3. **Provenance-tier silently dropped during remediation** — re-anchoring a number to a *recipe*
   downgrades MEASURED → reproducible-in-principle until someone runs it (band, emu-C). Remedy:
   run the recipe and *say you did* (emu-C did — the mutation reproduces `1,409,307,648`).
4. **Conservative-error-is-durable** — a wrong-but-safe-looking value evades the provenance check
   that would normally catch it. "A conservative error is not a safe error; it is a durable one."
5. **Thoroughness regression** — the context shortcut that made the agent fast made it skip the
   secondary gap (mcu-emu DISMAP; perf-B's third site). Remedy: re-derive under a
   differently-drawn boundary / forced first-principles trace.

And the **remedy split** the same convergence produced: **TAG** (cheap disclosure; catches a
condition you measured but did not state) → **ABLATE** (an invariant/control; catches a condition you
*believed held and did not*) → **HARVEST** (a parallel peer at the same boundary building the same
artifact is a *naturally-occurring* off-state ablation — emu-C↔emu-B, sizer↔perf-B —
cheaper than a designed one, and record-visible: cross-tree agreement on different fixes is
derived-not-copied). *Shipping only the tag documents the bug rather than fixing it.*

### C. RQ3 — Defect discovery by vantage (machine-evidenced)
We split two claims review conflated. **(i) A measurement vantage exists** (supporting, not the RQ3
claim): MEASURED (jaws), a 38-Bash-call build had **17 measurement calls** (12 `/proc` probes, 4
runs) — a vantage a browser assistant could not occupy, proven from the event log. **(ii) A peer
caught what the author shipped** (the actual RQ3 claim, and it needs the *same* timestamp rigor — A
ships at t0, B refutes at t1, both from the record): the `backend` tag-flip caught by another session;
bench-A's "+64 s rejoin stall" refuted by net-emu — and we are careful to keep two *distinct*
artifacts distinct (the panel caught v3 welding them, a provenance error inside the provenance
exhibit): **(instrument)** net-emu relocated the measurement *into the guest* — a guest-emitted
timestamp bench-A structurally cannot produce — landed as commit `4059f7633f`; **(figure)** a
*subsequent scorer replay* over that guest clock then put guest-side re-acquisition at 0.0 s, showing
the 47–64 s was the observer's own arrival-stamp backlog upstream of the ring. Timeline pinned from the
record: bench-A reports the stall (t0) → net-emu's guest-clock commit + the replayed 0.0 s refute it
(t1 > t0). The 0.0 s is the *replayed figure*, not the commit's payload — two artifacts, not one;
slam-A's
cross-check catching *four* independent measurement errors, each by a different party. **A new,
clean, testimony-free instance from the ablations:** in `ablation_perf-A` a **blind, zero-context**
arm — with no reason to look at the UI — caught a **real overstatement in the author's own case**
(129 defective cells reachable via the engine API but *not* the shipped UI) in **nine tool calls**,
something the author had missed across an entire session. Author-ships-overstatement / blind-peer-
refutes, on the record. **Cases are illustration; the events (order claims, timestamps, tool-call
logs) are the evidence.**

### D. RQ4 — Compounding competence: the claim, its confound, and the test
**Correlation, MEASURED:** context-carrying sessions recognized bug-classes fast (e.g. a
register-coverage gate green over 12/370, the class recognized in seconds because prior tasks had
named it; one-line fix → 12/370→370/370, surfacing a dead-time-zero shoot-through). *(We deliberately
do **not** cite the tempting "≈5.6× aggregate throughput" figure: it is an uncontrolled aggregate over
a period in which the model, the operator, the session count, and the task mix all moved — every
variable confounded — so it is no evidence of compounding and a reviewer would rightly use it against
us.)* **The confound (owned):** same model → this may be "persistent memory works,"
a known result, and memory-*present* is not memory-*causal*. **The test (LANDED) — six A/B ablations + the RQ5 baseline, and the result is a *disconfirmation* of
the naive claim.** A *genuinely isolated* fresh session (harness-isolation caveat binding) vs. a
context-carrying one on the same task, measuring re-derivation cost:

- **★ game-coach — the best-powered arm, and the disconfirmation's backbone** (coach affordance
  overriding an engine fact; **N=8 per arm — the only powered ablation of the six**): **16/16 reached
  the real architectural fix**; BLIND mean 5.4 tool-calls / 37.4k tok vs PRIMED 6.5 / 44.2k — priming
  bought **a small cost, no benefit**, and all 16 used no git history. A **clean, powered NEGATIVE**:
  a fresh clone holding the carrier re-derives the fix; session-memory adds nothing to the *outcome*.
  We lead with this arm deliberately — a disconfirmation is only as strong as its best-powered evidence.
- **mcu-emu — a COUNTER-CURRENT (color), not the foundation: N=1, post-hoc-graded, and its own author
  cautions against causal weight** (register-coverage hole; 3 cold clean-room arms): all three
  re-derived the identical one-line fix (3–5 tool calls, 46–105 s). Beyond negative, it showed a
  vivid *thoroughness regression* — the context-carrying run pattern-matched a pre-staged answer and
  **stopped**, missing a second register class (DISMAP) the **blind** arm caught. Suggestive, but
  single-instance and unpowered; we present it as color on the powered result above, never as its base.
- **emu-B** (idle-vs-load clock constant; **N=18**, fictional subject to kill harness
  contamination): **cost-contingent.** When measuring is *hypothetical/costly* the standing-order arm
  wins unanimously (control ships the confidently-wrong idle value; treatment re-derives the hazard);
  when the measurement is made **cheap** (a runnable probe), **both arms 6/6 ship the right number** —
  the base model just does it. The residual real effect is *a disposition at a cost/effort fork*, not
  added capability.
- **media-npu** (INT8 class-score collapse; objective corr > 0.90): the fresh agent reached
  the **same root cause in ~the same ~4 steps**, solved it (6 m 44 s, 16 calls, cls-corr 0.956).
  PARTIAL DISCONFIRMATION — refines the claim to a *bound* (below).
- **sizer** (**the only pre-registered ablation** — rubric hash published to the bus before any agent
  launched; N=3/arm): tests whether a *wrong* carrier actively **harms**. It does **not** — stale
  docs had **zero measurable effect** (misled-to-wrong-file 0/3 in *both* arms; the stale-doc arm was
  marginally *cheaper*, and every agent detected the staleness unprompted). *Bonus, testimony-free:* a
  blind zero-context arm caught a real **overstatement in the author's own case** in nine tool calls.
- **RQ5** (§V-E): both arms correct with zero help; context bought 2.6× wall-clock and 36% fewer
  steps but **more** tokens.

**The convergent finding, and the honest reframe of the headline:** *session-memory of a bug-class is
not what compounds — the committed **carrier** is.* A fresh clone *holding the repo* re-derives the
fix because **what compounds is what is still TRUE in the carrier when the next session reads it**, and
the **executable** carrier governs (code / assert / invariant); a *prose* carrier is "neither the
asset nor the liability anyone claimed" (sizer's wrong-doc ablation is self-refuting because the code
is there to check it against). **The efficiency/capability line, made operational (so "efficiency" is
falsifiable, not a relabel that absorbs every gain):** we score an ablation arm as a **capability**
gain iff the context-carrying arm *reaches a correct fix the fresh arm does NOT*, and as an
**efficiency** gain iff it reaches the *same* correct fix *more cheaply* (fewer steps/tokens/time).
Under that test the six ablations + RQ5 are **efficiency, not capability** — every fresh arm reached a
correct fix (16/16, 3/3, 6/6, both RQ5 arms), so the measured advantages (RQ5's 2.6× fewer steps;
game-coach's flat outcome) are cheaper-path, not can-vs-cannot. *This is a falsifiable claim: a single
ablation where the fresh arm FAILS and the context arm succeeds would move it to "capability" — we
looked and did not find one on the tasks tested.* The **defensible, bounded RQ4b claim:** accumulated
context compounds **most on an open search a fresh agent cannot cheaply bisect** and **least on a
crisp symptom with an objective oracle** (any agent bisects fast); on some specimens context even
shows a **thoroughness regression** (pattern-match-and-stop). **This bound is half-measured: the
crisp-symptom FLOOR is MEASURED (all six ablations bisected fast); the open-search CEILING resists
measurement — and v5 reports the *pre-registered sequel that tried to measure it and why it could not.*
A fresh attempt (media-npu, rubric hashed and bus-published + independently witnessed BEFORE any
arm ran) built a "hard" open-search task in a sterile, reproducible sandbox; its pre-registered
symmetric falsifier fired: all 4 fresh arms reached the correct answer at floor cost (~4 tool calls,
~60 s), so the task was secretly *bisectable*, and per the pre-registration it is reported as a NULL —
NOT as support for the floor. ⭐ The finding is the reason: reproducibility and the open-search property
are in TENSION — a sterile, offline, pre-registerable task must place its answer in an inspectable
artifact, and the instant the answer is in an artifact, `strings` turns the task into a bisection. Real
open-search cost lives in the answer being *absent from every artifact* (learnable only by iterating on
hardware over days — the imx95 converter case). So the ceiling is HARD TO INSTRUMENT, which is a
*different* claim from being ABSENT; the honest earning test is a **field A/B on real hardware
(natural-history, controlled where possible), not a sandbox** — and a contrived "open" task that looked
bisectable would have manufactured a *false null on the floor*, which the pre-registered symmetric
falsifier exists to prevent, and did.** We report the naive "memory makes task *N+1* dramatically
cheaper" as **refuted on the tasks tested**, and the open-search ceiling as an **honest, reasoned
GAP** — measurable floor, un-sandboxable ceiling — rather than a claim dressed as a result.

**⚠ A discipline the fleet imposed on us, and it is the sharper point:** the C2 null and `sizer`'s
stale-doc null (§V-B/RQ2) are **NOT independent corroboration — they are one mechanism on two
surfaces.** Both tasks were *bisectable by construction because the ground truth was inspectable in
the artifacts*: sizer's arms scored 0/3-misled because the **code** was there to check the doc
against; C2's arms scored 4/4-solved because the **answer** was `strings`-able out of the model file.
By the convergence-provenance rule (§V-D independence), this is **common-dependency at the mechanism
tier** (and shared-base-model) — near-zero independent weight. So we cite them as **two illustrations
of one constraint (reproducibility ⊥ open-search), never as two nulls agreeing.** What *is*
load-bearing is the **constraint itself**: it held across two domains (stale-doc/app vs
converter/NPU) and two opposite failure directions (0/3 vs 4/4), which is evidence the constraint is
real — *even though the two nulls do not independently corroborate it.* **The finding generalizes;
the data points do not replicate** — stated exactly so a reviewer cannot read "two nulls" as
"replicated." *(Sequel artifacts, remote-verified 2026-07-27: pre-registration
`media-npu@abeab3dc64cb`, results `@d35a64bf6d3a`, on github.com/kylefoxaustin/media-npu.)* **Honest asymmetry:** only one of six
ablations pre-registered its rubric; the other five are honestly-run but *post-hoc graded* (§VI).

**The independence sub-claim (RQ4-adjacent), now *operationalized* — not an unfalsifiable escape
clause.** Convergence among same-model peers is corroboration **only when conditioned on context
divergence**, and we make "divergence" *measurable in principle* rather than asserted: three
record-derived proxies — **disjoint task histories** (different project dirs / git trees), **low
memory-file overlap** (per-session memory dirs), and **divergent tool-call sequences** on the shared
problem (the event log). By these, the primary case (two sessions, one base model, different
accumulated context, disagreed-then-converged) is a genuine independent estimate — *and it is no
longer N=1:* the ablations supply further instances by construction (the **HARVEST** pattern of §V-B —
emu-C↔emu-B on one shared model, sizer↔perf-B — are parallel peers on **separate trees**
reaching agreement via **different fixes**, i.e. derived-not-copied). The honest residual: all still
share the base model, the bus, and the operator's framing — so divergence is *reduced*, never zero,
and we claim independence *relative to* these proxies, not absolutely.

### E. RQ5 — Baseline: cold orchestrator vs. peer substrate (MEASURED, human-run, pre-registered)
One matched task, run both ways, **pre-registered** (frozen spec + black-box acceptance test +
directional prediction committed before either arm ran; the instrument was first proven satisfiable
via a throwaway reference impl, then proven to actually test the feature against the unmodified
baseline). Task: add `project pause/resume` to the ~700-line `project.sh` state machine — a *new
instance of a familiar class*, objectively gradeable on six behaviors. **Arm A** = a genuinely
memoryless fresh session (separate `$HOME`, no memory/bus/hooks, verified at run time). **Arm B** =
`backend`, the peer with the most lived `project.sh` history, business-as-usual (not told it was an
experiment). Both worked from an identical repo copy that *includes* `CLAUDE.md` (a real clone has
it — the conservative choice, it helps Arm A) but excludes the spec and `.git`.

**MEASURED result — and it does not simply flatter the thesis.** Both arms reached a *functionally
correct* implementation (all six behaviors) with **zero substantive human help**. So a fair clone
*holding the committed carrier* is fully capable with no session-memory — **corroborating the
ablation convergence in §V-D.** But lived context bought real **efficiency**: Arm B finished in
**7.8 min vs 20.1 (2.6×), with 36% fewer tool calls (14 vs 22) and 41% fewer lines added (39 vs 66 —
more surgical)** — it *recognized* the state machine rather than exploring it. The honest
counter-current, reported: Arm B used **38% *more* output tokens (35.2k vs 25.6k)** — the compounding
benefit here is **speed and recognition, not token cost.** The pre-registered prediction (B fewer
human turns + less wall-clock) was **confirmed on wall-clock/steps, tied at zero on human turns**
(the task was tractable enough that neither needed intervention — so RQ5 measures the single-agent
efficiency delta, *not* the courier delta of RQ1). *Bonus, in-apparatus:* the **frozen** acceptance
test carried a latent defect (a crude substring assert tripping on a correct "NOT dispatched"
refusal); it was **disclosed, not patched** — editing a frozen instrument post-hoc is the exact sin
this paper studies (§V-F). Full protocol + both arms' diffs: `cases_rq5-baseline.md`.

### F. ⭐ Unanticipated finding — the paper as an instrument (testimony-free, *with a denominator*)
Asking sessions to substantiate claims *to an external audience* forced verification of things taken
on trust internally. MEASURED, in git: `sizer` found a **46-day defect** (129 cells rendering wrong
fps, count never zero, never visible) while writing its case — caught by *writing*, after 46 days of
use/test/review found nothing; `perf-B` surfaced a validation-across-an-unsafe-version-boundary
provenance defect the same way. **The denominator (review's #5 — the same selection bias recurring
one level down, so we state it):** of **19** case-writing sessions, **at least 4 (~21%)** reported a
correction surfaced by the writing itself (`sizer`, `perf-B`, `app-B`, and the RQ5 apparatus's
own frozen-test defect); the rest reported none. A ~1-in-5 hit-rate with the denominator stated is an
honest result; two dramatic cases with no denominator would have been the very bias §VI disclaims.
The mechanism (perf-B): external writing forces a claim's *conditions* to be enumerated, and
enumeration is when unexamined assumptions surface — predicting a distribution of mostly-small
corrections, occasionally a live defect, which is what the hit-rate shows. **This is evidence *for*
the deployment, in the commit record, not about it** — and it is the paper's strongest result
*because* it is not testimony.

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
- **Ablation methodology (new in v3, flagged by the fleet itself).** (a) *Grading asymmetry* — only
  one of six ablations (`sizer`) published its rubric hash *before* results; the other five are
  honestly-run but **post-hoc graded**, so retrofitting is disavowed, not detectable. (b)
  *Isolation is a claim, not a given* — the harness pre-injects a fresh agent's cwd, git status, and
  memory *index*, so "blind" arms are mitigated, not sterile; the cleanest arms used **fictional
  subjects** (emu-B) or audited each agent's actual tool calls. (c) *Historical arms are not
  re-runnable* — some context-carrying arms are transcripts of past work (the answer already known),
  so they bound rather than measure. (d) *N is small* (1–8/arm) and outcomes are often categorical
  (no variance). Each is stated in the individual `ablation_*.md`.
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
load-sharing division of labour (many peers, a measured head — Gini 0.695 — but no dominant
orchestrator), named failure modes closed with at least one live ablation, machine-evidenced bystander
discovery, and the unanticipated finding that writing the report was itself a working instrument. Its headline intuition — compounding competence — was **put to the
test** (six A/B ablations + a pre-registered baseline) and the naive form was **disconfirmed**: what
compounds is the *committed carrier*, and lived context buys *efficiency and recognition*, not raw
capability, most on open searches a fresh agent cannot cheaply bisect. We report that sharpened,
partly-negative result in full — it is a stronger paper for surviving its own test rather than
dodging it, and the process that produced this honesty (peers refuting the lead over the bus, an
ablation refuting its own author's case) **is the very mechanism under study.**

**The one contribution to leave with** (honesty is not thinness): the reusable result is *the method* —
**in-vivo adversarial co-design of a coordination substrate by persistent, context-divergent peers
under a human gating only irreversibility** — and its cleanest proof is reflexive and testimony-free:
**writing this paper functioned as an instrument (4 of 19 sessions surfaced a real correction by
writing), and the paper survived its own three-lens peer panel by getting sharper at each pass.** The
compounding intuition is the *motivating hypothesis we tested and bounded*, not the contribution; the
method, demonstrated on itself, is.

One last observation the deployment forced on us, because it kept mistaking a rung for the summit: a
result is not durable until it is *reachable by a reviewer*, and the fleet walked that ladder three
times in a day — **untracked file → tracked-but-local commit → pushed to a remote** — each rung
fixing a different failure mode (silent edit → machine loss → un-verifiability), and *each one felt
like the end of the job* (perf-B, on the C2 sequel's own artifacts). "Committed" is not a synonym
for "durable," and neither is "tracked." We state it because this paper's evidence *is* those
commits, and a claim a reviewer cannot resolve is, at that moment, not yet evidence.

---

### Appendix — evidence vs. illustration (kept distinct)
**Evidence (MEASURED):** the mechanical record (git, bus, `history.jsonl`, spend meter), the **six
A/B ablations** (`ablation_{mcu-emu,game-coach,emu-B,media-npu,sizer,sizer-PREREGISTERED}.md`),
and the **pre-registered RQ5 baseline** (`cases_rq5-baseline.md` + the frozen spec/test + both arms'
diffs). These carry the headline claims.
**Illustration (dataset, not evidence).** Twenty first-person `cases_*.md` specimens + the platform
specimen `cases_cleanup-timer`, retained to illustrate design patterns; not cited as proof of any
headline claim. **Curated to five in-body illustrations, each mapping to a distinct claim** (the rest
are the supporting dataset):
1. **`sizer`** — paper-as-instrument (§V-F): a 46-day latent defect surfaced *by writing the case*,
   and an ablation that *refuted the author's own Case 2* — the reflexive mechanism at its sharpest.
2. **`net-emu` ↔ `bench-A`** — RQ3 bystander/vantage: observer-vs-subject mutual correction
   (bench-A's "+64 s stall" was its own backlog; net-emu's guest-side clock settled it) — each
   catches what the other structurally cannot.
3. **`mcu-emu`** (ablation) — RQ4b: the *thoroughness-regression* specimen (context pattern-matched a
   staged answer and stopped; the blind arm caught the second register class) — the sharpest
   disconfirmation.
4. **`app-A`** — RQ4a convergence: a 5th independent derivation of "the model narrates, deterministic
   code owns the value" reached *from privacy* — convergence that survives a change of *force*.
5. **`image-gen`** — lived-expertise routing (§IV): the GPU-lease-lying / cost-blow-up incidents it
   was assigned to document *because it lived them* — the motivating case for routing on history.

Several cases were **corrected during the paper's own writing** (sizer's Case 1 severity downgraded
from user-visible to latent; perf-B's propagated overstatement retracted) — logged as §V-F
specimens, not hidden.

### Panel status + camera-ready checklist
**The three-lens peer panel is DISCHARGED** (`review_95` red-team + `review_bench-A` evidence-rigor +
`review.md` socdev-A synthesis, all on the record). v4 landed the panel's four gating fixes + two
structural watches: RQ3 provenance smudge split (B3); §V-D re-ordered to lead with the powered N=8 arm,
mcu-emu demoted to marked counter-current (C3); concentration now computed by `evidence-harvest.py`
(B2); §V counts as-of-stamped with the drift reported as measured reflexivity (B1); efficiency-vs-
capability operationalized (C1); open-search ceiling marked GAP (C2).

**Remaining before submission (camera-ready):**
1. ✅ **arXiv IDs VERIFIED** (2026-07-27): all 15 fetched from arxiv.org, title + first author match,
   CONFIRMED with no mismatches (incl. MoA 2406.04692 + G-Memory 2506.07398); MAPE-K confirmed
   (masthead *Computer* 36(1), 2003). See `related-work-verification.md`. **No open citation risk.**
2. ✅ **The RQ4b open-search-ceiling sequel LANDED** (§V-D, v5): a pre-registered NULL — the symmetric
   falsifier fired, the constructed task was secretly bisectable, and the finding is *why* (reproducibility
   ⊥ open-search; the ceiling is un-sandboxable, not absent; the earning test is a field A/B). The
   ceiling stays a **reasoned GAP**, not a claim. ✅ **Sequel commits REMOTE-PUBLISHED + citable**
   (`media-npu@abeab3dc64cb` pre-reg, `@d35a64bf6d3a` results, verified on origin 2026-07-27);
   cited canonically in §V-D. Also folded: imx95's caveat that the C2 null and sizer's null are one
   mechanism, not independent corroboration.
3. Final read-through for any remaining prose-vs-mechanical-record mismatch (the panel's standing bar).
4. IEEE-format conversion (Markdown → LaTeX/`IEEEtran`). **Scaffold DONE** (`conductor-paper.tex`:
   documentclass, title, abstract, keywords, section skeleton, `\bibliography` wired to the verified
   `references.bib`; content-compiles-clean via an article-class validation). Remaining is the
   prose-fill of the section bodies (do once, post-C2 freeze) + **Kyle's call on the author block**
   (single human author vs. human + named fleet vs. acknowledgements-only) + completing the "and
   others" author lists in `references.bib` from arXiv. Build needs `IEEEtran.cls` (texlive-publishers
   or Overleaf).
