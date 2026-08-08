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
