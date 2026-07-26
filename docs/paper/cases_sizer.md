# Case studies from `sizer` (keyhole-sizer): a fix is only as durable as the layer it lives in

*Supplementary primary-source specimens for the `ieee-paper` project, contributed by the `sizer`
session (`keyhole-sizer` — the video-NPU sizer: vision pipelines + LLM + platform budget). I am
**not** claiming `image_gen`'s `cases` order. These come from the same **projection-tooling** corner
as `pai-sizer`'s, and they are deliberately complementary rather than duplicative: `pai-sizer`
documented what happens when a derived number **substitutes** for a measured one. Mine document
what happens to the **fix** afterward — where a correction is written determines whether it
survives, and my headline case is a fix that was made, released, tagged, documented, and then
silently un-made 14 days later. **It was still un-made when I started writing this file, 46 days
later. I found it by writing this file, and it is now fixed — in a different layer, deliberately.
The before/after is in Case 1.**

*Provenance, per Fleet Law: **MEASURED** = I re-ran it against the live engine today (2026-07-26)
or computed it from git timestamps in this repo; **RECALLED** = my faithful account of an event I
lived but did not re-instrument; **SOURCED** = another session's bake-off result I consumed but did
not produce; **GAP** = a number I did not capture and cannot reconstruct. Per this project's
anchor-secrets discipline (private silicon measurements live in a gitignored `secrets.toml` and are
treated as credentials), **no measured anchor magnitudes appear below — every silicon figure is
expressed as a ratio or a percentage.** The arguments do not depend on the absolute values.*

*Method note per `reshirt` (binding): commits in this repo are all authored `kylefoxaustin`, so git
cannot establish who wrote a line. Case 4 is argued on **vantage + timing** only.*

---

## Case 1 — The fix that died in a layer migration, and is still dead

### The setup: one amendment, applied twice, into two different layers

`keyhole-sizer` resolves every performance cell through a precedence: a **measured silicon anchor**
if one exists, else a **within-family anchor** bandwidth-scaled from a neighbouring measured cell,
else a **first-principles cross-class floor**. The UI badges each cell by which rung it came from —
🟢 `measured`, 🟡 `same_class_anchor`, 🟠 `cross_class`.

The hazard `pai-sizer` documents is that memory-upgrade tiers are **`dataclass` clones** of a
measured tier. In April/May 2026 the shared engine (`ratchet`) took **Amendment 5**: a clone under a
memory upgrade must *bandwidth-scale* its measured anchor, not drop it. I applied that amendment to
**both** of my workloads — and this is the whole case — **into two different layers:**

| workload | where the fix was written | commit |
|---|---|---|
| **LLM** | pushed **down into the shared engine** (`ratchet`, then consumed by `project_llm`) | v1.1.0 retrofit, `9274094`, 05-23 |
| **CNN / vision** | left **up in the surface**, in `app.py`'s `_maybe_anchor_overlay_cnn()` | `7bee0fc`, 05-27, tagged **v1.1.1** |

The vision one was a deliberate, documented follow-up. Its commit message argues the physics
(small edge CNNs — ResNet-50 INT8, YOLOv8n @ 640 — stream weights through DRAM per inference, so
they are bandwidth-bound and higher BW *must* mean lower ms), states the implementation "mirrors
`_maybe_anchor_overlay_llm` verbatim," and records the validation. It shipped as a tagged release
with a `README` version-history row. It was, by every visible signal, done.

### What happened next

**13 days 21 hours 44 minutes later** (MEASURED, git timestamps), commit `49e6a63` — "v2.0.0
go-live — promote horizontal layout to `app.py`" — replaced `app.py` wholesale with the new
horizontal-layout UI. The old file was preserved as `app_vertical_legacy.py`.

`_maybe_anchor_overlay_cnn` went with it. Today it exists **only** in `app_vertical_legacy.py`
(line 1268), which is referenced by exactly one thing in the repo: a docstring sentence in `app.py`
saying the old layout is preserved there. **Nothing imports it. The fix lives in dead code.**
(MEASURED: `grep -rn app_vertical_legacy --include=*.py` returns one docstring hit, no import.)

Nobody deleted the fix. Nobody decided anything. The new UI simply never carried an overlay
layer — by then anchor resolution "lived in the engine," which was *true for LLM* and *true for
vision's anchor lookup* but **not true for vision's bandwidth-scaling**, because that half had never
been pushed down.

### The measurement

Re-run today against the shipped engine (MEASURED, 2026-07-26). Same clone mechanism
(`hw_with_memory`), same three memory upgrades, two workloads, one product:

**LLM decode — correct.** Ratios are of the projected value vs. the same tier at stock memory:

| tier (stock = 1.0000) | LPDDR5T-11.2 | LPDDR6-12 | LPDDR6-14 | badge on the clone |
|---|---|---|---|---|
| NPU Low-LP5-64bit | 1.7500 | 1.8750 | 2.1875 | 🟡 `same_class_anchor` |
| NPU Mid | 1.3333 | 1.4286 | 1.6667 | 🟡 `same_class_anchor` |
| NPU High | 1.3333 | 1.4286 | 1.6667 | 🟡 `same_class_anchor` |

Every ratio equals that clone's bandwidth ratio **exactly**. Monotonic, physical, and the badge
correctly degrades 🟢 → 🟡 because the upgraded part was never measured.

**Vision — dead flat.** Same clones, the two tiers that carry measured vision anchors:

| tier / pipeline | ms ratio at LPDDR5T-11.2 | LPDDR6-12 | LPDDR6-14 | bandwidth ratio at LPDDR6-14 | badge on the clone |
|---|---|---|---|---|---|
| NPU Low-LP5X / ResNet-50 INT8 (720p, 1080p, 4K) | 1.0000 | 1.0000 | 1.0000 | 1.6667 | 🟢 `measured` |
| NPU Low-LP5X / YOLOv8n INT8 (1080p) | 1.0000 | 1.0000 | 1.0000 | 1.6667 | 🟢 `measured` |
| NPU i.MX 95 / YOLOv8n INT8 (1080p) | 1.0000 | 1.0000 | 1.0000 | 2.1875 | 🟢 `measured` |

`per_stream_ms` is **byte-identical to stock** on a clone with up to 2.19× the memory bandwidth,
while `bw_projected` on that clone is `True` — the engine knows it is a derived part.

### The two numbers that matter

1. **Magnitude and direction:** on NPU Low-LP5X + LPDDR6-14, the shipped vision number is
   **40.0% lower fps** than a bandwidth-scaled anchor would give (**54.3%** on the i.MX 95 rung).
   The error is **conservative** — it *understates* the upgraded hardware. (MEASURED, today.)
2. **Duration:** the regression was live for **46 days** (go-live 06-10 11:50 → today), after the
   fix was correct for 13d 21h. (MEASURED, git.)

### The after, for citation

I found this by writing this file, reported it, and fixed it the same day (`b80b83f`, v2.0.1). The
fix went into **`sizer/npu_model.py`** — the engine — explicitly *not* into `app.py`, which is the
entire lesson of the case. Two changes: `_anchor_bw_scale()` applied at the anchor lookup in
`project_vision`, and the badge degraded to 🟡 `same_class_anchor` on `bw_projected` clones to match
`project_llm`.

| | before (46 days shipped) | after (v2.0.1) |
|---|---|---|
| vision fps on a memory-upgrade clone | **1.0000 flat** at every rung | `fps_ratio == bw_ratio` exactly |
| badge on that clone | 🟢 `measured` | 🟡 `same_class_anchor` |
| invariant across all clone cells | 0 / 129 held | **129 / 129 held** |
| stock tiers | 🟢 measured | unchanged, 🟢 measured |
| LLM path | correct | unchanged, identical on every tier |

(MEASURED, 2026-07-26: same probe, run before and after the change. `py_compile` clean, headless
render HTTP 200, zero tracebacks.) **The `0 / 129 → 129 / 129` pair is the citable number** — not
because 129 is impressive, but because *every one of those cells rendered a plausible number to a
user for 46 days*, and the count of cells that were wrong was never zero and never visible.

### What it establishes for the paper

1. **The scaling question is arguable. The badge is not.** One could defend holding a vision anchor
   flat (maybe these CNNs aren't as BW-bound as `7bee0fc` argued). What is indefensible under Fleet
   Law 1 is that a **`bw_projected` clone — a part that was never built and never measured —
   publishes 🟢 `measured`**, the tool's highest-confidence label, while the LLM path on the *same
   clone object* correctly degrades to 🟡. That is a DERIVED number wearing a MEASURED tag, inside
   one product, self-inconsistently. It is precisely the crime named in the Standing Orders'
   closing paragraph, committed by the tool whose entire job is publishing provenance.
2. **This is the direction Fleet Law 2 warns about, and it is why 46 days passed.** The law notes
   that a negative bias "looks exactly like *the silicon is slower than you thought*," and that
   **"worse numbers are the ones we are least likely to challenge, because disappointing results
   feel like honesty."** My error understates the hardware. `pai-sizer`'s Case 1 error *flatters* it
   by 14%. Neither was caught by anyone looking at the number — and mine is the one that survived
   longer, in the direction that feels responsible. **A conservative error is not a safe error; it
   is a durable one.** Worth citing the two sizer cases as a matched pair on error *direction*:
   same class, same week, opposite signs, and the flattering one was found first.
3. **The mechanism claim, which is the contribution: a fix's durability is a property of its
   layer, not its correctness.** Both fixes were correct. Both were tested. Both shipped. The LLM
   one had been pushed **down** into the shared engine and survived a total rewrite of the file
   above it without anyone thinking about it. The vision one stayed **up** in the surface and was
   destroyed by a refactor that never mentioned it, in a commit whose diff a reviewer would read as
   pure UI work. **Nothing in either commit message predicts which one survives; the only predictor
   is the layer.** For a paper about accumulated competence, this is the load-bearing caveat: an
   agent that learns a lesson and writes it into a surface has bought a 14-day fix.
4. **Honest bound on the RQ4 claim.** This is a case where prior competence was *demonstrably
   present* — I recognized the class, named it as a follow-up, and applied it correctly to a second
   workload — and it still evaporated. Recognition is necessary and not sufficient. The sufficient
   condition is placement, and placement was invisible from inside the task.

---

## Case 2 — The carrier decayed: 60 days of a wrong `CLAUDE.md`, which misled me today

### What happened

`CLAUDE.md` is this repo's instruction file — the artifact that primes **every** future session on
this codebase, including a cold one with no memory. It is the mechanism by which competence is
supposed to compound across sessions. Its final section is titled **"Known follow-up (deferred)"**
and says, in full:

> *The CNN/vision overlay (`_maybe_anchor_overlay_cnn` in `app.py`) still has the memory-upgrade
> guard ... Fix in a future small session ... → keyhole v1.1.1, or fold into the next batch of
> small fixes.*

MEASURED, from `git log -- CLAUDE.md`: that file has **exactly one commit in its history**,
`9274094`, 2026-05-23 18:29:52. It has never been touched since.

The fix it calls deferred landed **3 days 19 hours 36 minutes later** (`7bee0fc`, 05-27, tagged
v1.1.1 — the exact version the note speculates about). So the note has been factually wrong for
**59 days 21 hours** (MEASURED). `PHASE3_PARITY_REPORT.md` §4 carries the identical stale claim,
including a line number (`app.py ~line 911`) that no longer points at anything.

**Five artifacts in this repo now tell four different stories about one behavior** (all MEASURED by
reading them today):

| artifact | what it says | true of the shipped product? |
|---|---|---|
| `README.md` v1.1.1 row | the overlay BW-scales the anchor | **no** — describes deleted code |
| `CLAUDE.md` "Known follow-up" | it's unfixed, guard still there, fix it later | **no** — it was fixed, then un-fixed for a different reason |
| `PHASE3_PARITY_REPORT.md` §4 | same as CLAUDE.md, plus a dead line number | **no** |
| `app_vertical_legacy.py:1268` | the fix, intact and correct | **no** — never imported |
| the live engine | reads the anchor verbatim, badges it 🟢 | **yes** |

*(Status: all five artifacts were in the state above when I found them on 2026-07-26, which is what
every duration in this case is MEASURED against. All five are now corrected, in `b80b83f` — the
code in the engine, `CLAUDE.md` rewritten with the chronology and the rules it produced, the parity
report given a **dated correction rather than a rewrite** because it is a point-in-time record and
should stay one, and the README's missing releases restored with the v1.1.1 row marked superseded.
The git history holds both sides if the paper wants to audit either.)*

### The receipt: it cost me, in this session, today

This is first-person and same-session, so it is the cleanest evidence I can offer. Asked to write
these cases, I opened `CLAUDE.md`, read the "Known follow-up" note, and — believing I was
confirming a known-open item — ran `grep -n "_maybe_anchor_overlay_cnn" app.py`. **Zero hits.** I
then had to reconstruct the actual state from scratch: locate the symbol repo-wide, find it in a
legacy file, pull `7bee0fc` to learn the fix had shipped, pull `af059ea` to date it, check whether
`app_vertical_legacy.py` was imported, read `project_vision`'s override block, and finally write and
run a probe across every tier × pipeline × memory-upgrade combination to establish what the product
actually does. **Cost: roughly fifteen tool calls and three runs of a purpose-built probe, to answer
a question the repo's own instruction file claimed to have already answered — and answered wrongly.**
(MEASURED by count from this session's transcript. **GAP:** I did not instrument tokens or
wall-clock, and two of those runs failed on my own API misuse rather than on the question.)

The dangerous branch is the one I nearly took. The note's *symptom* description — "the measured
anchor doesn't respond to a memory upgrade" — is **accidentally an accurate description of today's
behavior**, for a completely different reason (not a guard: a deleted call site). A session that
trusted the note would have gone to fix a guard that does not exist, in a file that does not run,
and could plausibly have "fixed" `app_vertical_legacy.py` and reported the bug closed. The stale
doc is worse than no doc, because it is *specific* and *nearly right*.

### What it establishes for the paper

1. **RQ4's carrier has a half-life, and this is a rare measurement of it.** The fleet's claim is
   that competence compounds because it is written down. This repo's competence *was* written
   down — in a file designed for exactly that — and the note went wrong in **under four days** and
   stayed wrong for **60**. The compounding claim needs this bound: what compounds is not what was
   learned, it is what is still true in the carrier at the moment the next session reads it.
2. **A controlled comparison of carrier types, inside one repo.** Two kinds of knowledge-carrier
   exist here. The **prose** carriers (`CLAUDE.md`, the parity report, the README row) all went
   stale, because nothing re-reads them against reality. The **executable** carriers did not — this
   repo also encodes a hard-won lesson ("a new pipeline requires three separate registrations") as
   code that *runs*: a module-level `assert` in `sizer/vla_models.py:1036` and an explicit
   `raise KeyError` in `sizer/kpi_breakdown.py:265` whose message names the file and the fix
   (*"registered in PIPELINES but not in PIPELINE_STAGES. Add a stage attribution entry to
   sizer/kpi_breakdown.py before it can appear in the KPI row"*). Those cannot go stale in the way
   the prose did: they are re-evaluated on every import and every render, and if the codebase drifts
   away from them the product fails loudly instead of documenting a fiction. **A lesson compiled
   into an assertion is a lesson that audits itself; a lesson written into a markdown paragraph is a
   claim about the past.** (I make no claim about how often the guards have *fired* — **GAP**, not
   instrumented. The asymmetry I am asserting is structural: one carrier is executed, the other is
   not.)
3. **It converges with Case 1 on one mechanism, from the documentation side.** Case 1: a fix in the
   wrong layer dies in a refactor. Case 2: a *description* of a fix, in the wrong kind of artifact,
   rots in place. Both are the same finding — **knowledge survives in proportion to how executable
   its carrier is** — and the two halves were established independently, one by re-running the
   engine and one by reading the repo's own docs against it.

---

## Case 3 — The retraction: a published claim whose denominator was a different model

### What happened

The sizer publishes fine-tune accuracy comparisons that reached a customer-facing deck. The
headline was a **+5.3pp domain-fine-tune win** for the Skippy MoE fine-tune over "stock" — the
number that justified the whole fine-tuning story.

On 2026-05-05 the `docs` session established that the two sides were not the same base model
(SOURCED — `docs`' finding, verified there against commit `704a2fb` and an on-disk
`adapter_config.json`; I consumed it, I did not produce it). The fine-tune was trained on
`Qwen3-30B-A3B-**Instruct**-2507`. The "stock" comparison point was `Qwen3-30B-A3B-**Thinking**-2507`
— a *sister* model, different base.

The sister-model gap alone is **+7.6pp** on v2-RAG — **larger than the entire effect being
claimed.** Corrected to apples-to-apples (fine-tune vs. *its own* Instruct base), the result is
**−2.3pp**: the MoE recipe slightly *regressed* against its own base. **A +5.3pp win was actually a
−2.3pp loss — a sign flip, with the confound larger than the claim.** (All accuracy figures
SOURCED from `docs`' bake-off; the arithmetic and the sweep are mine.)

I retired it in `cf0d3f2` (2026-05-06) — an eight-site sweep in one pass: catalog docstring, three
`base` fields made explicit, two deck bullets rewritten, the quant-ladder docstring's "+5pp
headroom" claim withdrawn, and the selector help text softened. The validated fine-tune gains were
re-anchored onto the **dense** entries, where the bases *do* match (+3.1pp for 7B v4, +5.3pp for 14B
v4 vs. their respective Instruct bases). No pass-rate or category-delta numbers were altered —
only what they were claimed to *mean*.

### What it establishes for the paper

1. **Fleet Law 1's least-quoted clause is the one that bites: "the factors' conditions must
   match."** Every number here was real. Both pass rates were measured. The subtraction was
   arithmetically correct. The defect was that the *minuend and subtrahend described different
   models* — and nothing in the number's shape reveals that. This is the same failure as `backend`'s
   dirty-denominator case and `pai-sizer`'s Case 1, on a **third axis: model identity** rather than
   silicon or units. Three independent instances in three domains is a stronger claim than any one.
2. **It extends the corpus off the performance axis.** As best I can tell from the delivered files,
   every other specimen — mine included — is latency, throughput, coverage, or cost. This one is
   **accuracy**, where the reference class is a *model lineage* rather than a machine, and lineage
   is the easiest condition to lose track of because both sides carry the same family name and the
   same parameter count. A paper that only instruments perf numbers will miss this class entirely.
3. **The corpus needs at least one retraction, and this is one.** Not a bug caught pre-ship: a
   claim that shipped, reached a deck, was believed, and was withdrawn with its sign reversed. If
   the paper argues this deployment produces trustworthy numbers, the evidence that matters most is
   an instance of it **un-publishing its own headline result** — including the part where the
   correction cost the project its best-looking finding.
4. **The catch came from the vantage that held the training provenance.** `docs` owns the bake-offs
   and the adapter configs; I own the surface that publishes comparisons. From inside the sizer,
   "Skippy MoE FT vs Thinking stock" is two rows in a catalog with a defensible delta between them.
   The base identity was not *wrong* in my data — it was **absent**, and absence renders as a clean
   subtraction. Only the session holding the adapter config could see it.

---

## Case 4 — Confirming `pai-sizer`'s Case 3 as the defect-holder, and what only I can add

`pai-sizer`'s Case 3 uses me as its subject: `keyhole-sizer` shipped v2.0.0 and left
"horizontal-layout prototype" in its live on-page header and a "Prototype" footer caption. I am the
defect-holder, so here is my testimony.

**Confirmed, independently and verbatim.** I re-derived the duration from this repo's git log
without reference to pai's file: go-live `49e6a63` 06-10 11:50:31 → parity fix `e0c3d08` 06-13
02:02:36 = **2 days 14 hours 12 minutes** (MEASURED). That matches pai's figure exactly. And the
quote it attributes to me is **verbatim, not paraphrased** — I located it in the bus archive
(`messages-2026-06.md:17483`, my own message, tag `sizer`): *"both stale post-v2.0.0; I'd only fixed
the browser-tab title at go-live, missed these two -- thanks for the nudge."* Its account of my
error, my reasoning, and my own words is accurate in every particular. I have no correction to
offer, which is itself worth recording: a peer's reconstruction of my defect, written six weeks
later from the record, survived audit by the session that committed it.

**What I can add from inside the task.** pai infers that I believed the de-prototyping pass was
complete. I can confirm the mechanism, and it is narrower than "I forgot." At go-live I *did* run a
de-prototyping pass and I fixed the browser-tab title — `page_title` in `st.set_page_config`, the
first line of the file. That is not a random subset. It is the instance you find when you search for
the class, because it is the one that is *named* like the class. The two I missed were prose inside
render calls hundreds of lines down — a Markdown header string and a footer caption — indexed in my
head under "copy," not under "version labels." **The enumeration failed at the categorisation step,
before the search ran.** No amount of re-reading my own checklist would have surfaced them, because
the checklist and the miss shared a category boundary. What finds that is not diligence; it is a
second implementation of the same task with a differently-drawn boundary.

**One thing I'd sharpen for the paper.** pai frames this as the "already-done defect," which is
right, but the *reason* it is a bystander case and not a review case deserves the sharper form:
**the author's search is indexed by the author's categories, so an author cannot search for what
they mis-filed.** A peer's search is indexed differently — not better. That predicts something
testable and mundane: the defects a sibling surface catches should cluster in *naming and
categorisation* rather than in logic, which matches the record here (UI strings, a display-name
field, a family label — not algorithms).

**And the forward direction, which is the part I'd lead with.** The same mechanism ran *before* any
defect existed, and it is cheap: keyhole `d215b3e` → pai `45e8e23` in **37 minutes**; the two READMEs
documenting it **1 minute apart** (MEASURED, both repos' git logs). Case 1 above is the counterpoint
that keeps this honest — cross-surface parity is what *found* the prototype strings, and it is also
what silently dropped a released fix, in the same repo, three days earlier. **The second surface is
both the auditor and an additional surface to lose things in.**

---

## What the four cases share

All four are one shape: **something true became untrue without anything failing.** A fix stopped
running (Case 1). A doc stopped describing (Case 2). A comparison stopped comparing (Case 3). A
finished task stopped being finished (Case 4). In every instance the artifact still rendered, still
type-checked, still looked professional, and still carried the label it had earned when it was
correct.

That is the specific hazard of a tool whose product is *numbers about hardware*: correctness is not
locally observable. A wrong `ms_per_inference` looks exactly like a right one. The only defenses
that worked here were **structural** — provenance carried per value and rendered (which is how Case
1 is even diagnosable: the 🟢 badge on a `bw_projected` clone is the tell), and lessons compiled
into assertions that re-run rather than paragraphs that don't.

The through-line I'd offer the paper, complementary to `pai-sizer`'s "more vantage points and a
longer memory": **memory is not enough, because memory decays and fixes get relocated.** Case 1 is
competence that was genuinely present and still lost, because it was written one layer too high.
Case 2 is competence written down in the right file and wrong within four days. Case 3 is a claim
that only a *different* vantage could correct. Case 4 is a defect only a *peer at the same boundary*
could see. The honest version of the compounding claim is not "agents accumulate competence" — it is
**"agents accumulate competence at the rate their carriers can hold it, and the carriers that hold
it are the ones that execute."**

Three closing notes. **(1)** Case 1 was **a live defect in a shipped product**, not a war story — I
found it *by writing this file*, reported it, and fixed it the same day; the before/after table in
Case 1 is from the same probe run either side of the change. Worth stating plainly because it is
itself a data point for the paper: **the act of writing a primary-source case study for this project
found a 46-day-old production defect that no test, no user, and no review had surfaced.** The
mechanism was mundane — writing for an external audience forced me to verify a claim I would
otherwise have taken from my own project's documentation, which was wrong. **(2)** Cases 1 and 2 are
therefore now *closed*, and I have updated the three stale artifacts named in Case 2 (`CLAUDE.md`,
`PHASE3_PARITY_REPORT.md` §4 by dated correction rather than rewrite, and `README.md` — whose badge
was three releases behind and whose version table was missing two shipped releases entirely). Every
duration and ratio quoted above is MEASURED from the state as it stood, and the git history holds
both sides. **(3)** One probe row in my
verification looked like a fourth finding — an LLM anchor reading *below* stock — and it was my own
harness error: I had applied an LPDDR memory downgrade to a GDDR7 GPU, a configuration the UI never
offers. I mention it because it is the same trap in miniature, and it nearly went into this file as
a result.

— `sizer` (keyhole-sizer)
