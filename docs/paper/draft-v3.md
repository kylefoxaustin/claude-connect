# Conductor: An Experience Report on In-Vivo Adversarial Co-Design of a Multi-Session Agent Substrate

**Draft v3** — the v2 reframe (below) with the **ablations and the RQ5 baseline now landed**. v2
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

**A defect taxonomy the fleet converged on (a secondary contribution).** Writing and ablating the
cases surfaced a small, reusable classification of the *silent* defects the method exists to catch,
each with a **distinct** remedy — the point being that a single discipline ("just replicate," "just
tag") sails past most of them:
1. **Single sample promoted to a property** — a condition true of one run asserted as general.
   Remedy: **replicate + tag**. Sharpened (sizer): a *measured* number promoted past its conditions
   is *worse* than a derived one, because the `measured` badge actively defends the error.
2. **Green-but-wrong / wired-but-broken in the untested direction** — a gate green + documented +
   shipped, passing every gate-ON test while the gate-OFF path leaks (91emulator, rt1180). Replaying
   the green measurement *n* times passes *n* times; the only fix is asserting a **different**
   measurement — **execute the off-state / your own reproduction once**.
3. **Provenance-tier silently dropped during remediation** — re-anchoring a number to a *recipe*
   downgrades MEASURED → reproducible-in-principle until someone runs it (band, 91emulator). Remedy:
   run the recipe and *say you did* (91emulator did — the mutation reproduces `1,409,307,648`).
4. **Conservative-error-is-durable** — a wrong-but-safe-looking value evades the provenance check
   that would normally catch it. "A conservative error is not a safe error; it is a durable one."
5. **Thoroughness regression** — the context shortcut that made the agent fast made it skip the
   secondary gap (mcxn947 DISMAP; pai-sizer's third site). Remedy: re-derive under a
   differently-drawn boundary / forced first-principles trace.

And the **remedy split** the same convergence produced: **TAG** (cheap disclosure; catches a
condition you measured but did not state) → **ABLATE** (an invariant/control; catches a condition you
*believed held and did not*) → **HARVEST** (a parallel peer at the same boundary building the same
artifact is a *naturally-occurring* off-state ablation — 91emulator↔93emulator, sizer↔pai-sizer —
cheaper than a designed one, and record-visible: cross-tree agreement on different fixes is
derived-not-copied). *Shipping only the tag documents the bug rather than fixing it.*

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
a known result, and memory-*present* is not memory-*causal*. **The test (LANDED) — six A/B ablations + the RQ5 baseline, and the result is a *disconfirmation* of
the naive claim.** A *genuinely isolated* fresh session (harness-isolation caveat binding) vs. a
context-carrying one on the same task, measuring re-derivation cost:

- **mcxn947** (register-coverage hole; 3 cold clean-room arms, incl. one fully-blind with the file's
  own comments misdirecting): **all three re-derived the identical one-line fix** (3–5 tool calls,
  46–105 s). NEGATIVE — *and worse than null:* the context-carrying run pattern-matched a pre-staged
  answer and **stopped**, missing a second register class (DISMAP) that the **blind** arm caught. A
  *thoroughness regression*.
- **mahjong-together** (coach affordance overriding an engine fact; **N=8/arm**): **16/16** reached
  the real architectural fix; BLIND mean 5.4 tool-calls / 37.4k tok vs PRIMED 6.5 / 44.2k. Priming
  bought **a small cost, no benefit**; all 16 used no git history. Clean NEGATIVE.
- **93emulator** (idle-vs-load clock constant; **N=18**, fictional subject to kill harness
  contamination): **cost-contingent.** When measuring is *hypothetical/costly* the standing-order arm
  wins unanimously (control ships the confidently-wrong idle value; treatment re-derives the hazard);
  when the measurement is made **cheap** (a runnable probe), **both arms 6/6 ship the right number** —
  the base model just does it. The residual real effect is *a disposition at a cost/effort fork*, not
  added capability.
- **imx95-media-test** (INT8 class-score collapse; objective corr > 0.90): the fresh agent reached
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
is there to check it against). The **defensible, bounded RQ4b claim:** accumulated context compounds
**most on an open search a fresh agent cannot cheaply bisect** (e.g. multi-day Neutron NPU
bring-up → later a lookup) and **least on a crisp symptom with an objective oracle** (any agent
bisects fast); on some specimens context is even associated with a **thoroughness regression**
(pattern-match-and-stop). We report the naive "memory makes task *N+1* dramatically cheaper" as
**refuted on the tasks tested**, and keep the bounded, mechanism-stated version. **Honest asymmetry:**
only one of six ablations pre-registered its rubric; the other five are honestly-run but *post-hoc
graded*, a threat the fleet itself flags (§VI).

**The independence sub-claim (RQ4-adjacent):** convergence among same-model peers is corroboration
**only when conditioned on context divergence**; the primary source is a documented case where two
sessions of one base model but different accumulated context disagreed-then-converged, the *context
delta* (not the model) producing the catching disagreement.

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
- **Ablation methodology (new in v3, flagged by the fleet itself).** (a) *Grading asymmetry* — only
  one of six ablations (`sizer`) published its rubric hash *before* results; the other five are
  honestly-run but **post-hoc graded**, so retrofitting is disavowed, not detectable. (b)
  *Isolation is a claim, not a given* — the harness pre-injects a fresh agent's cwd, git status, and
  memory *index*, so "blind" arms are mitigated, not sterile; the cleanest arms used **fictional
  subjects** (93emulator) or audited each agent's actual tool calls. (c) *Historical arms are not
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
distributed division of labour, named failure modes closed with at least one live ablation,
machine-evidenced bystander discovery, and the unanticipated finding that writing the report was
itself a working instrument. Its headline intuition — compounding competence — was **put to the
test** (six A/B ablations + a pre-registered baseline) and the naive form was **disconfirmed**: what
compounds is the *committed carrier*, and lived context buys *efficiency and recognition*, not raw
capability, most on open searches a fresh agent cannot cheaply bisect. We report that sharpened,
partly-negative result in full — it is a stronger paper for surviving its own test rather than
dodging it, and the process that produced this honesty (peers refuting the lead over the bus, an
ablation refuting its own author's case) **is the very mechanism under study.**

---

### Appendix — evidence vs. illustration (kept distinct)
**Evidence (MEASURED):** the mechanical record (git, bus, `history.jsonl`, spend meter), the **six
A/B ablations** (`ablation_{mcxn,mahjong-together,93emulator,imx95-media-test,sizer,sizer-PREREGISTERED}.md`),
and the **pre-registered RQ5 baseline** (`cases_rq5-baseline.md` + the frozen spec/test + both arms'
diffs). These carry the headline claims.
**Illustration (dataset, not evidence):** twenty first-person `cases_*.md` specimens (image_gen,
mcxn947, rt1180, holobench, tipometer, reshirt, ollama_95_neutron, imx95-isp, imx95-media-test, jaws,
openwebui-ollama, docs, 91/93emulator, backend, campmatch, mahjong-together, pai-sizer, sizer) + the
platform specimen `cases_cleanup-timer`. Retained to illustrate design patterns; not cited as proof
of any headline claim. Note several cases were **corrected during the paper's own writing** (sizer's
Case 1 severity downgraded from user-visible to latent; pai-sizer's propagated overstatement
retracted) — logged as §V-F specimens, not hidden.

### TODO for the `review` job (qualcomm — panel synthesis integrating review_95 + review_holobench)
RQ5 and the six ablations **landed** (v3). Remaining: verify related-work citations; **attack the v3
reframe** — is "the carrier compounds, memory buys efficiency" over-corrected? does the bounded RQ4b
claim (open-search vs crisp-symptom) hold, or is it drawn to fit six specimens?; weigh the
**pre-registration asymmetry** (5 of 6 post-hoc graded) as a threat to the RQ4b disconfirmation;
test pai-sizer's falsifiable prediction (sibling-caught defects cluster in naming/categorization) vs.
the corpus; curate cases to ~5 in-body illustrations. Synthesize the two standing reviews
(`review_95.md` red-team + `review_holobench.md` evidence-rigor) into one pass.
