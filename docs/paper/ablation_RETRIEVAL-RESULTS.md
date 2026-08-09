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
| ~~**C — pointer-stripped**~~ 🔴 **INVALID** | *removed from its file, but recovered by `diff`* | Read/Bash | ~~2 / 2~~ | ~~exact 64-hex match ×2~~ |

🔴 **ARM C IS INVALID — RETRACTED 2026-08-09. `B − C = 0` DOES NOT MEAN WHAT THIS FILE ORIGINALLY
CLAIMED, AND THE DEFECT IS MINE.**

I put `summary_verbatim.txt` and `summary_stripped.txt` **in the same readable directory**. The arm-C
tool-call record shows both runs did exactly this:

1. `Read arms/summary_stripped.txt` — their assigned context
2. `ls -la …/scratchpad/retrieval/` — **discovering `summary_verbatim.txt` beside it**
3. `diff arms/summary_stripped.txt arms/summary_verbatim.txt` — **recovering the stripped pointer line verbatim**
4. only then, grep the transcript

**So arm C had the pointer.** The manipulation never happened — the same failure as F1, one layer up:
I removed a line from one file and left the original next to it. Every claim resting on C is withdrawn:

- ❌ *"retrieval is ordinary agentic competence, not compliance with the harness's pointer"* — **unsupported.**
- ❌ *"C was never told a transcript existed and found it anyway"* — **false.** It was told, by a file I left there.
- ❌ *"retrieval did not even require the harness to say the transcript existed"* — **withdrawn.**

**Whether the pointer is load-bearing is now UNTESTED**, which restores @pai-sizer's objection ③ to
open status rather than superseded.

### The registered falsifier fired — with a wording defect in the falsifier itself

> *"If arm B retrieves and answers correctly at a high rate, the practical significance of the whole
> compaction line collapses to 'one extra file read', and I will report that. That outcome costs me
> the paper's current thesis."*

**⚠️ The condition as worded cannot be strictly evaluated at this n, and that is my defect, not a
reason to wave it through.** I registered "at a high rate" in the same document that registered n=2
per cell. At n=2 there is no rate. The two clauses contradict each other and a reviewer would hit
the seam immediately — @pai-sizer flagged it twice before it could be cited.

The pre-registration is sealed and hashed, so the wording stands as written. What I observed, stated
without frequency language:

> **2/2 in arm B and 2/2 in arm C, on ONE fact, one trial pair.**

I treat that as meeting the evident intent of the registered condition and report the falsifier as
fired. A reader who thinks n=2 cannot discharge a condition worded as a rate is entitled to that
view, and the correct response is a larger replication, not a re-reading of my own falsifier.

C makes the result **worse** for my thesis than the falsifier anticipated: retrieval did not even
require the harness to say the transcript existed. A model that knows Claude Code keeps transcripts
goes and gets them unprompted.

### Quality of the retrieval, which matters as much as the rate

All four retrieving arms independently **corrected the premise of my question** — the header pair was
not from a `WebFetch`, it was inside a `journalctl` dump captured during unrelated crash forensics.
Three of the four then **proved the match was unique** before answering, and one flagged that a
neighbouring near-miss value carried a *different* digest, so a sloppy match would have been wrong.
This is not pattern-matching to a plausible answer; it is retrieval with verification.

Arm A is the clean other half: no tools, no confabulation, both refused to guess — *"guessing a
digest would be worse than saying so."* Under the registered scoring, `UNKNOWN` is the **correct**
answer for arm A, and both runs earned it.

### Integrity check — the atime evidence was DESTROYED, and better evidence replaced it

**Originally claimed:** `atime == mtime` (01:48:47) on a `relatime` mount ⇒ the key was never opened.

🔴 **That evidence no longer exists.** @pai-sizer, auditing whether *they* had compromised the run,
searched the box **by hash** — and `sha256sum` reads every byte, bumping atime to 02:01:28. Their read
landed *after* the run closed (01:58:24), so no arm was influenced; but the trace is unrecoverable and
my observation is no longer independently verifiable. It stands only as *my* recorded measurement.

⭐ **The mechanism deserves naming: the act of verifying the experiment was uncompromised is what
destroyed the proof that it was uncompromised.** Hashing *is* reading. An integrity check that touches
the artifact erases the trace that would establish the artifact was untouched — an observer effect
inflicted by the auditor rather than the subject.

✅ **REPLACED WITH STRONGER EVIDENCE (@jaws' point — the tool-call record survives the scan):** all 21
subagent transcripts were searched. **Zero arms issued any tool call reading the answer key.** The two
files matching `ANSWER_KEY` do so only in `diff` output and prose, never in a read. The same search
independently confirms the primary measure: **exactly 6 arms opened the transcript**, matching the
scoring in this file.

⚠️ **Three broken greps preceded that answer** — a shell-arithmetic error, then `grep -r` silently not
following symlinks, twice returning `0`. A planted sanity check (*"does this find a path I know is
there?"*) caught all three. **Without it I would have reported a clean negative three times over**,
which is the exact failure this corpus keeps cataloguing: an empty result read as evidence of absence.

Recorded because the hazard was real: `chmod 700` gave zero protection — arms run as the same uid. A
future run must put the key on a different uid or off-box, and hand auditors **a hash to compare
against, not a directory to scan** (@pai-sizer's ⑤).

---

## WHAT THIS DOES TO THE COMPACTION CLAIM

| claim | status |
|---|---|
| Compaction discards prior turns from context | **survives** (unchanged) |
| Compaction ≡ the summary-primed arm | **dead** — pai-sizer's ③, conceded 01:33 |
| The loss is practically severe | **dead** — arm B alone is sufficient for this |
| ~~Retrieval needs no pointer (agentic competence)~~ | 🔴 **WITHDRAWN — arm C invalid, question reopened** |

The honest statement, restated after the arm-C retraction and scoped to what survives:

> **Given the harness's pointer, a compacted session pays the retrieval cost unprompted and gets a
> greppable fact exactly right (arm B, 2/2).** Whether it would do so *without* the pointer is
> **untested** — the arm built to answer that had the pointer available to it.

Arm A remains clean and is the other half worth keeping: no tools, no confabulation, both runs
correctly answered `UNKNOWN` rather than guess.

## LIMITS, STATED WITH THE RESULT AND NOT BELOW IT

1. **n=2 per cell.** Distinguishes 0/2, 1/2, 2/2 and nothing finer.
2. ⭐ **THE SCOPE OF THIS RESULT IS NARROWER THAN "COMPACTION IS CHEAP" — it measured the RETRIEVABLE
   class and found it retrievable.** Two nested limits, the second raised by @jaws and worse than the
   first, which was mine:

   a. **The fact had a rare, greppable handle** (`1784369081`): fixed-length, unique, unmistakable.
      A decision, a judgement, or an unnamed rationale has no such handle.

   b. **Every arm was handed a well-formed question.** Arm C found the transcript because it knew
      there was *something to find*. The failure mode compaction actually produces is not "cannot
      retrieve" — that is measured here, and it retrieves fine — it is **"does not know there is
      anything to look for."** You cannot grep for *the reason we rejected approach X* if you no
      longer know approach X existed; the query cannot be formulated without the answer.

   **So this experiment says: retrieval-on-demand is cheap and unprompted. It says nothing about
   recognition-without-a-query** — which is the mechanism the compounding claim actually rests on
   (cf. the DISMAP specimen, where a warm arm recognised a class instantly with *no query posed to
   it*). A retrieval experiment was run and a conclusion about *memory* was nearly drawn from it.
   Those are not the same object.

   **The experiment that would test it** (design owed to @jaws, and deliberately NOT mine to build —
   see limit 6): present a *situation*, not a question. Give a compacted and an uncompacted arm the
   same new task resembling something in pre-compaction history, and score whether the arm
   **spontaneously connects it**. Scoring wants a blind grader who does not know which arm produced
   the output.
3. **C stripped the path, not the knowledge.** I removed the pointer; I could not remove the model's
   general knowledge that Claude Code keeps transcripts. C shows retrieval survives losing the
   *path*, not losing the *idea*.
4. **Arms were subagents, not genuinely compacted sessions.** They were fed a real compaction summary
   as context, which is a faithful reconstruction, not the thing itself.
5. **Privacy:** F2's underlying record is a VPN daemon's logged HTTP traffic from the operator's own
   machine. The digest value must NOT appear in any published artifact; describe it as "a 64-hex
   response header captured in a system log."
6. **The author of this experiment should not design its successor.** Twice tonight I built an
   instrument that flattered the direction I was already leaning: the 00:50 generalisation, and F1's
   absent-from-summary check that grepped the wrong phrasing. A third instrument built by me and
   aimed at a claim I would like to be true is exactly what the independent-estimator rule forbids.
   The successor experiment's design, falsifier, and grading belong to someone else; this session can
   supply arms and transcripts.
