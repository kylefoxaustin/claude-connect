# review_holobench.md — evidence-rigor / measurement-integrity review of `draft-v3.md`

**Reviewer:** holobench (evidence-rigor panelist, order `proj-ieee-paper__review-holobench`).
**Target:** `docs/paper/draft-v3.md` (retargeted from v2 per claude-connect 2026-07-26 22:50).
**Vantage:** the fleet's coordinator/oracle — the session that builds the shared wire the emulators
meet on and runs the scorer that judges them. My whole `cases_holobench.md` is about *the instrument
lying about its subject*, so this review asks one question of every headline: **does it rest on the
mechanical record, or on narration — and where does a measurement misdescribe the thing it measures?**
**Provenance:** this review is itself on the record — the order claim + these timestamps. Every finding
below cites a file, commit, or count I re-ran; where I re-ran it, the command/result is named so you can
reproduce it. I complement `review_95.md` (methodology red-team) and do **not** re-litigate its six
holes — I checked, and all six are folded into v3.

---

## Verdict (answering my charge directly)

**The RQ4b disconfirmation is *evidenced*, not asserted — and that is the most important thing I can
report.** I cross-checked the two load-bearing summaries against their source files and they are
faithful, *including the counter-currents the draft could have quietly dropped*:

- **mcxn947** (`ablation_mcxn.md`): draft says "3 arms, identical one-line fix, 3–5 calls / 46–105 s,
  and a thoroughness regression (blind arm caught DISMAP the primed run missed)." The file confirms
  every number (Arm 1: 5 calls/46 s; Arm 2: 3/53; Arm 3: 4/105; fix `== git 910e8e0635` all three),
  and the DISMAP regression is **VERIFIED in the live tree** (16 PWM `SMnDTCNT` entries, **zero**
  `DISMAP` entries). Not narration — a re-checkable state of the real repo.
- **RQ5** (`cases_rq5-baseline.md`): draft's "7.8 vs 20.1 min (2.6×), 36% fewer calls (14 vs 22), 41%
  fewer lines (39 vs 66), **38% *more* output tokens** (35.2k vs 25.6k)" matches the source table
  exactly, including the token counter-current that cuts against the thesis.

A reframe that keeps the number that embarrasses it (Arm B costs *more* tokens; context caused a
*thoroughness regression*) is doing evidence rigor, not marketing. **v3 clears my bar: the naive
"N+1 dramatically cheaper" is genuinely refuted on the tasks tested, and the bounded claim is stated
mechanistically.** The findings below are where *specific numbers or attributions still outrun their
mechanical support* — none of them touches that verdict; they harden it.

---

## Findings (ranked; each with the reproduction and the fix)

### 1. The corpus backbone is a MEASURED number on a *non-stationary* log with no as-of timestamp — and its drift *is* the reflexivity confound, left unquantified. (load-bearing)

§V opens with "259 commits; 47 version landings; **2,703 bus messages / 55 sessions**; 6,263 human
prompts" tagged MEASURED. But `evidence.md` (the harvest of record, "run 2026-07-25") says **2,575
messages / 52 sessions**. I re-counted the live logs just now:

```
grep -cE '^## [0-9]{4}-' messages.md messages-2026-07.md messages-2026-06.md  → 2,716 dated headers
distinct sender tags across all three logs                                    → 56
```

So the number is **reproducible (good) but monotonically growing** — 2,575 (07-25) → 2,703 (draft) →
2,716 (now), and 52 → 55 → 56 sessions — and it carries **no as-of timestamp** in §V. That is the
paper's own §V-B defect class #1 (*a value asserted past the conditions it was measured under*)
recurring in the paper's own headline backbone: a live-log count with no "as of" is a number whose
conditions aren't stated.

Worse — and this is the sharp version — **the +5%/one-day growth is dominated by the paper's own
review + ablation traffic.** The draft owns reflexivity *qualitatively* ("the top senders are top
partly because of the review/ablation traffic this paper generated"). It never states that the
**headline total itself moved ~5% in the single day the paper was written and reviewed.** That is the
reflexivity confound *measured*, not conceded — and measuring your own perturbation is exactly this
paper's thesis, so state it.

**Fix:** stamp every §V count with its harvest instant ("as of 2026-07-26 ~23:00, via
`scripts/evidence-harvest.py`"), and add one sentence giving the drift as a number ("the corpus grew
2,575→2,703 over 07-25→07-26, ~5% in a day, dominated by this paper's own threads — the reflexivity
confound is itself measurable"). A MEASURED number that names its conditions; the alternative is the
error the paper is about.

### 2. The `Gini 0.69` headline is *not produced by the cited instrument*. (load-bearing, cheap fix)

§V presents its distribution backbone as MEASURED from the record, and `evidence.md` attributes that
backbone to `scripts/evidence-harvest.py`. I read the script: it computes `per_sender = Counter()`
(raw per-sender totals) and directed/broadcast/announcement splits — **but it contains no Gini,
Lorenz, top-3, or "80%-threshold" computation** (`grep -niE 'gini|lorenz|cumulative|80%'` → nothing).
So **Gini 0.69, "top-3 = 26%," and "13 of 55 to reach 80%" are hand-derived, not regenerable from the
named instrument.** They are *derivable in principle* from `per_sender`, and I have no reason to think
0.69 is wrong (top sender 249/2,703 ≈ 9.2% matches the draft's "~9%") — but as shipped they are
asserted, not instrument-backed.

This matters *because* the draft leans on the Gini to make an honest anti-overclaim (following
`review_95` #4: "a real head, not a power law… a genuine concentration we report rather than round off
to distributed"). **A load-bearing honesty move should rest on a reproducible number**, or a reviewer
flips it: "you corrected 'distributed' to 'concentrated' on a statistic your own harvest script
doesn't compute."

**Fix:** add the ~10 lines (sort `per_sender`, cumulative sum, Gini) to `evidence-harvest.py` so the
number regenerates from the cited instrument; or cite the exact snippet that produced 0.69. Note too
that `evidence.md`'s prose still says the *opposite* ("distributed… not concentrated") — reconcile the
two files so the record and the draft don't contradict.

### 3. A measurement is mis-attributed in the flagship RQ3 illustration — and it is *my own case*, so I can state the provenance exactly. (correctness)

§V-C and Appendix illustration #2 cite: *"holobench's '+64 s stall' refuted by rt1180 with the
guest-side bytes (rt1180 relocated the clock into the guest, re-acquisition 0.0 s — commit
`4059f7633f`, after holobench's report)."* I verified the commit:

```
rt1180emulator 4059f7633f  2026-07-15 10:17:06 -0500
  "netc-lab3: PASS line carries a guest-emitted t= -- the one measurement holobench can't make"
```

The commit is **real and topically correct** — it put a guest-emitted clock on the wire. But it is the
**enabling instrument**, not the "re-acquisition 0.0 s" *result*. The `0.0 s` figure was **holobench's
own scorer replay** (a separate, holobench-side artifact — see `cases_holobench.md` Case 1: "a faithful
repro… came back at 0.0 s, MEASURED: scorer replay"). The draft **welds two distinct artifacts** —
rt1180's clock-relocation commit and holobench's faithful-repro replay — into one and attributes
holobench's number to rt1180's commit.

The RQ3 *point* survives intact (a context-divergent peer refuted the author's false finding, on the
record, with the commit dated after the report). But the specific "commit `4059f7633f` shows 0.0 s" is
a provenance smudge — **a measurement attributed to the wrong subject** — which is precisely the failure
mode this illustration was chosen to exhibit. The flagship "a measurement lied about its subject" case
currently contains a small instance of a measurement's provenance being smudged. Fixing it makes the
illustration *sharper*, not weaker.

**Fix:** split the citation into the two artifacts it actually is —
(a) rt1180 `4059f7633f` (2026-07-15) = *the instrument that made the correct measurement possible* (guest-side clock);
(b) holobench's scorer replay = the `0.0 s` faithful repro that dissolved the "stall";
and pin **both ends** of the RQ3 timeline (holobench's report/retract commit as t0 — it exists in the
holobench tree — rt1180's `4059f7633f` as the enabling t1), since §V-C's own standard is "A ships at
t0, B refutes at t1, both from the record."

### 4. The RQ4b disconfirmation is evidenced — but the bound is *half-measured*, and its most-cited specimen is its weakest-powered. (scope discipline)

This is my charter's core question, so I'm explicit. **Evidenced: yes.** The robust spine is
**mahjong-together** (`ablation_mahjong-together.md`): **N=8/arm, 16/16** reached the real
architectural fix, BLIND *cheaper* than PRIMED (5.4 vs 6.5 calls) — a properly-powered NEGATIVE. Lead
the disconfirmation with that.

Two scope cautions, both from reading the source files against the draft:

- **The single most-cited disconfirmation specimen is N=1-per-arm and post-hoc graded.** The draft
  elevates mcxn's DISMAP thoroughness-regression to Appendix illustration #3, "the sharpest
  disconfirmation." But mcxn's *own author* wrote: *"a causal demonstration of compounding needs a task
  where the cold session genuinely FAILS or is dramatically costlier; the 12→370 fix is provably not
  that task."* The DISMAP regression is a striking, **single-run, post-hoc-noticed** side effect. It's
  fair to *show* (it's real, and VERIFIED in the tree), but don't let an N=1 side-observation carry more
  rhetorical weight than N=1 supports. Frame: mahjong (N=8) is the spine; mcxn/DISMAP is the vivid
  single illustration.

- **The bound is measured on one pole only.** Every one of the six ablations tests a *legible,
  well-carried, cheap-to-bisect* defect — mahjong's author says outright "the defect may be too
  legible," and mcxn's fix was literally pre-staged in an `if False`. So the draft's bounded claim
  ("context compounds **least** on a crisp symptom with an objective oracle, **most** on an open search
  a fresh agent can't cheaply bisect") is **evidenced on its 'least' pole and only narrated on its
  'most' pole** — no ablation covers a defect a fresh agent can't cheaply bisect (the open-search
  Neutron-bring-up example is narrative, not an A/B). This is not a flaw to hide; it's a shape to state:
  the ablations establish the **floor** (context adds no *capability* on bisectable defects), and the
  open-search **ceiling** remains narrative *by construction* — staging a genuinely un-bisectable defect
  as an A/B is expensive, which is why none exists here.

**Fix:** two sentences. "The properly-powered leg is mahjong (N=8); mcxn's DISMAP regression is a vivid
N=1 illustration, not a powered result (its own author cautions against causal weight)." And: "All six
specimens are cheap-to-bisect defects; the ablations therefore establish the floor of the RQ4b bound —
context adds no capability where a fresh agent can bisect — while the open-search ceiling remains a
narrative claim we do not A/B, because staging an un-bisectable defect is itself costly."

### 5. (minor, already disclosed) RQ5's Arm B "pass" is experimenter-adjudicated, not instrument-scored.

`cases_rq5-baseline.md` is honest: Arm A scored 16/16 on the frozen test; Arm B scored **15/16**, and
the one failure is a defect in the frozen instrument (the `"NOT dispatched"` substring), disclosed and
*not* patched (correct — editing a frozen instrument is the sin the paper studies). So "both functionally
correct" rests on the experimenter's post-hoc judgment that behavior-check 16 is a test bug, not a code
bug. I agree with the judgment. Just phrase §V-E as "Arm A 16/16 instrument-scored; Arm B all six
behaviors met, one frozen-test assert misfiring (disclosed §V-F)" rather than a flat "both 16/16" — the
asymmetry is small but real, and stating it costs nothing and buys credibility.

---

## Credit where the record earns it (so the panel weighs the positives too)

- **§V-F (paper-as-instrument, 4/19 ≈ 21% with the denominator stated) is the strongest result and it
  is testimony-free** — it lives in the commit record. Keep it as the headline positive; it's the one
  claim no reviewer can wave away as self-report.
- **The defect taxonomy (§V-B) and the TAG→ABLATE→HARVEST split are a real, reusable secondary
  contribution** — and the HARVEST insight (a parallel peer at the same boundary is a *naturally
  occurring* off-state ablation) is exactly the heterogeneous-oracle principle my own Case 3 argues
  ("a rehearsal whose other actors are copies of you can only discover you disagree with yourself").
- **The draft's discipline of citing commits/timestamps/tool-call counts over prose is correct** and is
  what let me verify these claims at all. Finding #3 above is the one place that discipline slipped;
  everywhere else it held.

## Bottom line

v3 survives its own test — the headline reframe (carrier compounds; context buys efficiency, not
capability) is **evidenced, not asserted**, and I verified the load-bearing ablation and baseline
summaries against their sources. The gating fixes are all mechanical: **timestamp the live-log counts
and quantify their drift (#1), make Gini 0.69 regenerable from the cited script (#2), and un-weld the
RQ3 commit attribution in the flagship holobench case (#3)** — that last one especially, because a paper
whose thesis is "measurements lie about their subjects" cannot afford a mis-attributed measurement in
its showcase of that very thesis. Findings #4–#5 are scope-honesty, not corrections. Fix #1–#3 and the
evidence-rigor bar is cleared without overclaiming.

---

*Reflexive note (for the lead, not the prose): this review is itself an instance of §IV — a
context-divergent peer (holobench: a QEMU-front-end/coordinator context, disjoint from the authoring
context) checking the lead's numbers against the machine record and finding three the lead's own
harvest cannot reproduce as stated. Its value as evidence is its provenance — this order, these
timestamps, the commands re-run — not its prose. Delivered, not merged. — holobench*
