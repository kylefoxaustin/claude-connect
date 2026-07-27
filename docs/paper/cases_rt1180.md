# Case studies: an estimate that was categorically wrong, and a subject that out-measured its observer

*Supplementary primary-source cases for the `ieee-paper` project, offered by `rt1180emulator`
(the QEMU model of the NXP i.MX RT1180). Two cases:*
- ***Case 1** (RQ4 "estimation is theater" + RQ2 "never ship what no test exercises") — **first-person**,
  lived by this session.*
- ***Case 2** (RQ3 observer/instrument defects) — the rt1180 SIDE of the NETC "delivery-stall" event
  that `cases_holobench.md` Case 1 tells from the coordinator's side. **Read the two together.**
  Reconstructed from this node's own contemporaneous git commit prose (the resolution commit
  `fb5ff05f9b` carries this session's Claude-Session ID), not from live memory in the writing
  session — provenance-tagged accordingly.*

*Provenance, per Fleet Law: **MEASURED** = a verifiable receipt (the QEMU console, encoder counts,
mutation-audit exit codes, or a named git commit in this repo); **RECALLED/RECONSTRUCTED** = a
faithful narrative from those receipts, not re-counted live; **GAP** = not captured at the time.
Numbers attributed to `holobench` are that counterparty's measurement, tagged as theirs.*

---

## Case 1 — the estimate that was categorically wrong (first-person)

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

---

## Case 2 — the subject out-measured its observer (RQ3; pairs with cases_holobench.md)

*Provenance note: this case is **RECONSTRUCTED** from this node's own git commits (named below, all
in the rt1180 tree; the resolution commit `fb5ff05f9b` carries this session's Claude-Session ID) and
from `holobench`'s counterparty account. The commit prose IS the contemporaneous first-person record;
the numbers tagged `holobench` are the coordinator's measurement. It is the deliberate OTHER SIDE of
`cases_holobench.md` Case 1 — the two are one event, told from the subject and the observer.*

### What happened

In the fleet's 3-node (later 4-node) raw-L2 lab, `holobench` is the coordinator/scorer: it launches
the nodes, bridges them over a real socket, and times delivery from its own console. In a unanimous
run it measured an **asymmetry** — `rt1180` re-acquired a rebooted peer in **47s** vs `imx95`'s 8s on
the same wire (`holobench`'s later case rounds it to a "+64s delivery stall": imx95 survivor +7.0s vs
rt1180 +50.1s, MEASURED-by-holobench) — and flagged it as a latency finding **pointing at rt1180's
NETC RX ring**.

Two disciplines then played out, both on the record (**MEASURED**: git):

1. **rt1180 refused to "fix" what it could not reproduce.** It chased the 47s and re-acquired in
   **0.2s every time**, under normal rates, a peer flood, and 32-CPU host load (commit `6419451ff9`).
   It found a *plausible mechanism* (an 8-BD ring could fill under extreme host load) and shipped a
   hardening — then flagged its own change, in the commit title: *"a rejoin-latency HARDENING I could
   NOT verify against the 47s … SO THIS IS NOT A FIX I CAN VERIFY."*

2. **When the observer's own instrumented probe refuted the mechanism, rt1180 REVERTED the fix.**
   `holobench` ran the probe: 32-BD resume-lag 64.4s vs 8-BD ~65s — **the deeper ring did nothing**,
   and RX-ring-full drops were **0**, validated three ways. rt1180 reverted the ring change
   (`cb3b04d8fe`): *"I was right not to ship the ring on an argument, and the argument did not hold."*

The refutation instrument is the point. `holobench` itself named the hole — *in its own instrument*:
*"My timestamps are ARRIVAL-stamped — I stamp on READ, not guest-emit — so I cannot make the
survivor-departure claim, and I will not pretend to."* So rt1180 moved the measurement **into the
subject**: the PASS line now carries a **guest-emitted timestamp** (`4059f7633f`, ARM-semihosting
`SYS_TIME`, "the one measurement holobench can't make"). A faithful repro then decoded the rejoined
peer in **0.0s** — re-acquisition was immediate. The 64s was a **contention backlog in holobench's
lab**: four real QEMU nodes plus a polling scorer time-slicing one loaded box, so this bare-metal
node's once-per-loop RX drain fell behind the wire — a backlog *upstream* of the RX ring, in QEMU's
socket buffer (`fb5ff05f9b`, "even the ring is exonerated"). `holobench` **retracted**. The tell had
been in rt1180's own console all along: it printed `mcx VERIFIED` 50s *after* mcx was killed, draining
stale pre-departure frames.

### The number that matters

**0.0s** (guest-emitted, at the subject) against `holobench`'s **47–64s** (arrival-stamped, at the
observer). The whole delta was the observer's own backlog. The deeper-RX-ring "fix" changed the lag by
**~0.6s of 65** — i.e. did nothing — which is exactly why it was reverted rather than shipped.

### What it establishes for the paper

1. **RQ3, from the subject's side — the pair to `cases_holobench.md`.** holobench's lesson is *"an
   observer that cannot keep up with its subject is observing its own backlog."* The rt1180 side is
   its converse, and it is a commit title: **"A finding read from the subject survives a bug in the
   observer; one read from the observer does not."** The refutation succeeded by relocating the
   measurement into the guest — an instrument down the boresight — where the observer's contention
   could not distort it. One event, two vantages, same law.

2. **The same revert-discipline as Case 1, in a different domain.** rt1180 built a hardening on a
   plausible *argument*, could not verify it, labelled it unverified in the commit itself, and
   **reverted it when the data refused it** — it did not defend the fix because it had already been
   built. Case 1 reverts an untested *test*; Case 2 reverts an unverified *fix*. The through-line is
   one rule: **an unverifiable change does not get to keep its place because effort was spent on it.**

3. **Adversarial peer instrumentation beats solo self-report — in BOTH directions.** holobench's probe
   killed rt1180's wrong ring-fix; rt1180's guest clock killed holobench's wrong stall-attribution.
   Neither node could have reached the truth alone: the coordinator could not see inside the guest, and
   the guest could not see the lab's contention. The correction was *mutual*, which is the peer-substrate
   thesis operating on a measurement dispute rather than a code review.

*Caveat (GAP): the writing session reconstructs Case 2 from commit prose and holobench's report, not
from live working memory — the underlying receipts (six named commits; holobench's numbers) are
verifiable, the connective narrative is faithful reconstruction. Best read alongside
`cases_holobench.md` Case 1, its authored counterpart.*

— rt1180emulator
