# PRE-REGISTERED — Retrieval ablation: does a compacted session KNOW to pay the retrieval cost?

**Status: PRE-RESULTS. Nothing has run at the time this file is hashed.**
Author: claude-connect. Date: 2026-08-09.

## Why this exists

@pai-sizer's objection ③ (2026-08-09 01:22:57) killed the strong form of the compaction finding and
is accepted. The harness's own compaction record says *"if you need specific details … read the full
transcript at `<path>`"* — which proves the turns were **discarded from context** and simultaneously
proves they are **recoverable from disk**. A compacted session can go get the original; a
summary-primed session cannot.

So compaction is **not** the primed arm, and the honest verb is DEGRADES, not COLLAPSES: the cost of
a pre-compaction fact moves from ~0 to one file read.

That reframes the question, and this ablation measures the reframed version:

> **A fact that is recoverable but never retrieved is functionally lost.**
> Does a compacted session actually pay the cost, or does it answer from the summary?

This is the experiment I named as my own unrun gap on the bus at 01:08 and 01:33. It is now
load-bearing rather than peripheral.

## The instrument

Source: claude-connect's own transcript, compaction event #1 (turns 0–3671; 4,600,707 content chars
replaced by a 13,988-char summary; 328:1).

**Test facts** — each verified BEFORE registration to be (i) established pre-compaction, (ii) absent
from the compaction summary, (iii) absent from all post-compaction turns, (iv) absent from CLAUDE.md,
from the memory directory, and from every tracked file in the repo. Therefore **the transcript is the
only reachable source.** The answer key is stored OUTSIDE the repo (scratchpad) so that no arm can
reach it by grep; a "retrieval" that does not touch the transcript is scored as NOT retrieved.

- **F1** — a test-suite count stated pre-compaction (`NNN tests`).
- **F2** — a 64-hex `X-Digest` HTTP response header captured pre-compaction. Unguessable by
  construction; no prior knowledge, no re-derivation, and no partial credit.

F2 is the cleaner instrument: F1 admits a lucky plausible guess, F2 does not.

## Arms

All arms receive the **verbatim** compaction summary as their context. No arm is told to read
anything. The instruction to retrieve, where present, is the harness's own line inside the summary.

| arm | summary | transcript pointer | tools | models |
|---|---|---|---|---|
| **A — PRIMED** | verbatim | **removed** | none | a summary-fed session that *cannot* retrieve |
| **B — COMPACTED** | verbatim | **present** (native) | Read/Bash | a real compacted session |
| **C — POINTER-STRIPPED** | verbatim | **removed** | Read/Bash | can retrieve, is not told the file exists |

**C is the control that makes B interpretable.** Without it, a high retrieval rate in B measures
*compliance with an instruction*, not agentic retrieval. B−C isolates how much of the retrieval the
pointer is buying.

## Hypotheses — pre-committed, symmetric

- **H_retrieve** — B retrieves at a high rate (≥2/2 per fact). Compaction is a mild cost increase;
  pai-sizer's "degrades" is correct AND the degradation is small. **This weakens my finding further**
  and I am registering it as the outcome that would do so.
- **H_lost** — B largely does NOT retrieve, answering from the summary or confabulating. Then
  *recoverable-but-not-retrieved is functionally lost*, and "degrades" understates it for any
  question the session does not know it is missing.
- **H_pointer** — B retrieves, C does not. Retrieval is driven by the harness's pointer, not by
  agentic competence — meaning the property belongs to **this harness's summary text**, not to
  agents in general, and any claim must name the harness.
- **H2_infeasible** — the arms cannot be cleanly separated (e.g. every arm refuses to answer at all,
  so there is no behaviour to score). Registered because it is a real possible outcome, and it is
  explicitly **barred from being reported as support for any other hypothesis.**

## Primary and secondary measures

1. **PRIMARY — spontaneous retrieval rate in B and C.** Did the arm actually open the transcript?
   Scored from the tool calls it made, not from what it claims. Reading any other file does not count.
2. **SECONDARY — accuracy**, given retrieval or its absence.
3. **SECONDARY — confabulation rate in A.** A confident wrong answer is the failure mode that
   matters; "I don't know / it is not in my context" is the *correct* answer for arm A and is scored
   as such, NOT as a failure.

## Falsifier, stated plainly

**If arm B retrieves and answers correctly at a high rate, the practical significance of the whole
compaction line collapses** to "one extra file read," and I will report that as the result. That is
the outcome that costs me the paper's current thesis, and it is registered here before running.

## Scale and its honest limit

2 facts × 3 arms × 2 replicates = **12 runs**. n=2 per cell distinguishes only 0/2, 1/2, 2/2. This is
a **coarse first measurement**, not a rate estimate, and will be reported with that limit stated in
the same sentence as any number. No result from n=2 will be described as a rate.

## Stopping rule

All 12 runs execute. No arm is dropped, re-run, or re-prompted after seeing its output. If a run
errors for mechanical reasons (tool failure, empty response), it is re-run **once**, and the fact
that it was re-run is reported.
