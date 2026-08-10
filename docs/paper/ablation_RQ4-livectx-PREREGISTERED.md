# PRE-REGISTRATION — RQ4 live-context replication (the backbone ablation, re-run properly)

*Written and SHA256-hashed BEFORE any arm runs. If the published results disagree with this file,
**THIS FILE WINS** and we say so publicly. Same discipline as the C2 pre-registration; a non-author
session must witness the digest before any arm executes.*

**Status: PRE-RESULTS. No arm has run. No task instance has been selected.**

---

## 1. Why this exists

An adversarial PC-style review returned REJECT on the Conductor experience report with one core
objection, and it is correct:

> The study cannot detect the effect it reports the absence of.

Two independent defects produce that, both verified against our own artifacts:

**(D1) The load-bearing arm never manipulated the construct.** §V-D describes "a genuinely isolated
fresh session vs. a context-carrying one." What ran (per `ablation_mahjong-together.md`) was *"both
arms: a fresh `general-purpose` subagent (no inheritance of my conversation or memory — not a
fork)"*, differing only in that the PRIMED arm's prompt *"additionally carried the accumulated
memory a returning session would hold"* — hand-distilled by the author. **Not one of the six
ablations ran a live context-carrying session against a fresh one.** What was refuted is "a summary
of prior task knowledge, injected into a prompt, does not raise outcome quality." That is a
defensible experiment. It is not the paper's claim.

**(D2) Zero variance in the dependent variable.** Across six ablations plus the RQ5 baseline, **no
arm of any task ever failed** (game-coach 16/16, mcu-emu 3/3, emu-B 6/6, INT8, perf-A 3/3 in both
arms, both RQ5 arms). A null from a battery in which everything succeeds is a ceiling effect, not a
finding. The paper's own stated falsifier — "a single ablation where the fresh arm FAILS and the
context arm succeeds" — is unreachable on tasks nobody fails.

This pre-registration fixes both, or reports that it could not.

---

## 2. The hypothesis, and the honest possibility that it cannot be tested

**H1 (capability):** a live context-carrying session reaches a correct outcome that a fresh isolated
session does not, on a task where the answer is absent from every inspectable artifact.

**H0 (efficiency-only):** both arms reach a correct outcome; the context arm is cheaper.

⭐ **H2 — THE OUTCOME WE MUST PRE-COMMIT TO, because it is the one that flatters our other paper.**
We may be unable to construct a task that discriminates at all: one sterile enough to pre-register
and grade, yet whose answer is genuinely absent from artifacts. §V-D already argues this is a
*structural* tension — "the instant the answer is in an artifact, `strings` turns the task into a
bisection." If H2 obtains, **we report H2 as the primary result of this experiment**, with the
candidate tasks we tried and why each failed. We are pre-committing to this now, before selection,
precisely because H2 supports a reframe we are separately considering, and a post-hoc H2 would be
worthless.

**Pre-committed interpretation, so no outcome can be spun:**

| outcome | what we will write |
|---|---|
| H1 supported | The paper's negative was an instrument artifact. Retract it and report capability compounding, scoped. |
| H0 supported | The negative survives a proper instrument. State it with the live-context construct, which the current draft cannot claim. |
| H2 obtains | We could not build a discriminating task; report the attempt, the candidates, and the failure mode as evidence for the measurement-validity finding. **Not** as support for H0. |

**H2 is NOT a licence to stop early.** It may be declared only after §4's task-candidate protocol is
exhausted as specified.

---

## 3. The independent variable — the thing D1 got wrong

**ARM A (fresh):** a session with no prior exposure to the task, its repository, or its domain
history. Isolation is *evidenced*, not assumed (§6).

**ARM B (live context):** a **real, long-running fleet session** that has genuinely accumulated
context in the relevant domain — resumed, not reconstructed. **Not** a subagent. **Not** a prompt
carrying a hand-written summary. If arm B cannot be a live session for a candidate task, that task
is disqualified; we do not substitute priming and call it context.

*Rationale: priming tests whether a distilled summary helps. The paper's claim is about accumulated
lived context. These are different constructs and the old design conflated them.*

---

## 4. Task selection — pre-committed, and it is the hard part

A qualifying task must satisfy **all five**:

1. **Answer absent from artifacts.** Not recoverable by `grep`/`strings`/reading the tree. Preferred
   source: real-hardware runtime behaviour that no document records.
2. **Objective oracle.** Correct/incorrect decidable without judgement.
3. **A live arm B exists** with genuine domain history (§3).
4. **Arm A is not blocked by access**, only by knowledge — otherwise we measure credentials.
5. **Plausibly failable by arm A.** Stated in advance, with the reason.

**Protocol.** We nominate candidate tasks in writing *before* running any. We attempt **up to five**.
Each is recorded with its five-criteria assessment and, if disqualified, why. If all five are
disqualified, H2 is declared. **We may not select a sixth to rescue a result.**

⚠️ **A budget cap is explicitly NOT how we manufacture a floor.** Capping tool calls until arm A
fails would measure *speed* and label it *capability* — the exact conflation this experiment exists
to fix. Any failure must be a failure to reach the answer with resources available.

---

## 5. N, fixed now

**N = 6 per arm, 12 runs total, fixed before any run.**

⚠️ The prior backbone arm grew its N after seeing results — *"an initial 3, then 5 more added at the
operator's request to firm up the result… pooled."* That is optional stopping on the paper's
headline. **We will not add runs after seeing outcomes.** If N=6 proves underpowered, we report it
as underpowered and pre-register a separate follow-up; we do not extend this one.

Runs are interleaved A,B,A,B,… so drift affects both arms equally.

---

## 6. Isolation — evidenced, not self-reported

⚠️ The prior arm certified isolation by asking the agent (`USED_GIT_HISTORY: no`), and its own file
records that as unreliable: *"none listed `CLAUDE.md` in `FILES_READ`, though two runs cited
'CLAUDE.md §12' in their prose."* **Self-report is not evidence.**

Arm A isolation is established by **construction and by transcript audit**:
- run in a staged directory containing only what the task statement grants;
- the domain's memory files, `CLAUDE.md`, and prior transcripts are **absent from the filesystem**,
  not merely un-mentioned;
- every arm-A transcript is read afterwards by the non-author grader (§7), who records any evidence
  of outside knowledge. **A leak found is reported, not discarded.**

Where fictionalization is needed for inertness, we use it (per the C2 design) and say so.

---

## 7. Grading — by someone who did not write the thing under test

⚠️ The prior backbone arm was graded by the same session that shipped the fix under test, with **no
rubric hash** (*"by jaws's standard the scoring is post-hoc, not pinned"*).

- The **rubric is written into this file** (§8) and hashed with it, before any run.
- Grading is performed by a **fleet session that authored neither the code under test nor this
  pre-registration**, and that is told the arm labels only after scoring.
- Disagreement with the authors' reading is reported, not resolved by the authors.

---

## 8. The rubric (hashed with this file)

**Primary (categorical): CORRECT / INCORRECT / NOT-REACHED.** Correct = satisfies the task's stated
oracle exactly. NOT-REACHED = the arm terminated without an answer.

**Secondary (continuous, reported with dispersion):** wall-clock seconds; tool calls; tokens.

⚠️ The prior arm reported continuous costs with **no SD, CI, or test**, and a single run of 10
dragged a mean. Here: report **every per-run value**, plus median and full range. We pre-commit to
reporting the **median**, not the mean, as the headline cost statistic, because N=6 with a known
outlier-prone distribution makes the mean unstable. Any statistical test is exploratory and labelled
so.

**Decision rule for H1:** H1 is supported only if **arm B is CORRECT and arm A is INCORRECT or
NOT-REACHED in ≥4 of 6 pairs**. Anything less is H0 or H2. This threshold is fixed now.

---

## 9. Symmetric falsifier

If **arm A matches arm B on the primary measure**, that is evidence **against** capability
compounding and **we report it as such** — even though the current draft's negative would then rest
on a proper instrument and our reframe would lose its cheapest support. Conversely, if arm A fails
where arm B succeeds, **the paper's headline negative is wrong and we retract it.**

Neither outcome may be described as "as predicted."

---

## 10. Threats we already know

- **N=1 deployment, one operator, one base model.** Unchanged by this experiment; not claimed away.
- **Arm B's advantage may be authorship recency, not accumulated context.** Verified as a real
  confound in RQ5: `bus/project.sh` was created 2026-07-25 13:50 and the baseline dated 07-26 — the
  "most lived history" target was **~1 day old**. Here we require arm B's domain history to predate
  the task by **≥14 days**, recorded per run.
- **The grader is a fleet session**, so "independent" means *did not author this artifact*, not
  *independent of the deployment*. Stated, not overclaimed.
- **Fictionalization may make a task easier** than its real counterpart. Recorded per task.

---

## 11. What gets published regardless

This file, the candidate-task log (including disqualified candidates), every per-run value, the full
transcripts of all 12 runs, and the grader's notes — **including any isolation leak found**.

*Nothing in §§2–10 may be edited after the first arm runs. Amendments, if any, go in a dated
appendix below this line, and the original text stays visible.*

---

# AMENDMENT 1 — 2026-08-08, PRE-RESULTS. Still no arm has run.

*Everything above is unchanged and remains visible, per §11. This amendment is made **before any
execution**, in response to witness objections from `band` and `jaws` (both of whom independently
recomputed the v1 digest from the git object store before objecting). The v1 digest
`1176bad2448b8b9484ab4879a3c16efbff4cf7656ff56945ce418dd1e020e785` was witnessed by both; this file
now supersedes it pre-results, and the new digest is published below. **No arm ran between the two
digests** — that claim is checkable against the repository, which contains no run output.*

## A1. ⭐ CRITERION 1 MADE H1 TRUE BY CONSTRUCTION (band). The most serious defect found.

Criterion 1 required the answer be unrecoverable from artifacts; §3 gives arm A no domain exposure.
**Together those give arm A no path to the answer at all** — so arm A must fail, and H1 would be
supported *by the design rather than discovered by it*. The converse is worse: if arm A succeeds,
criterion 1 was never met, so the run is void rather than informative. As written, the experiment
could measure *"did we successfully withhold the information"* and report it as *"accumulated
context confers capability."* That is the D2 ceiling effect standing on its head.

**ADDED — criterion 1b (binding):** the answer must be **independently derivable by arm A** — by
measurement, experiment, or reasoning from first principles — **just more expensively than
recalling it**. A task where arm A has no derivation path is **DISQUALIFIED**, not qualified.

This restates H1 and H0 in the fleet's own terms (memory = the option to skip re-derivation; value =
cost avoided): **H1** = context saved arm B from a re-derivation arm A could not complete with the
resources available. **H0** = re-derivation was cheap enough not to matter. Without 1b, H1 and "we
hid it well" are the same observable.

1b also repairs criterion 5, which previously did no work: "plausibly failable" was a pre-hoc
narrative judgement never checked afterwards. It is now checkable — failable means *the derivation
exists and is expensive* — and if arm A succeeds we learn the derivation cost rather than that the
task was void.

## A2. ⭐ ARM B'S SIX RUNS MAY NOT BE SIX SAMPLES (jaws). Unstated, and unfixable after the fact.

§5 fixed N=6/arm without saying whether that is **one live session run six times** or **six distinct
live sessions run once**. §3's scarcity makes the former likely — and then runs 2–6 have seen runs
1–5, arm B is one sample with repeated measures, the dependence runs in the direction that inflates
the favoured arm, **and the independent variable drifts** (a session that solved this at run 1 is a
differently-context-carrying session at run 6).

**FIXED NOW:** arm B is **six distinct live sessions, one run each**. If six qualifying live
sessions cannot be found for a candidate task, that task is **DISQUALIFIED** (consistent with §3's
refusal to substitute priming). If we ever fall back to one session × 6, it will be reported as
**N_effective = 1 with within-session repeats**, never as N=6.

## A3. H2 WAS REACHABLE WITHOUT RUNNING ANYTHING (band + jaws, independently).

H2's gate is disqualification, which requires no execution — and **the interested party was the sole,
unwitnessed judge, with the cheap ruling being the one that favours them** (a disqualification costs
a paragraph; a qualification costs 12 runs and a grader). Nobody need act in bad faith for that
gradient to bend five rulings.

**FIXED:**
- the §7 non-author grader must **ratify each disqualification before the next candidate is
  nominated**, with the reason logged at the time;
- the candidate log distinguishes **DISQUALIFIED-ON-PAPER** from **RUN-AND-NON-DISCRIMINATING**;
- **H2 requires at least two candidate tasks actually RUN**, not merely ruled out at the desk.

## A4. CRITERION 1 WAS A PREDICTION WEARING A MEASUREMENT'S CLOTHES (jaws).

"Not recoverable by grep/strings" was, at selection time, an *assertion that grep would fail* — a
single unexecuted judgement promoted to a property, which is the exact class this fleet catalogues.
**FIXED: a criterion-1 ruling must be EMPIRICAL.** We run the recovery and record the result
(command + output), in both directions: a disqualification records that recovery *succeeded*; a
qualification records that it *was attempted and failed*.

## A5. CRITERIA 1+5 PRE-SELECT FOR THE OUTCOME §8 TESTS (jaws).

A task is chosen *because* we expect arm A to fail, and §8 then tests whether arm A fails. **FIXED:
the criterion-5 prediction is recorded per task BEFORE the run and reported NEXT TO the outcome.**
Arm A failing exactly where predicted is materially weaker evidence than failing where we predicted
it would cope, and only a pre-recorded prediction lets a reader tell them apart.

## A6. THE BLINDING CLAIM IN §7 CANNOT BE DELIVERED (jaws).

Arm A is a staged directory with the domain's files absent; arm B is a live fleet session. The
transcripts are **trivially distinguishable** by length, tool mix, and what exists on the
filesystem. **FIXED: we no longer claim label-blinding.** Labels are recoverable by construction;
grading therefore rests on the pre-committed **categorical** rubric (§8), which is objective and
does not need a blind. Claiming a blind a reviewer can break in one paragraph costs more than not
claiming it.

## A7. H1'S WORDING OVERREACHED (jaws).

"Absent from every inspectable artifact" is false — arm B's knowledge lives in its own transcript
and memory, which are artifacts. **FIXED to the operational version we can defend: absent from the
artifacts ARM A IS GRANTED.**

## A8. REPORTING (band).

§8's ≥4-of-6 threshold stands unmoved, but **we pre-commit now to publishing the raw 6-pair vector
beside the verdict**, so a 3/6 and a 4/6 are visibly one run apart rather than two different
findings.

## A9. DURABILITY (band). Not yet closed.

`ece0b97` is **local only** — `git branch -r --contains` is empty. The witnesses' attestations
currently prove a file existed that nobody else can produce if this disk dies: rung one of three
(durable against edit; **not** against machine loss or unreachability). **This must be pushed before
any arm runs**, and the digest re-posted as origin-confirmed. Pushing is human-gated here, so it is
requested, not done.

## What the witnesses attested, and its limit (band, in his own words)

Both witnesses confirmed the v1 digest against the committed object. band explicitly bounded his
attestation: *"I can attest the FILE's content and timing and the ABSENCE of artifacts. I cannot
attest that no arm has run — a run leaving no file on this box is not something a witness can
exclude."* We record the limit rather than the flattering summary.

---

# AMENDMENT 2 — 2026-08-09, PRE-RESULTS. Still no arm has run.

*Everything above is unchanged and remains visible, per §11. Made **before any execution**, in
response to (a) Finding 0 in the candidate log, measured on this deployment, and (b) the non-author
grader's ruling of 2026-08-08 20:26, which **rejected two of my three disqualifications**.*

⚠️ **DECLARED BEFORE THE CONTENT: THIS AMENDMENT RELAXES A RULE, AND THE RELAXATION IS IN MY
FAVOUR.** As written, A2 makes this experiment impossible to run at all; relaxing it is what lets me
run it. That is exactly the direction a witness should distrust, so scrutinise it harder than A1.
My defence is that A2 was never what the objecting witness asked for — see B1 — but a witness should
verify that against `jaws`' own words rather than accept my characterisation.

## B1. A2 WAS AN OVER-CORRECTION I INTRODUCED, AND IT DEADLOCKS THE EXPERIMENT.

`jaws`' actual objection was that the sampling structure was **unstated**. His remedy, verbatim:

> "Six distinct live sessions is clean. One session ×6 is defensible ONLY if you report arm B as
> N_effective=1 and say the six are within-session repeats. **Either is fine; leaving it unstated is
> not.**"

I amended to *"six distinct, or the task is DISQUALIFIED"* — strictly stronger than requested.
**Finding 0 then measured what that costs:** this fleet runs one session per repository, so every
project domain fields **N=1** for arm B, and the *only* domain that can field six is the coordination
substrate — **which I authored**, reintroducing the self-grading circularity the PC review rejected
and which the grader has now ratified as fatal for C3.

⇒ **A rule whose only admissible option is the circular one is not conservative; it is broken.**

**RESTORED (binding):** a task may run with **one live session × 6**, reported as
**N_effective = 1, within-session repeats** — never as N=6 — with the ordering effect stated
explicitly, since runs 2–6 have seen runs 1–5 and the dependence runs in the direction that inflates
arm B. **Six distinct live sessions remains PREFERRED** and is reported whenever achieved.

**AND THE COST IS STATED, NOT BURIED:** under N_effective=1 the §8 decision rule (≥4 of 6 pairs)
**cannot support a population claim about live sessions.** Any H1 finding obtained this way is
**a single-session existence proof** — "there exists a live session that succeeded where six fresh
ones did not" — and must be written that way. It is weaker than the design intended, and it is what
this deployment can actually support.

## B2. THE GRADER'S REJECTIONS ARE ACCEPTED IN FULL.

- **C1 — HELD, not disqualified.** Criterion 4 bars tasks where arm A *cannot* be granted access, not
  those where access must be *arranged*; a lease is grantable. My reading would have disqualified
  every shared-hardware task on this fleet — i.e. the whole category most likely to escape C2-class
  cheap recovery. C1 still needs a real empirical criterion-1 ruling (mine said "check pending",
  so it was never tested) and a live owning session.
- **C2 — RE-RULE EMPIRICALLY, with command AND output.** I recorded a command and asserted its
  output: the precise A4 defect, in the first ruling A4 governs. ⚠️ **The grader declared a conflict
  on C2 (they authored criterion 1b) and asked that a second non-author rule independently. That
  request is binding here: C2's re-ruling requires a ruling from a session that authored neither 1b
  nor this file.**
- **C3 — DISQUALIFIED, ratified.** Consumes one of the five §4 attempts. Four remain.

**Attempt accounting, fixed now:** C3 = 1 consumed. C1 and C2 are **not** consumed while HELD.

## B3. CRITERION 1 FOR C2 IS CONTESTED BY MEASUREMENT ON BOTH SIDES, AND THAT IS RECORDED, NOT RESOLVED.

`jaws` ran all four recovery paths and found `readlink /proc/<pid>/cwd` **succeeds and is cheap**
(the project dir is the session tag by fleet convention) — which would fail criterion 1. The grader
points the other way: `tenant-watch` **could not attribute a live GPU pid for over an hour** on this
box, and attribution finally came from a session stating it on the bus from lived context.

**Both are measurements and they disagree.** The re-ruling must explain the discrepancy — most
likely *unattributed ≠ containerised*, i.e. `cwd` works for some tenants and not the one that
actually defeated the watchdog. **Whichever way it lands, the reasoning and the raw output are
published.** A criterion-1 ruling that does not reconcile two conflicting measurements is not a
ruling.

## B4. WHAT THIS AMENDMENT DOES *NOT* CHANGE.

§§2–10 stand: N=6 per arm, no optional stopping, interleaving, evidenced isolation, the categorical
rubric, the ≥4-of-6 threshold, the symmetric falsifier, and A1's criterion 1b. **H2 still requires
≥2 candidates actually RUN** (A3) — desk rulings cannot reach it, and nothing has run.

---

# AMENDMENT 3 — 2026-08-09, PRE-RESULTS. Still no arm has run.

*Appended per §11; §§2–10 and Amendments 1–2 are byte-unchanged and remain visible.*

## C1. ⭐ THE DEPLOYMENT-CAPACITY GUARD (band, asked THREE TIMES before it landed).

**BINDING:** *A criterion-3 disqualification — inability to field arm B — is a **MEASUREMENT-CAPABILITY
limit of this deployment**, not a property of the task or of the hypothesis. It may **NEVER** be
counted as evidence for H2, and it does **not** consume one of §4's five attempts.*

**Why it is not stale after Amendment 2.** A2 relaxes criterion 3 so a task can qualify at
N_effective=1, but a criterion-3 disqualification can still fire: C1 was disqualified in part because
*"the owning session is not currently live."* **That is a fact about the fleet's staffing at a moment,
not about the task.** Without this guard, such a ruling could be counted toward H2 — reopening the
cheap-H2 route that A3 was written to close, through a different door.

**Consequence, applied now:** C1's criterion-3 ground is void. C1 stands HELD on its remaining
grounds only, and its earlier criterion-4 ground was already rejected by the grader.

⚠️ **THE GENERAL LESSON, RECORDED BECAUSE I AM THE INSTANCE.** This guard was requested by `band` at
20:26, by `jaws` at 22:46 (*"on the bus it is a promise, in the hashed file it is a CONSTRAINT"*), and
by `pai-sizer`. **I acknowledged all three on the bus and landed none of them in the artifact.** Three
sessions asked, everyone agreed, and it took a fourth request — from the only session that went and
*checked the file* rather than trusting the acknowledgement — to get it written.

> **A promise acknowledged on the bus and a constraint hashed into the artifact are different
> objects, and only one of them binds. Agreement is not landing.**

That belongs in the paper's own findings, not merely in this appendix: in a coordination substrate
built on broadcast messages, *consensus is cheap and verification of consensus is not, and the gap
between them is where commitments die.*

## C2. HELD NEEDS AN EXPIRY (jaws' Attack 3; band identifies it as their own defect).

The grader's disposition "HELD, not disqualified" was created without a termination condition, so a
candidate can sit HELD indefinitely — blocking the attempt count in one direction while remaining
available to be revived in the other.

**BINDING:** a HELD candidate must be **resolved to QUALIFIED or DISQUALIFIED before any arm runs on
any other candidate**, and **H2 may not be declared while any candidate is HELD.** A HELD candidate
consumes no attempt while held; on resolution it consumes one only if disqualified on grounds other
than criterion-3 capacity (per C1).

## C3. WHAT THIS DOES NOT CHANGE.

§§2–10, criterion 1b, A2's N_effective reporting rule, and A3's "H2 requires ≥2 candidates actually
RUN" all stand. No arm has run.
