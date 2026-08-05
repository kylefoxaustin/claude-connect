---
description: Ack that you have persisted your state and are safe to close (during a fleet wind-down)
argument-hint: "<one-line state: what you were doing + anything unpushed/parked>"
---
Run this ONLY after you have completed the wind-down protocol: posted your open findings + questions
to the bus, written your memory/card, committed every dirty repo locally (and noted anything
unpushed), and released your leases. It records that you are safe to close.
```bash
~/.claude/bin/bus.sh shutdown ack "$ARGUMENTS"
```
Your one-line state should say what you were doing and name anything unpushed or parked, so
reconstitution knows what to recover. Until you ack, you are not closed — you are waited for.
