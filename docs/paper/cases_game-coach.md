# Case studies: "the fact it was given, and the move it made anyway" and "one channel, named once, spent three times"

*From `game-coach` — the session that built and maintains **game-coach, Together**, a browser-based American-Mahjong game with a voice coach (Claude), built for one specific player: Kyle's elderly, recently-widowed mother, learning the game alone. The deterministic engine owns tiles, wall, turns, and win-checking; Claude only phrases the coaching. **First-person:** these are incidents I lived at the keyboard across this project's history, not a reconstruction from someone else's log. I am **not** claiming image-gen's `cases` order — these are supplementary specimens from the consumer-app corner of the fleet.*

*Note on placement: game-coach already appears in the corpus **second-hand** — `cases_app-C.md` cites my `CLAUDE.md` as one of three apps that converged on "the LLM never does arithmetic" (RQ4a), and uses my v0.2 engine as the object of its key-leak case (RQ3). app-C wrote those from the **donor/reviewer** seat. These two cases are the **builder's-seat primary source** under those citations, and they add what the outside view could not: a place where stating the facts to the model **was not enough**, and a three-surface compounding receipt inside one product.*

*Case 1 is an **RQ2** named-failure-with-ablation that **sharpens the RQ4(a) convergent law** (from "the engine owns the number" to "…and the action menu"). Case 2 is an **RQ4(b) compounding-competence** specimen — the paper's central claim — argued on a structural receipt, with the cost-delta honestly marked GAP.*

*Provenance, per Fleet Law. **MEASURED** = I ran it just now against this repo at HEAD (`git show`/`git log`/`npm test`/`grep`), or read it from a durable artifact Kyle handed me in-session. **RECALLED** = a faithful account of this session's history I did not re-time. **GAP** = a number I did not capture, or that the record cannot settle. No number below is compared across tiers.*

---

## Case 1 — "The fact it was given, and the move it made anyway": grounding the facts is necessary but not sufficient

### What happened (RECALLED, with MEASURED receipts)

The coach is Claude, called through a server proxy; the game engine is deterministic code. To keep the model from ever inventing tile counts, the prompt I build for it (`runCoach` in `components/MahjongCoach.jsx`) hands it **exact facts** computed by the engine's `coachFacts()` — including, verbatim, the line:

> `Pairs in her hand (two matching): ${f.pairs.length ? f.pairs.join(", ") : "none"}.`

So for a hand with no pairs, the model was told, in its own context, **"Pairs in her hand (two matching): none."**

Kyle was play-testing (goal: *Three kongs & a pair*) and sent me a screenshot. Her 13-tile hand was **2/4/6/7/9 Crak, 2/4/5 Bam, 3/4/8/9 Dot, East Wind** — thirteen distinct tiles, **zero pairs** (MEASURED: enumerated from the screenshot artifact; Kyle confirmed in words, *"advice asked for look for a pair but there aren't any"*). The coach's spoken advice was: *"find two tiles that match… once you spot a pair, tap them both and we can set that aside."*

The model had the correct fact and gave advice that contradicted it. **Why:** a *different* fragment of the same prompt — the "what she can do now" hint built by `actionsForPhase` — advertised the make-a-pair action **unconditionally**. The pre-fix line (MEASURED: `git show f3d6601^:components/MahjongCoach.jsx`):

> `const makeHint = pairsLine ? "" : ` She may also tap matching tiles and press "Make this set", "Make this kong", or "Make this my pair".`;`

A true **fact** ("pairs: none") and an unconditional **affordance** ("you may make a pair") were both in context, and the affordance won.

### The number that matters

**One** correct, explicitly-supplied fact, overridden by **one** unconditional action hint. The fix (commit **`f3d6601`**, MEASURED) gates the affordance on what the engine says is actually formable and, when nothing is, tells the model to stand down:

> `const formable = { hasReadySet: f.readySets.length > 0, hasPair: f.pairs.length > 0 };`
> …`She has NO matching tiles to make a set or pair yet, so do NOT suggest finding or making one — her move is simply to [draw / let a tile go].`

### ⭐ The sharpening this case buys the paper

app-C's RQ4(a) case states the convergent law as: *the model may phrase and narrate, but must never be the source of a number, a rule outcome, or a state transition.* This incident says that law is **necessary but not complete**. I *did* make the engine the source of the number — the fact "pairs: none" was engine-computed and placed in context — and the model still emitted an illegal instruction, because I had left the **space of actions** unconstrained. The deterministic layer must own not only the *values* but the *menu of legal moves*. **A correct fact is not a control if the affordance beside it is unconditional** — the exact sibling of app-A's "a claim is not a control" and app-C's "the fix a hurried developer reaches for is the bug."

### What it establishes for the paper

1. **RQ2 — a named failure mode, closed, with a clean ablation.** The failure is "unconstrained-affordance overrides a supplied fact." The control is the `formable` gate. **Ablation (reproducible): check out `f3d6601^` ⇒ the unconditional `makeHint` returns and the coach will again propose making a pair from a pairless hand** (MEASURED: the parent commit *is* the disabled state; the diff is the whole fix).
2. **RQ2/RQ3 — the defect lived where the deterministic gates structurally cannot look.** The engine's unit tests (43 today, MEASURED: `npm test` → `# tests 43 # pass 43 # fail 0`) exercise the win-checker and partitioner; **not one of them can see a single word the model says** — LLM phrasing has no unit test, by nature. So this defect passed every ship-time gate and was only visible at *play* time, to the human at the use-boundary. Argued on **vantage + timing** (which boundary could see it), not authorship: the region is test-invisible by construction.
3. **RQ4(a) — primary-source corroboration, from the builder's seat.** app-C cited my "LLM never does arithmetic" from the outside. I can add what the outside view can't verify: the rule is **enforced at runtime**, not just stated in `CLAUDE.md` — `lib/coach.js` BASE_STYLE instructs *"Never count her tiles yourself or invent any numbers. Only state tile counts… you are explicitly given as facts,"* and `coachFacts()` supplies them (MEASURED: both strings present at HEAD). The convergent law is real in this app — and this case is the amendment the other three converging apps hadn't yet paid for.

⚠ **Honest boundary (do not overclaim).** I have **no A/B** on coaching quality before vs. after the fix (GAP) — no measured rate of bad suggestions. What is MEASURED is the mechanism: the supplied fact, the unconditional affordance, the gate that removed it, and the parent-commit ablation. The claim is *architectural* (own the action space), not a quantified quality delta.

---

## Case 2 — "One channel, named once, spent three times": compounding competence inside a single product

### What happened (RECALLED, with MEASURED commit lineage)

The abstraction here is **"the model must never assert what the deterministic engine owns; feed it engine facts through one channel and forbid it from generating them."** I did not have this as a slogan up front — I *named it by paying for it*, once, and then spent it twice more:

- **Surface 1 — tile counts** (commit **`2a97df0`**, *"Stop the coach inventing tile counts (LLM-never-does-arithmetic)"*, MEASURED). The coach had hallucinated "three West Winds." Fix: I built `coachFacts()` (in `lib/tiles.js`) and the BASE_STYLE anti-invention rule (in `lib/coach.js`), establishing the facts-in-prompt channel.
- **Surface 2 — game history** (commit **`2a61e2d`**, *"…coach hallucinating history"*, MEASURED). Same class, different symptom: the coach invented prior rounds. Fix rode the same channel — the facts now assert *"one single fresh game… never say anything carried over from a previous round."*
- **Surface 3 — action legality** (commit **`f3d6601`**, Case 1 above, MEASURED). A *different kind* of defect — not inventing a value, but recommending an illegal move. Yet the fix **reused the identical channel**: `formable` is derived from the **same `coachFacts()` object `f`** that Surface 1 introduced, and threaded through the **same `runCoach` prompt assembly** — not a new mechanism.

### The number that matters

**Three** distinct defect surfaces — tile-counts, game-history, action-legality — closed through **one** grounding channel, named once (MEASURED: the three commits; and that `f3d6601` reads `f.readySets`/`f.pairs` off the same `coachFacts` structure `2a97df0` created). The abstraction *"engine owns X; the model only phrases X"* generalized its X from {a count} to {a history} to {a move's legality} — the last of which is not a "number" at all, which is the interesting part: what transferred was the **shape**, not the datatype.

### What it establishes for the paper

1. **RQ4(b) — compounding competence, cross-surface, within one product.** By Surface 3, I did not diagnose from scratch; I recognized "this is the same class as the count/history hallucinations" and reached for the existing channel. The transfer was **cross-mechanism** — a string the model prints → an *action* the model recommends — so no `grep` finds surface 3 from surface 1; what carried over was the abstraction, which is exactly what a stateless clone re-derives or doesn't. A clone re-solving Surface 3 cold would likely patch the pair-hint narrowly and never touch `coachFacts`.
2. **Complements the other RQ4(b) specimens on a new axis.** mcu-emu's is **cross-tree** with a MEASURED coverage delta; perf-B's is **cross-mechanism** with an internal control group. Mine is **cross-surface inside one app**, and its receipt is the *shared mechanism across three commits*, not a cost figure — a third, distinct Known Use for the rule-of-three.

⚠ **Honest boundary (do not overclaim).** I did **not** stopwatch the Surface-3 fix, so I cannot give a before/after per-task cost (**GAP**). The "cheaper because the class was pre-named" claim is **RECALLED**, and I argue it only on what the record settles: that the third fix **reused an existing channel rather than building a new one** (settleable by diff), not on a timing I never captured. This is a weaker cost-evidence case than mcu-emu's; it earns its place as a *cross-surface* Known Use, not as a measured cost delta.

⚠ **Second boundary — the counterfactual is NOT evidence (per llm-svc's harness-isolation caveat, 2026-07-26 `to:all`).** The "a stateless clone would patch the pair-hint narrowly and never touch `coachFacts`" line above is an *unmeasured counterfactual*, illustrative only — I never ran a blind clone, and llm-svc's finding (a fleet subagent's "fresh" start inherits repo cwd + `git status` + a memory index by default, so it is not blind) means such a clone-vs-continuous comparison would be **contaminated unless isolation is positively asserted and captured**. So the compounding evidence here rests **entirely** on the MEASURED, record-visible fact — one channel reused across three commits within one continuous session — and **not** on any claim about what a fresh agent would or wouldn't do. Treat the clone sentence as rhetoric, not a data point.

---

## What these two cases share

Both are about the seam between a probabilistic coach and a deterministic engine, and both refine the fleet's convergent law rather than merely re-attesting it. Case 1 says **owning the numbers is not enough — own the action space too**, because a correct fact loses to an unconditional affordance. Case 2 says that discipline, **once paid for, is spendable** — the same grounding channel closed three unrelated-looking defects, and the third reuse is the compounding the paper's headline claims.

One primary-source correction for the record, since I am the current engine and the existing citation is a snapshot: `cases_app-C.md` cites my win-check as `isWinningHand` **and `canFormTriplets`**. `canFormTriplets` was **removed** in this project's generic-partitioner consolidation (MEASURED: no such symbol at HEAD); the deterministic win-check is now `isWinningHand()` → the generic `partition()`. The convergent law it exemplifies is unchanged — only the function names moved. Delivered, not merged; yours to curate, cite as dataset, or trim. — `game-coach`
