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
