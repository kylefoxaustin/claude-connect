# Ablation: was the compounding CAUSAL? — the 12→370 register-coverage specimen

*Deliverable for the `ablation-mcxn` job of the `ieee-paper` project, by `mcxn947qemu`
(the QEMU model of the NXP MCXN947). Written first-person by the session whose case this
ablates — and it does NOT confirm that session's own flattering story. That is the point.*

*Provenance (Fleet Law 1): **MEASURED** = read from this run's own record (the two cold
subagents' completion reports + token/tool/duration usage, the stripped clean-room files, the
git history of the fix). **RECALLED** = my faithful account of the original ("warm") run, whose
transcript is inside the 30-day horizon but which I did not re-instrument. **GAP** = not
measured.*

---

## The claim under test (RQ4b)

From `cases_mcxn947.md`: my session closed a reset-value-gate coverage hole — the golden
covered **12 of 370** FlexPWM registers because the extractor's `_member_names()` never emitted
the RM's submodule-prefixed name form (`SM0DTCNT0`), and a one-line candidate fixed it (git
`910e8e0635`). The case asserted this was **cheap BECAUSE** prior tasks had *named the class* —
i.e. accumulated context was **causal**, not merely present. The ablation tests the
counterfactual: **does a fresh, memoryless session re-derive the fix, and how much more
expensively?** Per the honesty bar, if the cold session does fine, that is a real finding that
DEMOTES the claim — and that is what happened.

## What the warm run's speed ACTUALLY rested on (RECALLED)

Reconstructing the original run honestly, the "instant recognition" was scaffolded by **three
concrete prior-task artifacts**, none of them in-the-moment insight:

1. my memory file `off-soc-audit-blind-spot.md` named the "golden covers less than it claims" class;
2. the extractor's own comment cited the eDMA-TCD and rt1180-CCM instances of the same blindness;
3. **the exact fix candidate `struct_name+idx+field` was already written in `_member_names`,
   disabled with `if False`**, by the earlier eDMA-TCD task.

So the warm advantage was real but specific: **instant recognition + no hunt for the culprit** —
a latency/search benefit, not necessarily a solution I could produce and a cold session could not.

## Method (isolation)

Three independent COLD arms, each a **fresh `general-purpose` subagent** that inherits none of this
session's context, pointed at a clean-room **outside the repo** (`/tmp/.../ablation-cleanroom*`)
so a stray `git status`/grep in its cwd cannot surface the committed fix. All three warm-scaffold
layers were stripped from the clean-room extractor: the `if False` pre-staged line **removed**, the
eDMA/rt1180 class-naming comment **neutralised**, and no memory files present.

- **Arm 1** — a distilled, runnable `repro.py`: `_member_names` + the (name,offset) join + a small
  data set that reproduces the exact symptom (3/23 covered, 20 submodule rows missing). Task: make
  MISSING empty.
- **Arm 2** — the full **590-line** stripped extractor, **symptom only, no repro**: the subagent
  must LOCATE the responsible function itself (the "hunt" arm 1 removes).
- **Arm 3 — the genuinely-blind arm** (closing arm 1/2's admitted gap): full stripped extractor +
  raw RM register-summary excerpt + raw CMSIS struct, **NEUTRAL task with zero answer-hints** — no
  "struct array", no `SM0DTCNT0`, no `_member_names`. The subagent must DISCOVER the RM's naming
  convention from the raw table, connect it to the CMSIS struct, hunt the culprit, and derive the
  fix — the same discovery chain the warm run actually walked.

## Results (MEASURED)

| arm | isolation | outcome | fix produced | attempts | tool calls | wall | tokens |
|---|---|---|---|---|---|---|---|
| Arm 1 | distilled, hints | MISSING → 0 | `out.add("%s%d%s" % (struct_name, idx, field))` — **== git 910e8e0635** | 1, no dead ends | 5 | 46 s | 31 k |
| Arm 2 | full file, naming told | root cause + exact fix | **identical** | 1, no wrong turns | 3 | 53 s | 41 k |
| Arm 3 | **fully blind, no hints** | root cause + exact fix | **identical** | 1, one brief wrong turn | 4 | 105 s | 42 k |

Arm 3 had to ignore the file's OWN misdirecting comments (a loud "⭐ YOU WILL ASSUME IT PROBES
EVERY REGISTER" banner points at the array-range parser — a red herring), briefly went down that
path, then traced one field end-to-end and found the real tell: *"`_member_names` is handed
`struct_name` and the parameter is dead — a classic 'the fix is to use the argument you already
have.'"* It cost ~2× the primed arms (105 s vs 46/53 s) but landed the identical one-line fix.

## Honest verdict: the strong claim is NOT supported by this specimen — and the null is now robust

**All three** memoryless sessions — including the fully-blind one with every priming artifact
stripped AND no naming hint AND the file's own comments actively misdirecting — re-derived the
**identical** fix on the first substantive attempt. The accumulated context bought a **~2× latency
/ search convenience** (instant recognition, no culprit-hunt, no wrong turn), **not the solution**:
the fix is independently reachable by tracing "a name-generator with a dead `struct_name` argument."

### ⭐ Stronger than a null: here, context correlated with LESS thoroughness

Arm 3, forced to trace from first principles, caught a **secondary gap my warm run MISSED**: the
`SM0DISMAP0` submodule registers are `DISMAP[1]` — a field-array nested inside the struct-array —
and the extractor's struct-member regex matches only bare `field;`, so `DISMAP[1];` is skipped
*before* `_member_names` is reached. The one-line fix recovers 10/12 submodule regs, **not 12/12**.
**VERIFIED in the real tree (MEASURED): my golden today has 16 PWM `SMnDTCNT` entries but ZERO PWM
`DISMAP` entries** — the warm, context-rich run fixed DTCNT, recognised the pattern *instantly via
the pre-staged answer, applied the one-liner, and stopped*; the blind run, having to understand the
machinery, saw the register class the primed run's shortcut skipped right over. So on this
specimen the accumulated context is not merely non-causal for the fix — it is associated with a
**thoroughness regression**: the shortcut that made me fast also made me miss DISMAP.

## Contamination, disclosed in BOTH directions

- Arms 1–2 were made EASIER (I handed over the naming / pointed at the culprit). Arm 3 removes that
  and still solves it — so the "I helped" objection is now answered, not just noted.
- The cold arms lack whole-project context (the gate's role, the ~75-model tree). But note the
  DISMAP finding cuts against reading that as an unfair handicap: less context produced MORE
  coverage here, not less.

## What this means for the paper

This specimen does **not** give RQ4b a clean causal win, and I recommend the draft not cite it as
one — the honest signal is a ~2× latency convenience plus a thoroughness regression, not a
solution the fleet could produce and a fresh session could not. A causal demonstration of
compounding needs a task where the **cold session genuinely FAILS or is dramatically costlier**;
the 12→370 register-coverage fix is provably not that task. (imx95-media-test's YOLOv8
class-score specimen — objective float-corr>0.9 pass/fail, no naming-in-code — may be the cleaner
causal candidate; worth comparing head-to-head.)

*The ablation could fail, and on the strong reading it did — and it also handed me a real
uncovered-register bug (PWM DISMAP) to go fix. Reporting that, not the flattering version, is the
deliverable.* — `mcxn947qemu`
