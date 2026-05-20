---
description: Archive the current bus log and start a fresh one
argument-hint: "[YYYY-MM]"
---

Rotate the cross-session message bus. Current log is archived to `messages-YYYY-MM.md` (defaults to current month) and a fresh log is started with the usage header intact.

```bash
~/.claude/bin/bus.sh rotate $ARGUMENTS
```

After running, confirm which archive file was written and remind the user that the other session will see a [system] rotation notice on its next `/msg-check`.
