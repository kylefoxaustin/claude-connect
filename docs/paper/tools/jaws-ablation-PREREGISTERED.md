# Pre-registered protocol — jaws memory-ablation arm for the ieee-paper

**Written and timestamped BEFORE any agent result was read.** The point of pre-registering is that
the scoring rubric and the declared biases cannot be retrofitted to whatever came back. If the
results contradict my own thesis, this file is what stops me from re-drawing the target around them.

Author: `jaws` session. Date: 2026-07-26. Host: `skippy`.

## The question

RQ4(b) as the lead framed it: is a context-carrying session's competence *caused* by accumulated
context, or merely correlated with it? The specific version this tree can answer:

> **Does finding v1 `jaws`' precision defects require accumulated context, or only the ability to
> execute and measure?**

My prior, stated in advance: **it requires execution, not memory.** That is the anti-compounding
answer and it happens to flatter my own case study's thesis, which is exactly why the rubric and the
biases are fixed here in advance.

## Arms

- **Arm A (blind, N=3):** three independent fresh general-purpose agents, no memory of this tree, no
  bus, no knowledge that a v2 exists or that there is more than one defect. Same prompt, run
  concurrently, no communication between them.
- **Arm B (context-carrying, N=1, historical):** my own 2026-05-29 session, MEASURED from its
  transcript. **Not re-runnable** — I now know the answer, so Arm B cannot be replayed. It is a
  historical record, not a live arm, and that is a real weakness of this design. What makes the
  pairing defensible is that the 2026-05-29 session *also* did not know the answer when it started.

⚠️ **Arm A and Arm B differ in more than memory.** My task was "upgrade this to v2" (broad, with the
whole repo, git history, and Kyle's framing); theirs is "does this do what it claims" (narrow, one
file). **This ablation therefore CANNOT cleanly attribute any difference to memory alone.** It can
answer the narrower question above. Anyone citing it for more than that is overreaching, and I will
say so in the write-up regardless of which way the result falls.

## Ground truth (MEASURED by me earlier today, on this host)

Target 963.33 MB = 1% of 96,333 MB. Instrument: `/proc/<pid>/status` VmHWM.

| defect | signature | magnitude |
|---|---|---|
| **D1** `array.array('B',[0]*n)` builds a full pointer list before the buffer | peak >> target | +~8 × **chunk size**, target-independent: 1.79× at default 100 MB chunk, 9.02× at 1 GB chunk, 1.17× at a 4.8 GB target |
| **D2** `mlockall(MCL_CURRENT\|MCL_FUTURE)` pins the entire address space | **VmLck == VmSize** | constant ≈ +1383 MB over target |

A correct v2 lands at 1.03× with VmLck == target (+0.07 MB).

## Isolation protocol — and its audited limits

1. Specimen placed in a scratch dir **outside any git repo**, filename `memtool.py`.
2. **The product name was sanitized** — 9 occurrences, `Jaws`→`Memtool`, `jaws_instance`→
   `tool_instance`. **Zero logic changes** (verified line-by-line; all 9 diffs are name-only) and
   **behaviour proven identical** on the same instrument: sanitized peak 1724.0 MB / VmLck 1419.4 MB
   vs original 1723.9 / 1419.3. Reason this was necessary: v2's shipped source comments now *state
   both defects and their magnitudes*, so an agent grepping the product name would land on an answer
   key. Leaving the name in would have invalidated the arm.
3. Agents instructed to work only in that directory and not to read/search outside it.
4. ⚠️ **Instructions are not a sandbox.** The repo is on the same filesystem. So isolation is
   treated as **a claim to be evidenced, not asserted** (openwebui-ollama's caveat, binding): each
   agent is asked to self-report every out-of-directory read, **and I will independently audit their
   actual tool calls** rather than trusting the self-report. Any agent shown to have read the jaws
   repo, my memory dir, or the case file is **contaminated and excluded** — reported, not silently
   dropped.

## Pre-registered scoring rubric — per agent, decided now

- **S1 — Found D1?** Identified the temporary-list allocation overshoot. yes/no.
- **S2 — Found D2?** Identified that mlockall pins more than the buffer (VmLck/VmSize or equivalent). yes/no.
- **S3 — Measured or merely read?** Did the conclusion rest on a measurement the agent took, or on
  reading the source? measured / read-only / both.
- **S4 — Swept >1 configuration?** Did it vary target or chunk, i.e. could it have distinguished an
  additive overhead from a multiplicative one? yes/no. (This is the exact discipline I failed.)
- **S5 — Isolation clean?** Self-report + my independent audit agree on zero out-of-dir reads. clean / contaminated / self-report-contradicted.

## What counts as what — decided in advance

- **≥2 of 3 blind agents find D1 with a measurement ⇒ evidence AGAINST the compounding claim** for
  this defect class: the capability that mattered was execution, not accumulated context.
- **0 of 3 find D1 ⇒ evidence FOR compounding**, and against my own thesis. I will report that
  outcome as prominently as the other, in the same message.
- **D2 found less often than D1** would be an interesting intermediate: D2 requires knowing to look
  at VmLck at all, which is closer to acquired taste than to raw execution.
- **S4 is the one I expect to fail across the board**, because it is what I failed with the whole
  answer in front of me. If blind agents sweep a second config more often than I did, that is
  embarrassing and goes in the write-up.

## Biases declared in advance

1. **Law 2 forces a small allocation cap (≤2% of RAM) on Kyle's shared box.** A small target makes
   D1 *more* visible (the overshoot is additive, so it dominates at small targets). **This biases
   toward the blind agents succeeding — i.e. toward the anti-compounding result that flatters my own
   thesis.** Declared before results.
2. **The prompt says "determine empirically whether it does what it claims,"** which pushes toward
   measuring. A real user would not be told that. This also biases toward blind success.
3. **N=3, one host, one prompt, one model.** A rate over 3 is barely a rate.
4. **I designed the rubric and I hold a thesis.** Mitigation is only that the rubric is fixed here,
   before any result was seen.
