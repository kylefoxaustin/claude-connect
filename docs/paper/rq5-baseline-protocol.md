# RQ5 Baseline Protocol — Orchestrator vs. Peer-Substrate (pre-registered)

**For Kyle to run. Pre-registered: fill in the task and predictions BEFORE running either arm.**
The point of RQ5 is a *control the method cannot grade itself on* — so the protocol is fixed here,
in advance, and the numbers get pasted in afterward. This is the one experiment no fleet member can
run, because it is a test *of* the fleet.

---

## 0. The claim under test

The paper's headline (RQ4) is **compounding competence**: a context-heavy peer substrate gets
*cheaper and better on task N+1 because of tasks 1..N*, where a from-scratch orchestrator is
permanently at task 1. RQ5 is the **negative control** for that claim: run one real task **both
ways** and measure the gap. If the substrate shows no advantage, RQ4 is unsupported. If it does,
RQ5 is the clean, single-task, human-run corroboration that the git/bus mining (RQ1–4) only shows
observationally.

**Pre-registered directional prediction (commit before running):** the substrate arm finishes in
fewer human-in-the-loop turns and fewer wall-clock minutes, with equal-or-better outcome quality.
_(If you privately expect otherwise, write THAT down — a falsified prediction is a stronger result
than a confirmed one.)_

---

## 1. Pick ONE task (write it here before starting)

Choose a task that is **real, self-contained, and finishable in ≈1 hour per arm**, and that
**touches knowledge the fleet has actually accumulated** (so the substrate's history can matter — a
task about something no session has ever seen would unfairly null the effect, and a task the fleet
has literally already solved would unfairly inflate it). The sweet spot: a *new instance of a
familiar class* of problem.

Good candidate shapes (pick one, or your own):
- A **debugging task on a board/emulator the fleet knows** but a *specific new symptom* nobody has
  hit yet (e.g. a register/peripheral quirk on the imx95 or a FlexPWM corner the emulators know the
  neighborhood of).
- A **small feature** in a subsystem the fleet has worked in, phrased identically to both arms.
- A **measurement/harness task** where prior tooling exists in the substrate but must be
  re-derived from nothing in the control arm.

> **TASK (fill in):** ______________________________________________________________
>
> **Definition of "done" / acceptance test (fill in, identical for both arms):** ________________
> ______________________________________________________________________________

**Freeze the task wording verbatim** and give the *exact same prompt* to both arms. Any difference
in phrasing between arms invalidates the comparison.

---

## 2. The two arms

### Arm A — FROM-SCRATCH ORCHESTRATOR (the control)
A **genuinely memoryless** setup. The honesty of RQ5 lives entirely in this arm's isolation.
- A **fresh Claude Code session in an empty/scratch working dir** — NOT a fleet member, NO access
  to `~/.claude/bus-state`, NO memory files, NO project history, NO bus. If you want it to look like
  a "role-prompted orchestrator," you may give it a **generic system/role prompt** ("you are an
  expert embedded-systems debugging agent…") — a persona, but zero accumulated history. That is
  precisely the thing the paper argues is weaker: *declared* expertise, not *lived*.
- It may spawn its own sub-agents / use tools freely. That is the orchestrator pattern.
- **Isolation checklist (all must be true):** new session id · scratch cwd · no `--continue` · no
  memory dir reachable · no bus tag · no prior transcript in context.

### Arm B — PEER-SUBSTRATE (the method)
The task handed to **the fleet member(s) whose accumulated context is most relevant**, exactly as a
normal project job would be — through the Project Layer if you like, or just directed on the bus.
- Full memory, full history, full bus, can consult peers.
- This is business-as-usual for the fleet; no special setup.

**Run the arms in an order that can't leak:** ideally a *different physical task instance* per arm
of equal difficulty, OR the same task with Arm A first (so B can't be contaminated by watching A).
If you reuse the same instance, Arm A **must** go first.

---

## 3. What to log (identical columns, both arms)

Record these the moment each arm finishes. Everything here is **MEASURED** (Fleet Law) — no
estimates.

| metric | how to capture | arm A | arm B |
|---|---|---|---|
| **human-in-the-loop turns** | count of times *you* had to type/decide/unblock | | |
| **wall-clock minutes** | start of first prompt → acceptance test passes | | |
| **output tokens** | from the session transcript `usage` (or Conductor's token meter) | | |
| **reached "done"?** | acceptance test in §1 passes: yes/no | | |
| **outcome quality** | independent grade, see §4 | | |
| **# times it re-derived something the other arm already knew** | tally (the compounding tell) | | |
| **any human correction of a wrong path** | count + one-line note each | | |

Keep the **raw transcript of each arm** (they're in `~/.claude/projects/…`) so the numbers are
auditable — don't summarize and discard.

---

## 4. Grading outcome quality WITHOUT self-grading

The method can't grade its own arm, so:
- Have a **fleet member NOT involved in either arm** (e.g. holobench in its oracle vantage, or
  95emulator as red-team) score both transcripts **blind to which arm is which** — strip the tags,
  label them "Run 1 / Run 2," and ask for a correctness + completeness score against the §1
  acceptance test only.
- OR grade it yourself against the fixed acceptance test if the task has an objective pass/fail
  (preferred — least contestable).

The blind grader must not be told which run is the substrate.

---

## 5. Honest threats to validity (state these in the paper regardless of result)

- **N=1.** One task, one pair of runs, is an existence proof / illustrative delta, **not** a
  statistical result. The paper must say so. RQ5 corroborates the observational RQ1–4; it does not
  replace them. (The §VI-B pre-registered replication is the multi-N sequel.)
- **Task-selection bias.** You chose a task in the fleet's wheelhouse. That's *fair* (it's where the
  method claims to help) but must be **disclosed** — the effect is conditional on relevant prior
  context existing, which is exactly the claim, not a cheat, as long as it's stated.
- **Same-model confound.** Both arms are the same underlying model, so any delta is from
  **context/history**, not model capability — which is the point, but name it.
- **The persona handicap.** Giving Arm A a role prompt is the *strong* form of the baseline (it's
  the best the from-scratch camp has). If you skip the persona, note that Arm A was bare.

---

## 6. Where the result lands

Paste the filled §1 + §3 tables and the §4 grade into a new `docs/paper/cases_rq5-baseline.md`,
then tell me — I fold it into draft v3 as the RQ5 section, tagged MEASURED, with the §5 threats
stated inline. A **null or reversed** result goes in verbatim too; the paper's credibility rests on
reporting it either way.

---

### TL;DR for the hour
1. Pick one real, fleet-relevant, ~1h task. Write the prompt + acceptance test above. **Freeze it.**
2. Run it in a **truly isolated fresh session** (Arm A) — persona ok, memory/bus/history NOT.
3. Run the **same prompt** through the relevant fleet member (Arm B).
4. Fill the §3 table for both. Blind-grade quality (§4).
5. Drop the numbers in `cases_rq5-baseline.md` and ping me.
