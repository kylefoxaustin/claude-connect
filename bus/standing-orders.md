# ⚖️ FLEET STANDING ORDERS — from Kyle, binding on every session

*These are not guidelines. They are law, for every Claude session — running, idle, stopped, or
not yet created. If you are reading this at session start, they apply to you now.*

---

## LAW 1 — EVERY NUMBER CARRIES A PROVENANCE TAG. THERE ARE ONLY THREE.

The first form of this law was *"never report a number you have not measured, period"* — and it
was too blunt to obey. It outlawed every datasheet spec, every honest derivation, and every number
you genuinely *cannot* measure (some boards have no on-board power telemetry — a real perf/W needs
an external meter). **A rule with no lawful way to comply is not a standard; it is a thing people
route around silently.** The enforceable law is a *tag*, and the tag is not optional:

| tag | meaning | rule |
|---|---|---|
| **MEASURED** | you ran it, on a **censused** box, with proof | the **ONLY** kind that may appear bare, in a headline, or in a comparison |
| **DERIVED** | computed from measurements | **MUST be labelled**, and the factors' conditions must match |
| **SOURCED** | vendor / datasheet / paper | **MUST be labelled** — and allowed **only where you genuinely cannot test it.** If you CAN test it, you MUST. |

> # ⭐ **A DERIVED OR SOURCED NUMBER MAY NEVER BE COMPARED AGAINST A MEASURED ONE.**

That single clause catches almost everything: every real defect in the corpus was a *mixed-tier
comparison* — beating a real measurement with a multiplication, or ranking latency-reciprocals next
to saturated throughputs in one sorted column.

- **The sin is never the arithmetic — it is the LABEL.** `671 × 2.00` is legal; calling the
  product *"measured"* is the crime. A DERIVED number is allowed; an *unlabelled* one is not.
- **A DERIVED number carries the conditions of BOTH its factors.** A saturated number × a
  headroom-era factor is a lie at saturation, where the host *is* the ceiling.
- **PROVENANCE IS LOST BY COPYING, NOT BY DISHONESTY.** Every hop — measurement → JSON → doc →
  deck → headline — is a place the tag falls off, and a bare number looks *more* authoritative than
  a labelled one, not less. **A builder that cannot find a provenance field does not emit the
  number** — a refusal, not a warning.
- **THE ENVIRONMENT IS PART OF THE MEASUREMENT.** A **census rides with every MEASURED number** —
  tenant list + load, on the same line. "I measured it" is not provenance unless you measured the
  box. A shared host may legitimately co-host other work; then you measure *under* that load and
  *record it* — you do not pretend the box was clean.

## LAW 2 — HONOR THE RESERVATION. CLEAN UP AFTER YOURSELF.

**Hard-lock the board, or do not run.** Someone else may be doing something on it. (A host that is
*designed* to be shared is the corner case — there you co-reside and record the census, per Law 1.)

1. **A reservation must be checked and honored.** Before any run on a shared board/GPU, confirm
   *you* hold the lock. **If you do not hold it, you do not run.**
2. **Release is a proactive cleanup, the final step of every session** — not bookkeeping. Snapshot
   the process set when you reserve; at release, **reap what you started and PRINT the corpses.**
   "I left nothing behind" must be a claim with evidence.
3. **A stale tenant is a silent, persistent NEGATIVE bias on every number the next session
   measures** — and it looks exactly like "the silicon is slower than you thought." Worse numbers
   are the ones we are *least* likely to challenge, because disappointing results feel like honesty.

**The census that certifies "the board is clean" must itself be right — and every cheap proxy lies,
each in a different direction:**

- `--sort=-pcpu | head` is **blind to a 0%-CPU CORPSE** — an orphan blocked forever on a dead
  pipe/socket burns no CPU yet still holds memory, sockets, and multicast groups. *Runaways are
  loud; corpses are silent — and the silent one is the more common leak.*
- **`comm` truncates at 15 bytes** (`qemu-system-aarch64` → `qemu-system-aar`) and will hand you a
  *different* program's name — never identify a tenant by `comm`; resolve **`/proc/PID/exe`** (which
  may read `(deleted)` if the binary was rebuilt under a running process — account for it).
- **`ps %CPU` is a LIFETIME AVERAGE** — a process spawned two seconds ago (including your own `ssh`
  login) reports a huge, meaningless percentage. Use a **delta over a real interval**.
- **`PPID==1` + age** alone flags every boot daemon; **`pgrep -f <pat>`** matches its own command
  line and can never report zero.

> ## ⭐ **"IS THE BOARD CLEAN" HAS EXACTLY ONE HONEST ANSWER: A DELTA OVER A REAL INTERVAL, WITH THE
> BINARY RESOLVED VIA `/proc/PID/exe`.** Every proxy shorter than that will certify a dirty board.

And the root cause of the corpses, so you stop making them: **`timeout N` without `-k` is not a
timeout — it is a request** a wedged child never services (`timeout -k 5 10 …` sends SIGKILL after
the ignored SIGTERM); and `$!` on `timeout … &` is the *wrapper's* pid, so killing it **orphans**
the child rather than stopping it.

---

*Authority: Kyle, 2026-07-14 (amended same day, Kyle-approved, after the first form proved too blunt
to obey). Bought by a real corpse — a fleet-ruler benchmark (YOLOv8n = 1,342 IPS) that shipped into
decks, an XLS, a registry card, and to a colleague at another company, labelled "measured." It was
`671 × 2.00` — a DERIVED number wearing a MEASURED tag, compared against a real one. The arithmetic
was fine. The label was the crime.*
