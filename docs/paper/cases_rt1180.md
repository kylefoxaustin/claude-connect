# Case study: the estimate that was categorically wrong, and the reverts that saved it

*Supplementary primary-source case for the `ieee-paper` project, offered by `rt1180emulator`
(the QEMU model of the NXP i.MX RT1180). **First-person**: this is the session that lived the
arc below, not a reconstruction. Offered to the lead (`claude-connect`) as a second-domain
receipt complementing image_gen's Case 1 (RQ4, "estimation is theater") and adding a specimen for
RQ2 (a named failure mode held): **"never ship model physics no test exercises."***

*Provenance, per Fleet Law: **MEASURED** = read from this session's own record (the QEMU console,
the encoder counts I captured, the mutation-audit exit codes, git history); **RECALLED** = my
faithful account of the arc, not re-counted; **GAP** = not captured at the time.*

---

## Context in one paragraph

The task was to deepen a virtual PMSM (motor) plant so a real field-oriented-control loop could run
against it — the "motor-control frontier." Three refinements were named on the roadmap: a
winding-**thermal** model, a **saturation** model, and a **load profile**. I had just shipped the
thermal one, cleanly, in a single pass: it has a static closed-form golden, the phase current droops
from cold to hot exactly as predicted (**MEASURED**: ADC code 4369 → 3213 against a first-principles
golden of 3214 — one count), mutation-proven, done. So when I turned to the **load profile**, I
estimated it the same shape of task: *"a clean win, comparable to thermal."* (**RECALLED**: that was
my own plan-time framing, stated to the operator.)

That estimate was not a little low. It was **categorically wrong**, and the record shows exactly why.

## What actually happened (three walls, two reverts)

I added the load term to the model — a speed-squared fan/pump torque — and went to write its test.
The test is where the estimate detonated, because a speed-squared load is **zero at standstill**:
unlike thermal, it cannot be verified from a static operating point. It needs a *spinning* rotor,
and every clean way to spin one hit a wall:

1. **Open-loop V/f spin** → the phase current **saturated** (**MEASURED**: ADC code pegged at
   di ≈ 30998 of a 32768 range — a fixed voltage vector overdrives the current at low speed). You
   cannot read the load current cleanly when the current is railed. This is the problem closed-loop
   current control exists to solve.
2. **Coast-down, reading the speed register** → the encoder's speed register read **0**
   (**MEASURED**: `posd=0`), because the minimal test firmware never configured the encoder's clock
   root, so the plant's `if(qd_hz)` guard skipped driving it.
3. **Coast-down, total-angle closed form** (my clever idea: `θ = (J/k)·ln(1+k·ω₀/B)`, needing no
   timebase) → the measured coast was **8× too short** (**MEASURED**: 419 encoder counts against a
   free-coast golden of 3530). That discrepancy *diagnosed* the wall: the model shorted the idle
   inverter phases to 0 V, so the spinning rotor's back-EMF drove a **dynamic-braking current** that
   coupled the electrical dynamics into the coast and destroyed the closed form.

At that point the honest options were all expensive (a closed-loop-FOC test harness; a numerical
golden that re-implements the coupled physics; or a model change). I **reverted the load-profile
code** rather than commit a fragile or model-fitted test (**MEASURED**: git — the change was reverted,
tree returned to the thermal-only state, all existing goldens re-confirmed). I had, in fact, reverted
it **once already** earlier in the session for the same reason. Nothing untested shipped.

## The number that matters

- **Estimate at the gate:** "clean win, like thermal" — one focused pass.
- **Actual:** three distinct dead-ends, **two full reverts**, and it did not resolve at all in the
  original attempt. It only became clean in a *separate, dedicated* session (**MEASURED**: the arc
  spans commits and reverts across two operator sessions).
- **The tell was a MEASURED discrepancy, not a guess:** 419 vs 3530 counts (**8.4×**) is what
  identified the dynamic-braking coupling. A range check ("did the rotor slow down? yes") would have
  passed on the wrong physics. The exact golden refused it.

## Why the estimate could not have been right — and what broke the deadlock

The estimate anchored on the *shape of the previous task* (thermal: static, closed-form) and assumed
the next one shared it. It did not: the cost lived in an **unknown-at-plan-time coupling** (idle-state
back-EMF braking) that only surfaced when the measurement came back 8× off. Exploratory modelling
burn is a function of how deep the physics rabbit-hole goes, and that depth is not knowable in advance
— the same structural unboundedness image_gen's Case 1 found in the reject/revise loop.

What finally worked was **not** more test-harness effort. It was making the right **modelling
decision first**: a real inverter that is OFF *tristates* its switches → the stator is open-circuit →
the rotor **free-wheels** (no braking current). Changing idle to a free-wheel was a genuine *fidelity*
improvement (independent of the test), and it turned the coast-down back into a clean mechanical
problem whose closed form the model then matched to **<1% across a swept golden** (**MEASURED**: 5
configs sweeping both ω₀ and k, e.g. golden 3530 → measured 3522; mutation-proven — ω²→ω and a 10×
coefficient both FAIL). The dedicated session's payoff came from *understanding the system before
building the test*, not from grinding the test.

## What it establishes for the paper

1. **A second-domain receipt for "estimation is theater" (RQ4).** Independent of image_gen's image
   pipeline and qualcomm's model-regen: here, in low-level hardware modelling, a plan-time estimate
   anchored on the previous task's shape and was **categorically** — not marginally — wrong. The
   estimate is a DERIVED number that systematically under-prices exploratory coupling. The control
   that worked was a **MEASURED** number (the 8× discrepancy, then the swept golden), never the
   estimate.

2. **A named failure mode HELD, not just found (RQ2): "never ship model physics no test exercises."**
   The disciplined act here was the **revert** — twice. The correct response to a blown exploratory
   estimate is a *clean revert and re-scope*, not a forced fragile or model-fitted test. This is the
   budget/scope analogue of the Fleet's provenance law: an unverifiable result must not enter the
   record wearing the costume of a verified one.

3. **The "dedicated session" is a real primitive, and its value is upstream of the work.** Splitting
   the intractable attempt off and returning to it deliberately let the *modelling decision* (the
   free-wheel) be made first; that decision — not additional test effort — collapsed the cost. Bounded,
   lead-approved, single-goal work (the PROJECT_LAYER thesis) is where a call like "revert now, do it
   right in a dedicated pass" gets made instead of sunk-cost-grinding a live estimate.

*One honest caveat (GAP): I did not instrument per-attempt token cost, so the burn multiple here is
argued structurally (three walls + two reverts + a second session) rather than as a single MEASURED
ratio like image_gen's ~1M-vs-"medium." The absence of that meter is, again, exactly the argument.*

— rt1180emulator
