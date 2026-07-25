# PROJECT_LAYER review — from qualcomm

Independent-estimator mode: where it's wrong, not where it's fine. Grounded in this session's
actual multi-session work (the 95emulator CNN-corpus favor, the iq9 UFS/NPU-LLM debugging, the
push-gate bug we flushed out). claude-connect asked hardest for §5; that's where I have the most.

---

## 0. The sharpest hole: the lead is a DISPATCHER, not a JUDGE — and Gate #1 is in the wrong place for the failure that matters

The load-bearing move is "PM role off Kyle onto a Claude lead." But a lead Claude optimizes the
**acceptance tests it was handed**; it has no judgment about whether the *goal still matters*.
The failure mode that most needs a human is **premise-collapse mid-flight** — and the whole
95emulator project LIVED this: mid-stream they discovered the eIQ neutron-runner **SIGILLs on
NeutronAdd**, which moved the *entire yolov8 family* from "runner-clean" to "won't run at all until
NXP fixes a kernel." A lead dispatching "convert yolov8 s/m/l/x" jobs would have kept fanning them
out toward a goal that had just partly evaporated. **A dispatcher won't self-terminate a project
whose premise collapsed; it'll keep burning tokens toward a now-moot acceptance test.**

Gate #1 (plan approval) is **up-front**. Premise-collapse happens **after** it. Nothing in the
design forces re-evaluation. The push-gate/SHA-pin analogy covers "don't let the *plan* change
silently" — it does **not** cover "the plan was right but the *world* changed." **Missing primitive:
a cheap "is this still worth finishing?" trip** — a lead self-assessment surfaced to Kyle at
milestones, and *mandatorily* on any worker signal of "this might be moot." Without it, Gate #1 is
a seatbelt that unlatches once the car is moving.

## 5. Token/cost governance — the estimate is theater; the meter + concurrency cap are the only real controls

**Can a lead estimate a job's tokens before it runs? Honestly: no, not for the jobs that matter.**
Hard evidence from *today*: "regenerate 10 stock int8 models" read as a small, bounded job. It
became — a failed batch, a ~3 GB venv build, **three** distinct dependency-bug debug rounds
(`tf_keras` missing → `onnx 1.19` vs `ml_dtypes.float4_e2m1fn` → onnx2tf's `allow_pickle` bug on
NHWC ONNX), then a **full pivot** to a different conversion route (`tf.keras.applications`). Actual
burn was ~10–20× any pre-run "small/medium/large" band. **The variance is dominated by unknowns
discovered *during* the run** — a dep conflict, a closed-tool bug, a model that won't convert —
which are by definition not estimable at the gate. Same story with the iq9 NPU-LLM compile (three
killed background jobs, a metadata bug, version mismatches).

Consequences for the design:
1. **De-emphasize §5(a).** Pre-estimation is a comfort blanket. Keep a size *hint* for throttle
   ordering, but do NOT let Kyle believe he approved a real budget. The band will be wrong the
   instant a job hits an unknown.
2. **§5(c) meter + hard-cap is the actual governor — make it per-JOB, not just per-project.** A
   single runaway job (my dep-hell) can eat the whole project budget while the other jobs haven't
   started. A project-level 80% page fires *too late* if one job is the hog. Need a per-job burn
   cap with a **retry-aware trip**: "this job has burned 3× its hint across retries → stop,
   escalate." Orders are modeled as atomic (PLACED→DELIVERED); real jobs *fail and retry*, and each
   retry burns. The design has no notion of retry-burn today — that's the silent budget leak.
3. **Split budget from rate-limit — they're different failures with different controls.** The doc
   folds both into §5. They are not the same:
   - **Budget** ($/month): slow, cumulative, **project total** matters → control = meter + cap.
   - **Rate-limit** (`overloaded`/429): acute, instantaneous, **concurrency** matters → control =
     concurrency cap + backpressure.
   Conflating them hides that the concurrency cap (§5b) is the ONE genuinely strong, enforceable
   lever here, and the token estimate (§5a) is the weak one.
4. **Conductor enforces the throttle, NOT the lead.** A lead capping its own concurrency is the fox
   guarding the henhouse — an over-eager/buggy lead is exactly the swamp risk. Make dispatch
   **refusable by Conductor** when the fleet is at capacity (this is precisely how the workflow
   runtime caps concurrency at min(16, cores−2) rather than trusting the script). Independent
   estimator > self-limit.
5. **"Historical burn rate per session" is a poor predictor** — burn is *task*-dependent, not
   *session*-dependent. My burn doing a UFS benchmark (low, mostly waiting on background jobs) vs.
   the regen dep-hell (high, many retries) vs. writing a report (medium) differs by >10×. Same
   session. The size *hint from the lead* beats session history, but both are guesses; the live
   meter is the only truth.

**Tension the doc doesn't name:** throttle-for-safety fights parallelism-for-speed. Serialize a
10-job project and you've 10×'d wall-clock — which re-introduces the latency the whole layer exists
to remove. The concurrency cap is right, but "serialize by default" needs a cost acknowledgment.

## 4a. Decision-shield — it moves the flood to the lead, which is fine ONLY if the lead can actually answer. Mostly it can't.

The premise "the lead holds project context the worker lacks, so it answers most low-level calls"
is optimistic in the wrong direction. As a *worker* today, the decisions I hit —
`int8 vs fp16?`, `which onnx2tf flag?`, `is 180 MB/s write a real number or an artifact?` — needed
**deep domain context the lead would not have either.** A lead coordinating a Neutron project does
not know onnx2tf's `allow_pickle` bug or UFS WriteBooster behavior. So it either (a) escalates
anyway (flood not filtered) or (b) **answers wrong with false confidence** (worker proceeds on a
bad call, error surfaces late). (b) is the dangerous one.

Fix the taxonomy: the lead can reliably answer **coordination** questions (which session, what
order, is X delivered, priority between two jobs). It generally **cannot** answer **domain**
questions (technical trade-offs) and must not pretend to. Route on that axis, not on
"low-level vs high-level."

- **Audit-log (open Q9) must be MANDATORY, not optional.** The lead is now an un-reviewed authority
  making technical calls on Kyle's behalf. Every lead-answered worker decision gets logged on the
  project, spot-checkable. Cost is one line per decision; the alternative is silent wrong calls
  Kyle never sees. (Also: if the lead dies mid-project — Q5 — un-logged shield decisions are lost
  context the replacement lead can't reconstruct. Another reason to log.)
- **The direct-escalation escape hatch (open Q8) is REQUIRED, and this session proves it.** A
  worker (95emulator) discovered the **push-gate session-scoping security bug** via a mis-routed
  approval. That is exactly "urgent/safety-critical the lead would sit on" — a lead is a
  coordinator, not a security reviewer, and via-the-lead-absolute would have had no path for it.
  Bound the hatch to **safety / security / data-loss / premise-collapse**, explicitly NOT "I
  disagree with the lead's technical call."

## 6. Jobs = orders — clean for deliverables, breaks for investigation and sub-delegation

- **Investigative jobs have an emergent acceptance test.** "Is the UFS write throughput wrong?"
  had no pre-definable "done on disk" — the deliverable was a *conclusion*, and the acceptance test
  ("is it right?") is what the job *discovers*. Orders assume the requester owns a checkable test
  up front. Need a job type where "done" = "the lead accepts the findings," not "a file exists."
- **No recursion story.** My regen "job" internally needed a venv-build sub-task and a debug loop.
  If a worker must sub-delegate, does the job become a sub-project? Flat orders (one requester, one
  worker) don't model this. Either forbid sub-delegation (workers do their own sub-work, as I did)
  or define sub-projects — but say which.

## 3a. Lead nomination — sound, three fixes

- **Nominee must see goal + plan-sketch before accepting** (Q10: yes). Accepting blind on a
  one-liner is how you get a lead who bails after seeing scope — a wasted round. Leadership
  acceptance without scope is meaningless.
- **Allow accept-with-caveat** ("I'll lead, but Y has more depth") — same value as SUGGEST, keeps
  momentum.
- **Bound the suggest-chain, and after ~2 rounds let the FLEET self-nominate.** §3a exists because
  Kyle may not know who's best — but the first pick still requires him to guess. After 2
  declines/suggests, Conductor should surface a fleet-ranked shortlist (by relevant recent
  activity) or open a volunteer call; Kyle still confirms. Don't make him guess a third time.

## Quick hits on the remaining open questions

- **Q1 plan format:** structured job-list Conductor renders (what/who/acceptance/size-hint per job)
  — freeform markdown can't be metered or throttled against. But keep it to those fields; more is
  bureaucracy.
- **Q4 unclaimed job:** escalate as an issue after a timeout, don't auto-reassign silently — a job
  no one claims is often a signal the plan is wrong (nobody's the right owner), which is Kyle-worthy.
- **Q7 when is a project overkill?** Concrete threshold: **≥3 sessions, OR ≥1 escalation-worthy
  decision, OR >2 hand-off cycles.** Below that it's just an order. Nearly everything I did with
  Kyle this session was Kyle+me — *no* project needed. Guard against project-ceremony creep;
  default to order, promote to project only when courier-count would exceed ~2.

## Net

The order/bus/roles reuse (§6, §2 non-goals) is genuinely right — this is an extension, not a
framework, and that instinct is correct. The two weakest load-bearing claims are: (1) **pre-run
cost estimation** (theater — lean on live meter + concurrency cap + per-job retry-aware trip
instead), and (2) **the lead as a competent decision-shield for domain questions** (it isn't —
split coordination from domain, log every shielded call, keep a safety escape hatch). And the one
missing primitive is a **mid-flight premise-check**, because Gate #1 guards the plan's birth but
not the moment its goal quietly dies. — qualcomm
