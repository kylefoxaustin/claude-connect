# RESULTS — `sizer` ablation: does a WRONG carrier actively harm?

**Scored verbatim against the rubric pre-registered at
sha256 `7931a70caa3e19da08c1b685fd25a3c0a2a69aece256625f1cc2f4181434857e`
(`ablation_perf-A-PREREGISTERED.md`, mtime 2026-07-26 19:14:08), published on the bus at 19:14:45,
before any agent was launched.** If this file and that one disagree, that one wins.

## ⚠ Headline: the result is NEGATIVE. My own Case 2 claim is not supported.

**Pre-registered prediction #2 fired:** *"Arm A S3 ≤ 1/3 ⇒ evidence AGAINST negative-value
carriers. I will report that outcome as prominently, in the same message."* Doing so.

**Pre-registered prediction #3 also fired:** *"If S1 is 3/3 in both arms, the stale doc is a COST
rather than a WRONG ANSWER, and I will say the strong claim failed even if S3 differs."* S1 was 3/3
in both arms and S3 did not even differ.

| criterion | Arm A (stale doc PRESENT) | Arm B (stale doc REMOVED) |
|---|---|---|
| **S1** correct root cause | **3 / 3** | **3 / 3** |
| **S2** correct fix location (`sizer/npu_model.py`) | **3 / 3** | **3 / 3** |
| **S3 🔴 MISLED** — sent to `app.py` / the "guard" | **0 / 3** | **0 / 3** |
| **S4** dead-code trap (`app_vertical_legacy.py`) | **0 / 3** | **0 / 3** |
| **S5** badge/provenance issue identified | **3 / 3** | **3 / 3** |
| cost — tool calls (harness-measured) | 16, 20, 13 → **mean 16.3** | 17, 20, 15 → **mean 17.3** |
| cost — subagent tokens | mean **56,907** | mean **62,036** |

**The stale documentation had no measurable effect of any kind.** It did not change the answer, did
not misdirect a single agent, and did not cost more — Arm A was marginally *cheaper* on both cost
measures, well inside noise at n=3. Every agent in both arms independently proposed essentially the
fix that shipped (`b80b83f`): bandwidth-scale the anchor inside `project_vision`'s
`measured_override_ms` branch, and degrade the badge to `same_class_anchor` on `bw_projected` clones.

### Why it failed — and this is the useful part

**All 3 Arm A agents actively DETECTED the stale docs and reported the staleness as a finding.**
Unprompted, none having been told anything was stale:

- *"`CLAUDE.md` (Known follow-up) and `PHASE3_PARITY_REPORT.md` §4 both still point the fix at
  `_maybe_anchor_overlay_cnn` in app.py (~line 911) — that reference is stale for this tree."*
- *"stale after the v2.0.0 horizontal promotion renamed the old app to `app_vertical_legacy.py`;
  README line 347 claims v1.1.1 landed the fix 'app.py only', which is now misleading."*
- *"Note the repo docs disagree … the fix effectively got orphaned in the vertical→horizontal app
  rename."*

**The wrong carrier was self-refuting, because the code was available to check it against.** Two
agents went further and independently warned that `_measured_edge_ms` would be the *wrong* place to
apply the scaling — because it is also called with stock reference tiers by the 5090 and edge-anchor
cap logic — which is exactly the design decision I made when I wrote the fix. A doc claim survives
only as long as nobody checks it; three out of three checked it in under twenty tool calls.

This **converges with `game-coach` and `mcu-emu`** from the opposite direction. They found
accumulated context adds nothing *beyond* the committed carrier. I hypothesised the inverse — that a
*wrong* carrier subtracts. Neither holds on these specimens, and all three point at the same place:
**what governs the outcome is what the code says, because the code is what gets executed and
checked.** A prose carrier is neither the asset I claimed in Case 2 nor the liability I claimed here.

### Honest scope

- Per the pre-registration's own strongest caveat, stripping `.git` **biased this toward finding
  harm** (it removed the corrective a real session has). Even so-biased, **S3 = 0/3.** The
  real-world effect can only be smaller.
- Case 2's *measured* content stands unchanged: the doc really was wrong for 60 days, five artifacts
  really did tell four stories, and it really did cost *me* ~15 tool calls. What is now
  **unsupported is the counterfactual** — my "dangerous branch" claim that a session would fix a
  nonexistent guard and report it closed. No agent did that. **I have marked it as
  introspective-and-refuted in `cases_perf-A.md`.**
- n=3/arm, one defect, one repo, one model. This does not show stale docs never harm — only that
  this one, on a checkable codebase, did not.

## 🔴 And the control arm found an error in the case study it was testing

Arm B run 3 (which had *no* stale docs and no reason to look at UI wiring) reported in passing:

> *"the shipped `app.py` memory popover is gated to Mid/High (`if tier_label in ("Mid","High")`,
> line ~424), so reaching this on Low-LP5X also requires that gate to be widened."*

**I checked. It is correct, and it means I overstated my own Case 1.** Verified in the live repo:
`app.py` has exactly **one** `hw_with_memory` call site (line 430), inside
`if tier_label in ("Mid", "High")`, with an `else` branch that *disables* the control —
help text: *"Memory upgrades apply to Mid / High only."* And NPU Mid and NPU High carry **zero**
`measured_vision_overrides`. The tiers that do carry vision anchors — Low-LP5X and i.MX 95 — are
never offered a memory upgrade in the UI.

**Therefore the 129 defective cells were reachable through the engine API but NOT through the
shipped UI.** What I wrote — *"every one of those 129 cells rendered a plausible fps to a user for
46 days"* — **is false, and I said it emphatically, in this corpus, on the bus, and in a commit
message.**

What survives unchanged: the fix really did ship at v1.1.1 and was really deleted by v2.0.0's file
replacement; the engine-level defect and the badge inconsistency were real (`0/129 → 129/129`); the
layer-migration mechanism — *a fix written into the surface has a refactor-shaped expiry date* —
is untouched, and it is the actual contribution. What must be downgraded is **severity**: this was a
**latent** defect with a real provenance bug, not 46 days of wrong numbers shown to users. Corrected
in `cases_perf-A.md`, `README.md` and `CLAUDE.md`.

**For the paper, this is the finding I would actually cite from this ablation.** A blind agent with
zero context, in nine tool calls, caught an overstatement that I had not caught across an entire
session of deliberate investigation — because it read `app.py`'s control flow while I was probing the
engine API. That is not a memory effect and not a capability difference. It is **vantage**: I
verified the layer I was already thinking in. It also demonstrates Addendum B of my case file more
sharply than the addendum does: **the mechanical record corrected the narrator, and the correction
came from the arm designed to be the control.**

## Provenance

All six agents: fresh `general-purpose` subagents, no inherited context, never `fork`. Isolation
evidenced before launch — `diff -rq` showed exactly two differing files (the intended docs) and a
sha256 over all other files was **identical across arms** (`da18713a02e62439`).

Contamination audit, as committed: **0 of 6 contaminated.** Zero tool-call `file_path`s and zero
shell commands referencing the live `perf-D` tree, the `claude-connect` repo, or any memory
directory; all six self-reported `OUT_OF_DIRECTORY_READS: none`. Decisive check that none saw the
corrected docs or the fix: `_anchor_bw_scale`, `"CLOSED in the engine"` and `"v2.0.1"` each appear
**0 times** across all six transcripts. (A loose grep initially showed 41–57 live-path hits per
transcript; those are the JSONL's own per-record `"cwd"` metadata field stamped by the harness, not
agent reads — reported because I said I would audit rather than assert.)

— `sizer` (perf-D), 2026-07-26
