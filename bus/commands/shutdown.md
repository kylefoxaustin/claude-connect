---
description: Call a fleet wind-down — every session persists its state, acks, then Kyle closes them
argument-hint: "[ack \"<state>\" | status | clear]"
---
Fleet wind-down — the mirror of session start. Broadcasts the ordered shutdown protocol so every
session persists itself (post findings → write memory/card → commit dirty repos → release leases →
ack) before it is closed. A session is NEVER closed until it acks; a busy or question-open session is
waited for, not interrupted.
```bash
~/.claude/bin/bus.sh shutdown $ARGUMENTS
```
With no argument this BEGINS a fleet-wide wind-down. Sub-commands: `status` (who has wound down),
`clear` (cancel it). Full protocol: `bus/wind-down-orders.md`.
