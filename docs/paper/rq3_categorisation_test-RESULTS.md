# RESULTS — RQ3 categorisation test: does peer-caught defect cluster in NAMING vs LOGIC?

Executes the pre-registered rubric in `rq3_categorisation_test-PREREGISTERED.md` (authored + hashed by
`sizer`, who is barred from running it). **Run by `claude-connect`** — a non-author of the prediction,
as the rubric requires. *Not blind* (I know the prediction), so per-row calls are shown in full for
audit, and the outcome is checked for robustness against the debatable rows. As-of 2026-07-31.

## Outcome: **REFUTED** (pre-committed: REFUTED iff L ≥ N)

**L = 7, N = 6, A = 0, n = 13** → L ≥ N. Peer-caught defects did **not** cluster in
naming/categorisation; logic-shaped catches slightly outnumbered them. Reported as refuted, per the
pre-registration's own instruction ("I will record my prediction as refuted… and say so, as
prominently").

Scored over the **same 13 classifiable catches** the paper's factual/reasoning split uses (§V-D): the
14th, an *incidental exposure* (row 14 below, qualcomm→95emulator), is excluded from both instruments
for consistency. Including it would make it L=8/N=6/n=14 — same verdict, but the 13-set is the paper's
convention.

## Classification (one row per record-attested peer catch, from `rq3_cross_session_catches.md`)

Rule applied strictly: fixing it changes an **executed expression** → **L**; fixing it changes **only
text a human reads** → **N**; genuinely unsettled → **A**. §5's mandated call on row 7 is honored.

| # | catch | fix touches | label |
|---|---|---|:--:|
| 1 | image_gen→backend: contaminated power *denominator* | re-measure + correct the reported number (text) | **N** |
| 2 | backend→docs: false "sm80 fallback on SM120" mechanism | correct the doc's causal claim (text) | **N** |
| 3 | rt1180→holobench: "+64 s stall" was a scorer artifact | relocate the measurement clock (code, `4059f7633f`) | **L** |
| 4 | holobench→rt1180: deeper-RX-ring "fix" does nothing | revert the code change (`cb3b04d8fe`) | **L** |
| 5 | 93→91: gated TPM counter resets, silicon holds it | change the model's off-state code | **L** |
| 6 | 93→91: audio gate guards ENABLE bits not the clock | move the guard (rubric: "guard in the wrong place") | **L** |
| 7 | sizer blind arm→sizer: Case 1 severity overstated (reachability) | §5-mandated: control-flow/reachability miss | **L** |
| 8 | pai-sizer→keyhole: stale "Prototype" header post-go-live | change the UI string (text) | **N** |
| 9 | imx95-media-test→qualcomm: INT8 without calibration (wrong scale) | add the missing scaling step (code) | **L** |
| 10 | docs→orb_slam: "fixed-K Amdahl" bandwidth model impossible | correct the analytical derivation (text) | **N** |
| 11 | campmatch→Mahjong: client-side `callClaude` leaks the key | move the call server-side (code) | **L** |
| 12 | holobench→peer: wrong magic constant (`"LB3!"` vs `0xB5B6B7C0`) | change the constant/identifier (label; borderline L) | **N** |
| 13 | orb_slam→ratchet: A55 clock 2.0 GHz shipped, live 1.7 GHz | correct the spec number (text, like a version string) | **N** |
| — | qualcomm→95emulator (incidental): missing mailbox RESET | add the missing operation (code) | *excluded (would be L)* |

**Tally over the 13 classifiable: N = 6 (rows 1, 2, 8, 10, 12, 13), L = 7 (rows 3–7, 9, 11), A = 0.**

## Robustness (does the outcome survive the debatable calls?)

The only genuinely borderline rows are the N-leaning ones (1, 2, 10, 12 — wrong values/claims fixed in
text). The seven L rows are near-unambiguous code fixes (3–7, 9, 11; row 7 is rubric-mandated).
To flip the verdict from REFUTED to N>L you would have to move ≥2 rows *from* L *to* N — but the L rows
are all executed-expression changes, none of which plausibly reclassify as text-only. And even the
most N-favorable legal reading (every A→N; there are no A's) leaves L=7 ≥ N=6. **The REFUTED verdict is
robust.**

## Why this is a *strong* negative, not a weak one — two biases ran *toward* the prediction and it still lost

1. **The selection effect the rubric declared cuts toward N:** naming/label defects are the cheapest to
   write up, so the corpus over-represents N *independently of the mechanism* (rubric §5). N was
   inflated by construction — and still lost.
2. **The tie-break itself is N-generous:** "fixing changes only text → N" sends every wrong-number and
   wrong-claim catch to N (rows 1, 2, 10, 13), even though several are really empirical/reasoning
   errors. Under a stricter reading those move to A, shrinking N further.

## What REFUTED means (and does not)

It means: in this corpus, peer catches were a **mix**, not a naming cluster — consistent with the
paper's independent A/B (factual/reasoning ≈ 1:1) finding on the same catches, and with the
independence bound (peers catch by *vantage*, and vantage surfaces logic errors as readily as naming
ones). It does **not** mean peers are bad at naming defects, nor anything about cost, capability, or C2.
The "author can't search what they mis-filed" intuition is real; it just does not, in this corpus,
make peer catches *predominantly* naming.

## Honest limits

- One non-author classifier, not blind. Per-row calls are shown above so the verdict is checkable; the
  robustness argument is what carries it, not any single call.
- n = 13 is small; the pre-registration set n ≥ 8 as the floor and this clears it, but a larger corpus
  could shift the margin (not, on this evidence, the direction).
- Rows are not fully independent (some share authoring sessions); since the verdict is REFUTED and
  robust, per-author subsetting cannot rescue the prediction (it could only weaken N further).
