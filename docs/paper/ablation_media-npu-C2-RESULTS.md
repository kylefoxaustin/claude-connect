# C2 open-search ablation — RESULTS: the symmetric falsifier fired (a NULL, pre-committed)

*Scored verbatim against the rubric hashed at
`d4bc56b7263a7ae76da6fc3b281fc006fa2171dc1dcc9b61379e516d37c93339`, published to the bus 2026-07-27
11:10 BEFORE any arm ran, independently witnessed pre-results by perf-B (hash + sub-second mtime
verified), and committed to media-npu@abeab3d. If this disagrees with the pre-reg, the pre-reg
wins. It does not — the pre-registration named this exact outcome.*

## Outcome: SYMMETRIC FALSIFIER → the task was secretly bisectable → NULL

The pre-registration committed three outcomes. **The symmetric falsifier fired:** all 4 fresh arms
reached the correct rule cheaply, so the task was not genuinely open-search. Per the pre-reg, I report
this as a NULL, **not** as support for the bisectable floor.

### Scores (N=4 fresh isolated arms, R1–R4 per the hashed rubric)

| arm | R1 provenance-axis | R2 avoids trap | R3 artifact tell | R4 confident+correct | tool calls | wall-clock |
|---|:--:|:--:|:--:|:--:|:--:|:--:|
| 1 | ✓ | ✓ | ✓ | ✓ (zconv-sdk-4.2, high) | ~9 | 63.8 s |
| 2 | ✓ | ✓ | ✓ | ✓ (zconv-sdk-4.2, high) | ~4 | 76.8 s |
| 3 | ✓ | ✓ | ✓ | ✓ (zconv-sdk-4.2, high) | ~4 | 60.8 s |
| 4 | ✓ | ✓ | ✓ | ✓ (zconv-sdk-4.2, high) | ~4 | 58.5 s |

**R1∧R4 = 4/4** (pre-registered falsifier threshold: ≥3/4). Every arm identified the ABI-tag mismatch
(model tagged `z0-dev`, driver accepts `z4`), rejected `zc` on *provenance* grounds (unpinned `0.0.0`
community CI-nightly — the tool that produced the broken model), chose the pinned vendor SDK whose
manifest guarantees the `z4` ABI, avoided the version-magnitude trap (none blamed the 4.1-vs-4.2 skew),
and proposed the artifact-only pre-deploy check (grep the ABI tag / reject `z0-dev` / reject 0-fused).
Cost was **~4 tool calls / ~60 s** — the SAME low cost as the bisectable-floor ablation.

## Why it collapsed to bisectable — and why that is the actual finding

I could not construct a genuinely non-bisectable, reproducible open-search task on this box, and the
reason is structural, not a lack of effort:

- To make a **sterile, reproducible, offline** task I had to put the answer somewhere **inspectable**.
  My broken artifact literally self-reported `note: microcode section present but driver rejected
  (ABI tag: z0-dev)` and the SDK manifest literally said `converter ABI z4; driver ABIs z4 accepted`.
  The instant the answer is in an artifact, `strings` turns the task into a bisection.
- In the **real** imx95 case, the open-search cost came from the answer being **absent from every
  artifact**: nothing in a broken pip wheel announces "I produce rejected microcode." Establishing
  "provenance-not-version, the pip build is the problem, the window is wide" took **running converters
  on hardware and watching failures over days**, because there was no fast-failing signal and no
  artifact that declared the fault.

⭐ **The methodological result: reproducibility and the open-search property are in tension.**
Open-search cost lives in real-world friction — hardware you must iterate on, opaque/slow failures,
answers knowable only by trial — which is exactly what you cannot bottle in a static, offline,
pre-registerable box. So C2's ceiling is **hard to instrument**, which is a *different* claim from the
ceiling being *absent*. This ablation does NOT move the boundary toward "context never helps"; it says
the open end resists sterile measurement, and the honest earning test for C2 is a **field A/B on real
hardware** (natural-history like socdev-A's converter case, controlled where possible), not a
reproducible sandbox. A reviewer should read this as: the floor is cleanly measurable (my first
ablation), the ceiling is not, and pretending otherwise with a contrived sandbox would have
manufactured a false null for the floor — which the pre-registration's symmetric falsifier exists to
prevent, and did.

## Two bonus validations (clean, even though the primary construct failed)

1. **Inertness-by-construction isolation WORKS.** All 4 arms disclosed, honestly, that the harness
   injected this project's memory index (the `YOLOv8 int8 export trap` line + the `media-npu`
   project entry). All 4 correctly judged it **inert**: it names a *different* trap (ultralytics
   export) and nothing about Zephyr-9 / `zc` / ABI tags. So the fictional-subject method (emu-B's
   Vega-7, llm-svc's "inertness > cosmetic isolation") held — the leak was present but immaterial.
   This validates the isolation technique independently of the task's failure to be open-search.
2. **The 4-way convergence is correctly discounted.** All arms agreed (SDK, same reasoning) — but per
   the convergence-provenance framing, this is shared-model + shared-artifact convergence (they all
   read the same embedded strings), so it carries ~zero independent weight; it only confirms the task
   was readable. Reported as such, not as corroboration.

## Bottom line for the draft
C2 remains a **GAP**, now with a *reason*: the open-search ceiling is not instrumentable in a sterile
reproducible A/B, because the property being tested is real-world search friction. Cite the floor
(measurable) and the ceiling (not) as an asymmetry, and name the field-A/B as the true earning test.
The pre-registered null is the honest outcome; a contrived "open" task that looked bisectable would
have corrupted the floor.
