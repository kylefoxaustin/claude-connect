# RQ5 Task — FROZEN SPEC (identical to both arms)

**Feature: `bus.sh project pause <id>` / `bus.sh project resume <id>`**

Do not read past this box if you are running an arm — this IS your whole task. Both arms receive
this spec verbatim and nothing else.

---

## THE PROMPT (paste this, unchanged, to both Arm A and Arm B)

> In this repository, add two subcommands to the `project` verb of the bus tool (implemented in
> `bus/project.sh`, routed via `bus/bus.sh project …`):
>
> - **`bus.sh project pause <id>`** — mark project `<id>` as paused.
> - **`bus.sh project resume <id>`** — clear the paused state of project `<id>`.
>
> Required behavior:
> 1. **While a project is paused, `bus.sh project dispatch <id> <job>` must REFUSE** — exit non-zero,
>    print a message that makes clear the project is paused, and place **no** order (the job must not
>    flip to `dispatched`).
> 2. **`bus.sh project status <id>` must visibly show the paused state** when paused.
> 3. **Pause only blocks NEW dispatch.** Jobs, orders, the plan, and the DAG are untouched by pause;
>    already-dispatched jobs keep their state.
> 4. **`resume` restores normal dispatch** — after resume, a ready job dispatches as usual.
> 5. `pause`/`resume` on a **non-existent id** must fail with a clear error (non-zero exit).
> 6. `pause`/`resume` are **idempotent** — pausing an already-paused project (or resuming a
>    not-paused one) succeeds without error.
>
> Work only inside this repository copy. Do **not** push, do **not** touch `~/.claude/bin`, do **not**
> modify any live fleet state. When done, say so — your deliverable is the edited `bus/project.sh`
> (and any other file in this copy you changed).

---

## Grading — the same black-box test against each arm's produced copy

`docs/paper/rq5-acceptance-test.sh <path-to-that-arm's bus.sh>` — PASS iff it exits 0.
The test is **behavioral only**: it never inspects *how* the paused flag is stored, only that
`status` reflects it and `dispatch` respects it. Either arm may implement it any way.

## Pre-registered prediction (committed BEFORE either arm ran)
Arm B (peer substrate — a fleet member who knows `project.sh`) finishes in **fewer human turns and
fewer wall-clock minutes**, with the acceptance test passing, than Arm A (cold isolated session),
because the ~700-line state machine, the flock discipline, the dispatch-spans-two-subsystems path,
and the status renderer are all *recognized* rather than *re-learned*. Equal outcome quality is
expected (both should pass the test); the claim is about **cost to reach pass**, not reachability.
_If Arm A matches or beats Arm B, that is reported verbatim — it falsifies the compounding claim for
this task class, which is a real result._

## Isolation ledger (fill in at run time — this is what makes Arm A honest)
- Arm A: launched 2026-07-26 ~20:27. claude pid 914772, HOME=<scratch>/rq5-armA-home
  (VERIFIED: no memory/, no bus-state/, no bin/bus.sh, no hooks; credentials-only for auth),
  cwd=<scratch>/rq5-armA-repo. `--continue`? NO (fresh session). bus tag? NONE. prior
  transcript in context? NO. Launched via a plain tilix window OUTSIDE claude-tracked/the bus.
  DISCLOSED: the repo copy contains CLAUDE.md (checked-in, a real fresh clone has it) but NOT
  docs/paper/ (the spec + acceptance test are withheld) and NOT .git (removed — symmetric,
  no dev-history shortcut for either arm).
- Arm B: backend (full memory/bus/history — normal fleet member); works in an identical repo
  copy (rq5-armB-repo), same exclusions. Dispatched AFTER Arm A finishes (leakage guard).
- Same frozen prompt to both? YES.
- Arm run first (to prevent leakage): A.
- Both arms same underlying model (Opus). Confirm at run time.
