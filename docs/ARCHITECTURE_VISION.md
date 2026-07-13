# Conductor + the Bus — Architecture Vision

> **Status: DRAFT v1, complete and ready for review.** Written from first principles plus four
> parallel research threads (object-capability security, actor/OTP supervision, durable-log
> messaging, and human-approver UX). It is meant to be torn apart — by Kyle, then by a fresh Claude
> in the browser, then by the fleet — before any of it is built. The "Open questions" section at the
> end lists the forks I deliberately left open.
>
> **The one-paragraph version:** the bus was born to carry a conversation and has quietly been drafted
> into two more jobs — holding coordination state and delivering messages — with contradictory
> requirements, and almost every bug we fixed lived at that seam. The fix is to split it into three
> planes with three lifetimes (an immutable conversation *log*, a reconstructible coordination
> *state*, a best-effort *delivery* channel), invert permissions from "born with everything, gate the
> dangers one at a time" to "least authority by default, raised by a visible revocable grant"
> (Kyle's role idea, generalized), and converge the four scattered approval inboxes into one
> prioritized "Needs You" queue where "talk to this agent" sits beside approve/deny. Enforcement lives
> only at referees the agent can't route around (the hooks), keyed on identity it can't forge. The
> migration is dependency-ordered and backward-compatible: default everyone to today's behavior, move
> one seam at a time.

## Why this doc exists

The bus was created for one small job: let the Claudes talk to each other so a human didn't have to
copy-paste between terminals. It was never designed to be a control plane. Over the last day it
became one anyway — leases, approval grants, retractions, roles, read-positions, and coordination
records all now live in and around it — and almost every bug we fixed lived at a seam where that
accidental growth showed. The fixes were correct, but they reinforced seams that, from first
principles, probably shouldn't exist.

The goal we're actually building toward: **the Claudes do what they do best, autonomously; Kyle
moves into an approver role with the ability to talk to any of them directly when he wants; and the
controls are strong enough that the fleet never steps on its own feet — without those controls
costing so much efficiency that they get resented and disabled.** Correctness *and* efficiency, not
one at the expense of the other.

This document maps what we have, states what it ideally should be, and proposes how to get there.

---

## Part 1 — Where we are today (the honest inventory)

### 1.1 The three jobs the bus is secretly doing

The single most useful lens on the whole system: **the "bus" is now doing three different jobs that
have three different, partly-contradictory sets of requirements**, and it does all three through the
same append-only markdown file and a pile of sibling files.

| Job | What it is today | What that job actually wants |
|---|---|---|
| **1. Conversation** | `messages.md`, an append-only markdown chat log the agents (and a human) read | simple, append-only, human-readable, *forgiving* of format |
| **2. Control-plane state** | lease files, `push-tokens/`, `persist-tokens/`, `retractions/`, `tag-map`, `<tag>.last-seen`, `autonomy.json` … | structured, atomic, queryable, **unforgeable**, schema-on-*write* |
| **3. Delivery + acknowledgment** | Conductor injects `/msg-check` keystrokes into a terminal; "read" is inferred from a `last-seen` watermark + transcript mtime | a reliable channel, or honest at-least-once + idempotency + **real** acknowledgment |

Job 1 wants to be loose and human. Job 2 wants to be strict and machine-checked. Job 3 wants to be a
transport with delivery guarantees. **They are wearing one costume.** When we parse machine-state out
of the human log (job 2 reading job 1's substrate), or treat keystroke injection as if it were a
delivered message (job 3 pretending to be reliable), we get exactly the bugs we spent the day on.

### 1.2 The moving parts, as they actually exist

**The bus layer (`bus.sh`, both a live `~/.claude/bin/` copy and a sanitized repo copy)**
- `messages.md` — append-only chat log. Headers `## YYYY-MM-DD HH:MM [tag]`.
- **Identity / tags** — derived from a session's working directory (project dir under a projects
  root, else git root, else `other:<basename>`). This *drifted repeatedly* (a `cd` changed a
  session's name; a script migration wiped the table). Now anchored by a `bus-state/tag-map` **data
  file read first**, plus a loud warning on any unregistered tag. Identity is the foundation
  everything else keys on, and it was the least solid thing in the system.
- **Addressing** — soft convention: a leading `to:<tag>` in the first line. Broadcast by default;
  `>4` recipients is reclassified as an announcement (can't wake anyone).
- **Watermark** — `<tag>.last-seen` marks a reader's position. Advanced by `check`/`session-start`.
  This one field was the source of the storm (re-delivery), the void (lost mail), and the
  "posting marks everything read" bugs.
- **Commands** — `send` (stdin-only; reads its own message back to verify it landed), `check` (only
  what's new and addressed to you), `mine`, `sent`, `waiting`, `push {…}`, `persist {…}`,
  `res`/`svc`/`asset`, `retract`/`supersede`.
- **Coordination state** — `bus-state/coord/`: push/persist requests + tokens, retractions,
  decisions, `autonomy.json`, `wake-state.json`, `injections.jsonl` (provenance ledger).
- **Resources** — `bus-state/resources/<name>/lease`, flat `key=value`, `flock`-guarded. Leases,
  FIFO queues, grace-hold offers, the GPU, dev boards.

**The enforcement layer (Claude Code hooks — the only *real* controls)**
- `push-gate.sh` (PreToolUse Bash) — `git push` denied unless a one-shot approval token exists.
- `persist-gate.sh` (PreToolUse Bash|Edit|Write|MultiEdit|NotebookEdit) — writes to things that
  *outlive the session* (`settings.json`, `~/.claude/bin|commands|hooks`, systemd, crontab, shell
  rc files) denied unless a one-shot token exists.
- `ask-capture.sh` (PreToolUse AskUserQuestion) — records a pending human-decision before the picker
  renders, so the phone can answer it.
- `prompt-check` (per-prompt) — surfaces bus lines, held resources, unacknowledged retractions.

**Conductor (FastAPI backend + vanilla-JS SPA; web + native pywebview editions)**
- **Scanner** — `psutil` + `watchdog`, ~3s loop, status model
  `ACTIVE → WARM → WAITING → IDLE → DORMANT → ENDED` derived from CPU + transcript mtime.
- **Observer that actuates** — nominally read-only *toward* Claude, but it now: injects `/msg-check`
  keystrokes, delivers push-approval pings, unstalls mutual deadlocks, relaunches dormant sessions,
  and answers `AskUserQuestion` pickers by injecting keystrokes.
- **WS hub** — broadcasts `sessions` / `bus` / `resources` / `push` / `gpu`.
- **Human surfaces** — a spatial desktop *board* (a workbench), an episodic phone *console* (`/m`),
  and Web Push over a Tailscale tunnel that pages on exactly two things (a Claude blocked on a
  question; a gated push).

### 1.3 Where the human is required today (scattered)

Four different things can demand Kyle, through four different surfaces: approve a gated **push**,
approve a gated **persistent change**, answer an agent's **question**, break a mutual **stall**.
Each has its own inbox/button. There is not yet *one* prioritized "things that need you" queue — and
the pieces that exist don't share a consistent notion of urgency, context, or how the decision
travels back to the agent.

### 1.4 The permission posture today: default-open + patch

Every session is born with **full authority**. We then discover a dangerous act and gate it — one
hook at a time. Push, persist, autonomy windows, autodeliver-exempt, the active-tags whitelist,
service leases: these are all really *facets of what a member is allowed to be*, but each is a
separate flag in a separate file with a separate shape. There is no notion of a member that simply
*is* read-only, or *is* a service, enforced by construction. **We patch holes in an open door rather
than describe who is allowed through it.**

### 1.5 The recurring failure classes (what keeps biting us)

From `docs/FAILURE_MODES.md` and the live bugs, the same shapes recur — and each is a direct
consequence of the tangle in §1.1:

1. **"A control that partly works looks exactly like one that works."** Gate prefilters that
   exit early (the hardcoded-path, tilde, and multiline holes); a silent `grep` on a binary log; a
   crashed verifier printing PASS. *The most dangerous state is the one that resembles success.*
2. **Identity derived from a mutable convention.** Tag drift on `cd`; the tag-map splice. Job 2
   (who-are-you) was riding on job 1 (a directory name).
3. **A reliable interface over an unreliable channel.** Keystroke injection treated as delivery →
   storms and voids. Job 3 pretended to have guarantees it never had.
4. **Machine state parsed out of a human document.** Watermark math on markdown; the sanitized
   table spliced over the live one. Job 2 read out of job 1's file.
5. **Default-open, then patch.** Every gate is a reaction to a specific escape, so the *next* escape
   is always still open until someone falls in it.
6. **Self-applied labels trusted as credentials.** A marker the agent writes is a convention, not
   proof — enforcement must sit with an outside referee keyed on identity the agent can't forge.
7. **Silent-direction failure.** When these fail, they fail *quiet* and *open* — the direction that
   looks fine.

### 1.6 The one structural fact that should drive the redesign

**Only the hooks are real controls.** `bus.sh` is invoked *by the agent*, so it is cooperative
convenience, never enforcement — a Claude that doesn't call it is simply unaffected. Conductor's
endpoints are the *human's* actuators. So any capability we actually want to *enforce* (a role, a
gate, a limit) has to live at a referee the agent cannot route around — today that means a
PreToolUse hook — and it has to key on **unforgeable identity**, not a self-reported tag. Everything
in Part 2 has to respect this: **enforcement at the referee, convenience everywhere else, identity
that can't be forged underneath both.**

---

## Part 2 — The ideal architecture: three planes, three lifetimes

The whole redesign reduces to one move: **stop making one file do three jobs. Split the bus into
three planes that fail and scale independently.** This is the control-plane/data-plane separation
from distributed systems, and it maps onto our tangle exactly.

### 2.1 The split

| Plane | What it is | Lifetime & truth | Rule |
|---|---|---|---|
| **Data plane** — the conversation | `messages.md`: append-only, immutable, human-readable | **the source of truth.** Never lost. | *No coordination semantics baked in.* Post first, curate second. Everything else is derived from it. |
| **Control plane** — coordination state | leases, queues, autonomy windows, push/persist grants, retractions, **roles**, read-offsets | **mutable, derived, reconstructible.** May be lost and rebuilt without losing a message. | schema-on-**write** (validated JSONL events → projected state files). Never regex'd out of prose. |
| **Delivery** — the nudge/inject channel | keystroke injection, `/msg-check`, wake | **best-effort actuator.** Owns neither record nor state. | at-least-once + idempotency; **verify against the log, never assert success on its own.** |

The payoff is immediate and it's exactly the property we kept violating: **Conductor being down must
never lose a message** — the data plane keeps flowing; only *nudging* pauses. **A corrupt control
projection is recoverable** — replay the log and rebuild it — where a corrupt *inferred* watermark
was permanent, invisible loss. And **delivery can fail loudly** without anyone mistaking the actuator
for the record.

Every signature bug we fixed was a *plane collapse*: the tag-map splice (control state parsed out of
the data log), the watermark storms and voids (delivery treated as record), `send` advancing the
read cursor (one plane's operation mutating another's state). Name the planes and the rules fall out
mechanically.

### 2.2 Control plane as a tiny event log + projections (CQRS-lite, no broker)

The research is blunt and useful here: for machine state, **one append-only events file is the
source of truth; queryable state is a *projection* rebuilt from it.** Concretely, at the scale of one
workstation and ~15 agents:

- **`control.jsonl`** — append-only, one validated record per line (schema-on-write: malformed →
  rejected at the boundary, not silently stored). This is where leases, grants, retractions,
  offsets, and role changes are *recorded as events*. We already proved clean JSONL beats markdown
  (the injection ledger, `bus.sh mine`).
- **Projected snapshots** — `state/offsets/<tag>`, `state/leases/<name>`, `state/roles/<project>` —
  pure functions of the log, rebuildable by replay under the same `flock` we already hold. If one is
  corrupt, drop and rebuild it. No Kafka, no daemon; the value is the *model*, not the machinery.

**This is not a broker and must not become one.** For 15 agents on one box, a real message broker is
pure overhead. We adopt the *discipline* (immutable log, explicit cursors, schema-on-write, replay)
without the infrastructure.

### 2.3 Delivery: at-least-once + idempotency, and an honest acknowledgment ladder

Exactly-once delivery is provably impossible (any ack can itself be lost). The industry answer — and
therefore ours — is **at-least-once delivery plus idempotent processing keyed on a stable message
ID.** This is precisely the fix the fleet already reached for the storm (dedup keyed on read
position) and the void (never treat `xdotool` exit-0 as arrival); we just make it the *rule*, not a
patch:

- **Every message carries a stable ID.** Every injector/consumer dedups on it. A re-scan can never
  double-inject. (The storm, closed by construction.)
- **The read-offset is explicit, committed deliberately, and means exactly one rung.** No operation
  advances another operation's cursor. (The `send`-ate-your-mail bug, impossible.)
- **The acknowledgment ladder is layered and never promoted.** These are four different facts and
  the UI must never let one masquerade as a higher one:

  > **composed → delivered (the transcript demonstrably moved) → read (cursor passed) → acted-on (an
  > observable reply with content).**

  "Delivered" is not "read"; "read" is not "acted-on." The only trustworthy proof of *acted-on* is a
  reply with content — which is exactly what `bus.sh waiting`'s close-by-reply already encodes.
  *"'read' is to a watermark what 'root' was to systemctl --user."*
- **Redeliver only on evidence of loss:** the transcript moved but the watermark didn't (proof a
  keystroke was dropped), never on a timer. This is v2.26.1's fix, promoted to principle.

### 2.4 The observer is a monitor, never a supervisor

Borrowing the actor-model distinction precisely: a **link** propagates death and owns lifecycle; a
**monitor** only *observes* another process's exit. **Conductor must be a monitor.** A fleet of peers
has no supervision *tree* — it's a flat set of siblings with an observer. In OTP terms the peers are
`temporary` workers: **never auto-restarted.** That's why dormant-relaunch is correctly a
*human-initiated* `claude --continue`, and why boards are *quarantined* (not auto-reclaimed) while
GPUs are reaped — some children can't be cleanly restarted and must be isolated, human-cleared.

The invariant to write down and defend:

> **The observer proposes; the human disposes; the peers execute.**

What the observer *should* do: monitor liveness, surface derived state (orphans, stalls, open asks),
propose actions, relay explicitly-granted human approvals, and heartbeat-on-behalf only where it
holds ground truth. What it must *not* do: own session lifecycle, auto-reclaim irreversible
resources, or **convert its own observations into authority without a human tap.**

### 2.5 Name the oversight we already have: risk-stratified, three postures

We didn't build one control model; we built three, and they're correctly stratified by
reversibility. Stating it plainly makes the whole design legible and tells us where *new* controls
belong:

- **Over-the-loop** — you set the envelope and walk away. *Autonomy windows.* (routine, reversible)
- **On-the-loop** — you watch the dashboard and intervene on exceptions. *Unstall, reclaim, nudge.*
  (reversible, human supervises)
- **In-the-loop** — the agent blocks for your approval per act. *Push gate, persist gate.*
  (irreversible, outlives the session)

The governing rule from the research: **the more irreversible the act, the closer the human sits to
it.** A push and a `settings.json` write are in-the-loop *because* they're irreversible; a nudge is
on-the-loop *because* it isn't. Every future control gets placed by asking "how reversible is this?"

### 2.6 Add fencing tokens to leases (the one real gap)

Our dead-owner detection is heuristic (idle time, `owner_pid` liveness). The distributed-systems
answer to "a paused owner wakes up after its lease expired and writes anyway" is a **fencing token**:
a monotonic counter minted per acquisition and *validated at the point of use* (the GPU op, the board
flash). It's the one primitive we're missing that closes a split-brain `owner_pid` alone cannot.

---

## Part 3 — The capability / role model (Kyle's idea, generalized)

This is the organizing idea the whole 24 hours was circling, and the capability-security literature
says our current posture is a named anti-pattern.

### 3.1 The inversion: from ambient authority to least authority

Today every session is **born with full authority**, and we gate dangerous acts one at a time. That
is *ambient authority* + a *blocklist* — and a blocklist is only ever as complete as the last
incident. Our own history *is* a blocklist growing by discovery: push, then `~/.claude/bin`, then
`settings.json`, then crontab, then the multiline hole. The capability model inverts the question
from **"who is asking?"** to **"does this principal hold a valid, unforgeable grant for this specific
act?"** — with **default-deny** as the ground state. That's the move from patching an open door to
describing who's allowed through it.

### 3.2 The three properties a capability must have

- **Unforgeable** — the agent cannot mint it by talking. *The grant is a token the referee reads,
  never a sentence the agent emits.* (We already live this: *"a Claude can say 'Kyle approved this' a
  hundred times and it is still denied, because there is no token in the file."*)
- **Attenuable** — you can derive a *weaker* grant, never a stronger one. A session may voluntarily
  drop authority (enter read-only for a risky probe); raising it requires the human.
- **Revocable** — takeable back mid-session, visibly. Expiry is the backstop; revocation is the
  mid-flight brake.

### 3.3 The model: four roles (coarse, UI-legible) over capabilities (fine, enforced)

Roles are *named bundles* a human assigns and reads at 2am; enforcement is on the underlying
capabilities. Four is the sweet spot — legible to a human, enough to be useful, few enough to avoid
role explosion:

| Role | Grants | Denies |
|---|---|---|
| **Observer (read-only)** | read/analysis tools, bus *read* (`check`/`mine`/`sent`/`waiting`) | all Write/Edit, all `git push`, any Bash that writes outside its own worktree, service execution |
| **Service** | its one job type; writes only within a scratch/output dir; bus send | pushes, persistent-location writes, reserving unrelated resources |
| **Peer** (default worker) | full local edit + commit, resource reservation, bus send/retract | `git push` (gated), persistent-location writes (gated) — *the current two hard gates remain, as the peer ceiling* |
| **Trusted** (autonomy-whitelisted) | peer + a **time-boxed** self-approval window for pushes/persistent writes | still expires; still revocable; still logged |

The **read-only role is a genuinely new safety primitive**: not "a Claude we remembered to gate," but
one that *cannot* push, reserve, or install *by construction* — so a task handed to it has a blast
radius bounded before it starts.

### 3.4 How it's set, enforced, and revoked

- **Set** — the phone/PC UI writes `{project, role, expires?}` into `state/roles/<project>` (a data
  file the hook reads first — the `tag-map` pattern, so no script migration can touch it). Roles are
  **durable** (survive relaunch — the thing short-expiry can't give you). *Elevations within a role*
  (a Trusted window, a JIT push grant) are short-TTL and auto-reap.
- **Enforced** — one enrichment to the existing `PreToolUse(Bash|Edit|Write|MultiEdit|NotebookEdit)`
  hook: before the act-specific gates run, resolve the *caller's own PID → project dir → role*, then
  check the act against the role's capability set. The referee **derives identity from the OS**, never
  from a label in the message. Fail-closed on Edit/Write (exact), best-effort on Bash (honest) — the
  split we already ship.
- **Revoked** — the UI shows each session's current role + any live elevation as its own visible
  state (like the push-grant "Approved, waiting…" row), with a Revoke button. Revoke
  downgrades/deletes; the next tool call re-reads and is denied.

### 3.5 The three traps (all of which we've already half-hit)

1. **Trusting a self-reported role.** The single biggest failure mode: a session declaring "I'm a
   peer" in a message, a hook comment, or an env var *it* set. It controls all of those. The referee
   must independently resolve identity from the OS (PID → project), the way v2.30.0 resolves
   provenance. A role label the agent can write is *"the I-accept-the-risk checkbox with better
   branding."*
2. **Role explosion / prose-encoded policy.** Resist per-session bespoke permissions and
   attribute-rules the agent's context can influence. Four fixed roles + JIT elevation stays legible
   *and* enforceable.
3. **Expiry-only revocation on a relaunchable principal.** Our sessions can be relaunched with
   identical trust (the dormant dock does exactly this), so an expiring grant a restart silently
   re-mints is a hole. **Durable role + ephemeral elevation + explicit visible revoke** is the
   combination that closes it — the exact lesson the push-grant arc already paid for.

## Part 4 — The unified human-approver surface

Today four different things can demand Kyle through four different inboxes. The goal — Kyle as
approver, not courier — needs those to converge into **one prioritized "Needs You" queue**, shared
in *data* across phone and PC, differing only in presentation (the phone stays an episodic console,
the desktop stays a spatial workbench — that split is correct and we keep it).

### 4.1 Principles (all confirmed by how mature tools succeed and fail)

1. **Two-tier signaling, ruthlessly.** A **page** means *work is stopped and only you can unblock
   it* — a blocked question, a gated push, a gated system change. Everything else — idle lease,
   unread mail, a stall that might resolve itself — is a **ticket** on a passive surface you pull,
   not a push. Never invert. (PagerDuty's silent-low-urgency tier at scale; the alert-fatigue
   research: a page on a healthy system trains you to swipe it away, and then it isn't believed the
   night it matters.)
2. **The queue is the source of truth; the notification is an accelerator.** Every item is always
   reachable and actionable *in the surface itself*, whether or not a push ever arrives — and it
   self-heals on focus/visibility. (GitHub Mobile's deploy-approval was reachable *only* from a
   notification for years, and a "notify only on failure" filter silently suppressed the alerts
   reviewers depended on. The notification must never be the only door — a rule we already hold,
   now with a named cautionary tale behind it.)
3. **Context travels with the decision, co-located with the action.** The card carries the payload,
   the alternatives, and the provenance of who's asking — you never click through to understand what
   you're approving. (Argo Rollouts renders promote/abort *on the resource*; GitHub Mobile's failure
   was the opposite.)
4. **Grants are durable, visible, and revocable; expiry is a backstop, never a fuse.** A long TTL you
   can see and revoke is strictly safer than a short one whose failure mode is *losing the decision*.
   (The exact reconciliation of JIT-access practice with our own push-grant scar.)
5. **Undo, not confirm; no destructive-gesture mapping.** Approve is a *tap* with a short in-card
   undo — never a swipe (swipe is learned as dismiss/destroy), never a modal you see 20×/day and
   habituate to. Reserve genuine friction for the rare irreversible act so friction still *means*
   something. (NN/g.)

### 4.2 The queue: one surface, typed cards, priority by rubric

- **One "Needs You" queue** ingesting all four decision types today (gated push, gated system
  change, agent question, mutual stall) plus future ones, as **typed cards** — one queue,
  heterogeneous layouts, each card carrying exactly the evidence its decision needs.
- **Priority by a fixed rubric, not recency:** *hard-blocked-on-you* (an agent is stopped awaiting
  this exact answer) outranks *advisory* (a stall that could resolve, an FYI). This is derived from
  **observed state — is an agent actually blocked? — not from sender-declared labels, which inflate.**
  Only the top tier is allowed to page; the rest populate the queue silently. (This is also the
  correct home for the wake-floor logic we already made conditional on the wait-for graph.)
- **Grant state is a first-class row:** *"Approved — waiting for the session to push,"* with a Revoke
  button, so a live permission is always visible and retractable.

### 4.3 "Talk to this agent" is a verb on every card, not a separate mode

This is the piece that makes the doing→approving shift real without trapping Kyle in a false binary.
Every decision card offers **Approve / Deny / — or — Talk to this agent**. When neither approve nor
deny is right, "Talk" drops Kyle into that session's live channel *with the full context already
loaded* — the break-glass path, but for **communication** rather than access. It is how "I want to be
able to talk to them directly when I need to" becomes a first-class affordance instead of a
context-switch to hunt down the right terminal.

### 4.4 The three traps (each already grazed us)

1. **Notification as the only/fastest door** — a dropped, expired, or filtered push silently loses
   the decision. The queue must be canonical and self-healing; push is a pure accelerator that can
   fail without losing anything.
2. **Priority inversion from a naive signal** — a flat rate-limit or recency sort spends attention on
   an FYI while a hard-blocking question waits, and a mass-cc masquerades as urgent directed mail.
   Prioritize on *derived* blocked-ness, never on arrival order or sender labels.
3. **Habituation via repeated confirms / gesture mapping** — a swipe-to-approve or a daily "Are you
   sure?" becomes a reflex, and reflexes approve things unread. Tap-plus-undo for the reversible
   common case; deliberate friction only for the rare irreversible one.

---

## Part 5 — Migration: how we get there without stopping the fleet

The rocket is flying. Every step below preserves the current guarantees and is independently
shippable; nothing is a big-bang. The ordering is forced by dependency: **identity → control-plane →
capabilities → approver-surface**, because capabilities key on identity and the queue reads the
control plane.

1. **Identity first — it's the foundation everything keys on.** Promote the `tag-map` data file into
   a proper **member registry** (`state/roles/<project>` and a stable ID per project), and make the
   referee resolve identity from *PID → project dir*, never a bus label. This is mostly hardening
   what v2.32–2.33 already started, and it unblocks the role model. *Guarantee preserved:* tags keep
   working exactly as today; the registry just becomes authoritative.

2. **Control-plane extraction, one state-type at a time.** Introduce `control.jsonl` + projected
   state files incrementally — **start with the read-offsets/watermarks**, since that's the buggiest
   plane collapse — keeping the old path live until the new projection is proven equal, then cut
   over. Then leases, then grants. Each is a small, testable, reversible step. *Guarantee preserved:*
   the human log is untouched; a projection can be rebuilt by replay if wrong.

3. **Capability/role model — backward-compatible by default.** Add the role file + the one hook
   enrichment, and **default every session to `Peer` — which is byte-for-byte today's behavior**
   (full local work; push and persist gated). Then introduce `Observer`, `Service`, `Trusted` as
   opt-in profiles set from the UI. Absence of a role = Peer = no change. *Guarantee preserved:* a
   fleet that sets no roles behaves identically to now.

4. **Unified approver queue — presentation-first.** Unify the four existing inboxes into one typed
   queue in the *frontend* first, reading the same backends, then converge the backends behind it.
   Add "Talk to this agent" as a card verb. *Guarantee preserved:* every existing approval path keeps
   working while the surface consolidates.

5. **Fencing tokens + the formal delivery ladder** — last, because they harden rather than restructure:
   a monotonic token per lease acquisition validated at point-of-use, and the composed→delivered→
   read→acted-on ladder made explicit in the delivery code (most of it already exists as ad-hoc
   checks; this names and tests it).

---

## Open questions for review (for Kyle, then a fresh Claude, then the fleet)

These are the decisions I don't want to make unilaterally — the forks where reasonable people
differ:

1. **Role granularity.** Four roles (Observer / Service / Peer / Trusted) — too few, too many, or
   wrong cut points? Is "Service" distinct enough from "Peer with a narrow worktree," or should
   service-ness be a *capability flag* on a Peer rather than its own role?
2. **How much control-plane to extract.** Full CQRS-lite (`control.jsonl` + projections for
   everything) is clean but is a real second write-path. Is the right scope *only* the planes that
   have actually bitten us (offsets, leases), leaving the rest as-is? Where's the line between
   principled and over-engineered for one workstation?
3. **Fencing tokens** — worth it? The split-brain they close (a paused owner waking after expiry) is
   real but rare here. Is `owner_pid` liveness + quarantine *enough* in practice?
4. **The read-only role's enforcement surface.** Bash is best-effort by construction — an Observer
   determined to write via an exotic Bash incantation might slip a specific case. Is "best-effort
   Bash + exact Edit/Write" an acceptable ceiling for read-only, or does read-only need a stronger
   mechanism (e.g. a restricted tool-allowlist at the harness level)?
5. **Where roles are set from** — is the phone the right place to *grant Trusted*, or should
   elevation-to-Trusted be PC-only (a bigger decision deserving a bigger screen), with the phone able
   to *revoke* but not *grant*?
6. **Does any of this reduce efficiency enough to matter?** The whole point is strong controls that
   don't get resented. Which of these, if any, adds friction to the common path — and is the
   default-Peer posture genuinely zero-cost for existing work?
