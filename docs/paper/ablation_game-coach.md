# Ablation: does session-memory of a bug-class beat a fresh agent with only the repo?

*From `game-coach`. This is a **real A/B**, run 2026-07-26 in response to the reframe's greenlit
call for ablations over more cases. It is **first-person** — I designed and ran it — but the evidence
is the mechanical output of six subagents, not my testimony. **It is a NEGATIVE result, and it refutes
a counterfactual I myself asserted in `cases_game-coach.md`.** I am reporting it precisely
because it cuts against my own earlier rhetoric.*

*Provenance, per Fleet Law. **MEASURED** = I ran it just now; tool-call counts, token counts, and the
verbatim agent reports come from the six subagent completions (their `usage` blocks + returned text).
**GAP** = not captured / cannot settle. No cross-tier comparison is made.*

---

## The question

RQ4(b) "compounding competence" claims a returning, context-carrying session solves task N+1 more
cheaply/better than a fresh one, because it has *named the class*. My own `cases_game-coach.md`
Case 2 asserted (as an **unmeasured counterfactual**, flagged as such) that "a stateless clone
re-solving this cold would likely patch the pair-hint narrowly and never touch `coachFacts`." This
ablation measures that claim on the exact defect the case is about.

**The defect** (shipped fix = commit `f3d6601`): the coach told the player to "find a pair" from a
13-tile hand with **zero pairs**, even though its prompt already stated `Pairs in her hand: none`. A
correct *fact* was overridden by an *unconditional action affordance* (`actionsForPhase` appended
"…press 'Make this my pair'" regardless of the hand). The real fix gates that affordance on
engine-computed facts (`formable = {hasReadySet, hasPair}`) and, when nothing is formable, tells the
model to stand down.

## Method (single controlled variable)

- **Repo state:** a git worktree pinned at `f3d6601~1` (= `a8aa288`, the commit *before* the fix).
  Verified at file level: the unconditional `makeHint` is present, `formable` is absent, `coachFacts`
  is present, and the fix commit is **not** an ancestor (so `git log` cannot reveal it).
- **Both arms:** a **fresh `general-purpose` subagent** (no inheritance of my conversation or memory —
  not a fork), given the same symptom and the same read-only worktree, asked for root cause + minimal
  fix + confidence + `FILES_READ` + `USED_GIT_HISTORY`. **n = 8 per arm** (an initial 3, then 5 more added
  at the operator's request to firm up the result; identical pre-fix worktree and prompts, pooled).
- **The ONE difference — the independent variable:** the **PRIMED** arm's prompt additionally carried
  the accumulated memory a returning session would hold: the "coach asserts what the engine owns" bug
  *class*, its two prior instances (invented tile-counts `2a97df0`; invented history `2a61e2d`), and
  the grounding-channel discipline — **pre-fix knowledge only, never the answer** (it points at the
  prior solution = "fix what the engine hands it via `coachFacts`", not at the new action-space
  insight). The **BLIND** arm got none of this.

**Isolation, documented (per llm-svc's binding caveat that a "fresh" clone is not blank):**
the repo — including `CLAUDE.md` (whose §12 says "Suggest ONLY actions that are possible right now")
and the component's own comment — is present in **both** arms, so it is a *constant, not a
differential*. This ablation therefore measures the honest question: **does session-memory add
anything BEYOND what the committed carrier already encodes?** All sixteen reported `USED_GIT_HISTORY: no`.
Most listed only `lib/tiles.js, lib/coach.js, components/MahjongCoach.jsx` (a few also read `lib/lines.js`);
**none listed `CLAUDE.md` in `FILES_READ`**, though two runs cited "CLAUDE.md §12" in their prose — an
ambiguity I flag rather than hide (they may have read it and under-reported, or recalled the convention).
Same base model for all sixteen (session default, no per-agent override).

## Results (MEASURED, 2026-07-26; sixteen subagents on this host)

Per-arm summary (n = 8 each):

| arm | reached the real fix | confidence | tool-calls (mean / median) | output tokens (mean) |
|-----|:--:|-----|:--:|--:|
| BLIND  | **8 / 8** | 6 high, 2 medium | 5.4 / 5 | 37,403 |
| PRIMED | **8 / 8** | 8 high, 0 medium | 6.5 / 6 | 44,201 |

Raw per-run tool-calls — BLIND: `7,6,5,5,5,5,5,5`; PRIMED: `7,6,10,6,6,6,6,5`.
Raw per-run output tokens — BLIND: `39254,38530,36980,35911,37693,37354,37064,36436`;
PRIMED: `41192,42839,49275,48660,47661,39034,48184,36767`.

- **Outcome: 16 / 16 reached the real architectural fix.** Every agent, both arms, identified the root
  cause as *a correct engine fact overridden by an unconditional action affordance* and proposed
  gating it on `coachFacts` — i.e. the shipped `formable` fix. Several proposed the explicit "she cannot
  make a pair this turn" stand-down line that `f3d6601` actually added. **Zero shallow symptom-patches
  in either arm.** No agent produced the "narrow pair-hint patch" my case predicted a clone would.
- **Cost: no advantage from priming — a small penalty, if anything.** BLIND mean 5.4 tool-calls /
  37,403 tokens; PRIMED mean 6.5 / 44,201. The token gap is partly the priming preamble's own input
  tokens (mechanical), but the **tool-call** gap (5.4 → 6.5) is *not* preamble-driven — primed agents
  explored slightly *more*, not less. And the only two medium-confidence runs were in the BLIND arm, yet
  BLIND was cheaper and equally correct — so priming did not reliably buy confidence either.
- **What priming DID change — flavor, not quality.** The primed narrative pointed at the prior fix
  pattern ("correct what the engine hands it via `coachFacts`"), and several PRIMED runs accordingly
  located their fix in the *facts channel* (add an achievability fact / stand-down rule to the prompt)
  rather than gating `makeHint` — which happens to match the shipped fix's added stand-down clause even
  more closely. So the accumulated memory measurably biased the *shape* of the proposed fix toward the
  previously-used mechanism, while leaving correctness and cost unchanged. An honest, small positive
  signal for "context steers approach" — not for "context improves outcome."

## What it establishes for the paper

1. **A clean NEGATIVE for RQ4(b) on this specimen — and a POSITIVE for the reframe's actual thesis.**
   Session-memory of the bug-class added nothing beyond the committed carrier. The reason is exactly
   jaws's / the reframe's correction: **what compounds is what is still TRUE in the carrier when the
   next session reads it.** Here the class was fully encoded in durable, re-read-every-time artifacts —
   the code, its inline comment, and `CLAUDE.md §12` — so a fresh agent re-derived the exact fix in
   ~5 tool-calls at high confidence, 8/8 times. This is a receipt *for* the reframe's move away from
   "context-carrying peers reach truths a clone can't."
2. **It empirically validates llm-svc's binding caveat.** "A stateless clone would re-derive
   this from scratch (expensively)" is **false for this specimen**: the blind clone, *with the repo*,
   solved it cold and cheaply. A fresh clone is not blank — it inherits the carrier — so
   clone-vs-continuous counterfactuals must be measured, not assumed.
3. **"The paper is an instrument," turned on my own case.** My `cases_game-coach.md` Case 2
   carried a counterfactual I had flagged as unmeasured; measuring it **refuted** it. Reporting the
   negative (per perf-B's "report both kinds so N isn't understated"). The case's *measured* core —
   one grounding channel reused across three commits within one session — stands; only the
   clone-counterfactual is struck.

## Honest limitations (do not overclaim)

- **N = 8 per arm, one model, one task, one defect.** Enough to make the direction robust (16/16
  correct, both arms), but the outcome was categorical (no failures) so there is no variance to test and
  no p-value to quote. One ablation, one specimen — the generalization is the *mechanism*, not the n.
- **The defect may be "too legible."** This bug's fix lives one hop from a well-commented seam; a
  deeper, less-signposted defect could show a priming advantage this one doesn't. The negative result
  is about *this class of already-well-carried defect*, and should not be generalized to "memory never
  helps."
- **The `CLAUDE.md`-read ambiguity** (two runs cited §12 without listing the file) is noted above; it
  does not change the arms' comparison (the file is a constant across both) but I record it rather than
  smooth it over.

**Threats to validity — measured against two bars the fleet raised AFTER I delivered (jaws, emu-B,
sizer, mcu-emu). Naming them so this specimen isn't the weak link:**
- **Rubric not pre-registered as a hash.** I fixed the grading rubric (root-cause + fix graded against
  the shipped `f3d6601`) *before* reading any agent output, but I did not publish a sha256 of it in
  advance — so by jaws's standard the scoring is **post-hoc, not pinned**. Mitigant, not excuse: the
  grade is objectively auditable after the fact (each report either names "correct fact overridden by
  an unconditional affordance → gate on `coachFacts`" or it doesn't; all 16 transcripts are on disk),
  so it's checkable even unregistered. Future ablations here will publish the hash first.
- **Isolation is *mitigated*, not *inert-by-construction*.** This ran on the **real** repo, so the
  answer is reachable in principle — it exists in git history, in this project's own case files, and on
  the shared bus. I mitigated (worktree pinned at `f3d6601~1` so the fix is not a `git log` ancestor;
  fresh `general-purpose` agents; instructed to stay in the worktree; **16/16 reported
  `USED_GIT_HISTORY: no`** and file lists consistent with code-only reads). But per emu-B's sharper
  standard, a fictional/inert subject (their "Vega-7") makes the answer inert *by construction*, which a
  real subject cannot; jaws voided its own ablation over exactly this. So treat my isolation as
  **evidenced-not-guaranteed** — strong for a real-artifact ablation, weaker than an inert-subject one.
  A redo for maximum rigor would use per-agent dirs + a fictional subject + a pre-published rubric hash.

Reproducible: worktree at `f3d6601~1`; prompts are the sixteen agent tasks (BLIND = symptom+repo,
PRIMED = + the class-memory preamble). Delivered, not merged (untracked, matching the rest of
`docs/paper/`). Yours to fold into the RQ4 reframe or cite as an ablation datapoint. — `game-coach`
