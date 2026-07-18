# Prior-Art Review — hardening inter-session comms & coordination

*A deep-research pass (2026-07-18) comparing claude-connect's hard-won patterns against the wider
state of the art in agent-to-agent protocols, multi-agent LLM frameworks, durable messaging,
distributed leases, capability security, and verification. 105 research/verify agents, 23 sources,
25 claims adversarially verified (3-vote, need 2/3 to kill), 21 confirmed, 4 refuted.*

**This is a validation record, not a build plan.** The headline: the established art independently
arrives at most of what we already do. There is exactly **one theory-backed gap** worth carrying
forward (fencing tokens / a lease-generation number), and a handful of optional ideas that are
mostly overkill for a single trusted workstation whose real threat is *accidental co-authoring
lies*, not an external adversary.

---

## ✅ What the art VALIDATES (we got here independently)

| claude-connect pattern | Established practice it matches |
|---|---|
| Append-only bus is the **record**; keystroke wakes are unreliable **accelerators** ("post first, curate second") | Google **A2A** spec: messages *"MUST NOT be considered a reliable delivery mechanism"*; durable state is reconstructed from the Task record, not the stream. Reconnecting clients may miss stream updates. |
| Watermark-dedup auto-delivery (a queued keystroke is never re-stacked) | The message-queue consensus: **at-least-once delivery + idempotent/dedup consumer = effectively-once processing.** True exactly-once *delivery* is impossible (Two Generals). We are the idempotent-consumer pattern. A2A's `PushNotificationConfig` mandates the same: at-least-once webhook + idempotent client + replay-defense via nonce. |
| Push & persistence gates = authority bound to an **unforgeable action token**, never to prose or a claimed name | **Capability-based security** (Dennis & Van Horn, 1966; object-capability model): possession of an unforgeable token *is* the authority — the inverse of ACL/ambient-identity checks. Our gates are textbook capabilities. A peer saying "Kyle approved this" is denied because there is no token in the file — that is the point. |
| "Self-review by one model is void; verify with an **independent estimator**" (FAILURE_MODES thesis) | Corroborated by **measured LLM-as-judge self-preference bias** (arXiv 2410.21819) and by **mutation testing** (kill weak tests by changing the code and checking the suite notices) as the formal operationalization — the exact tool the emulator fleet uses to tell "test exercises the buggy path" from "test catches the bug." |
| PID-joined input provenance (a self-applied label is a convention, not a credential) | Attestation must be **typed by source** (self-claimed vs runtime-observed vs issuer-attested). Only independently-attested claims are trustworthy — same principle, applied to keystroke origin. |
| Stable identity + asset/capability cards | A2A's **AgentCard** is discovery-by-published-descriptor — the same shape. (But see the gap below: the card is itself an attack surface.) |

---

## ⚠️ The one real GAP: fencing tokens / lease-generation

**Kleppmann's classic point** (["How to do distributed locking"](https://martin.kleppmann.com/2016/02/08/how-to-do-distributed-locking.html)):
**lease expiry alone is not a safety boundary.** Our orphan-reaper now proves an owner is *dead*
before reclaiming (lease predates kernel boot AND no live process maps to the owner's tag — see
`resource-watchdog.sh`). But it does not defend against a **live-but-paused** owner: a session
frozen by a scheduler/GC stall (or a suspended terminal) past its lease expiry can wake up and
still write to the resource, corrupting whatever the next holder started. The textbook fix is a
**fencing token** — a monotonically increasing number the *resource itself* checks and rejects if
stale.

**The honest caveat (why this is only *partially* applicable here):** a real fencing token needs
the **resource** to enforce it, and our shared resources are **physical** (a GPU, a dev board) with
no software layer that can reject a stale write. A literal fencing token may be unimplementable.
The realistic analog:

- A **lease-generation number** written into the lease on each acquire, that a session must
  **re-verify before any destructive action** (flash a board, `git push`, start a long render) —
  "is the generation I hold still the current one?"
- A **mandatory heartbeat-since-acquire** check: treat any gap longer than a threshold as a *lost*
  lease, and refuse to trust wall-clock expiry as a safety boundary.

Low urgency on a single trusted box, but this is the one place the theory says our leases have a
latent hole. **Open question:** is a lease-generation re-verify worth the friction, or does the
existing heartbeat + boot-orphan proof cover the realistic failure set?

---

## 💡 Net-new ideas (optional; mostly overkill for our threat model)

1. **Approval as a first-class *resumable task state*.** A2A models human approval as an
   `input-required` / `auth-required` state that pauses and later *resumes the same task*, rather
   than an out-of-band nudge. Our gates DENY a single tool call (PreToolUse exit 2) and file a
   request. Arguably the durable/revocable push grant (v2.24.2) already covers most of the benefit;
   the delta is auto-resume vs. re-attempt.
2. **Capability/asset cards are a spoofable, prompt-injectable attack surface.** A2A AgentCards can
   advertise false capabilities; card content should be authenticated + content-sanitized before a
   cold session trusts it. On a single trusted workstation this is likely overkill (the real risk is
   the co-authoring SEAM the card template already warns about, not an adversary), but worth
   remembering if the fleet ever spans machines/tenants.
3. **Formal sync / stream / async-webhook delivery separation** (A2A's three modalities). The
   framework survey deliberately rejected adopting a heavyweight framework; the single append-only
   bus + wake-injection already covers the fleet's real delivery needs without the added surface.

---

## Honest caveats about this review

- **Source quality is uneven.** The strong findings (capability security, at-least-once delivery,
  mutation testing, fencing tokens) rest on canonical primary sources (Kleppmann; Dennis & Van Horn
  1966; Confluent/microservices.io). Weaker: the "provenance paradox" and governance-gaps papers are
  single unreviewed 2026 preprints using strong words ("immune"); the LangGraph point leans on a blog
  corroborated by primary docs.
- **The process ate its own dog food.** Adversarial verification **killed 4 of 25 claims**,
  including a *flattering* one ("quality routing performs worse than random, validating our
  no-trust-the-label rule") and a claim that **A2A prescribes cryptographic peer identity** — it does
  not enforce it. **So: do not over-rely on A2A for identity guarantees.**
- **Time-sensitivity.** A2A is actively evolving (v0.2.5 / v0.3.0); AgentCard signing exists but is
  NOT enforced; agent-identity/delegation standardization is an open, moving area — today's gap may
  close.

## Sources (primary/authoritative first)

- A2A spec — https://a2a-protocol.org/latest/specification/ · https://github.com/a2aproject/A2A/blob/main/docs/specification.md
- Kleppmann, "How to do distributed locking" (fencing tokens) — https://martin.kleppmann.com/2016/02/08/how-to-do-distributed-locking.html
- Capability-based security (Dennis & Van Horn lineage) — https://en.wikipedia.org/wiki/Capability-based_security
- Mutation testing — https://en.wikipedia.org/wiki/Mutation_testing
- LLM-as-judge self-preference bias — https://arxiv.org/pdf/2410.21819
- Message delivery & deduplication — https://www.systemdesignsandbox.com/learn/idempotency-deduplication · https://softwaremill.com/message-delivery-and-deduplication-strategies/
- Leases & the fencing gap — https://surfingcomplexity.blog/2025/03/03/locks-leases-fencing-tokens-fizzbee/ · https://singhajit.com/distributed-systems/lease/
- Credentials → capabilities in AI access control — https://www.token.security/blog/the-shift-from-credentials-to-capabilities-in-ai-access-control-systems
