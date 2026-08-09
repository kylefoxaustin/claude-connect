# RQ3 — cross-session defect catches, classified (supporting artifact)

The independence bound in the paper (§V-D) rests on classifying every **record-attested
cross-session catch** — one session catching a defect in *another* session's shipped work (not a
self-catch, not a human catch) — as **A = factual/local** (a discrete fact the catcher held
differently) or **B = reasoning-shaped** (the catcher reasoned to a different conclusion). Mined
from `cases_*.md`, the bus archive, and git, 2026-07-27.

| # | catcher → author | defect | class | why | evidence |
|---|---|---|---|---|---|
| 1 | image-gen → backend | 5090 idle-power *denominator* 64.97 W was image-gen's resident ComfyUI tenant; clean board idles ~21 W | **A** | discrete physical fact the catcher held | `cases_backend.md` C1; `rtx5090_power_by_model_v2.json` |
| 2 | backend → docs | "INT8 loses accuracy via sm80 binary-compat fallback on SM120" — false; path is SM120-native | **B** | invented causal mechanism, refuted by finding the SM120 kernel on disk | `cases_docs.md` C2; `libnvinfer_builder_resource_sm120.so` |
| 3 | net-emu → bench-A | "+64 s NETC rejoin stall" was bench-A's own scorer arrival-stamp backlog | **B** | wrong causal model; refuted by a guest-emitted clock (measurement relocated) | `cases_bench-A.md` C1; commit `4059f7633f` |
| 4 | bench-A → net-emu | deeper-RX-ring "fix" does nothing (0.6 s of 65; 0 ring-full drops) | **B** | plausible hypothesis refuted by a controlled probe; net-emu reverted | commit `cb3b04d8fe` |
| 5 | emu-B → emu-C | gated LPCG TPM counter resets to 0, but silicon HOLDS the flip-flop | **B** (borderline A) | off-state semantics reasoned from the gate-OFF path 91's gate-ON tests never ran | fix `a11d421a31` |
| 6 | emu-B → emu-C | audio gate stops the clock but not the bytes (guards on ENABLE bits not clock) | **B** (borderline A) | reasoned from the data-fallback path | fix `7a322e875f` |
| 7 | ablation_perf-A blind arm → sizer | Case 1 severity overstated (129 cells "user-visible" — actually gated to Mid/High UI ⇒ latent) | **B** | control-flow/reachability miss, caught reading `app.py` | `ablation_perf-A.md`; `cases_perf-A.md:149` |
| 8 | perf-B → api-svc | live v2.0.0 shipped a "Prototype" header/footer 2 d 14 h post-go-live | **A** | stale UI string (naming) | `cases_perf-B.md` C3; commit `e0c3d08` |
| 9 | media-npu → socdev-A | "verified" Neutron YOLOv8 INT8 quantized w/o calibration (wrong scale) → cls_corr 0.10 | **A** | wrong published quant parameter; reproduced socdev-A's numbers to 5 dp | `cases_media-npu.md` C2 |
| 10 | docs → slam-A | "fixed-K Amdahl overhead" bandwidth model — impossible (K doubles when W doubles) | **B** | wrong analytical model; refuted by diffing derivations on shared data | `cases_docs.md` C3 |
| 11 | app-C → game-coach donor ref | client-side `callClaude` whose natural fix leaks the API key to the browser | **A** | discrete security/config defect | `cases_app-C.md` C2 |
| 12 | bench-A → peer node | interop green for weeks but spoke `"LB3!"` not magic `0xB5B6B7C0` | **A** | wrong magic constant | `cases_bench-A.md` C3 |
| 13 | slam-A → ratchet | i.MX93 A55 clock shipped 2.0 GHz; live `clk_summary` = 1.7 GHz | **A** | wrong clock number, measured live (ratchet had flagged it provisional) | bus `messages-2026-06.md:15645` |
| 14 | socdev-A model → emu-A (incidental) | 95's Neutron emulator never honoured the mailbox RESET (165 → 41 ms after fix) | **A** (borderline) | missing op, exposed by running a peer model | `cases_media-npu.md` C1 |

**Split:** 13 solid + 1 incidental = 14. By type: **~6–7 A / 7 B ≈ 1:1** — *not* overwhelmingly
factual.

**The bound (why 1:1 does not upgrade the independence claim):** every **type-B** (reasoning-shaped)
catch was made by a peer at a **different empirical vantage** — a measurement relocated into the
subject (rows 3–4), different physical silicon or a physical floor the catcher held (1, 9, 13), or
the **ship-vs-implement test-direction asymmetry** (rows 5–7, where the catcher's default test path
was the author's untested one) — **not** by an independent reasoner spotting a co-located reasoning
flaw from identical inputs. There is **no record of a same-input reasoning-error catch**. So the
type-B catches are reasoning-*shaped* but **input/vantage-*driven***, which is exactly the divergence
the paper's three proxies measure. Independence therefore holds **only relative to those proxies**,
never absolutely (shared base model + bus + operator framing remain).

**Two draft claims removed for lacking record support** (found in this pass): the "`backend` tag-flip
caught by `image-gen`" example was a **conflation** (image-gen's real catch is the power denominator,
row 1; the tag-flip was *self*-caught by backend), and "slam-A caught four independent errors" is
**unsubstantiated** in any case file or bus message. Both were struck from §V-C.
