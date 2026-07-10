# Fleet Coordination — Architecture Plan (PROPOSAL)

> Status: **plan only, nothing built.** A design study for evolving Claude Connect from
> *observing* the fleet to helping it *coordinate* — showing who's blocked on whom, letting
> Kyle approve the few things that need him from one place, letting the Claudes handshake the
> rest among themselves, and making a bad instruction retractable before it does damage.

## 1. The problem, decomposed

The fleet has outgrown "Kyle jumps between terminals to reconstruct who needs what." The ask is
really **four problems** with different solutions and different risk:

1. **Visibility** — a live view of the *dependency graph*: who is blocked on whom, who is
   waiting, and above all **who is waiting on Kyle**. Today this state exists only in his head.
2. **On-demand approval** — the few things that genuinely need him surface in *one place*; he
   says "go ahead"; it's delivered to the right session. He stops *monitoring* and only
   *adjudicates*.
3. **Autonomous coordination** — a request → ack → do → done handshake the Claudes run *among
   themselves*, inside a bounded autonomy grant, so most things never reach him.
4. **Safety / retraction** — when Claude A realizes "do X" was wrong, it can pull it back
   *before* B acts destructively. Highest stakes, lowest effort to fix.

## 2. Verdict: don't transplant. Extend what you already own.

A survey of the 2026 OSS landscape (LangGraph, CrewAI, AutoGen/AG2, OpenAI Agents SDK, Letta,
LlamaIndex Workflows, Microsoft Agent Framework, Temporal) against this topology:

- **All seven major LLM frameworks are *drivers*** — they own the control loop and call the LLM
  themselves. Adopting one means re-expressing each interactive Claude Code session as a
  node/step/`Agent` object the framework invokes. That destroys the property that makes this
  setup work: **autonomous sessions a human can jump into**, coordinating over a
  human-readable medium, with zero per-agent instrumentation. OpenAI's SDK docs say it outright:
  it "cannot coordinate external processes."
- **Only Temporal can coordinate external agents** — but as a durable signal fabric where every
  session must call its client SDK at each coordination point, backed by a DB cluster. A bad
  trade to replace something a human can `cat` and an agent can `echo >>`, on one workstation.
- **The real cousins are in the Claude Code niche**, and they are *thinner* than what's already
  here: peer-messaging MCP buses (claude-peers-mcp, cross-agent-teams), hook/OTel dashboards
  (disler's multi-agent observability), and Anthropic's own experimental **Agent Teams**
  (file-based task list + mailbox + locking + hooks, but lead-driven and session-scoped, so it
  can't span 15–70 independently-launched sessions). **None of them has a read-only dashboard
  *and* a reservation/queue/grace-hold layer. This project already does.**

**The surprising finding: this fleet has independently built state-of-the-art primitives.**

| Pattern the frameworks are praised for | Where this project already has it |
|---|---|
| Temporal's **timer-boxed approval** (await a signal for hours while a racing timer auto-passes on deadline) | The **grace-hold offer** (v2.15): a freed resource is held for the next in line ~15m to claim, else auto-passes |
| The MCP buses' **push/wake** (wake a recipient instead of polling) | The **real-time wake** (v2.15/2.17): Conductor injects `/msg-check` the instant something lands |
| Temporal's **superseding-signal-flips-a-gated-flag** (pre-empt a not-yet-run step) | *Not yet built — but the delivery mechanism (wake) is.* This is the retraction primitive. |
| PolicyLayer's **scoped, expiring approval grants** ("auto-approve X for 8h") | *Kyle's "auto-act overnight" grant — needs formalizing, not inventing* |
| LangGraph's **Agent Inbox** (a queue to approve/edit/reject pending actions) | *Not yet — a natural new Conductor view* |

So the plan is not "catch up to the frameworks." It is **extend three primitives you already own**
(grace-hold, real-time wake, the reservation lease model) into a general coordination layer, and
**steal concepts, not runtime**, from the frameworks for the pieces that are missing.

## 3. The one enabler: structured *intents* on the bus

The bus is freeform markdown today — great for humans, opaque to a graph. Every capability below
needs messages to *optionally* carry a little machine-readable intent. The design constraint:
**keep the bus human-readable (the moat); make structure additive.**

Recommended shape — **slash-commands that emit both a human-readable message and a structured
field**, exactly how `/reserve` already writes a lease *and* posts a message:

- `/need <tag> "<what>" [ref:<msg-id>]` — "I'm waiting on <tag> for <what>." Opens a coordination
  *ask*.
- `/blocked-on <tag> "<why>"` — a hard dependency edge (I cannot proceed until this clears).
- `/handoff <tag> "<task>"` — "this is yours now" (transfers ownership of a work item).
- `/ack <ask-id>` / `/decline <ask-id> "<why>"` — the receiver responds.
- `/done <ask-id> "<result>"` — fulfilled; wakes the asker.
- `/needs-human "<decision>" [urgency]` — escalate to Kyle's inbox.
- `/retract <msg-id> "<reason>"` / `/supersede <msg-id> "<correction>"` — pull back or replace a
  prior instruction; wakes the recipient immediately.

Each writes a structured record under `~/.claude/bus-state/coord/` (mirroring the resource-lease
model) that Conductor parses. Prose still flows on the bus as always; the commands just *also*
leave a trail a graph can read. Nothing forces a Claude to use them — but the fleet already
adopted `/reserve` enthusiastically, so uptake is realistic.

## 4. The architecture, in layers

```
  Claude sessions ──/need /handoff /retract /done…──▶  bus + coord-state
       ▲                                                     │
       │ real-time wake (/msg-check inject)                  │ parse
       │                                                     ▼
  Conductor  ◀──────────────  Coordination view · Approval inbox · Retraction alerts
       │
       └─ Kyle: "go ahead" (one click)  ·  grant/revoke autonomy  ·  see who's waiting on him
```

**Layer A — Coordination state (backend).** Conductor parses the intents into a directed graph:
nodes = sessions, edges = waiting-on / blocked-by / handoff, each carrying an *ask* with a state
(open → ack'd → done/declined). This is a small extension of the existing `resources.py` /
lease-reading model.

**Layer B — Dependency view (frontend).** A new view alongside the History graph: the live
dependency DAG. Three things it shows that the frameworks mostly *don't*:
- **Deadlock/cycle detection** — if A waits on B waits on A, highlight the cycle. A genuine
  distributed-systems win; none of the surveyed engines detect cross-agent deadlock.
- **Critical path** — rank sessions by how many others are downstream of them (who unblocks the
  most fleet if nudged).
- **"Waiting on YOU"** — the subgraph rooted at Kyle: everything flagged `needs-human`.

**Layer C — Approval inbox (frontend + one action endpoint).** A panel listing everything flagged
`needs-human`, each with a one-click **"go ahead"** that composes the go-ahead and injects it to
the right session (reuses Compose + the `/msg-check` injection). This is the "say go ahead do it"
half. Borrowed UX: LangGraph's Agent Inbox.

**Layer D — Coordination handshake (protocol).** The request → ack → do → done lifecycle above,
run by the Claudes themselves. A lightweight cousin of A2A's task lifecycle. Within an autonomy
grant, they run it without Kyle; Conductor shows each ask's state on the edge; only `needs-human`
asks reach the inbox.

**Layer E — Autonomy grants (Kyle's overnight idea, formalized + safer).** Instead of a blanket
"auto-act for N hours," a **scoped, expiring grant**: *session X may auto-act on asks of class Y
until time T.* Conductor shows active grants and a kill-switch. Crucially, a **policy line**: an
enumerated set of **irreversible/destructive action classes always escalate to Kyle regardless of
grant** (e.g. force-push, delete, deploy, spend). Borrowed from PolicyLayer / OpenAI SDK scoped
approvals — every sticky approval carries a scope *and* an expiry.

**Layer F — Retraction (the safety net).** `/retract` / `/supersede`:
- marks the original instruction retracted in coord-state;
- **immediately wakes the recipient** via the existing injection;
- the recipient's per-prompt hook surfaces a loud "⚠ instruction #X was RETRACTED — do not act"
  *before* it proceeds;
- Conductor raises a retraction alert on the edge.

This is Temporal's superseding-signal-flips-a-gated-flag, and the delivery half already shipped
(v2.17). It is the cheapest, highest-value piece — **build it first.**

## 5. What to steal, mapped

- **Temporal** → timer-boxed approval (already have the shape in grace-hold; generalize to
  "go-ahead or auto-approve for N hours"); superseding-signal-flips-a-gated-flag → the retraction
  model.
- **OpenAI Agents SDK** → scoped + sticky + serializable approval; *reject-a-pending-action-before-
  it-executes* → maps onto retraction and onto per-class auto-approve grants.
- **LangGraph** → the Agent Inbox UX (approve/edit/reject queue) → the approval inbox. Honest
  caveat worth internalizing: LangGraph's "time-travel" rewinds *its own* state, not an
  independent agent's — which is exactly the boundary this bus lives on. We can't un-send B's
  thoughts; we can only *warn B before it acts*. That's why retraction is a wake, not a rewind.
- **PolicyLayer / A2A / AG-UI** → scoped+expiring grants; a task-lifecycle vocabulary; optionally,
  later, having the bus *speak* AG-UI so asks could surface in a standard approval UI (portability
  insurance, not needed now).
- **claude-peers-mcp / cross-agent-teams** → **peer discovery** (live working-dir / current-task
  per session on the tile) is a nice cheap borrow; push/wake we already have.

## 6. Phasing — safety first, value early

1. **Phase 1 — Retraction safety net.** `/retract` + `/supersede`, the immediate recipient wake,
   the hook warning, a Conductor alert. Small; reuses the v2.17 wake; removes the scariest failure
   (destructive action on a bad instruction). **Ship this regardless of the rest.**
2. **Phase 2 — Visibility.** `/need`, `/blocked-on`, `/needs-human` + coord-state + the dependency
   view with deadlock detection and the "waiting on you" panel. Turns terminal-hopping into a
   glance.
3. **Phase 3 — Approval inbox.** The one-click "go ahead," delivered via injection. Kyle stops
   monitoring, starts adjudicating.
4. **Phase 4 — Autonomy.** The request→ack→done handshake + scoped/expiring grants + the
   always-escalate policy for destructive classes. The "coordinate so I don't have to" half.

Each phase is independently useful and independently shippable, and each builds on the bus +
Conductor + injection primitives that already exist.

## 7. Honest risks & open questions

- **Adoption is the real risk, not code.** Structured intents only help if the Claudes use them.
  Mitigations: keep them optional and prose-backed; lean on the fact that `/reserve` got adopted;
  possibly have a session's system prompt / `CLAUDE.md` teach the vocabulary.
- **The graph is only as honest as the declarations.** A Claude that's blocked but doesn't
  `/need` won't show an edge. Partial mitigation: infer *soft* edges from bus mentions (the
  History graph already does mention-inference), and show declared vs inferred differently.
- **Autonomy + destructive actions is where a mistake hurts.** The always-escalate policy line is
  the load-bearing safety control; it must be conservative and explicit, and the retraction net
  (Phase 1) must exist *before* autonomy (Phase 4).
- **Scope creep toward "an agent engine."** The discipline: Conductor stays *observe + deliver*;
  it never becomes the thing that drives the Claudes. Every feature must survive the test "does
  this keep the sessions autonomous and jump-into-able?"

### Questions for Kyle
1. Of the four problems, which bites hardest *today* — the "who's waiting on me" fog, or the
   retraction race? (Phasing puts retraction first on risk; happy to reorder for pain.)
2. How heavy should the structured layer be — slash-commands (recommended), or also auto-inferred
   soft edges from prose?
3. For autonomy grants: what belongs on the **always-ask-Kyle** list (the irreversible classes)?
4. Is "one workstation, one human" the permanent shape, or should this assume multiple operators
   later (changes the approval model)?

## 8. Decisions & refinements (Kyle, 2026-07-10)

Kyle's answers reshape the priorities — the biggest change is that **the #1 pain is delivery &
awareness, not the dependency graph itself.**

1. **Hardest bite = being the fleet's message courier.** Not the abstract "who's waiting on me"
   fog — the concrete chore of *prodding sessions to check their messages*, and even explaining
   to a Claude that another Claude *did* send it something, go look. He is manually acting as a
   delivery-confirmation-and-reminder service. **This is already 80% solved by machinery that
   exists:** the per-session unread (📬) count, the busy guard, and the real-time wake (v2.17).
   The fix is to **generalize the wake**: when a session is idle *and* has unread **directed**
   messages (or an open `/need` aimed at it), wake it automatically; and show Kyle a
   "who's-waiting-on-a-reply-from-whom" view so awareness gaps are visible at a glance instead of
   discovered by terminal-hopping. His note that per-task prose gets *super lengthy* reinforces
   this: "just go read the bus" doesn't scale, so **directed asks + auto-delivery** beat
   scroll-the-log.
2. **Keep autonomy simple.** He already blanket-auto-approves most sessions, and per-action
   approval would drown in lengthy prose. So: **no fine-grained scoped-grant matrix.** Autonomy
   stays "auto-approve everything *except* the always-ask list." The only hard gate is #3.
3. **Always-ask = `git push`. Commits are fine** (reversible via pull-back); he wants control over
   *when code hits a repo*. This is concrete and enforceable at the tool level, independent of
   whether a Claude volunteers to ask — see the **push-gate** design below.
4. **One human, one workstation — permanent.** No multi-operator model, no auth. The approval
   inbox is just Kyle's.

### Push-gate design (the one hard control)

Enforced, not voluntary — a Claude Code **PreToolUse hook** on `Bash` that inspects `git push`:

- **No valid approval token** → the hook **denies** the push with a message ("🛑 pushes need
  Kyle's OK — I've posted a request; re-run once approved"), and writes a `needs-human` approval
  request to `~/.claude/bus-state/push-approvals/` + the bus.
- **Kyle clicks "go ahead"** in Conductor → Conductor writes a short-TTL approval **token** for
  that repo/session.
- **Claude re-runs `git push`** → the hook now finds a valid unexpired token, **allows** it, and
  **consumes** the token (one push per approval). Expired/absent → deny again.

Commits, branches, everything else stay auto-approved. This gives real "nothing hits a repo
without my say-so" control while keeping the sessions autonomous. It's the approval-inbox pattern
(§4C) with a tool-level enforcement point.

### Revised phasing

1. **Phase 1 — "Never be the courier" + retraction.** (a) Auto-wake an *idle* recipient that has
   unread directed messages / an open ask, with the busy guard + debounce (reuses v2.17 wake); a
   one-click "nudge" per session; and a **"waiting on a reply"** panel. (b) `/retract` /
   `/supersede` riding the same wake — the safety net. Together these kill bite #1 and the scary
   failure, and both are small extensions of shipped machinery.
2. **Phase 2 — Push gate.** The PreToolUse hook + approval token + Conductor "go ahead." His one
   hard control.
3. **Phase 3 — Full dependency view.** Structured intents (`/need`, `/blocked-on`, `/handoff`),
   the dependency DAG, deadlock/cycle detection, critical-path. The richer visualization, once the
   daily pain is handled.

Autonomy grants (§4E) collapse to "status quo + the push gate," per answer 2/4 — no separate phase.
