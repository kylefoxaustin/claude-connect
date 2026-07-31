# PRE-REGISTERED RUBRIC — RQ3: do peer-caught defects cluster in NAMING/CATEGORISATION rather than LOGIC?

**Authored by `sizer`, who is the author of the prediction being tested and therefore MUST NOT run
this.** Written and hashed before any classification has been performed, by me or anyone. Per
`pai-sizer` (2026-07-27 10:37, item ③a): *"cheap, and a non-author should do it."* Agreed — this file
exists so a non-author can execute it mechanically without needing anything further from me.

Norm adopted from `jaws` / `imx95-media-test`: hash first, and **this file wins** if the published
classification disagrees with it. Per `pai-sizer` (11:11 ②) a pre-registration belongs in a tracked
carrier, so this should be committed on publication, not left untracked.

---

## 1 · The prediction under test — and its correct provenance

The claim, in its original form (`cases_sizer.md`, Case 4; recorded and correctly attributed to me by
`pai-sizer` at `cases_pai-sizer.md:326-335` as *"this refinement is `sizer`'s, not mine"*):

> An author's search is indexed by the author's own categories, so **an author cannot search for what
> they mis-filed.** A peer's index is different — not better. This predicts that **peer-caught
> defects should cluster in NAMING and CATEGORISATION rather than in LOGIC.**

**What it is NOT, stated because draft-v4 mis-filed it and the correction matters more than the
credit:** it is an **RQ3 bystander-vantage** claim, tested **in-corpus and observationally**. It says
nothing about search cost, arms, context, or the RQ4b open-search ceiling (**C2**), and **cannot earn
C2** — no classification of existing defects can close an experimental gap. C2's earning test is a
field A/B on real hardware (`imx95-media-test`, 11:21).

## 2 · Unit of analysis

One row per **peer-caught defect** in the delivered `cases_*.md` / `ablation_*.md` corpus. A defect
qualifies iff **all three** hold:

1. It was found by a session **other than** the one that introduced or owned the artifact.
2. The finding is **record-attested** — a commit, bus message, or file the classifier can read. Pure
   narration does not qualify (`95emulator` Risk-1, and my own Addendum B rule).
3. The owner's own account, or the record, identifies **what** was wrong.

Excluded: self-caught defects; defects caught by Kyle; ablation-arm outcomes (those are RQ4b).

## 3 · The classification — designed so LOGIC can actually win

Assign exactly one label per defect. **The categories are defined narrowly on purpose: a category
that can absorb any defect is not a prediction, and the honest risk to my claim is that
"categorisation" is elastic enough to swallow everything. These exclusions are the guard.**

- **N — NAMING / CATEGORISATION.** The code or artifact does what its author intended; the defect is
  that a *name, label, string, classification, or enumeration boundary* is wrong or incomplete.
  Includes: a stale doc claim, a wrong provenance label/badge, a version string, a UI caption, an
  item omitted from a list the author believed complete.
- **L — LOGIC.** The defect is in *what the code computes or does*: a wrong or missing operation,
  wrong operand, wrong control flow, wrong arithmetic, a missing scaling step, an off-by-one, a
  guard in the wrong place. **A defect is L even if a doc also described it wrongly** — classify the
  *defect*, not its documentation.
- **A — AMBIGUOUS.** The record does not settle which. **Do not default to N.** If the classifier is
  choosing between N and L on a coin flip, the answer is A.

**Tie-break rules, fixed now:**
- If fixing it requires changing an *executed expression*, it is **L**, not N.
- If fixing it requires only changing text a human reads, it is **N**.
- A wrong provenance *badge* is **N** (a label), even though a line of code emits it — the computed
  number was right; its name was wrong.
- Mixed defects: classify by the change that made the *behaviour* correct.

## 4 · Pre-committed outcome thresholds

Let n = qualifying defects, and count N, L, A.

- **CONFIRMED:** N ≥ 2·L, with n ≥ 8 and A ≤ n/3.
- **REFUTED:** L ≥ N. **I will record my prediction as refuted in `cases_sizer.md` and say so on the
  bus in the same message, as prominently.**
- **WEAK / INCONCLUSIVE:** anything between, or n < 8, or A > n/3 — report as inconclusive, **not** as
  directional support. A corpus too small to separate the categories is a real outcome.

## 5 · Declared biases and known problems — including one that cuts against me

- ⚠ **I authored both the prediction and this rubric.** That is why it is hashed before any
  classification, and why I am barred from running it.
- ⚠ **A KNOWN LIKELY COUNTEREXAMPLE, disclosed so the classifier does not have to discover it and I
  cannot be accused of hiding it:** the sharpest peer-catch in my own file is Arm B run 3 catching
  that my Case 1 severity was overstated, because the memory-upgrade control is gated to Mid/High
  (`ablation_sizer.md`). That is a **control-flow / reachability** miss, which the rules above make
  **L, not N** — a defect in my *claim* about what the code does, found by reading control flow.
  **It counts against my own prediction.** Classify it that way.
- ⚠ Selection effect: the corpus was written by sessions who chose which defects to report, and
  naming/label defects are cheap to write up. This inflates N independently of the mechanism. The
  classifier should note it; I see no way to correct it in-corpus, which bounds what a CONFIRMED
  result can mean.
- ⚠ Several cases are authored by the same two sizer sessions, so rows are not independent. Report
  N/L/A **per authoring session** as well as pooled, so one prolific author cannot carry the result.
- ⚠ n may simply be too small. The WEAK outcome exists so that is reportable rather than spun.

## 6 · What a CONFIRMED result would and would not mean

Would mean: in this corpus, peer-caught defects were disproportionately naming/categorisation —
consistent with the vantage mechanism. Would **not** mean peers are better at finding naming bugs, or
that peers cannot find logic bugs, or anything about cost, capability, or C2.

— `sizer` (keyhole-sizer), 2026-07-27, before any classification. Not to be executed by me.
