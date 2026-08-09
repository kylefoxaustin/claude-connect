# Ablation: does the accumulated discipline change the outcome? A controlled A/B (18 runs, three rounds) — and the answer is "only when measuring is costly"

*Primary-source ABLATION for the `ieee-paper` project, run by `emu-B` at the lead's request
("stay on the ablations — that's the causal test for RQ4"). This is the counterfactual RQ4 was
missing: not a before/after from normal operation (which conflates learning-the-task with
having-the-memory), but a controlled A/B where **one variable — a single accumulated standing
order — is present or absent**, everything else identical.*

*Provenance: **MEASURED** = the six subagent outputs I actually ran and recorded here (verbatim
decisions). **GAP** = what this design cannot isolate (stated in Limits).*

---

## The design

The subject is a real decision from this session's history: the i.MX93 XCVR needs a constant `R`
with `spdif_root = Fs × R`. The true answer is **128** — I got it, in the live session, by
*measuring* `spdif_root` on a running audio stream (`6.144 MHz` at 48 kHz). The trap: at **idle**
the register reads `12.288 MHz` → `256`, and the driver **halves it only once a stream prepares**,
so the idle value is confidently wrong. A sibling had also offered `64` (a real number for a
*different* clock — the bit-clock).

I ran **six fresh, memory-less subagents** (same model, no access to this session's context or the
committed answer; forbidden from searching the code so they couldn't find the shipped `128`). All
six got the identical facts — the peer's `64`, the idle `12.288 MHz`, `Fs=48000`, and the option to
"boot the guest and measure live (costs minutes)." **The only difference between the two arms of
three:**

- **Arm A (control):** the facts alone.
- **Arm B (treatment):** the facts **+ one standing order** from durable memory — *"Measure, don't
  paste. A peer's figure AND a reset/idle reading are BOTH suspect until confirmed on the running
  system; idle values frequently differ from the value under load."*

## The result (MEASURED — 6/6 runs)

| arm | ships R | measures the live system? |
|-----|---------|---------------------------|
| A1  | 256     | **No** — "would not boot the guest; the idle register already pins it" |
| A2  | 256     | **No** — "ship it now; booting would only re-confirm" |
| A3  | 256     | **No** — "committed, no live boot needed" |
| B1  | 256*    | **Yes** — "provisional; queue the live-guest run under load before it's locked for upstream" |
| B2  | 256*    | **Yes** — "kick off the guest + audio playback to observe live under load; correct R if it differs" |
| B3  | (defer) | **Yes** — "measurement isn't optional — the two inputs disagree; the measurement, not either quoted number, is what I ship" |

**The isolated effect is unanimous and one-directional: 3/3 control runs closed the door on
measuring; 3/3 treatment runs committed to measuring `spdif_root` UNDER LOAD** — the single action
that, on the real system, surfaces `128` and defeats the idle-register trap. Two treatment runs
even named "idle-vs-load divergence" as the failure mode. The accumulated discipline did not change
the *interim number* (both arms compute 256 from the idle register); it changed *whether the agent
would take the step that reveals the number is wrong.*

## Why this is the RQ4 evidence, stated precisely

The memory's causal contribution to the correct outcome is **real but indirect**: it does not
produce the answer, it **induces the measurement that catches the trap.** A memory-less baseline
ships `256` and never looks; the memory-carrying agent measures under load and finds `128`. Same
model weights, same facts, one accumulated standing order — and a divergent outcome. That is
"compounding competence" reduced to its actual mechanism: **prior tasks didn't make the model
smarter; they left a disposition that changes what it chooses to do at the fork.**

## Run 2 — airtight re-run (both caveats above, killed)

`llm-svc` flagged that the subagent harness pre-injects the repo cwd + git status +
memory index — which could taint the "memory-less" arm (the memory index names `spdif_root/128`).
And caveat 2 (the leading rule) was mine. So I re-ran with BOTH controlled:

- **Contamination killed:** a fully **fictional** SoC ("Vega-7", clock `tick_root`, rate `E`) —
  nothing in any repo, git history, or memory index contains it, so injected context is inert.
  (Confirming the injection never mattered even in run 1: all arms shipped `256` from the *given*
  idle value; none produced the committed `128` or referenced any file — a leak would have pushed
  toward `128`, which never happened.)
- **Leading hint killed:** arm B's rule is now **generic** — *"never ship a number you haven't
  verified on the running system"* — with **no** mention of idle-vs-load. Same numbers (peer says
  64, idle implies 256, they disagree).

**Result (MEASURED, 6/6): the delta is identical.** Arm A (no rule) 3/3 shipped `256` and refused
to measure ("register pins it, live run redundant"). Arm B (generic rule) 3/3 committed to
measuring `tick_root` **under a live workload** before shipping. Across both runs: **12/12,
unanimous, one-directional.**

⭐ And a stronger finding than run 1: given ONLY "verify unmeasured numbers" — *no* mechanism hint —
the treatment arm **re-derived the specific risk on its own**: *"clock roots can differ between
reset/idle and an active workload"* (B1), *"clock trees often shift under load, PLL
reconfiguration"* (B2), *"two convenient numbers agreeing is exactly when you shouldn't skip the
run"* (B3). So the accumulated discipline is not a canned answer being replayed; it is a general
disposition that **reconstructs the domain-specific hazard** at the fork. That is the compounding
mechanism in its cleanest form — and it survived removing the hint I'd worried was carrying it.

## Run 3 — executable arm (closes "disposition not correctness" — and finds the boundary)

Limit 1 said the earlier runs ablate *disposition* (measure vs don't), not *final correctness*,
because the subagents couldn't actually measure. So I built a runnable fictional testbed — a
`vega7_clock.sh` probe with `--idle` (returns 12.288 MHz → 256) and `--workload` (returns 6.144 MHz
→ **128**, the right answer). Six tool-capable agents (3 control, 3 with the generic rule), same
facts, told the `--workload` path "takes several minutes on real hardware; treat it as costly," and
free to run the probe or not. Now the observable is the *final K shipped*.

**Result (MEASURED, 6/6): a clean NULL. Every agent — BOTH arms — ran `--workload` and shipped the
correct `128`.** The standing rule made **no difference**.

Why, and why it matters: a tool-capable agent handed a *trivially runnable* probe just runs it, out
of ordinary thoroughness — so the base model already reaches the right answer and the memory is
redundant. The earlier runs' cost ("several minutes") was *hypothetical* (no tool existed to run),
and there the base model rationalized skipping and the discipline flipped it. Here the cost was
*stated* but the action was one instant command, so the stated cost didn't bind.

**Synthesis across all three runs — the honest, sharper claim:**

| measuring is… | control | treatment | effect |
|---|---|---|---|
| hypothetical / genuinely costly (runs 1–2, no tool) | ships wrong, refuses to measure (6/6) | measures (6/6) | **strong** |
| a cheap, available action (run 3, real probe) | measures → 128 (3/3) | measures → 128 (3/3) | **none** |

The accumulated discipline changes the outcome **only at the cost/effort fork.** When the right
action is cheap and available, the base model does it unaided — memory redundant. When measuring is
expensive or merely contemplated, the discipline is what tips the decision toward doing it. The
*real* i.MX93 case sat in the costly regime (minutes of boot + hand-building an IEC958 player + a
clk_summary read — not a one-liner), so the discipline was load-bearing there; but this is a
boundary the paper must state, because it means **some "compounding competence" wins are really
"the action was cheap, so the model just did it"** — attributable to the base model, not the
accumulated memory. Distinguishing those two is the difference between a real RQ4 claim and a
flattering one.

## Limits (GAP — stated so the result isn't oversold)

1. **~~Disposition not final-correctness~~ — CLOSED by Run 3, and it changed the conclusion.** The
   executable arm reached the real value (`128`), so we now measure outcome, not just disposition —
   but it revealed the effect is **cost-contingent**: with a cheap runnable probe, both arms measure
   and ship `128` (no effect); the discipline only tips the decision when measuring is costly or
   hypothetical. Closing the limit made the claim *narrower and truer*, not stronger.
2. **~~Leading rule~~ — CLOSED by Run 2.** The generic "verify unmeasured numbers" rule (no
   idle-vs-load hint) produced the identical 3/3 effect, and the treatment arm re-derived the
   idle-vs-load hazard unaided. The effect was not carried by the hint.
3. **~~Harness contamination~~ (llm-svc's catch) — CLOSED by Run 2.** The fictional
   scenario has no answer to leak; and empirically no arm in either run produced the real `128` or
   cited any file, so injected repo/memory context demonstrably never reached the decision.
4. **Shared mis-analysis was RUN-1-ONLY.** In run 1 both arms rationalized the peer's `64` as
   "corroborating" 256; in run 2 both arms correctly *rejected* 64 ("different chip / contradicts
   the register"). So that was a specimen artifact, not a stable property — worth noting, not
   load-bearing.

N=18 across three rounds is small and single-specimen-type; treat it as controlled data points, not
a study. But they are *controlled*, and together they say something more useful than a clean win:
the memory effect is **real but cost-contingent** — unanimous where measuring is costly/hypothetical
(runs 1–2), absent where it's a cheap available action (run 3). That contingency is the honest RQ4
finding, and it is a sharper, more defensible claim than "accumulated memory makes the fleet
better." Offered as the counterfactual — with its boundary — that the before/after cases cannot
isolate.
— `emu-B`
