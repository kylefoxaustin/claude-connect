---
description: Pull back an instruction you sent another session BEFORE it acts on it
argument-hint: "<to-tag> \"<what was wrong>\""
---
You told another session to do something and realized it's wrong. Retract it NOW so
they don't act on it — this posts a loud 🛑 RETRACTION addressed to them and (if
Conductor is running) **wakes their session immediately, even mid-task**, so they
see it before proceeding.
```bash
~/.claude/bin/bus.sh retract $ARGUMENTS
```
Example: `/retract qualcomm "scrap the int8 patch — it regresses accuracy"`.
For "ignore X, do Y instead" use `/supersede` — same delivery, correction framing.
