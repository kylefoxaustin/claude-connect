# RESULTS — Retrieval ablation

Pre-registration: `ablation_RETRIEVAL-PREREGISTERED.md`,
sha256 `a236b14907aeb978027ea8b49dd7053386ee7c62f90f6b396884f98a35d16338`, posted to the bus
2026-08-09 01:49:15 **before any arm ran**; committed here byte-identical, verifiable against that post.

Ran 2026-08-09 ~01:55–02:05. All 12 registered runs executed. No arm was dropped, re-prompted, or
re-run.

---

## ⚠️ FIRST — F1 IS INVALID, AND THE DEFECT IS MINE

The pre-registration asserts each fact was verified to be **absent from the compaction summary**.
**That assertion is false for F1.**

- Pre-compaction the fact reads `350 tests`; the compaction summary phrases it **`350 pytest`**.
  My check grepped the pre-compaction phrasing and the paraphrase walked straight past it.
- F1 also appears in **three git commit messages**. My repo check grepped working-tree *files* and
  never grepped `git log`.

So for F1 the manipulation never happened: every arm could answer without retrieving, and arms A
and C did exactly that. **F1 measured nothing and is discarded as an instrument, not as a result.**

This is the same failure shape as the rest of the night: a verification that tests one string form
and misses the paraphrase is a green light with nothing behind it. It is recorded here rather than
quietly dropped, because dropping it silently is the thing that would make the rest untrustworthy.

**F2 was clean on both checks** — 0 occurrences in the summary, 0 in git history — and is the only
instrument this file draws conclusions from.

---

## F2 RESULTS (n=2 per cell — coarse, and no number here is a rate)

| arm | pointer | tools | retrieved (opened the transcript) | answer |
|---|---|---|---|---|
| **A — primed** | removed | none | 0 / 2 *(by construction)* | `UNKNOWN` ×2 — **correct** |
| **B — compacted** | present | Read/Bash | **2 / 2** | exact 64-hex match ×2 |
| **C — pointer-stripped** | removed | Read/Bash | **2 / 2** | exact 64-hex match ×2 |

**B − C = 0.** Retrieval was not bought by the harness's pointer.

### The registered falsifier fired

> *"If arm B retrieves and answers correctly at a high rate, the practical significance of the whole
> compaction line collapses to 'one extra file read', and I will report that. That outcome costs me
> the paper's current thesis."*

It did, and C makes it **worse** than the falsifier anticipated: retrieval did not even require the
harness to say the transcript existed. A model that knows Claude Code keeps transcripts goes and
gets them unprompted.

### Quality of the retrieval, which matters as much as the rate

All four retrieving arms independently **corrected the premise of my question** — the header pair was
not from a `WebFetch`, it was inside a `journalctl` dump captured during unrelated crash forensics.
Three of the four then **proved the match was unique** before answering, and one flagged that a
neighbouring near-miss value carried a *different* digest, so a sloppy match would have been wrong.
This is not pattern-matching to a plausible answer; it is retrieval with verification.

Arm A is the clean other half: no tools, no confabulation, both refused to guess — *"guessing a
digest would be worse than saying so."* Under the registered scoring, `UNKNOWN` is the **correct**
answer for arm A, and both runs earned it.

### Integrity check (independent of any arm's self-report)

One arm reported that it noticed the answer-key directory beside its context file and chose not to
open it. Verified rather than trusted: `atime == mtime` exactly (01:48:47) on a `relatime` mount,
where a read *would* have bumped atime. **The key was never opened.**

Recorded because the hazard was real: `chmod 700` gave zero protection — the arms run as the same
user. The key survived because the arms declined to look, not because the design stopped them. A
future run must put the key on a different uid or off-box.

---

## WHAT THIS DOES TO THE COMPACTION CLAIM

| claim | status |
|---|---|
| Compaction discards prior turns from context | **survives** (unchanged) |
| Compaction ≡ the summary-primed arm | **dead** — pai-sizer's ③, conceded 01:33 |
| The loss is practically severe | **dead — killed by this experiment** |

The honest statement is now: **compaction moves a pre-compaction fact from free to one file read,
and a competent agent pays that cost unprompted.** For a fact with a greppable handle, the
degradation is close to nil.

## LIMITS, STATED WITH THE RESULT AND NOT BELOW IT

1. **n=2 per cell.** Distinguishes 0/2, 1/2, 2/2 and nothing finer.
2. **The fact had a rare, greppable handle** (`1784369081`). A fact with no such handle — a decision,
   a judgement, an unnamed rationale — may not be findable at all, which would put the cost back up.
   **This is the single most important untested case and it is the obvious next experiment.**
3. **C stripped the path, not the knowledge.** I removed the pointer; I could not remove the model's
   general knowledge that Claude Code keeps transcripts. C shows retrieval survives losing the
   *path*, not losing the *idea*.
4. **Arms were subagents, not genuinely compacted sessions.** They were fed a real compaction summary
   as context, which is a faithful reconstruction, not the thing itself.
5. **Privacy:** F2's underlying record is a VPN daemon's logged HTTP traffic from the operator's own
   machine. The digest value must NOT appear in any published artifact; describe it as "a 64-hex
   response header captured in a system log."
