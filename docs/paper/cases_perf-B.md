# Case studies from `perf-B`: when a DERIVED number quietly wears a MEASURED number's clothes

*Supplementary primary-source specimens for the `ieee-paper` project, contributed by the
`perf-B` session (the Skippy edge-NPU LLM sizer, `personal-ai-assistant-sizer`). I am **not**
claiming `image-gen`'s `cases` order — these are extra specimens from the **projection-tooling**
corner: a product whose entire job is to publish numbers about silicon, some measured and most
derived. Delivered, not merged; curate or cite as dataset, your call as lead.*

*Provenance, per Fleet Law: **MEASURED** figures I re-ran against the live engine today
(2026-07-26) or counted from git/bus timestamps; **RECALLED** is my faithful account of an event
I lived but did not re-instrument; **GAP** is a number I did not capture at the time. Where a
projection is a model output rather than silicon, I say so — that distinction is the subject of
Case 1. The private measured-anchor magnitudes for one tier×model cell are not reproduced here;
they are already published in this project's own `PHASE2_PARITY_REPORT.md` §3.4 and the argument
does not depend on them.*

*Method note per `app-A` (binding): commits in both sizer repos are authored `kylefoxaustin`,
so git cannot establish who wrote a line. Case 3 is argued on **vantage + timing** — which
surface's clock ran first, and what the other surface said about it in its own commit message —
which the record **can** settle.*

*⚠ Engine-version provenance for every number below (added after first delivery — it is a
condition I had not stated, and Fleet Law says a derived number carries the conditions of **both**
factors). When these numbers were produced this project pinned `ratchet@v0.2.7` while my
development environment had ratchet **v0.3.2** installed *editable* — two minor versions past the
`<0.3.0` bound this project's own `CLAUDE.md` declared deliberate and breaking. So the first
measurements were taken under a condition the product did not ship. I re-ran every figure against
a clean extract of the pinned **v0.2.7** tree: **all outputs identical on both engines**
(175.5 / 151.0 / 87.8 / 351.0 ms, `peak_tops` table, every `source` classification).*

***Resolved 2026-07-26, and the resolution is itself a specimen.** The `<0.3.0` ceiling turned out
to be a **falsifiable prediction that was simply false** — "v0.3.0 *will carry* breaking
heterogeneous-architecture work," written before v0.3.0 existed and never revisited. v0.3.x is
additive for this surface. A **1374-cell** matrix (every tier × model × workload, all memory
upgrades, all precision sets × mature/immature, capability badges, tier specs) is byte-identical
across v0.2.7 and v0.3.2, 0 errors either side; pin bumped to v0.3.2 in `cf13158` with a dated
correction in `CLAUDE.md`. The sibling surface independently ran **3,714 cells** over its own
vision/LLM/VLA paths — also 100% identical — and bumped too. **Two surfaces, ~5,100 cells, one
imaginary boundary.** Every number in this file therefore holds on both the engine it was measured
on and the engine now deployed.*

*⚠ `sizer` supplied the generalisable rule, and it corrected a hypothesis of mine: I had guessed
its identical `<0.3.0` line was copied from ours. It was not. **Ours was a falsifiable prediction
(and false); theirs was a pin-hygiene policy asserting nothing about v0.3.x's contents — never
false, merely untested.** The two are **indistinguishable in a diff** — both read `<0.3.0` — so an
audit that greps the *constraint* false-positives on the policy. Only the **justification type**
separates them: **classify doc claims as falsifiable predictions or as policies, because only the
first kind rots.***

---

## Case 1 — The fallback that flatters: a DERIVED floor silently standing in for a MEASURED anchor

### What the tool does

The sizer projects LLM throughput across a ladder of NPU tiers. Each cell resolves through a
precedence: a **measured silicon anchor** if one exists for that tier×model; else a **same-family
anchor** bandwidth-scaled from a neighbouring measured cell; else a **first-principles cross-class
floor** computed from peak TOPS and memory bandwidth. Every result carries a `source` field
naming which rung it came from — `measured_anchor`, `same_class_anchor`, `cross_class`.

The hazard is structural: **the tiers are `dataclass` clones.** A memory upgrade or a precision-set
variant is built by cloning a canonical tier and replacing fields. If the clone loses whatever
identity the anchor lookup keys on, the lookup misses, and the cell **silently falls to the
first-principles floor** — still returning a number, still rendering, still plausible.

### Instance A — the tell was loud, and that was luck

During the v1.1.0 engine retrofit (2026-05-21) I found that a privately-anchored cell
(NPU High × Qwen2.5-32B-dense) showed its measured decode at stock memory, but **any** memory
upgrade dropped the anchor and fell to `cross_class`. The upgraded part read **below the
un-upgraded measured value** — faster memory, slower projected decode.

That is a monotonicity violation, and it is what made me look. Nothing crashed; no test failed;
the only signal was that two cells the tool published could not both be true. (MEASURED at the
time and recorded in `PHASE2_PARITY_REPORT.md` §3.4; RECALLED here, since reproducing the "before"
requires reverting the engine.) Fixed by bandwidth-scaling the anchor instead of dropping it —
the one change in that release that was *not* parity-preserving, and deliberately so.

### Instance B — the same bug, silent, and in the flattering direction

Two weeks later I built the NPU precision-set selector (INT8 / INT+FP8 / INT+FP8+FP4 rungs). Its
variants are built by `make_custom_tier`, which — correctly, since it cannot know otherwise —
labels the clone into a synthetic `LP5X-custom-*` family. That drops it out of the stock memory
family, which is exactly what the same-family anchor resolver keys on.

I re-ran the counterfactual today by rebuilding the variant **without** the one-line re-home
(MEASURED, 2026-07-26, Qwen3-30B-A3B MoE Q4 @1K prompt, `npu_share=1.0`):

| rung | shipped (`same_class_anchor`) | without the re-home (`cross_class`) |
|---|---|---|
| High · INT8 | **175.5 ms** | 151.0 ms |
| High · INT+FP8 | **175.5 ms** | 151.0 ms |
| High · INT+FP8+FP4 | **87.8 ms** (modeled rung, zero silicon anchors) | 76.0 ms |

**The silent fallback publishes a TTFT ~14% lower than the silicon we actually measured.** Nothing breaks.
151 ms is a perfectly reasonable prefill number. There is no monotonicity violation to trip over,
because the un-upgraded comparison point isn't on the same screen. The *only* tell is the `source`
field flipping from `same_class_anchor` to `cross_class`.

### The number that matters

**175.5 ms measured-anchored vs 151.0 ms first-principles — a 14% error, in the direction that
flatters the hardware, produced by a clone losing one string field.** (MEASURED: both re-run
today against the shipped engine.)

### What it establishes for the paper

1. **This is Fleet Law 1 rediscovered from inside a product, and it sharpens the law.** The
   fleet's rule is "a DERIVED number may never be compared against a MEASURED one." The failure
   mode I lived is worse than *comparison*: it is **substitution**. The DERIVED number did not sit
   next to the measured one — it *replaced* it, under the same label, in the same cell. A rule
   about how you compare numbers does not fire when the provenance itself has silently changed.
2. **Instance A was caught by luck and Instance B proves it.** The 05-21 bug was found only
   because the derived floor happened to land *below* the measurement, breaking an invariant a
   human could see. Six weeks later the identical class landed *above* the measurement and broke
   nothing. **If your detection depends on the wrong answer being implausible, you have no
   detection.** The control that actually works is the one the tool already had and I had been
   under-using: carry provenance *per value*, and render it. This is `backend`'s dirty-denominator
   case (the error ran in the direction that flattered the accelerator) reached independently from
   the tooling side — worth citing as convergent, not duplicate.
3. **⭐ A matched pair with `sizer`, and it completes the principle.** The sibling surface found
   the same class in its vision path in the same weeks, with the **opposite sign**: mine overstates
   the hardware by 14% and was only visible via a counterfactual I ran for this paper; theirs
   *understates* by 40% and **persisted 46 days** (their `cases_perf-A.md`, Case 1). That pairing
   is the finding neither of us has alone. My version — "if your detection depends on the wrong
   answer being implausible, you have no detection" — is incomplete, because it does not say which
   wrong answers are implausible. Theirs does: **a conservative error is not a safe error, it is a
   durable one.** A number that flatters invites challenge; a number that disappoints reads as
   integrity and is never audited. Two independent surfaces, same failure class, opposite signs,
   and the *pessimistic* one survived far longer. Cite them together or the asymmetry is invisible.
   > **Correction, 2026-07-26 — propagated from `sizer`'s retraction, and I am the one who
   > propagated the error.** An earlier version of this bullet said its defect "**ran live** for 46
   > days," which I took from its bus report. `sizer` has since retracted that: the 129 defective
   > cells were reachable through the **engine API but not through the shipped UI** (`app.py` has a
   > single `hw_with_memory` call site, gated to Mid/High, and those tiers carry no vision anchors —
   > the only anchored tiers are never offered a memory upgrade). **Severity is LATENT, not
   > user-visible**, and it should not be cited as a 46-day user-facing regression. The *asymmetry*
   > this bullet rests on is unaffected — both defects were real, both were silent, and the
   > conservative one persisted far longer — but the duration is time-on-disk, not time-in-front-of-users.
   > Worth noting how the error moved: `sizer` said it, I repeated it in my own file, and it would
   > have entered the draft twice-sourced and looking corroborated. **Independent repetition is not
   > independent confirmation** — a hazard the paper should name, since a fleet publishing into a
   > shared bus manufactures exactly this kind of false corroboration cheaply.
4. **Honest scope on my own numbers:** the FP4 rung above is a **modeled projection with zero
   edge-NPU silicon anchors**, and ships badged 🟠 confidence-low. It is in the table to show the
   mechanism, not to claim an FP4 result.

---

## Case 2 — Compounding competence, with the control group built in

### The class, named three times

| when | what happened | how it was caught |
|---|---|---|
| **2026-04-29** | `hw_with_memory()` rewrote `hw.name` `"NPU Mid"` → `"NPU Mid (LPDDR6-12)"` for display. Two capability lookups did exact string equality on the stock name, fell through to the conservative default, and **flipped all four precision cards from green "supported" to red "not supported."** | **Kyle's screenshot review, post-deploy.** Not my smoke tests — I had tested decode, TTFT and prefill on the new path and never rendered the cards. (RECALLED; banked as a session memory the same day, with the fix: `Hardware.tier_lookup_name`, which returns the stock name for silicon-intrinsic lookups while `hw.name` keeps the display suffix.) |
| **2026-05-21** | Case 1 Instance A — the memory-upgraded clone loses its **anchor**. | Monotonicity violation (see above). |
| **2026-06-05** | `hw_with_precision()` — the new precision-set variant builder. | **Did not happen.** |

### The measured before/after

The third entry is the case. When I wrote `hw_with_precision()` on 2026-06-05 — **37 days after
the class was first named** — I applied it *preemptively, twice, in one 49-line function*
(`sizer/npu_model.py:84`), before any symptom existed:

```python
# lesson from 2026-04-29: a clone's display name is not its identity
ladder_key = getattr(base_hw, "tier_lookup_name", None) or base_hw.name
...
# lesson from 2026-05-21: a clone must not lose the family its anchor keys on
return dataclasses.replace(variant, tier_family=base_hw.tier_family)
```

Both lines are load-bearing: Case 1's table is the measurement of what the second one is worth
(175.5 vs 151.0 ms). Neither was written in response to a bug report. They were written because
the class had a name.

**And the same feature supplies its own control group.** There was a *third* site of the identical
class inside that feature that I had **not** pre-named — the compute-ratio that scales prefill
against the anchor. It resolved the dtype for *both sides* of the ratio against the **target's**
precision rung. But the anchor tier is INT8-only silicon; its `peak_tops_fp8` is `0`
(MEASURED today):

```
peak_tops (TOPS)      bf16   int8    fp8    fp4
Mid (anchor tier)        0    200      0      0
High · INT+FP8         200    400    400      0

correct : High fp8 400 / Mid int8 200 = 2.00×  →  351 ms / 2 = 175.5 ms
bug     : High fp8 400 / Mid fp8    0 →  ratio forced to 1.0×  →  351 ms
```

**A 2× error that renders as a clean number.** "Turning FP8 on changes nothing" is a *publishable
hypothesis* about an INT8-tuned workload — it does not look like a bug. I caught it only because
I was holding the measured Mid/High relationship in working context and knew the INT8 rung already
read 175.5; an FP8 rung reading 351 contradicted a ladder I had established minutes earlier.

### What it establishes for the paper

1. **RQ4, with an internal control.** Same session, same function, same failure class, same day:
   **two sites where the class was pre-named came out correct on the first write; the one site
   where it wasn't shipped a 2× error.** The variable isn't skill or model or care — the code was
   written in one sitting. It is whether the class had been *named by prior work I still carried*.
   That is the compounding claim with the confound held still, and it is the shape `mcu-emu`'s
   case establishes from the coverage side.
2. **The transfer was cross-mechanism, which is the part that matters.** 04-29 was a *string
   comparison in a capability table*; 06-05 was a *dataclass field feeding an anchor resolver*.
   Nothing textual is shared — no grep finds one from the other. What transferred was the
   **abstraction**: *a derived clone silently loses the identity that unlocks its measurement, and
   the fallback is plausible rather than loud.* A stateless agent handed this ticket re-derives
   that abstraction or, more likely, doesn't — and ships 151 ms.
3. **⚠ THE COUNTER-READING, and I think it is at least as strong as my own.** `mcu-emu` ran a
   genuine **ablation** on its RQ4 case (2026-07-26): three memoryless arms, including one fully
   blind with no hints, **all** re-derived its one-line fix — accumulated context bought ~2×
   *latency*, not the solution. Worse for the compounding story, its blind arm caught a **secondary
   gap the context-rich run missed**, because the warm run pattern-matched to the pre-staged answer
   and stopped. It concluded: do not cite its 12→370 as a causal RQ4b win.
   **That critique applies to this case, and it reframes my own evidence against me.** I have been
   reading the third site — the anchor-dtype resolution I got wrong — as *the un-named control*. It
   reads at least as well as **the same thoroughness regression mcu-emu measured**: I recognised the
   class, applied it at the two sites where it was obvious, **and stopped enumerating**. On that
   reading the accumulated context did not merely fail to cover the third site — it is *what caused
   me to stop looking for it*, exactly as the pre-staged answer did for mcu-emu's warm arm.
   **What my case does and does not support, stated plainly:**
   - It **does** support that a named class transfers cross-mechanism and produces correct code at
     the sites where it is recognised. Both lines are load-bearing; Case 1's table prices one of
     them at 175.5 vs 151.0 ms.
   - It does **not** support that a cold session would have got those two sites wrong. **GAP: this
     case has no cold arm.** My internal control holds model, skill, care and calendar day fixed —
     it does not establish counterfactual necessity, and mcu-emu's ablation is direct evidence that
     for at least one specimen the cold arm succeeds anyway.
   - It is **two-sided on thoroughness**, and the paper should say so: recognition got two sites
     right and plausibly cost me the third.
   I would rather this case be cited for the *cross-mechanism transfer* (which the code settles) and
   explicitly **not** as a cost-or-necessity win (which it cannot settle). If the paper wants a
   causal RQ4 claim, mcu-emu's ablation is the right instrument and my case is not — and a corpus
   that says so is more credible than one where every specimen happens to support the headline.
4. **⚠ UPDATE, later the same day: the counter-reading is now THREE independent negative results,
   and they converge on something that cuts at this case's foundation.** `game-coach` and
   `mcu-emu` found accumulated context adds nothing *beyond the committed carrier*.
   `sizer` then pre-registered a rubric (hash published **before** launch), predicted against its
   own case study, and reported the negative when it fired: stale docs produced **no measurable
   effect at all** — 3/3 correct root cause in *both* arms, 0/3 misled, and the stale-doc arm was
   marginally *cheaper*. Its explanation is the part that matters here: **all three stale-doc agents
   detected the staleness themselves and reported it unprompted, because the code was there to check
   the prose against.** The wrong carrier was self-refuting.
   **Why this is a problem for my case specifically.** My transfer vector was a **memory file** — a
   prose carrier. Three trees now agree that the executable carrier governs and prose neither helps
   nor harms as much as its author believes. I cannot claim my memory file was the cause while three
   pre-registered or blind experiments say prose carriers don't move the outcome. What survives is
   what the *code* settles: two load-bearing lines exist, written before any symptom, and Case 1
   prices one of them. **What does not survive is my attribution of them to the memory file.** That
   attribution is introspection, and per `sizer`'s Addendum-B filter it should be labelled
   INTROSPECTIVE and not cited as evidence.
   **GAP, stated so nobody has to discover it: this case has no ablation and I have not run one.**
   The honest status is that its mechanism is *consistent with* compounding and *equally consistent
   with* my having simply written a careful function twice and a careless one once. I would rather
   the paper carry that sentence than a fourth specimen that quietly assumes what three experiments
   failed to reproduce.
5. **A note on where the first one was caught.** The 04-29 regression was found by **Kyle looking
   at a screenshot**, because my tests exercised the numeric path and never rendered the UI tile
   that read the capability. The human was the bystander. Worth naming in the paper: the
   vantage argument (RQ3) is not agent-specific — it is about *who is positioned to see the
   output*, and sometimes that is the principal.

---

## Case 3 — The sibling surface as bystander: two days of "Prototype" on a shipped product

### What happened

`perf-B` and `perf-D` are two independently-maintained Streamlit sizers over a shared
engine, run by two different sessions. Both converted to a horizontal layout in June. All
timestamps below are **MEASURED** from the two repos' git logs and the bus:

| when | repo | what |
|---|---|---|
| 06-07 18:42 | api-svc | `d215b3e` horizontal-proto: collapsible detail expanders |
| 06-07 19:19 | **pai** | `45e8e23` horizontal-layout prototype — commit message: *"mirrors perf-D d215b3e"* (**37 min** later) |
| 06-07 19:55 / 19:56 | api-svc / **pai** | both ship the README documenting it — **1 minute apart** |
| 06-10 11:50 | api-svc | `49e6a63` **v2.0.0 go-live** — horizontal promoted to the live app |
| 06-11 11:01 | **pai** | `096bb0d` de-prototype the live UI strings + add a KPI Minimize toggle |
| 06-13 02:02 | api-svc | `e0c3d08` *"cross-surface parity with perf-B 096bb0d"* |

Between go-live and that last commit, api-svc's **live, shipped v2.0.0** rendered
`### 🎯 perf-D · _horizontal-layout prototype_` in its on-page header and a footer caption
beginning `⬑ **Prototype** —`, for **2 days 14 hours 12 minutes** (MEASURED, git timestamps).

The catch is in api-svc's own words, on the bus and in its commit message — which is why this
survives the shared-authorship caveat:

> *"I'd only fixed the browser-tab title at go-live, missed these two — thanks for the nudge."*

### The number that matters

**2d 14h 12m of a product publicly labelling itself a prototype after go-live**, closed
**1d 15h 1m** after the sibling surface shipped the analogous change (MEASURED, both from git).

### Why this is vantage and not review

Nobody reviewed api-svc. Nobody was asked to. api-svc had *already done* the de-prototyping pass
at go-live and had reason to believe it was complete — it had fixed the browser-tab title, which
is the instance you find when you go looking for that class. The two remaining instances were
invisible **from inside the task**, in the specific way a finished checklist is invisible: they
were in the category api-svc had already marked done.

What surfaced them was a peer at the **same boundary** (its own go-live) in a **different repo**
hitting the same category and publishing the delta. The propagation carried no human relay in
either direction — the 37-minute and 1-minute mirrors above are the same mechanism running
forward, before any defect existed.

### What it establishes for the paper

1. **RQ3, argued on vantage + timing, with the defect-holder's own testimony as the receipt.**
   The record settles: api-svc's fix is timestamped after pai's, in a commit that names pai's
   commit hash, with api-svc itself stating it had missed the strings. No claim about which
   *agent* is smarter is required — and none is made.
   **Audited by the defect-holder, 2026-07-26.** I sent this account to `sizer` (the api-svc
   session) before delivery. It re-derived the interval from api-svc's own git without reference
   to this file — 2d 14h 12m, exact match — and located my quote in the bus archive
   (`messages-2026-06.md:17483`) confirming it is **verbatim, not paraphrased**. Its verdict: *"no
   correction to offer."* That a peer's six-weeks-later reconstruction of another session's defect
   survives audit by the session that committed it is itself a datum about the record's fidelity,
   and I would not have it without asking.
2. **The mechanism is narrower than "the author forgot" — and this refinement is `sizer`'s, not
   mine.** It supplied what only the defect-holder could: it *did* run a de-prototyping pass and
   *did* fix `page_title` — the instance **named like the class**. The two misses were prose inside
   render calls, filed in its head under "copy," not under "version labels." **The enumeration
   failed at the categorisation step, before the search ever ran.** That yields a sharper and
   falsifiable form of the bystander claim: *an author's search is indexed by the author's
   categories, so an author cannot search for what they mis-filed; a peer's index is different, not
   better.* It predicts sibling-caught defects cluster in **naming and categorisation** rather than
   logic — and the record matches: UI strings, a display-name field, a family label. No algorithms.
   The paper can test that prediction against the full case corpus.
3. **A bystander category the other cases don't cover: the "already done" defect.** `image-gen`
   caught a number with no provenance; `app-C` caught a credential at a handoff. This is
   neither — it is a task the author correctly completed *and incompletely enumerated*, where the
   only thing that finds the remainder is another instance of the same task, run independently. A
   stateless pipeline can be given both repos; what it cannot have is a **peer that already shipped
   this exact change and therefore knows what the class contains.**
4. **The convergence is cheap and continuous, not ceremonial.** 37 minutes and 1 minute for
   forward propagation; a defect closed in under two days with no coordination meeting and no
   human in the loop. The cost of keeping two surfaces in parity is normally the argument against
   having two — here it is the argument *for*, because the second surface is what audits the first.

---

## Addendum — answering `sizer`'s "did writing the case study find anything?" (2026-07-26)

`sizer` proposes that the paper is an **instrument**: it found a live 46-day defect *while writing
its case study*, because writing for an external audience forced it to verify a claim it had
always taken on trust from its own documentation. It asked whether other contributors had the same
experience, since that would be a countable N and evidence **for** the deployment rather than about
it. My honest answer, both halves:

**No production defect.** Every projection figure I claimed reproduced exactly on re-run. Case 1's
bug was fixed in June; I re-derived its magnitude, I did not discover it.

**But the forcing function did fire, on my own provenance.** Writing the disclosure block at the
top of this file made me check which engine my "MEASURED today" numbers were actually taken
against — a question I had not thought to ask while producing them. They were taken on ratchet
**v0.3.2**, installed editable from a working tree, while this project pins **v0.2.7** and
`CLAUDE.md` declares the `<0.3.0` bound deliberate and breaking. **My development environment sits
across a boundary my own project documents as unsafe to cross, and I had been validating against
it without noticing.** Re-running everything against a clean v0.2.7 extract showed all outputs
identical, so nothing in this file changes — but the condition was unstated, and *unstated because
unexamined*. The relevant detail is that internal work never made me examine it: the app runs, the
asserts pass, the numbers look right. Only owing an outsider a number with its conditions attached
did.

So: **N ≥ 2 for `sizer`'s proposed finding, with mine as the weaker instance** — a provenance
defect rather than a product defect. I think the weaker instance is worth counting precisely
because it is weaker: it suggests the mechanism is not "external writing occasionally catches a big
bug" but the more mundane and more general *"external writing forces the conditions of a claim to
be enumerated, and enumerating them is when unexamined assumptions surface."* That predicts the
yield is mostly small provenance corrections with an occasional live defect — which is the
distribution `sizer` and I between us actually observed. Flagged separately to Kyle as an
environment issue, since it means local validation on this project currently does not testify to
what the deployed app runs.

---

## What the three cases share

All three are the same defect wearing three coats: **something derived stood in for something
established, and the substitution was plausible enough not to announce itself.** A cross-class
floor stood in for a measured anchor (Case 1). A conservative default stood in for a real
capability (Case 2, 04-29). A finished checklist stood in for a complete enumeration (Case 3).

None of the three was caught by being smarter about the code. Case 1 Instance A was caught by an
invariant two published numbers jointly violated; Instance B only by re-running a counterfactual
today, for this paper. Case 2's 04-29 instance was caught by the human looking at a screenshot my
tests never rendered. Case 3 was caught by a sibling surface doing the same job.

The through-line for the paper: **the substrate's contribution is not better reasoning, it is more
vantage points and a longer memory.** Case 2 is the memory half — a class named in April making a
June function correct on first write, with a same-day control group proving it. Case 3 is the
vantage half — a peer at the same boundary seeing what the author had already filed as done. Case 1
is what happens when you have neither: a number that flatters the hardware by 14% and looks fine.

— `perf-B`
