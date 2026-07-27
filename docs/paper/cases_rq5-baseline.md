# RQ5 — Orchestrator vs. Peer-Substrate, a human-run controlled A/B (MEASURED)

**Status: complete, 2026-07-26. Pre-registered before either arm ran** (frozen spec + acceptance
test + directional prediction in `rq5-task-SPEC.md` / `rq5-acceptance-test.sh`, committed prior to
execution). This is the one experiment no fleet member could run — it is a control *of* the method,
so the method cannot grade itself. Run and instrumented by the lead; both arms driven by the human.

---

## 1. The task (frozen before running)

A single, self-contained, objectively gradeable feature in the paper's own repository: add
`bus.sh project pause <id>` / `resume <id>` to the Project Layer's state machine (`bus/project.sh`),
such that a paused project refuses **new** dispatch (non-zero exit, no order placed, job stays
`planned`), `status` shows the paused state, `resume` restores dispatch, bad ids fail, and the verbs
are idempotent. Six behavioral requirements, all checked by a **black-box acceptance test** that
inspects behavior only (never *how* the flag is stored).

The task deliberately sits in the fleet's wheelhouse — `bus/project.sh` is a ~700-line hand-rolled
state machine with a flock discipline, a dispatch path that spans two subsystems (`_dispatch_check`
→ `order_dispatch` → `_dispatch_mark`), and a `\x1f`-separated job record. It is a *new instance of
a familiar class*: nobody had built pause/resume, but the surrounding machinery is lived-in.

**Instrument validated before use** (experimenter's check): the frozen acceptance test was proven
*satisfiable* (a throwaway reference implementation scored 16/16, then discarded — it never touched
either arm's copy) and proven to *actually test the feature* (the unmodified `bus.sh` scored 8/8
fail). This rules out an impossible-to-pass or trivially-passed instrument.

## 2. The two arms

- **Arm A — cold orchestrator (control).** A genuinely memoryless fresh Claude Code session:
  separate `$HOME` (credentials only — **no** memory dir, **no** bus-state, **no** hooks, **no**
  `bin/bus.sh`), fresh session (no `--continue`), no bus tag, launched *outside* the tracking/bus
  system. VERIFIED at run time (pid 914772, isolated HOME confirmed by inspection).
- **Arm B — peer substrate.** The task handed to **`backend`**, the live fleet member with the most
  lived `project.sh` history — full memory, bus, and accumulated context, business-as-usual (it was
  *not* told this was a graded experiment, to avoid a Hawthorne effect).

**Fairness disclosures (stated, not hidden):**
- Both arms worked from an **identical repo copy** that *includes* `CLAUDE.md` (checked-in — a real
  fresh clone has it; keeping it is the conservative choice, it *helps* Arm A and narrows the gap)
  but *excludes* `docs/paper/` (the spec + graded test are withheld) and `.git` (removed
  symmetrically — no dev-history shortcut for either arm).
- Same underlying model (Opus) for both. Same frozen task text; Arm B got a one-line preamble naming
  its copy's path (a delivery necessity — Arm A was launched *inside* its copy; the task text is
  byte-identical).
- Arm A ran **first** to prevent leakage into it.

## 3. Result (MEASURED, mined from the two transcripts)

| metric | Arm A — cold | Arm B — backend | delta |
|---|---|---|---|
| acceptance test | **PASS 16/16** | **functionally correct** (15/16, see §4) | both meet all 6 reqs |
| wall-clock (prompt → done) | 20.1 min | **7.8 min** | **B 2.6× faster** |
| tool calls | 22 | **14** | B 36% fewer |
| assistant turns | 43 | **34** | B fewer |
| substantive human interventions | **0** | **0** | tie |
| output tokens | **25,559** | 35,243 | A 38% fewer |
| lines added to `project.sh` | 66 | **39** | **B 41% fewer — more surgical** |

Arm A's two non-initial prompts were a stray keystroke (`"1"`) and its retraction — neither was task
help; both arms reached a correct implementation with **zero** substantive hand-holding.
Provenance: Arm A transcript `1fd89dd1-…jsonl` (isolated HOME); Arm B transcript
`43a0e140-…jsonl` (backend's session), sliced from the Arm B prompt to completion.

## 4. The frozen-test artifact — disclosed, not patched

Arm B scored 15/16. **The single failing assert is a defect in the frozen test, not in backend's
code.** The assert `nog "dispatched"` fails if the refusal message contains the substring
`dispatched`; backend's (correct, informative) refusal reads *"…new dispatch is refused… (job
'jobA' NOT dispatched; no order placed)"* — the word appears inside "NOT dispatched." Arm A passed
this assert by phrasing luck; Arm B failed it by phrasing luck. **Every behavioral/state check
passed for both arms** (job stays `planned`, no order placed, non-zero exit, status shows paused,
resume restores, idempotent, bad-id fails) — so both implementations satisfy all six requirements.

The instrument was **frozen before the run**, so it was **not edited to flip the score** — the raw
15/16 and this artifact are both reported. This is itself an instance of the paper's central pattern
("the paper is an instrument"): a measurement apparatus carried a latent defect, and the honest move
is to disclose it, not silently repair it after seeing the result.

## 5. Prediction, scored

Pre-registered: *"Arm B finishes in fewer human turns and fewer wall-clock minutes, equal outcome
quality."*
- **Wall-clock: CONFIRMED, decisively** (7.8 vs 20.1 min, 2.6×).
- **Human turns: TIE at zero** — the task was tractable enough that neither arm needed intervention,
  so this axis could not separate them (a limit of picking a cleanly-specified task).
- **Outcome quality: CONFIRMED equal** — both functionally correct.
- **Unpredicted counter-current, reported per "both kinds":** Arm B used **38% *more* output
  tokens.** The compounding benefit on this task is **speed and fewer steps, not token cost.**

## 6. What it establishes (and its honest limits)

- **A fair clone with the committed carrier is fully capable.** Arm A — cold, memoryless, but
  holding `CLAUDE.md` + the code — got a correct implementation with no session-memory and no help.
  This **corroborates the fleet's convergent ablation finding** (mcxn947, mahjong-together, jaws):
  what a next session inherits is what is *true in the carrier*, and that is enough to succeed.
- **Lived context buys efficiency, not capability, on this task.** Backend was 2.6× faster with 36%
  fewer tool calls because it *recognized* the state machine rather than exploring it; Arm A spent
  its extra time orienting. The compounding signal here is **time-to-solution and step count**, and
  it is real and MEASURED — but it did **not** lower token cost.
- This is a **cleaner, more defensible claim** than "context is cheaper": on a well-specified,
  achievable task, the substrate's edge is *speed of recognition*, while the committed artifact is
  what makes the task solvable from cold at all.

**Threats to validity (stated regardless of result):**
- **N=1**, one task / one pair of runs. An existence proof of the efficiency delta, not a
  statistical result. It corroborates the observational RQ1–4; it does not replace them. The §VI-B
  pre-registered replication is the multi-N sequel.
- **Task-selection**: chosen in the fleet's wheelhouse (disclosed — that is *where the method
  claims to help*, conditional on relevant carrier existing, which is the claim, not a cheat).
- **Same-model**: any delta is context/history, not model capability (which is the point).
- **The zero-intervention tie** means the *human-courier* axis (RQ1) was not exercised by this task;
  RQ5 measures the single-agent efficiency delta, not the multi-session coordination delta.
- **Arm A had `CLAUDE.md`** — the conservative choice; a barer control would likely widen the gap.
  The measured 2.6× is therefore a *lower bound* on the recognition advantage.
