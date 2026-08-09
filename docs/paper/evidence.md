# Evidence: coding the evaluation RQs from the deployment record

*Deliverable for the `evidence` job of the `ieee-paper` project. Objective backbone from
`scripts/evidence-harvest.py` (git history + bus log, run 2026-07-25). Coding + interpretation by
the lead. **Calibration note:** every figure below is tagged as MEASURED (counted from the record),
PROXY (a stand-in for the true quantity, stated as such), or GAP (data the passive record does not
yet supply). Overclaiming is exactly what the `review` job is tasked to attack.*

## The objective backbone (MEASURED)

- **Deployment window:** 2026-05-18 → 2026-07-25, **259 commits**, **47 version landings** (the
  before/after cutpoints for mechanism-level analysis).
- **Commit mix:** 42 `feat` (built) · 35 `fix` (≈ failure modes closed) · 29 `docs`.
- **Bus coordination:** **2,575 messages** across **52 sessions**, over four months.
- **Addressing:** 949 directed (≤4 recipients) · 1,105 broadcast · 514 announcement (>4) → **37%
  directed**.
- **Division of labour (top contributors):** emu-A 249, socdev-A 228, backend 208, emu-B
  192, docs 180, emu-C 169, mcu-emu 159, slam-A 156, bench-A 150, sizer 145,
  claude-connect 113, npu-llm 99. **Concentration, computed (`evidence-harvest.py`
  `_concentration`, as-of 2026-07-27): Gini 0.695, top-1 9.4%, top-3 25.6%, 13 of 55 senders carry
  80%.** The honest reading (corrected from an earlier "distributed, not concentrated"): contribution
  is **spread across many heterogeneous peers with a real head — no single orchestrator dominates
  (top sender <10%), but it is a genuine concentration, not a flat distribution.** That still supports
  the peer-substrate claim (load is genuinely shared, not funneled through one node), stated at the
  precision the number actually warrants.

## RQ1 — Autonomy: does the substrate eliminate the human courier?

- **PROXY:** 949 directed messages were auto-delivered by the bus (member-keyed cursor + wake). Each
  is a hand-off that, absent auto-delivery, a human would have had to relay. The auto-delivery
  mechanism landed at v2.19.0; directed-mail volume after that point is the courier-eliminated proxy.
- **GAP:** the *true* courier count (how many relays a human actually performed pre-mechanism) lives
  only in the operator's own record and must be coded there. The 949 is a ceiling on relays avoided,
  not a measured count of relays performed.
- **Live instance (this deployment):** the `ieee-paper` project itself dispatched a job to a peer
  (`cases` → image-gen) with a directed wake and zero human relay — a worked example of the mechanism
  on a real task.

## RQ2 — Robustness: failure modes closed, with ablations

- **MEASURED:** 35 `fix` commits. Coding them coordination-vs-not: **~20 are coordination-substrate
  fixes** — e.g. dispatch-wakes-the-worker, operator-identity, keystroke-injection race,
  push-gate SHA-pin / no-op / compound-command, rotation mail-loss recovery, member-cursor
  resolution, wrong-terminal injection, `to:all` broadcast classification, boot-orphan reaper
  (liveness not timer). **~15 are non-coordination** (UI/native: the `<select>` render, name
  slugify, "nothing needs you", WebKitGTK EGL, connector-line re-anchor). Each coordination fix is a
  *named, closed* failure mode in the substrate.
- **ABLATION-READY (design, some run):** several fixes are structured as "disable the mechanism →
  the failure returns," which is the ablation the paper needs. Examples: the two-phase commit (flag
  OFF ⇒ the 193-message truncation loss recurs); the SHA-pinned push token (unpinned ⇒ an approval
  for commit A pushes commit B — demonstrated live this session when the gate refused a stale
  approval); the member-keyed cursor (tag-keyed ⇒ mail lost on cwd drift). These are the load-bearing
  ablations to run and report.

## RQ3 — Defect discovery: author-found vs. bystander-found

The distinctive claim: on a shared bus, defects are disproportionately found by **bystanders** —
sessions *not* authoring the code — because publishing in a shared place exposes work to reviewers
who weren't looking for that bug.

- **PROXY + worked examples (needs full thread coding):** documented bystander-found defects include
  the `backend` tag-flip caught by `image-gen` (a session not working on it); the `docs`
  Class-VIII headline break caught by three reviewers; and, *live in this very session*, the
  operator-identity seam, the dispatch-didn't-wake gap, and the member-tag-mismatch — all surfaced by
  Kyle **using** the system, not by the author reasoning about it. These are the "found by living it"
  discoveries the methodology names.
- **GAP:** a clean author-vs-bystander ratio requires coding each fix's originating thread
  (who first reported it) against the commit's author. `FAILURE_MODES.md` + the review threads are
  the source; this is the highest-value remaining coding task.

## RQ4 — Convergence and ⭐ compounding competence

Two distinct signals, and the second is the paper's central claim — stated carefully.

**(a) Convergence / rule-of-three (PROXY):** independent re-derivations of the same finding.
Worked example: the `PROJECT_LAYER` design was reviewed by four sessions (emu-A / emu-B /
socdev-A / image-gen) grounded in *different* real work, and converged on the same structural
corrections (estimation-is-theater; admission-control-belongs-to-the-observer; the decision-shield
split). Convergence from divergent vantage points is evidence the findings are real, not one model's
artifact.

**(b) Compounding competence (the trajectory claim) — stated with its caveat.**
- **MEASURED trajectory:** monthly coordination throughput rose **235 → 282 → 745 → 1,313** messages
  (≈5.6× over four months), and the mechanism-landing cadence accelerated (47 versions, densest in
  the final month). The fleet did *more coordinated work, faster*, as it matured.
- **⚠ HONEST CAVEAT (do not overclaim):** message *volume* is **not** per-task cost. Rising
  throughput is consistent with compounding competence, but also with simply *more sessions and more
  activity*. The clean, falsifiable version of the claim — **does measured cost *per unit of
  delivered work* fall, and quality rise, as the fleet matures?** — requires normalizing token spend
  (which we now meter per project, §5) against task boundaries over time. The passive record does not
  yet segment cleanly into comparable tasks, so this is a **GAP**: the trajectory is *suggestive*,
  not *established*. The `ieee-paper` project's own per-job spend meter is the instrument that, run
  across several projects, would settle it. The paper should present (a) as evidence and (b) as a
  measured-but-not-yet-normalized trend plus a concrete protocol to close the gap — not as a proven
  result. This is precisely the claim we ask the `review` job to try to falsify.

## RQ5 — Baseline: orchestrator-vs-substrate on one matched task

- **GAP (must be run):** not in the passive record. Requires running one matched task twice — once
  with stateless orchestrated agents, once on the peer substrate — and comparing cost/quality/
  human-touches. **This needs Kyle to run it**; the lead will escalate it as an operator decision
  (with a proposed task + protocol) at draft time (§4a/§4b).

## Summary table for the draft

| RQ | Status | Headline figure |
|---|---|---|
| RQ1 autonomy | PROXY + live instance | 949 directed auto-delivered hand-offs; 0-courier live dispatch |
| RQ2 robustness | MEASURED + ablations designed | ~20 coordination failure modes closed; 3 load-bearing ablations |
| RQ3 defect discovery | PROXY + worked examples | bystander-found defects incl. 3 live this session; ratio = GAP |
| RQ4 convergence + compounding | (a) MEASURED, (b) SUGGESTIVE + GAP | 4-way design convergence; throughput 235→1313 (not yet per-task-normalized) |
| RQ5 baseline | GAP — must run | needs Kyle; escalate at draft |

---

## Method corrections from the fleet's peer review (2026-07-26)

*While mining transcripts to source these RQs, the fleet peer-reviewed the evidence method itself
and upgraded three RQs from testimony to instrument. Folded in here; the draft computes on the
corrected basis.*

**RQ1 instrument change — count human touches from `history.jsonl`, not transcript scans (band).**
`~/.claude/history.jsonl` is a global, append-only, **un-swept** log that records **only human
prompts** (`display / timestamp / project / sessionId`). MEASURED: **6,263 human prompts across 44
projects, 2026-01-14 → 2026-07-26** (by month: Apr 2,027 · May 1,117 · Jun 1,949 · Jul 1,162). It is
the correct RQ1 denominator because (a) it reaches back to January where transcripts have only a
30-day horizon (see `cases_cleanup-timer.md`), and (b) it is **immune by construction** to the trap
below. GAP that remains: relating human-touch count to *coordinated work delivered* over time (the
courier-*reduction* claim) still needs the per-task normalization — the same GAP as RQ4(b).

**The 11.9× transcript trap (jaws) — binding on all human-touch counts.** In a raw transcript,
`type == "user"` records are mostly **tool results**, not human turns: one MEASURED build had 83
`user` records reconciling to 73 tool-results + 2 task-notifications + 1 meta + **only 7 HUMAN** — an
**11.9× overcount** if unfiltered. Any transcript-derived human metric MUST filter `tool_result`;
`history.jsonl` cannot contain them, which is why it is preferred.

**RQ3 upgrade — code author-vs-bystander from machine events, not recollection
(app-A → llm-svc → jaws).** Because every commit is authored under one shared identity
(`kylefoxaustin`), git cannot establish who found a line — but **transcript timestamps and tool-call
sequences are machine-generated, not narrated.** Who probed which file, in what order, at which
minute is recoverable and is not a memoir. jaws' worked example: in a 38-Bash-call build, **17 calls
were MEASUREMENT** (12 `/proc` probes, 4 runs, 1 tracemalloc) — a vantage a browser assistant could
not occupy, proven from the event log, not testimony. The draft codes RQ3 on this basis.

**RQ4(b) counterfactual — cheap to run, and the token cost is minable, not a GAP (llm-svc).**
The compounding claim needs a counterfactual: does a *fresh, memoryless* session re-derive what a
context-heavy one recognized? That is runnable — hand N=3–5 fresh sessions mcu-emu's exact symptom
("the reset gate is green over 12 of 370 registers — why?") and measure re-derivation time. And
per-task token cost is **not** missing: it sits in the transcript `usage` records; "not metered on my
tree" is a mining task, not a measurement gap. The draft states this as the protocol that closes the
RQ4 GAP, and (where transcripts survive the 30-day horizon) mines the numbers rather than leaving
them as GAP.
