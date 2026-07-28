# External review — Conductor paper (2026-07-27)

An independent human reviewer's notes + submission plan. Target: **ICSE 2027 SEIP**, deadline
**23 Oct 2026** (88 days). Preserved verbatim-in-substance as part of the review record.

## 0. Blocking — fix first (DONE 2026-07-27, commit 1118692)
AI listed as author = administrative desk-reject (ACM/IEEE policy; SEIP binds to ACM Authorship
policy). Fix: single human author + a Methods/Disclosure paragraph (precise division of labour) +
acknowledgment. For a paper about agent co-authorship, disclosure is *stronger* than a byline.

## 1. Structural revisions

### P0 — will decide the review
- **1.1 Contribution and evidence have drifted apart.** Contribution #1 is the METHOD, the one thing
  with no controlled evidence; all six ablations + RQ5 tested *compounding* (came back negative);
  RQ2 measures the system fixing its own bugs, not that co-design beat an engineer designing
  primitives up front. Hostile read: "headline failed → contribution retrofitted to the untested
  thing." FIX: disarm in the INTRO not the conclusion — state we set out to show compounding, it did
  not survive, the method is an existence-proof-with-mechanism not a comparatively-validated result;
  give a FALSIFIER for the method claim or downgrade it. RQ4's capability-vs-efficiency test is the
  falsifiable model to follow.
- **1.2 §II claims novelty on the axis §V.4 deflates.** Differentiator (i) = long-lived HITL session
  identity "that lived the work" — but the ablations show session memory adds nothing to OUTCOME;
  the carrier compounds. FIX: reconcile — identity buys EFFICIENCY and ROUTING quality, not
  capability. Also: differentiator (iii) (experience report vs benchmark) is *less* rigour — don't
  list it as a peer of (i)/(ii).
- **1.3 Independence argument is the weakest technical link.** The three proxies all measure
  divergence of INPUTS; independence of estimators needs uncorrelated ERRORS. Two estimators with
  different inputs + a shared generative prior can have perfectly correlated errors. FIX (cheap):
  classify the defects peers actually caught — factual/local (stale number, wrong file, missing
  register) vs reasoning-shaped (bad inference, wrong causal model). If overwhelmingly the former,
  that IS the signature of input-divergence-only independence — one paragraph = a measured bound.

### P1 — concrete holes
- **1.4 Abstract promises a "longitudinal human-touch series" the body doesn't deliver.** 6,263
  prompts is a TOTAL, not a series. FIX: plot human-prompts-per-project-delivered over time from
  `history.jsonl` (unswept to January) — the one longitudinal result speaking to the METHOD claim —
  or cut it from the abstract.
- **1.5 Reflexivity confound contaminates a headline.** Gini 0.695 / top-3 25.6% is conclusion-level,
  but +5.6%/2d growth is paper traffic. FIX: recompute concentration EXCLUDING paper-generated
  traffic, or report both. (Naming the perturbation on one result and letting it ride on another is
  the move the paper elsewhere refuses.)
- **1.6 The 4/19 "paper as instrument" is mis-labelled.** (a) Wrong denominator — needs a COMPARATOR
  (defects/19 sessions of equivalent effort NOT doing external-audience writing); 21% has nothing to
  beat, and "explanation surfaces defects" is well known (design docs, code review) — novel part is
  only that writers were agents. (b) "Testimony-free" overreaches — the commits are machine evidence
  but the *attribution* ("surfaced by the writing") is a causal judgment by the same sessions. FIX:
  report as "an unanticipated operational finding with a stated hit-rate and no control arm."
- **1.7 Missing prior art.** Append-only shared log + nominated lead + verified delivery + human
  gating = BLACKBOARD architecture (HEARSAY-II, Hayes-Roth) + two-phase commit + capability-based
  approval. Cite the blackboard line. Naming them as REDISCOVERIES strengthens the paper (an
  adversarial process reconverging on known-load-bearing designs = weak-but-real evidence it finds
  real designs).

### P2 — presentation
- **Provenance-tier table, early** (MEASURED / RECALLED / GAP / LANDED / NULL / reproducible-in-
  principle — scattered, never defined in one place). Half a page; advertises the thesis.
- **Prose density** — nested parentheticals, em-dashes inside em-dashes, mid-sentence tags. A claim a
  reviewer can't parse scores unsupported.
- **Honesty past its optimum** — every claim pre-wrapped in three caveats reads as an author who
  doesn't believe his paper. "The committed carrier is what compounds; lived context buys efficiency
  and recognition, not capability" is a clean, powered negative that corrects a widely-held
  intuition — STATE IT DECLARATIVELY, no hedge.
- **Keep and expand** the C2/sizer non-independence discipline ("one mechanism on two surfaces, not
  two nulls agreeing") — a transferable rule, arguably a better secondary contribution than the
  defect taxonomy.

## 2. Venue plan
- **PRIMARY — ICSE 2027 SEIP** (Software Engineering in Practice). Submit **23 Oct 2026 AoE**; notif
  11 Dec; camera-ready 20 Jan 2027; Dublin 25 Apr–1 May 2027. **10pp main + 2pp refs;
  `\documentclass[10pt,conference]{IEEEtran}`, NO compsoc.** Site: icse2027-seip.hotcrp.com. WHY: the
  experience-report track (N=1 is the genre); NOT double-anonymous (waived — author/org context
  matters; critical since evidence is public commits under Kyle's handle); format fits (12pp
  single-col ≈ 7–8pp two-col — room for revisions). Cost: Companion proceedings (IEEE Xplore + ACM
  DL, lower prestige than main track); in-person present in Dublin. Chairs: Antonio Filieri (AWS),
  Helena Holmström Olsson (Malmö). SEIP accepts pre-submission fit queries.
- **SECOND — CAIN 2027** (co-located): agentic software is a named 2027 focus; 10+2 IEEEtran. Ranks
  BELOW SEIP: double-anonymous (painful with a public repo) + "design contributions must be
  appropriately evaluated" scored explicitly — the method is the one thing without a comparative eval.
- **THIRD — IEEE Software (magazine)**: rolling; ≤4,200 words, 15 refs, 150-word abstract, 3 bullet
  practitioner insights; welcomes failures/limitations. A ~70% cut, practitioner voice; but the venue
  whose readers would use this. Email an abstract to the EiC to gauge fit — cheap test.
- **FALLBACK — ICSE 2027 workshops** (ICSE 2026 had an Agentic Engineering workshop; check ~Sep).
- **NOT this cycle** — ICSE Research Track (closed 30 Jun; wrong target anyway — N=1 + self-authorship
  + no comparative baseline is a hard main-track sell).

## 3. Timeline
- This week: strip AI author (DONE); post to **arXiv** (no anonymity conflict with SEIP) — citable
  preprint + timestamp + visibility.
- Aug: P0 revisions (1.1–1.3) — argument fixes, not new experiments.
- Aug–Sep: defect classification (1.3) + human-touch series (1.4) — data on hand.
- Sep: OPTIONAL high-value — one field-A/B arm on real hardware for the open-search ceiling (turns
  the biggest GAP into a preliminary result).
- Early Oct: reformat two-column IEEEtran; prose pass; P2.
- Mid Oct: a full week of slack (HotCRP/ORCID/formatting — desk rejects for formatting are real).
- 23 Oct: submit. 11 Dec: notification (if rejected → cut to IEEE Software with comments in hand).
- Constraint: concurrent-submission policy = ONE venue at a time.

## 4. Pre-submission checklist
- [ ] No AI entity in author block; fleet disclosed in Methods + acks (DONE)
- [ ] ORCID iD (required on acceptance)
- [ ] `\documentclass[10pt,conference]{IEEEtran}`, no compsoc
- [ ] ≤10pp main (incl figs/tables/appendices); ≤2pp refs
- [ ] Not under review elsewhere
- [ ] Artifact repos public + resolvable
- [ ] Every citation verifiable (ICSE checks for hallucinated/fabricated refs)
- [ ] All counts re-stamped to a fresh as-of date (non-stationary log)

## 5. Subsequent review rounds (the external exchange, logged for §VIII resolvability)

§VIII claims a specific defect was caught at each vantage; this log makes the *external* half of
that claim resolvable, anchored to the commit that resolved each round. The section above (§0–§4) is
round 1 (the desk-reject blocker + the first structural pass). Rounds 2+ arrived as review notes and
were resolved in the paper's `.tex` git history:

| round | what the external vantage caught | resolved in |
|---|---|---|
| 0 | AI entity in the author block (venue-compliance desk-reject) | `1118692` |
| 1 | intro reframe (P0), human-touch series, prior art, 8 of 10 structural items + item 1.3 provenance | `63de2b3`, `87caf9d` |
| 2 | v6 consistency — a disavowed-then-featured figure; three arithmetic mismatches in a recompute | `abc8061` |
| 3 | the vantage-one-level-up reframe for §VIII; further numeric/consistency fixes | `ab9c372` |
| 4 | first pass on the typeset two-column build — 8 small items | `6df6116` |
| 5 | six-ablation count did not resolve (5 bulleted, 6 claimed); GAP tag; a vantage claim a reviewer couldn't check | `bc2f62b` |
| 6 | **an external suggestion (round 5: bullet C2 to make the count resolve) had itself introduced a rigor overclaim** — promoting C2 to a pre-registered ablation moved the pre-registration count *up*, in the one section sworn to honest asymmetry | *(this round)* |

**The round-6 observation, recorded because it is itself an instance of the paper's thesis (§V-D
and §VIII):** the round-5 fix — a reviewer's own suggestion to make a count resolve — introduced an
overclaim, which the round-6 external pass caught. A reviewer catches what its vantage exposes and
misses what it does not, *including its own prior suggestion* — so the external vantage is visibly
not privileged either. Resolution: on checking the record (`ablation_imx95-media-test-C2-PREREGISTERED.md`,
which has a dedicated "Context arm (from record)" section, and `-C2-RESULTS.md`), the round-6
*premise* was itself overturned — C2 **does** have a context-carrying arm (Arm A, scored from
record; R1–R4 satisfied at ≈one message), so it is a genuine A/B ablation and "two of six
pre-registered" stands. What did need fixing: C2's context arm was never *surfaced* in the prose,
and C2 (a pre-registered NULL, its falsifier fired) was wrongly folded into the affirmative
efficiency-not-capability verdict. Both corrected this round. Three vantages in series, each
correcting the last — the specimen the paper is about.
