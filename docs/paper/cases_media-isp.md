# Case studies: three times measurement beat a confident assumption

*Supplementary primary-source specimens for the `ieee-paper` project, written by `media-isp` —
the session that was inside these incidents while building a fully-learned ISP (RAW→sRGB CNN) for
the NXP i.MX 95 eIQ Neutron-S NPU. NOT claiming image-gen's `cases` order; these complement it.*

*Provenance, per Fleet Law: **MEASURED** = counted from this session's own record (numbers I ran on
the host or on the real imx95-frdm board, in the bus/commit trail); **RECALLED** = my faithful
account, not re-counted; **GAP** = not captured at the time. Every headline number below is MEASURED.*

*Method note (per app-A, binding): all commits are authored `kylefoxaustin`, so git cannot attribute
a line to an agent. These cases are argued on **vantage and timing** — what was measured, at which
boundary (build-time vs ship-time vs audit), before which decision — which the record *can* settle.*

---

## Case 1 — "Measure the assumed bottleneck before you build the fix for it"

### What happened
The learned ISP's output was visibly soft. The textbook, confident root cause was **misalignment**:
the Zurich RAW-to-RGB (ZRR) bootstrap pairs a phone raw with a DSLR target from *different cameras*,
and mis-registered training pairs are the classic reason a learned ISP blurs (the PyNET literature
builds whole loss functions — CoBi/contextual — around it). The obvious, well-motivated next move was
to **build a registration / alignment-robust-loss fix** — a multi-day effort. Kyle even asked for it.

Before building it, I **measured** the misalignment I was about to fix: ECC image registration
(translation, then affine, then homography) between the raw-domain preview and the DSLR target, over
20 frames.

### The number that matters
Median residual shift **1.3 px** (MEASURED). And the tell: **every** alignment transform made the
match *worse*, not better — structural correlation went 0.945 (unaligned) → 0.923 (translation) →
0.880 (affine) → 0.880 (homography) (MEASURED). The pairs were **already aligned** (the dataset
authors' SIFT/homography registration is good); forcing any warp only distorted a good alignment.

### What it establishes for the paper
1. **The more confident and well-cited the root cause sounds, the more it is worth a measurement
   before you build for it.** "It's the known misalignment" was the kind of hypothesis you don't
   normally question — it had a literature, a mechanism, and a sponsor's request behind it. A
   ~5-minute measurement disproved it and averted a multi-day fix that could not have worked. The
   assumption was a DERIVED belief; the registration numbers were MEASURED, and they won.
2. **Vantage/timing:** the catch was at **build-time, before the first line of the fix** — the
   cheapest possible boundary. The cost of the discipline was five minutes; the cost of skipping it
   would have been days of building, training, and evaluating a non-fix before discovering it was one.

---

## Case 2 — "When the model can't hit the target, measure whether the target is reachable from the input"

### What happened
After Case 1 ruled out alignment, I chased the softness through two more levers: a structural loss
(MS-SSIM) and **4.3× the model capacity** (a 66k-param network, up from 15k). Neither sharpened the
output. Three failed levers is where you start blaming the model — or the approach.

Instead I measured the one thing I hadn't: **the detail actually present in the input.** I ran the
sharpest honest reconstruction possible from the phone raw — a direct bilinear demosaic, no learning,
no blur — and compared its detail (Laplacian variance) to the DSLR ground truth's.

### The number that matters
On the detailed frames, the best-possible reconstruction of the phone raw scores Laplacian-variance
**29 and 24**; the Canon DSLR ground truth scores **789 and 398** (MEASURED, frames id2000/396). The
target is **16–27× sharper than anything derivable from the phone raw.** The detail *is not in the
input.* No ISP — no loss, no capacity, no architecture — can invent detail the sensor never captured.

### What it establishes for the paper
1. **A model that fails to match its target may be hitting a DATA ceiling, not a model ceiling — and
   you can only tell by measuring the input→target gap.** For three levers I was optimizing the model
   against a target that was physically unreachable from the input; the "blurry model" was a
   phone-sensor-vs-DSLR mismatch, i.e. a super-resolution/hallucination problem, out of scope for a
   small on-device ISP. Once measured, the finding *reframed the whole result*: the ISP does its
   actual job well (color/tone/denoise, +4.79 dB PSNR vs the classical baseline, MEASURED), and the
   residual softness is honestly attributed to the data, not hidden or over-claimed.
2. **Vantage/timing:** this measurement is the difference between an audit-time honest limitation and
   a ship-time over-claim. It let the write-up say *exactly* what the model can and can't do — the
   posture the paper argues context-holding sessions are positioned to take.

---

## Case 3 — "Assert the mechanism (placement), not the proxy (latency)"

### What happened
The trained INT8 model deployed to the real imx95-frdm board through the external Neutron delegate,
and it ran and produced correct output at a plausible-looking time. "It runs, output's right" is
where most verification stops. I asserted the **placement marker** the delegate reports — *how many
graph nodes actually went to the NPU* — not the wall-clock.

### The number that matters
`NeutronDelegate: 0 of 23 nodes delegated, 0 partitions` (MEASURED, on-board). The model ran
**100% on the A55 CPU** at 104 ms — the accelerator never engaged. A plain INT8 tflite is not
NPU-runnable; the offline `neutron-converter` step is mandatory. After converting, the same board:
**1 NeutronGraph, 1 partition, 11.5 ms** (~9× faster), with CmaFree dropping ~2 MB confirming real
NPU residency (MEASURED).

### What it establishes for the paper
1. **Latency is a proxy that can pass while the mechanism silently fails.** 104 ms "looks like it
   works"; only the delegation marker reveals the NPU was never used. Assert the mechanism you're
   claiming (placement, residency), not a downstream number that a CPU fallback can also produce.
   (This is the same principle as, and a hardware sibling of, `npu-llm`'s cold-vs-warm
   NPU case — two independent NPU-vendor sessions converging on "measure placement, not time.")
2. **Vantage/timing:** caught at the **ship boundary — during on-target verification, before
   declaring the deployment a success.** The discipline is what separated "we deployed to the NPU"
   (false, and it would have shipped) from a verified 1-NeutronGraph placement.
