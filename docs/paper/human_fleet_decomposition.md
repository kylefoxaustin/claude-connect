# Human-vs-fleet coordination decomposition (supporting artifact for §V-A)

Answers the reviewer's anticipated attack — *"the human architect is doing most of the work"* — by
decomposing **who originates coordination** on the shared bus. MEASURED from
`~/Documents/claude-bus/messages*.md` (the full append-only log + its monthly archives). As-of
**2026-07-31**; ratios are stable and will be re-stamped with every other count before submission.

## Method

Every bus message carries a `[sender]` header. Each sender is assigned to one category:

- **human** — `[operator]` (the tag Conductor posts under when Kyle drives the bus by hand — the
  compose box, the "tell them they're both waiting" button). This is the human's *direct*
  participation in the shared channel.
- **automated** — the substrate's own agents: `[system]` (rotation notices), `[resource-watchdog]`,
  `[resource-broker]`. Coordination the machinery does on nobody's behalf.
- **fleet** — every Claude session tag (`[backend]`, `[other:emu-A]`, …).

Addressing follows the paper's convention: recipients are the `to:` tags on a message's first body
line (before the em-dash); 0 = broadcast, ≤4 = directed, >4 = announcement. Same parser as
`evidence-harvest.py` (optional-seconds header regex, so the pre-seconds archives are counted).

## Result

| category | total | share | directed |
|---|---:|---:|---:|
| **fleet** | 2,621 | **95.5%** | 996 |
| **automated** | 92 | 3.4% | 92 |
| **human** (`operator`) | 26 | **0.9%** | 21 |
| **system** | 5 | 0.2% | 0 |
| total | 2,744 | | 1,109 |

- **The human authored 0.9% of all bus coordination, and 1.9% of the directed (routing) mail** (21 of
  1,109). Over 98% of coordination on the shared channel originates from the fleet itself.
- **The fleet's coordination is load-shared, not funneled through a lead.** Among the 52 fleet
  senders: the busiest single session is 9.8% of fleet mail, the top three are 26.6%, and it takes 7
  sessions to reach half. There is no dominant orchestrator and no human-proxy "lead" node routing
  the traffic (consistent with the Gini 0.698 / top-3 25.4% concentration reported in §V-A).

## The honest limit (why this is one channel, not the whole story)

The bus is the Claude↔Claude channel **by construction** — the human is not *expected* to post there
much, so "0.9%" alone does not prove the human isn't steering. The human's real coordination channel
is **direct prompts** (`history.jsonl`: 6,355 human prompts across 47 projects). That channel is not
silent — but it is measured, and per **active project** it **declines** over the deployment (the §V-A
human-touch series: ~70 prompts/project across May–June → 36 in July as concurrent projects grew).

So the two observable channels agree and point the same way:

1. the human generates <1% of the shared coordination traffic and <2% of its routing mail, and
2. the human's prompt-side intensity per project is falling, not rising, as the fleet scales.

What the human **does** own is real and unchanged: goal-setting, framing, and the irreversibility gate
(every `git push` is human-approved). That is **architect** work, not **courier/router** work — which
is exactly the paper's claim. The decomposition bounds the *coordination-routing* role; it does not,
and should not, claim the human is absent from the loop.

## Reproduce

Parse `messages*.md` headers; bucket senders as above; count `to:` recipients on each message's first
body line. `history.jsonl`: count records, distinct `project` values.
