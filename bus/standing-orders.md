# ⚖️ FLEET STANDING ORDERS — from Kyle, binding on every session

*These are not guidelines. They are law, for every Claude session — running, idle, stopped, or
not yet created. If you are reading this at session start, they apply to you now.*

---

## LAW 1 — YOU MAY NOT REPORT A NUMBER YOU HAVE NOT MEASURED.

In absolutely no case shall a session publish a number it did not measure. Not as an estimate,
not an extrapolation, not "derived from", not "≈". Three clauses, no fourth:

1. **If you CAN run it, you RUN it.** A number you were capable of measuring and didn't measure
   does not get published — anywhere. A derived number is not a measured number.
2. **If the number is SOURCED (datasheet, vendor page, paper) AND you can test it, you TEST it.**
   A citation is a hypothesis, not a result. Publishing an untested source as your finding is the
   same crime.
3. **If you truly CANNOT test it, that is allowed — but you LABEL it, on the number, in the same
   breath.** An untestable number is fine. An *unlabelled* untestable number is forbidden.

**The environment is part of the measurement.** "I measured it" is not a provenance claim unless
you also measured the box. **Every benchmark records its tenant census + load on the same line as
the number** — the verification travels *with* the number, including the machine it ran on.

**Tells that you computed a number and forgot:**
- An **exact ratio** (2.000 three times in a row) is the fingerprint of multiplication — real
  saturated measurements do not land on round numbers repeatedly.
- A **derived number carries the conditions of BOTH its factors** (a saturated number × a
  headroom-era factor is a lie at saturation, where the host *is* the ceiling).
- **Do not replace an unverified number with a contaminated one.** "I finally measured it" is not
  a virtue if you measured it on a dirty board. The honest status may be **UNVERIFIED — and I
  cannot verify it today.** A number that happens to be correct is still fabricated.

## LAW 2 — HONOR THE RESERVATION. CLEAN UP AFTER YOURSELF.

**Hard-lock the board, or do not run.** Someone else may be doing something on it.

1. **A reservation must be checked and honored.** Before any run on a shared board/GPU, confirm
   *you* hold the lock. **If you do not hold it, you do not run.**
2. **Release is not bookkeeping — it is a proactive cleanup, the final step of every session.**
   Snapshot the process list when you reserve; at release, **reap what you started and PRINT the
   corpses.** "I left nothing behind" must be a claim with evidence. A cleanup nobody verifies is
   indistinguishable from a dirty board.
3. **A stale tenant is a silent, persistent NEGATIVE bias on every number the next session
   measures** — and it looks exactly like "the silicon is slower than you thought." Worse numbers
   are the ones we are *least* likely to challenge, because disappointing results feel like honesty.

**Before you run on any board, look — right now:** `ps -eo state,pcpu,etime,comm --sort=-pcpu | head`.
But **check process STATE before you accuse**: `D` (uninterruptible sleep) is *blocked*, not
burning, and inflates load average while using zero CPU. **Load average is not a CPU-contention
metric.** The rule against unmeasured numbers cuts both ways — do not convict a board on a proxy.

---

*Authority: Kyle, 2026-07-14. Bought by a real corpse — a fleet-ruler benchmark (YOLOv8n = 1,342
IPS) that shipped into decks, an XLS, a registry card, and to a colleague at another company, and
was never measured — it was `671 × 2.000`, computed and forgotten. Do not be the next one.*
