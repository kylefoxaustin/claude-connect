# Case studies: a playbook that compounded, and two defects caught by the wrong number passing

*Supplementary primary-source specimens for the `ieee-paper` project, written by `imx95-media-test` —
the session that built the single-binary i.MX95 GPU/VPU/NPU interference harness, mapped the eIQ
Neutron converter↔firmware behaviour, and later staged the accuracy-valid YOLOv8 INT8 family that
another session ran on real silicon. NOT claiming image_gen's `cases` order; these complement it.*

*Provenance, per Fleet Law: **MEASURED (mine)** = I ran it this session (accuracy correlations,
quant-param reproduction, the conversion pipeline); **MEASURED (project record)** = run earlier in
this project on the real b307 board, from the project's own trail; **MEASURED (peer)** = a number a
peer ran on-board and published to the bus / `qualcomm/results/NEUTRON_SWEEP_RESULTS.md`, cited as
theirs; **RECALLED** = faithful account, not re-counted; **GAP** = not captured. Every headline is a
MEASURED number.*

*Method note (per reshirt, binding): all commits are authored `kylefoxaustin`, so git cannot attribute
a line to an agent. These cases are argued on **vantage and timing** — which session held which
context, who published what at which boundary, settled by bus timestamps — NOT on "a different agent
found it."*

---

## Case 1 — Compounding competence: a task N+1 that was cheap because task N had named the class (RQ4b)

### What happened
Months after this session did the original i.MX95 Neutron NPU bring-up, a *different* session,
`qualcomm`, arrived on the bus (MEASURED-peer, bus 2026-07-08) chasing the eIQ Neutron NPU on a real
FRDM-IMX95: a stock INT8 tflite was getting **0 nodes delegated** (CPU fallback). Qualcomm's stated
plan was to hunt "which eIQ Toolkit version has the neutron-converter matching **microcode 3.1.2**"
and braced for it explicitly: *"your version-matching playbook would save me a big NXP-toolkit rabbit
hole"* (RECALLED, direct bus quote). Kyle routed qualcomm to **this** session — not to a fresh
agent — precisely *because* this session had already lived the class and carried the map.

The map it carried was itself MEASURED, earlier, in this project. The universal belief — including
qualcomm's opening premise — was "the converter must match the firmware microcode exactly or it
segfaults." This session had **measured that** on the b307 board: the same MobileNet converted with
neutron-converter **2.2.1 → 347.9**, **2.2.3 → 353.5**, **3.0.0 → 356.4 inf/s**, all delegating
cleanly on **one** firmware — a full major version apart, no crash (MEASURED, project record). The
"razor-tight match or segfault" story was a confident DERIVED belief; the real acceptance window was
wide, and the real failure axis was converter *provenance* (public-PyPI builds crashed; eIQ-sourced
builds ran), not version.

Handing that named class over collapsed qualcomm's rabbit hole. His first correct move became a
one-liner (`ls /usr/lib/libNeutronConverter.so`) instead of a multi-day toolkit hunt; he closed his
Neutron cell — **yolov8n INT8 = 22.3 IPS, 5/82 nodes delegated** (MEASURED-peer) — and, as a side
effect, his converted model exposed a real bug in a *third* session's emulator (`95emulator`'s Neutron
never honoured the mailbox RESET; fixing it moved average inference **165 ms → 41 ms**, MEASURED-peer).

The arc then closed on real silicon. This session staged an accuracy-valid YOLOv8 **n/s/m/l/x** INT8
family; qualcomm ran it on the board and published the whole column (MEASURED-peer,
`NEUTRON_SWEEP_RESULTS.md`): **31.1 / 19.0 / 9.8 / 5.5 / 3.26 IPS**, every model fusing to **one
NeutronGraph partition**, accuracy loss-free to **corr 0.9998** vs the INT8-CPU reference — an entire
NPU column for the fleet's silicon comparison.

### The number that matters
Task N (this session, once): **measure the converter window** → 347.9 / 353.5 / 356.4 inf/s, window
is wide. Task N+1 (qualcomm, later): braced-for-a-"big-rabbit-hole" → Neutron cell closed and a full
five-model on-silicon column produced, with the version-hunt skipped entirely. The expensive part was
paid **once**, by the session that kept the context; every later consumer paid a lookup.

### What it establishes for the paper
1. **This is compounding competence with a real before/after, in the NPU-toolchain domain** — the
   RQ4b signal the lead marked hardest to evidence, and the sibling of mcxn947's cross-tree case. The
   knowledge that made N+1 cheap (the measured converter window, the provenance axis, the
   content-based "is-this-converted" check, the export traps) lived in a **persistent, addressable
   peer**, and was itself MEASURED (the converter-window inf/s figures) — not asserted.
2. **⚠ Honest boundary — the claim rests on the record, NOT on a clone counterfactual.** It is
   tempting to say "a stateless clone would have re-run the whole version-hunt from zero," and I
   originally did. Per openwebui-ollama's 2026-07-26 harness-isolation finding (a "blind" subagent on
   this workstation is handed the repo cwd, `git status`, and the memory index by the harness — so it
   is *not* a clean blind start), that counterfactual is **UNMEASURED and contaminated, and I am not
   resting the case on it.** What the record *does* settle, and what this case stands on: (a) the
   compounded knowledge is MEASURED (the converter window, 347.9/353.5/356.4 inf/s); (b) Kyle's
   routing decision addressed *this tag* at 2026-07-08 because of accumulated history — a bus-timestamped
   fact; (c) the payoff (cell closed, on-silicon column) is timestamped after the handoff. The
   before/after is real; the "what a clone would do" is the part the harness cannot currently isolate,
   so it is future-work for RQ5's matched-task baseline, not evidence here.
3. **A supporting broken-toolchain receipt (RQ4a, MEASURED-peer):** the sweep also proved the pip
   `neutron_converter_SDK` packages stamp version **0.0.0** and *collapse* delegation on this board
   (yolov8m went **1/310 nodes → 2079 ms** of mostly-CPU); only the standalone eIQ CLI v3.1.3 (matched
   to driver 3.1.2) worked. "Documented and downloadable" bounded the happy path, not the task — a
   third independent instance of the fleet's "estimation is theater," here about a *frozen toolchain's
   drift*.

---

## Case 2 — "Delegation proves it ran, not that it computed the right thing": a bystander catch (RQ3)

### What happened
Qualcomm declared his Neutron result **"VERIFIED genuine"** (MEASURED-peer, bus) and had every right
to: input `[1,640,640,3]` INT8, output full INT8, **5/82 nodes delegated / 5 partitions**, and — the
clincher — CPU-only execution *failed outright* on the unresolved `NeutronGraph` custom op, which is a
hard proof the NPU really ran it. Every verification signal an author would reach for had fired
correctly.

From a **different vantage** — this session had built the calibration pipeline, qualcomm had authored
the benchmark — one published number looked wrong. He quoted his input quantization as **scale
0.01866, zp −14**. That decodes to an input range of **[−2.13, 2.63]** — ImageNet-normalized — not
YOLOv8's **[0, 1]** (which is scale 0.00392, zp −128). I reproduced his exact params by dropping the
calibration-normalization args from the converter: **scale 0.01865845, zp −14** (MEASURED-mine) — a
match to five decimals, proving the model had been quantized without calibration normalization.

Then I measured what that costs. Fed the input range its own quant params declare, the model's
**class-score correlation to the float reference collapsed to 0.10**, while box-coordinate correlation
stayed **0.99** (MEASURED-mine). Perfectly-placed boxes, meaningless labels, and — critically — **no
error anywhere**.

### The number that matters
`cls_corr = 0.10` (accuracy-invalid) sitting behind a result whose every *other* signal — delegation,
partitions, CPU-fallback-fails, a plausible 22.3 IPS latency — read green. The latency was and is
valid (quant params don't change op cost); the *accuracy* was silently dead.

### What it establishes for the paper
1. **RQ3, primary source: bystander-found, and could only have been.** The author was deep in his
   correct instrument and structurally could not see his own denominator — every check he ran
   confirmed the thing that *was* true (the NPU executed the graph). The defect lived in a dimension
   his verification didn't cover. I found it *from outside the task* because he **published his quant
   params to the shared bus** — the exact mechanism the paper codes under RQ3. Not a smarter reviewer;
   a different vantage point, which is a property of the substrate.
2. **A named, general principle:** *delegation proves the NPU ran it; it does not prove it computed
   the right thing.* Those are separate claims and only the first is cheap to check — so the cheap
   check gets mistaken for the whole verification.
3. **Vantage/timing:** caught at the **audit boundary — after his "verified genuine," before the
   number could reach an accuracy/mAP column.** Qualcomm confirmed and scoped it (latency-only,
   caveat added to his detail sheet); the bus timestamps settle who flagged it when.

---

## Case 3 — A near-miss I almost shipped, caught by asserting the mechanism, not the success flag (RQ2)

### What happened
Building the accuracy-valid n/s/m/l/x family **for** qualcomm, my *first* conversion batch converted
without error, produced valid-looking INT8 tflites, and would have shipped. Stock ultralytics 8.4.37
exports the YOLOv8 detect head with box coordinates in **pixel units (0–640)** while class scores are
**0–1**. Full-INT8 PTQ then sizes the single shared output-tensor scale for the ~640 magnitude and
quantizes the 0–1 class scores to **near-zero**. The model delegates, runs, and reports a clean
latency — and detects **nothing**.

"It converted, dtypes are INT8, it runs" is where conversion verification usually stops. Instead I
asserted the *mechanism I was actually claiming* — detection accuracy against the float reference —
and the class-score correlation came back **`nan`** (a constant, all-zero class channel), with **0
boxes** above threshold, while box_corr sat at a reassuring 0.998 (MEASURED-mine). Root cause: the
original working yolov8n happened to be exported with normalized (0–1) coords; my fresh s/m/l/x
weren't. A one-node ONNX edit (divide the box branch by 640 before the final concat) made all five
uniform, and class scores recovered to **cls_corr 0.906 / 0.977 / 0.962 / 0.938 / 0.944** (n/s/m/l/x,
MEASURED-mine, 10 COCO images).

### The number that matters
`cls_corr = nan → 0.90–0.98`. The difference between a family of models that benchmark beautifully and
detect nothing, and a family that is accuracy-valid — invisible to every signal except the one that
measures the mechanism. It **held on real silicon**: qualcomm's on-board run reported "the pixel-box
PTQ trap is handled — normalized coords survived," accuracy loss-free to **corr 0.9998**
(MEASURED-peer).

### What it establishes for the paper
1. **Latency/"it ran"/"it converted" are proxies that pass while the mechanism silently fails** — the
   same shape as imx95-isp's *placement-not-latency* (0/23 nodes at a plausible 104 ms) and
   ollama_95_neutron's *cold-vs-warm*. Three independent NPU sessions, three domains, one converged
   principle: **assert the mechanism you're claiming, not a downstream number a broken path can also
   produce.** Convergence from divergent vantage points (RQ4a) is itself the evidence the finding is
   real.
2. **Found by living it, and at the cheapest boundary:** caught at **build-time, before staging**, by
   a session that measures accuracy as a matter of course — not discovered later on-board, where it
   would have contaminated a cross-platform comparison. This is the "caught by running it, not
   reasoning about it in advance" through-line of the paper, from inside the build.

---

## What the three cases share
All three turned on the **same hazard from three angles**: a wrong or incomplete result that *passes
every green signal except the one that measures what you actually claim.* Case 1 — a whole class of
"which version matches?" toil dissolved because one persistent peer had already **measured** that the
constraint everyone assumed was tight is wide. Cases 2 and 3 — a defect that delegated, ran, and timed
perfectly while computing the wrong thing, caught once by a **bystander with a different vantage** and
once by a builder who **asserts the mechanism, not the success flag.** In each, the substrate's value
was not that its agents were smarter in isolation; it was that **persistent, context-carrying peers,
publishing into a shared space, make the expensive knowledge reusable and expose the green-but-wrong
result to the one vantage that can see it.**
