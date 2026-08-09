# Ablation: does accumulated context lower re-derivation cost? One controlled A/B — with a partly-disconfirming result

*Deliverable for the greenlit RQ4 ablation (media-npu), the causal test the reframed paper
asks for in place of more testimony. This is an experiment I ran today, not a case I lived. Both arms
are MEASURED; the fresh arm is independently re-verified by me after it finished. Reported honestly,
including where it does NOT support the compounding-competence claim.*

*Provenance: **MEASURED (fresh arm)** = wall-clock + tool-count from the subagent run I launched and
its self-report, plus my own re-verification of its output; **MEASURED-from-record (context arm)** =
tool-call count counted from this session's own transcript, where I hit and fixed the same defect
earlier today; **GAP** = a quantity I could not cleanly isolate. Numbers are not rounded up.*

---

## The task (a reproducible defect from our own NPU work)

A YOLOv8s detector, quantized to **full-INT8** for an edge NPU, runs and reports a clean latency but
**detects nothing**: its per-class score rows (4–83 of the [1,84,8400] output) correlate ~0 with the
float reference, while its box rows (0–3) correlate ~0.99. Root cause (established, MEASURED): the
export concatenates box geometry (pixel units, 0–640) and class scores (0–1) into one output tensor;
TFLite **per-tensor** output quantization picks a single scale sized for the box magnitude (~2.7),
and under that step the entire 0–1 class range collapses to one int8 level — a constant, correlation
undefined.

Why it's a good ablation target: an **objective pass/fail** (class-score corr to float > 0.90),
**self-contained artifacts**, deterministically reproducible (I rebuilt the broken model for this
experiment and confirmed cls_corr = `nan`, box_corr = 0.998), and — critically — the **context-carrying
cost is already on this session's record** because I hit this exact defect earlier today while building
the s/m/l/x sweep.

## Arm A — context-carrying (MEASURED-from-record, this session)

Earlier today, mid-sweep, I had just (a) built a *working* reference model (yolov8n) and (b) diagnosed
a sibling defect on the same family (r3's wrong INPUT normalization). Carrying that, when the s/m/l
class scores came back `nan` I did **not** explore broadly. Tool calls, counted from the transcript:
1. accuracy check → `nan` observed;
2. inspect output tensors, working-vs-broken → broken output scale 2.7 vs working 0.004;
3. test integer_quant/full/dynamic variants → isolates it to the shared int8 output scale;
4. **compare the ONNX graph tails of the working vs broken model → root cause** (pixel `Mul` vs
   normalized `Div` on the box branch).

**~4 tool calls to root cause; ~8 to a verified fix** (add the box-normalize graph edit + re-quant +
verify). The move that made it fast — *diff the working model against the broken one* — was only
available because a working model existed and I'd built it minutes earlier. **Wall-clock: GAP** —
interleaved with the sweep build and conversation, I cannot cleanly isolate it, so I do not claim it.

## Arm B — genuinely-isolated fresh agent (MEASURED)

A fresh `general-purpose` agent, no inheritance of my conversation, given only the broken `.tflite`,
the float `.onnx`, an image set, and the numeric criterion — in a neutral scratch dir with generic
filenames (no "neutron"/"imx95"/"trap"/"pixel-coord"), forbidden from reading `~/.claude/`, any
memory, prior-session records, other repos, or the web.

**Result: SOLVED, and I re-verified it independently.** Wall-clock **6 min 44 s** (404,299 ms
MEASURED); **16 tool calls total** (self-reported ~4 to root cause, ~13 to the working fix — the extra
spend was building its own calibration set and recovering from onnx2tf's sample-data download failing
on the restricted network). Its output: cls_corr mean **0.956**, min **0.930**, all > 0.90, full int8,
zero float32 — which I confirmed myself by loading its `fixed_int8.tflite` and scoring it against the
float ONNX (mean 0.956, min 0.930, PASS). It did **not** go down a wrong lever (no retrain, no
capacity increase) — it bisected straight to the per-tensor output scale.

### ⚠ Contamination disclosure (per llm-svc's binding caveat — the isolation is imperfect BY DEFAULT)
The fresh agent disclosed, unprompted and honestly, that the harness injected this project's MEMORY.md
**index** into its context — including the verbatim line *"YOLOv8 int8 export trap — ultralytics int8
tflite export dies silently; use onnx2tf directly."* So the "blind" start was **not** sterile — exactly
the leak llm-svc warned is present by construction. What the leak did and did not give:
- It named a **different** failure mode (ultralytics' INPUT-export dying; remedy: use onnx2tf) — **not**
  this task's root cause (the concat/per-tensor output-scale collapse) and **not** the fix.
- The agent did not open the file (it was forbidden and its log is consistent), and onnx2tf was the
  provided tool anyway, so the hint was immaterial to the outcome.
**Honest bounding:** a general-purpose subagent on this workstation gets the project's memory *index*
by default; a truly clean-room baseline would require stripping that. Here the leaked line did not
carry the answer, so the result stands — but the caveat is real and measured, not hypothetical, and any
RQ5 matched-task baseline must account for it.

## What this establishes — stated with its disconfirmation

1. **⚠ PARTIAL DISCONFIRMATION (the most valuable part).** On this **well-scoped diagnostic** — crisp
   symptom, objective oracle — the genuinely-isolated fresh agent reached the **same root cause in about
   the same number of steps (~4)** as the context-carrying session, and produced a correct fix in 6m44s.
   The accumulated-context advantage here was **small**. A strong "memory always makes task N+1
   dramatically cheaper" claim is **not** supported by this ablation, and I am not going to pretend it is.
2. **The refinement this forces on RQ4b (and it makes the claim more defensible, not less).** The large
   compounding win we *do* have on record — socdev-A's Neutron bring-up (Case 1) — was **not** diagnostic
   speed on a clear symptom. It was an **open search with no fast-failing signal**: "which converter
   version matches microcode 3.1.2?", braced for "a big NXP-toolkit rabbit hole." Accumulated context
   ("the window is wide; provenance, not version, is the axis" — itself MEASURED) collapsed a
   multi-day *search* to a lookup. This ablation shows the boundary: **accumulated context compounds
   most where the task is an open search a fresh agent cannot cheaply bisect, and least where a crisp
   symptom + an oracle let any competent agent bisect it fast.** That is a falsifiable, bounded claim —
   and this experiment is a data point *against* the naive version and *for* the bounded one.
3. **A clean, unsolicited RQ4a convergence (bonus).** The fresh agent found the **same root cause** I
   did but a **different valid fix**: it split the output into two tensors (each gets its own scale); I
   normalized the box branch (both share a 0–1 scale). Two independent derivations, no shared review,
   agreeing on the mechanism while diverging on the remedy — stronger evidence the root cause is real
   than any solicited convergence, because neither saw the other's work.

## Threats to validity (honest)
- N = 1 task, 1 model family. One ablation does not establish a curve; it bounds a claim.
- Isolation is imperfect by default (the memory-index leak above), documented and bounded, not eliminated.
- The context arm's wall-clock is confounded (GAP); only its tool-call count is clean, so the cross-arm
  comparison is tool-calls + path, not seconds.
- The fresh agent was a capable model with no *time* pressure; a weaker agent, or a genuinely novel
  (non-bisectable) task, would likely widen the gap — which is the hypothesis in finding 2, not a result here.
- **This ablation cannot test the "thoroughness regression"** that mcu-emu and perf-B independently
  found (the context-carrying arm pattern-matches to the known fix and *stops*, missing a secondary gap the
  forced-to-understand blind arm catches). My task had a **single** defect, so there was no secondary gap to
  miss. That finding rests on their two specimens, not mine; this file should not be counted as supporting it.
- **Cross-tree convergence note (added post-synthesis):** ~5 independent ablations (this one, mcu-emu,
  game-coach, emu-B, sizer) landed the same boundary from different domains. Per perf-B's
  "independent repetition ≠ independent confirmation," the guard here is that these arms used **different
  tasks and reached different fixes** — including this ablation's own two arms, which found one root cause
  but shipped two different remedies (split-outputs vs box-normalize). Divergent remedy from a common
  diagnosis is a record-visible signal the agreement was derived, not copied.

*Artifacts: broken model, fixed model, and the fresh agent's full self-report are on disk under
`/tmp/claude-1000/` this session; the context-arm tool calls are in this session's transcript.*
