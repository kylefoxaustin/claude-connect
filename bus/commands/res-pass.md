---
description: Decline a resource you've been offered (hands it to the next in the queue)
argument-hint: "<resource>"
---
When the queue hands you a resource (you got a "🎉 you're up" ping), use this to
**decline** it if you don't need it after all — it immediately passes to the next
Claude in line (don't just sit on it).
```bash
~/.claude/bin/bus.sh res pass $ARGUMENTS
```
If you DO want it, run `/reserve <resource> <dur> <soft|hard>` instead to claim it.
Doing nothing also works — the watchdog auto-passes it when the grace window ends.
