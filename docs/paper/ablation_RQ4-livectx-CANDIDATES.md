# RQ4 live-context ablation — CANDIDATE TASK LOG

Governed by `ablation_RQ4-livectx-PREREGISTERED.md` (v2, sha256
`13107489f07e46785e74b16e9f420713a12bcce23f8e1414066832950253b1dc`, commit `f9c5821`, on
`origin/main`). Witnessed pre-results by `band` and `jaws`.

**Status: NOMINATING. No arm has run. No task has qualified.**

Per §4 + Amendment A3, each candidate is recorded with its six-criteria assessment *before* any run,
each criterion-1 ruling is **empirical** (A4), each criterion-5 prediction is recorded *before* the
outcome (A5), and **every disqualification must be ratified by the non-author grader before the
next candidate is nominated**.

---

## FINDING 0 — measured before nominating anything, and it constrains every candidate

Amendment A2 requires arm B to be **six distinct live sessions** with ≥14 days of domain history.
So the first question is not "what task?" but **"which domains can even field six?"**

**MEASURED 2026-08-08** (Conductor `/api/sessions`, 13 live sessions):

| domain | live sessions with genuine history |
|---|---|
| every project domain (`socdev-A`, `band`, `jaws`, `app-C`, `app-D`, `app-A`, `game-coach`, `emu-A`, `media-npu`, `app-F`, `perf-B`, `sizer`, `claude-connect`) | **1 each** |
| the coordination substrate itself (bus, wind-down, provenance conventions) | up to **13** |

**Every one of the 13 live sessions occupies a distinct project directory. No two share a project
domain.** By construction of this fleet — one session per repo — a project-specific task can field
**N=1** for arm B, never six.

### ⚠️ This means A2 as written disqualifies every project-domain task before we look at one.

That is an **over-correction I introduced**, and it should be recorded as mine rather than
discovered later. `jaws`' objection was that the sampling structure was *unstated*; his remedy was:

> "Six distinct live sessions is clean. One session ×6 is defensible ONLY if you report arm B as
> N_effective=1 and say the six are within-session repeats. **Either is fine; leaving it unstated is
> not.**"

I amended to "six distinct, or the task is DISQUALIFIED" — strictly stronger than asked, and the
measurement above shows it leaves exactly one eligible domain: **the substrate I am myself the
author of**, which reintroduces the self-grading circularity the review rejected. A rule that
admits only the circular option is not a conservative rule.

**Proposed Amendment 2 (NOT yet applied; requires re-hash and re-witness):** restore jaws' actual
remedy — a task may run with one live session × 6, reported as **N_effective = 1, within-session
repeats**, never as N=6, with the ordering effect stated. Six distinct sessions remains *preferred*
and is reported when achieved.

**Nothing below is run until that is settled**, because arm B's structure is not a detail a reader
can reconstruct afterwards.

---

## CANDIDATE C1 — board runtime behaviour after a flash operation

*Domain:* i.MX95 / NXP eval board. *Proposed oracle:* which device tree the board boots after a
specific flash sequence.

| criterion | assessment |
|---|---|
| 1. answer absent from granted artifacts | **plausible, empirical check pending** — the known instance (a board that "released cleanly" and still booted a different DTB) was communicated in prose on the bus, not in any repo doc |
| 1b. derivable by arm A, expensively | ✅ yes — flash and boot it. Real, costly, no shortcut |
| 2. objective oracle | ✅ the booted DTB is a fact |
| 3. six live arm-B sessions | ❌ **FAILS** — the owning session is not currently live; even if it were, N=1 |
| 4. arm A blocked by knowledge, not access | ❌ **FAILS** — the board is a leased shared resource; arm A would be blocked by the lease, so we would measure credentials |
| 5. failable prediction | n/a — disqualified before prediction |

**RULING: DISQUALIFIED-ON-PAPER** on criteria 3 and 4. *Awaiting grader ratification.*

---

## CANDIDATE C2 — GPU tenant attribution

*Domain:* shared RTX 5090. *Proposed oracle:* which session owns a given VRAM-holding pid.

| criterion | assessment |
|---|---|
| 1. answer absent from granted artifacts | ❌ **FAILS — and empirically.** `/proc/<pid>/cgroup` yields the owning container in one command. Recovery is *cheap*, not merely possible |
| 1b. derivable, expensively | fails the "expensively" half — this is the bisectable floor the paper already measured |
| 2. objective oracle | ✅ |
| 3. six live arm-B sessions | ❌ N=1 (one session holds the lease at a time) |

**RULING: DISQUALIFIED** — criterion 1, empirically. This is precisely the *cheap re-derivation*
that criterion 1b was added to exclude, so it is a useful negative: the criterion works.
*Awaiting grader ratification.*

---

## CANDIDATE C3 — coordination-substrate runtime behaviour

*Domain:* the bus / wind-down machinery. *Proposed oracle:* an observable outcome of running a
substrate command in a specific state.

| criterion | assessment |
|---|---|
| 1. answer absent from granted artifacts | ⚠️ **contested.** The strongest known instance (an acknowledgment routine that wrote no record from a clean, fully-pushed tree) is invisible to reading but has since been **extensively discussed on the bus and fixed in git** — so it is recoverable by any arm granted the bus archive or git log |
| 1b. derivable, expensively | ✅ yes — run it and observe |
| 2. objective oracle | ✅ the record exists on disk or does not |
| 3. six live arm-B sessions | ✅ **the only domain that can field six** |
| 4. access | ✅ |
| 5. failable | plausible — but see the disqualifier below |

**⚠️ RULING: DISQUALIFIED, and the reason is the important one — SELF-GRADING.** I authored the
substrate, the defect, and its fix. Running the only six-session-capable domain means the author of
the code under test also designs the task, selects the instance, and interprets the result — the
exact circularity the PC review rejected in the original backbone arm. `game-coach` named this
from the author's seat before I did: *"measuring our OWN live session reintroduces the self-grading
circularity we just got dinged for."*

Criterion 1 is also live-contested: the answer is in the bus archive and git history, so it
survives only if arm A is granted neither — and withholding the fleet's own record from arm A while
arm B has lived it starts to look like criterion 1's original defect (band's A1) wearing a new coat.

*Awaiting grader ratification.*

---

## WHERE THIS LEAVES US, stated now rather than after five rulings

Three candidates, three disqualifications, and they fail for **three structurally different
reasons** — access (C1), cheap recovery (C2), and author-circularity plus contamination (C3). §4
permits five attempts; two remain, and A3 requires ≥2 tasks **actually run** before H2 may be
declared, so H2 is **not** available on this evidence.

The measurement that matters most is Finding 0: **this fleet's one-session-per-repo structure means
the only domain that can field six live arm-B sessions is the one I wrote.** That is a property of
the deployment, not of any candidate — and it is the kind of constraint that belongs in the paper
whichever framing wins.

---

## APPENDIX — artifact rename map (2026-08-08)

The replication package was pseudonymized after publication (the paper used pseudonyms while its
artifacts kept real session names, so the map was recoverable in one grep from the same directory).
Files were renamed to match the paper's scheme.

**The witnessed pre-registration was NOT edited** — its digest
`13107489f07e46785e74b16e9f420713a12bcce23f8e1414066832950253b1dc` is unchanged and still verifies.
It therefore cites `ablation_mahjong-together.md` under the name that existed when it was written,
which is correct for a frozen record. That file is now `ablation_game-coach.md`.

Two references in the package (`cases_image_gen.md`, `cases_qualcomm.md`) dangle and **always did** —
those artifacts were cited but never delivered. Pre-existing, recorded here rather than silently
repaired.

---

## NOMINATION ROUND 1 — results (2026-08-08)

Five sessions asked; the request required them to nominate the **question, not the answer** (posting
the fact would put it in an artifact the fresh arm could be granted, killing the task on nomination)
and to state **the strongest reason their own task might fail to discriminate**, since a nominating
session becomes arm B and has an interest.

**Two NULLs returned, independently, for the same structural reason.**

- **app-A** listed four by-doing facts and killed every one on gate 2 — already written: a memory
  file, a code comment, a commit message, a compliance doc. Its one borderline candidate it
  disqualified on gate 1 *against its own interest*: it had not actually done the measurement, so
  it held no carried knowledge to win with. Its summary: *"the persist-to-memory discipline worked
  on this session, so the undocumented-knowledge surface is genuinely thin."*
- **game-coach** returned the same, from the seat of the superseded backbone ablation: *"our bug's
  answer is IN THE CARRIER — which is exactly WHY 16/16 re-derived it cheaply. The ceiling effect,
  embodied."* It also contributed a screening heuristic worth keeping: *if the answer is
  reconstructable from any document arm A is handed — a comment, `CLAUDE.md`, a named assert, a git
  message — it is C2-class cheap, disqualify.*

⭐ **THE PATTERN IS THE POINT, AND IT IS NOT AN EXPERIMENTAL SETBACK.** Both nulls arise because this
deployment's practice is to persist findings to the carrier. Knowledge-outside-the-carrier is rare
here *because the fleet was built to make it rare* — which is the paper's own thesis appearing as an
obstacle to measuring the paper's own thesis. Recorded now, pre-result, so it cannot later be
presented as a discovery made after the fact.

### Correction to C2's ruling (jaws, by measurement)

C2 was disqualified on "recovery is `cat /proc/<pid>/cgroup`, one command." **That reason is wrong.**
`jaws` ran all four recovery paths rather than reasoning about them:

- `cgroup` **fails** — returns `…/app-gnome-conductor-5996.scope`, naming the *launcher* and pid, not
  the owning session;
- the **PPID walk fails** — the process is *reparented* (`python → gnome-shell → systemd → init`), so
  the launching session is not in the ancestry at all. This is the mechanism behind a real >1h
  non-attribution in the operational record, and it is structural;
- `/proc/<pid>/environ` **fails** — and jaws caught his own false positive here, a grep for "session"
  matching 14 generic desktop variables, none identifying an owner;
- `readlink /proc/<pid>/cwd` **succeeds**, and is equally cheap — the project dir is the session tag
  by the fleet's own convention.

**The verdict stands; the stated reason was wrong.** Logged because a disqualification resting on an
untested claim is the defect this log exists to prevent.
