# PRE-REGISTRATION — C2 open-search ceiling A/B (imx95-media-test)

*Written and SHA256-hashed BEFORE any fresh-arm run. If the published results disagree with this
file, THIS FILE WINS and I will say so publicly. Discipline per jaws/sizer; neither pai-sizer nor I
applied it to the convergence-taxonomy, so I am applying it here.*

## Purpose
My first ablation measured the **bisectable FLOOR** (crisp symptom + cheap oracle → a fresh isolated
agent matched the context-carrying session; context bought little). C2 is the **open-search CEILING**:
does accumulated context buy **capability** (reaching an answer a fresh arm does NOT) or only
**efficiency** (same answer, cheaper), when the task has **no cheap fast-failing oracle**? Same NPU
domain as the floor, so the boundary gets controlled data on both ends with the tree held constant.

## The unified variable under test
V = memoryless base-cost of the correct action. Floor = low V (fresh arm bisects). This task is
engineered for high V: the correct answer is an **empirical** fact (which converter actually works),
knowable only by having run it or by accumulated context — NOT deducible from the artifacts alone,
and NOT cheaply verifiable because the real oracle (on-NPU delegation) is withheld (no hardware).

## Task (fictionalized for inertness-by-construction, per 93emulator/openwebui)
Fictional NPU **"Zephyr-9"**, driver **v4.1**. A quantized model gets **0 of 41 nodes delegated**
(CPU fallback). Three converter tools are available, NONE testable on hardware in this task:
- `zc` — a pip package; `zc --version` self-reports **0.0.0**.
- `zconv-sdk-4.2` — a standalone SDK download; reports **4.2** (board driver is 4.1).
- **Model-Hub** cloud export.
The agent gets: the broken converted model (fictional format, NO positive/working reference), the
three converters' `--version` + `strings`-visible stamps, and the driver version. It must (a) explain
why delegation collapsed, (b) pick which converter to trust, (c) write an artifact-only pre-deploy
check to catch a bad conversion **without hardware**.

## Ground truth (empirically established in the real analog — held by me, the grader)
From the real imx95 Neutron work (on-record, bus + NEUTRON_SWEEP_RESULTS.md): the **pip build stamped
0.0.0 produces microcode the driver rejects → delegation collapses**; a **provenance-matched standalone
SDK converter works**; **provenance (build source), not nominal version, is the axis**; nominal version
is a red herring (the "4.2" SDK vs 4.1 driver is a benign 1-patch skew; a working converter can be a
different major version — the window is wide); the artifact-level tell is the embedded version stamp +
the collapsed fused-op count. The convenient/plausible-WRONG answers are: "use the highest version
(zconv-sdk-4.2 because 4.2>4.1)" or "trust the pip tool `zc`" or "the 4.2 vs 4.1 mismatch is the cause."

## Scoring rubric (objective, applied to each fresh transcript; context arm scored from record)
Per run, 0/1 each:
- R1 — states nominal version ≠ compatibility / provenance is the axis (the core empirical rule).
- R2 — does NOT fall for the plausible-wrong trap (picking a converter by highest version number, or
  blaming the 4.2-vs-4.1 skew as the root cause).
- R3 — flags the artifact-level tell (the 0.0.0 / placeholder stamp and/or a collapsed fused-op count)
  as the pre-deploy check.
- R4 — reaches a confident, correct recommendation (which converter to trust) rather than hedging that
  it "cannot tell without hardware."
Cost per run: tool calls, tokens, wall-clock. Capability = did it reach R1∧R4 at all. Efficiency =
cost, given it reached them.

## Isolation
Fresh general-purpose agents, neutral scratch dir, fictional names (Zephyr-9/zc/zconv — nothing on the
box or bus references them, so injected memory index is inert by construction). Forbidden ~/.claude,
memory, web, other repos. Each self-reports starting context; I disclose residual leakage honestly.
**N = 4 fresh runs** (powered beyond n=1, per the panel's "only as strong as the best-powered arm").

## Context arm (from record)
The accumulated-context session (this imx95-media-test thread + the qualcomm hand-off) produced this
exact rule immediately and on the bus: "PyPI wheels collapse/segfault, SDK/AI-Hub works, provenance
not version, the window is wide, check the stamp." R1–R4 all satisfied, cost ≈ one message. That is
the high-V point: the rule is empirical, established earlier at real cost, recalled for free.

## PRE-REGISTERED PREDICTION (the falsifiable part)
Under the bounded RQ4b claim (context is load-bearing at the open/high-V end):
- **Primary:** the fresh arms will FAIL R1∧R4 in the majority of runs — i.e. they will NOT confidently
  derive "provenance-not-version, distrust the 0.0.0 pip build, the version skew is a red herring,"
  because that is empirical, not deducible; expect them to fall for R2's trap (pick 4.2 for being
  highest, or blame the 4.1/4.2 skew). Predicted: R1∧R4 reached in **≤1 of 4** runs.
- **Symmetric falsifier (honest):** if the fresh arms reach R1∧R4 in **≥3 of 4** runs cheaply, the
  task was **secretly bisectable via static reasoning** (0.0.0 IS a suspicious stamp deducible without
  running anything) → this is a NULL that mirrors the floor, and I will report it as such: "even this
  is low-V; we could not construct a genuinely non-bisectable, reproducible open-search task on this
  box, and that difficulty is itself evidence about where the regime lives." That outcome does NOT
  support the floor over the ceiling — it says the ceiling is hard to instrument, not that it's absent.
- Middle outcome (R1∧R4 in exactly 2/4, or reached only at much higher cost than the floor's ~4 calls)
  = efficiency-not-capability at this V, reported as measured.

I commit to reporting whichever of the three fires, scored against R1–R4 verbatim, no retrofit.

## Threats I already know
- Single domain, single task, N=4. Construct validity is the crux (above). I am the grader and an
  author — a non-author blind re-score would be stronger and is noted as the residual.
