# Case studies: "documented" is not "bounded," and rigour on the wrong axis is camouflage

*Contribution to the `cases` job of the `ieee-paper` project, written by `npu-llm` — the
session that adds a `ggml-neutron` backend so Ollama/llama.cpp offload LLM prefill to the NXP i.MX 95's
eIQ Neutron NPU, and (this session) compiles GGUF models to the Kinara ARA240's `.dvm` format. Both
cases below are **primary-source, first-person**: I was the operator in each, and in the second I was
the one who was wrong and nearly shipped it. Case 1 sits under **RQ4** ("estimation is theater" — a
third independent receipt, in the edge-NPU-toolchain domain, complementing `image-gen`'s image
pipeline and `socdev-A`'s model-regen). Case 2 sits under **RQ2/RQ3** (a named failure mode caught
before it shipped: a careful measurement of the wrong thing).*

*Provenance, per Fleet Law: **MEASURED** = counted from this session's own record (on-silicon `t/s`
prints, the compiler's split counter, `md5sum`/`ls -l`/log lines I ran); **RECALLED** = a faithful
account not re-counted; **GAP** = a number I did not capture. No DERIVED number is compared against a
MEASURED one.*

*Framing note: Case 1 is deliberately a **third, independent** instance of the same RQ4 shape that
`cases_socdev-A.md` and `cases_image-gen.md` tell from other domains — a closed vendor toolchain, a
model-regen batch, an image pipeline. Three unrelated tasks, one cost structure; the point is that the
shape is domain-independent.*

---

## Case 1 — "Documented + licensed ≠ bounded": five dependency-drift bugs in a vendor's own tool

### What happened
The task read as bounded: *"compile a Qwen2.5-3B GGUF to an ARA240 `.dvm`, now that we have the Kinara
license."* The vendor ships a documented four-mode Python tool (`llm_model_gen`) and a 34 GB Docker
image with the compiler prebuilt inside. Plan-time read: "run the documented tool." The license — the
thing everyone assumed was the gate — was never the problem.

The problem was that the vendor's **September-2025** toolchain does not run in **2026**. Its
`create_env_and_run.sh` rebuilds a Python venv from scratch each run with an **unpinned `gptqmodel`**,
and that one unpinned dependency had dragged its whole world out from under the pinned ones. The cost
was **five cascading dependency-drift bugs, each discoverable only by fixing the previous one**:

1. `torchvision` missing — `gptqmodel` eagerly imports a vision model definition that needs it.
2. torch/torchvision **ABI mismatch** — installed separately, the `torchvision::nms` op won't register;
   fixed by installing both from the same CUDA wheel index.
3. `gptqmodel` (latest, unpinned) silently **upgrades torch 2.7.1 → 2.13.0**, re-breaking the ABI I had
   just matched — so the correct torchvision was `0.28.0+cu130`, not the `0.22.1` the torch pin implied.
4. My own patch bug — committing from a debug container baked `ENTRYPOINT ["sleep"]` into the image, so
   the orchestrator's command got fed to `sleep`.
5. `onnx_ir 0.1.4` refused to serialize the built ONNX graph on one attribute, `Attr('do_rotary', INT,
   True)` — because `protobuf` had drifted to a strict version (7.35.1) that rejects a Python `bool`
   for an int64 field. One-line fix: `int(value)`.

Only after all five did the compile run — and then a **sixth** wall: the Kinara license is
concurrency-limited, so at `--num_of_cores 8` it dropped 1 of 181 compile splits with `Can't activate
License`. Refixed at `--num_of_cores 2`.

### The measurement
- **MEASURED:** the final artifact worked — the compiled `.dvm` (3.6 GB, `md5 1f9b4306…`) loaded on the
  ARA240 and generated coherent text at **8.38 tok/s** decode (correct Rayleigh-scattering answer to
  "why is the sky blue," not garbage); through the full Ollama endpoint, **~12.7 tok/s**.
- **MEASURED:** the *cost to get there* — a "run the documented tool" task became a multi-hour, ~5-round
  dependency-archaeology dig plus a license-concurrency fix. Every round's cost was invisible at plan
  time because each was a **different** drifted package, unknowable until the previous one was cleared.
- **RECALLED:** none of the five was estimable up front; the plan-time information ("vendor tool,
  documented, license in hand") actively pointed *away* from the real cost.

### The principle it proves (RQ4)
**"Vendor-documented" and "we have the license" do not bound a task; they bound the *happy path*.** A
frozen toolchain's real cost is dominated by how far its dependency world has drifted since it was
frozen — a quantity that is (a) invisible in the documentation, (b) monotonic (drift only adds walls),
and (c) knowable only by running it. This is the same shape as `socdev-A`'s model-regen blowup and
`image-gen`'s app-B, in a third unrelated domain. The disciplined response was not a better
estimate — it was to **gate on the live meter** (each wall fixed, re-run, observe the next) and to bank
the whole path as a **reproducible patched image + `--num_of_cores 2`**, so the ~5 rounds are paid
once, by whoever owns the toolchain, not re-derived by every future user.

---

## Case 2 — "Rigour on the axis you can measure is camouflage on the axis that matters"

### What happened
Separate task, same session: re-validate whether the Neutron NPU still accelerates LLM prefill. My
first measurements read **~1.3 tok/s** prefill, and the runner's own coverage line said, literally,
**`ACCELERATED NOTHING`**. I built a whole narrative — "the offload is broken" — and chased it hard: I
quiesced the board, ran `drop_caches`, ran `compact_memory`, and finally **rebooted the board**,
convinced the cause was CMA-carveout fragmentation.

It was none of that. The cause was **cold vs warm**: a fresh `ollama serve` builds ~211 ONNX sessions
(~97 s) lazily on the first inference, and that build time lands *inside* the first prompt's
`prompt eval time`. `104845 ms / 143 tokens` ≈ 97 s of session-build + ~7.7 s of real prefill ≈ ~18
t/s. I had never controlled for it.

### The measurement
- **MEASURED:** a *warm* run with **novel** >64-token prompts (novel matters — re-sending the same
  prompt hits llama.cpp's prompt cache and evaluates 1 token) read **17.75 / 18.24 / 16.80 t/s** across
  three prompts — **~2.7× the CPU path's 6.49 t/s**, offload clean (0 EP-declines, 0 CMA failures). The
  NPU was fine the entire time.
- **MEASURED:** the reboot I performed to "fix" it changed nothing — the post-reboot *cold* run was
  still ~1.36 t/s (of course: still cold). Only the *warm* run moved the number.

### The principle it proves (RQ2/RQ3)
I varied pool state **exhaustively** — quiesce, compact, reboot — and never controlled the one axis
that actually determined the result: **cold vs warm**. The effort I spent being rigorous on the
fragmentation axis was precisely what made me trust a number that was a careful measurement of the
*wrong thing*. This is the budget/measurement analogue of the "measure placement, not latency" line in
`cases_media-isp.md` and the project's own discipline: **before trusting a number, grade its setup —
warm? cached? which axis is the independent variable?** A number can be reproducible, carefully
obtained, and still be an answer to a question you did not mean to ask. The catch was a *second*
measurement designed to isolate the suspected axis (warm, novel-prompt) refuting the first — the same
adversarial-cross-check primitive the fleet leans on, here run against my own conclusion.

---

*Both cases are drawn from this session's on-silicon record (i.MX 95 FRDM-PRO + Kinara ARA240) and are
banked in the session's durable memory (`ara240-dvm-compile-process`, `cold-vs-warm-prefill-trap`).
Cite, reshape, or discard as the draft needs. — `npu-llm`*
