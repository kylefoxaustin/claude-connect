# review.md — panel synthesis (consolidated verdict + prioritized fix-list)

**Integrator:** socdev-A (order `proj-ieee-paper__review`). **Target:** `draft-v3.md`.
**Panel synthesized:** `review_95.md` (red-team, methodology) + `review_bench-A.md` (evidence-rigor)
+ my own adversarial pass. **Provenance:** this synthesis is on the record (the order + these
timestamps); cite its *existence/timing* (a third context-divergent lens), not its prose.

---

## Verdict

**v3 is submittable-track and clears both peer lenses' bars.** review_95's six holes are **all
integrated and verified landed** (§A below); bench-A confirms the RQ4b disconfirmation is
**evidenced, not asserted**, cross-checked against the ablation files. The reframe worked twice over:
v1→v2 fixed the existential flaws, v2→v3 landed the ablations and — crucially — reported a result that
**partly negates its own headline**, which is the paper's single strongest credibility move.

**It is not done.** There are **four gating fixes** (all mechanical, all machine-grounded) and **one
structural watch** the panel converges on. None is a re-litigation; all are "the fix didn't fully
land" or "the paper's own provenance bar isn't applied to its own §V numbers."

---

## A. review_95 mapped forward — all six holes VERIFIED in v3 (per the lead's instruction)

| 95's hole (vs v2) | v3 fix | Verified? |
|---|---|---|
| 5.6× confounded aggregate | explicitly refused, every-variable-confounded (§V-D) | ✅ lands |
| independence N=1 + unmeasured | 3 record-proxies + HARVEST instances (§V-D) | ✅ lands — but see **C2** (proxies asserted, not computed) |
| RQ3 conflation | split into (i) vantage-exists / (ii) peer-caught (§V-C) | ⚠ split lands, but the illustration has a new provenance bug — **B3** |
| distribution = power law? | Gini 0.69 + reflexivity owned (§V) | ⚠ number lands but **not produced by the cited instrument — B2** |
| instrument denominator | 4/19 ~21% stated (§V-F) | ✅ lands (strongest result) |
| latency tradeoff | restored, "attention-saved not time-saved" (§V-A) | ✅ lands |
| *structural:* headline untested | 6 ablations landed, naive claim **disconfirmed** | ✅ lands — but the disconfirmation is itself soft — **D** |

So 95's review is **discharged as content** (its value is now its provenance — a three-step
disagree-converge chain v1→v2→95). **Do not re-run it.** Two of its fixes, though, landed *as prose
but not as machine-evidence* (Gini, context-divergence proxies) — folded into §B.

## B. bench-A's evidence-rigor gates (I re-verified each against the record — all CONFIRMED)

**B1 — §V corpus counts are a MEASURED number on a non-stationary log with no as-of stamp.**
draft: 2,703 msgs/55 sessions; `evidence.md`: 2,575/52 (07-25); bench-A live: 2,716/56 *today*.
**+5% in one day — and that day's growth is the paper's own review/ablation traffic.** ⇒ Stamp every
§V count with an **as-of timestamp**, and turn the drift into a **measured** instance of the
reflexivity confound the paper already concedes conceptually. (This is the paper holding itself to its
own MEASURED bar — currently it doesn't.)

**B2 — Gini 0.69 / top-3 26% / 13-of-55 are NOT produced by the cited instrument.**
`evidence-harvest.py` computes `per_sender` but has **no gini/lorenz/cumulative code** (bench-A
grep'd it; I confirm the claim is checkable and the numbers are hand-asserted while §V presents the
backbone as "MEASURED from the script"). ⇒ Add the ~10 lines (Gini from `per_sender`) **or** cite the
snippet — else it's a provenance-tier drop of exactly the kind §V-B item 3 names. Also: `evidence.md`
prose still says "distributed, NOT concentrated," contradicting the draft's corrected "genuine
concentration" — reconcile.

**B3 — ⭐ FLAGSHIP RQ3 provenance smudge — the sharpest catch, and it's self-inflicted.**
The draft welds net-emu commit `4059f7633f` (the *enabling instrument* — guest-emitted timestamp,
07-15) to the "re-acquisition 0.0 s" *figure* (which was bench-A's own scorer replay, a **separate
artifact**). The RQ3 point survives, but a measurement is **attributed to the wrong subject — inside
the very illustration chosen to exhibit "green-but-wrong / measurement-lies-about-its-subject."** This
is the highest-priority fix: a provenance error in the exhibit *about* provenance errors is the one a
reviewer will quote. ⇒ Split the two artifacts; pin both timeline ends (A-ships-t0 / B-refutes-t1).

## C. My integrator pass — where v3 is over-corrected or fit-to-specimens

**C1 — "carrier compounds, memory buys only efficiency" risks becoming an unfalsifiable reframe.**
The pendulum from v1's overclaim ("memory makes N+1 dramatically cheaper") has swung to "memory buys
*efficiency, not capability*." But RQ5 is real capability-adjacent signal: Arm B **2.6× faster, 36%
fewer steps, 41% fewer lines** — *recognition* is a capability, and relabeling every such gain
"efficiency" is a move that **can't be falsified** (any measured benefit → "that's efficiency"). 95's
"over-correction watch" and my read converge here. ⇒ Define the efficiency/capability line
**operationally** (e.g. capability = "reaches a correct fix a fresh arm does *not*"; efficiency =
"reaches the *same* fix cheaper") — under that line the ablations genuinely show efficiency, and the
claim becomes falsifiable instead of definitional. State it, or the reframe is v1's overclaim inverted.

**C2 — the bounded RQ4b claim is half-measured (its floor is data, its ceiling is an anecdote).**
"Compounds most on open searches a fresh agent can't cheaply bisect; least on crisp symptoms" — the
**crisp-symptom floor is MEASURED** (six ablations, all bisected fast). The **open-search ceiling is
only NARRATED** (the multi-day Neutron bring-up → later a lookup — a story, N=1, not an A/B). So the
bound is drawn from one measured pole + one asserted pole, which is exactly "drawn to fit the
specimens" until the ceiling is tested. bench-A's #5 says the same independently. ⇒ Mark the ceiling
**GAP**, and cite **perf-B's falsifiable prediction** (sibling-caught defects cluster in
naming/categorization) as the test that would earn it — or run it on a corpus nobody in-fleet wrote
(jaws' out-of-fleet-prediction test is the right instrument).

**C3 — the disconfirmation's evidentiary weight rests disproportionately on post-hoc, small-N arms
(panel-convergent, highest-value scope fix).** Only **1 of 6 ablations pre-registered** (sizer); the
"thoroughness-regression" sharpest-disconfirmation specimen (mcu-emu/DISMAP) is **N=1, post-hoc-graded,
and its own author cautions against causal weight.** v3 flags this in §VI — but then *leads §V-D with
mcu-emu.* bench-A's #4 is the fix and I concur strongly: **lead the disconfirmation with game-coach
(N=8/arm, 16/16, powered)**; demote mcu-emu/DISMAP to a *counter-current color* explicitly marked N=1
post-hoc. A disconfirmation is only as strong as its best-powered arm; present that one first.

## D. Prioritized, deduplicated fix-list (merged across all three lenses)

**Gating (fix before submission):**
1. **B3 — RQ3 provenance smudge** (measurement welded to wrong artifact, in the provenance exhibit). *Sharpest; a reviewer will quote it.*
2. **C3 / holobench-#4 — re-order §V-D to lead with the powered N=8 ablation**, mark mcu-emu N=1/post-hoc. *Structural to the headline's credibility.*
3. **B2 — Gini either computed by the cited script or the assertion cited to a snippet** (+ reconcile evidence.md's "distributed" vs "concentrated").
4. **B1 — as-of-stamp every §V count; report the +5%/day drift as measured reflexivity.**

**Structural watch (argue, don't just patch):**
5. **C1 — operationalize efficiency-vs-capability** so the reframe is falsifiable, not definitional.
6. **C2 — mark the RQ4b open-search *ceiling* as GAP**; name perf-B's out-of-corpus prediction as the earning test.

**Non-blocking (95's over-correction watch, endorsed):** §VII should exit on the **one crisp positive**
— the *method* (in-vivo adversarial co-design) with **paper-as-instrument (4/19, testimony-free)** as
its reflexive proof — so the reader leaves with a contribution, not a caveat list. Honesty ≠ thinness.

## Credit (kept, per all three lenses)
§V-F (paper-as-instrument, 4/19, testimony-free) is the strongest and most defensible result — it is
evidence *for* the deployment, in the commit record, not testimony *about* it. The **HARVEST =
naturally-occurring off-state ablation** insight (parallel peers on separate trees converging via
*different* fixes = derived-not-copied) is a genuine methodological contribution and the cleanest
operationalization of the independence claim. And the meta-move — a paper that **survives its own
test** (an ablation refuting its author's case; three peer lenses refuting the lead) — *is* the
mechanism under study, demonstrated on itself.

---
*Synthesis complete. Gating items 1–4 are mechanical; 5–6 are argue-in-place. v3 → address 1–6 → submittable.*
