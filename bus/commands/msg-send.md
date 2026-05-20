---
description: Send a message to the other Claude Code session via the shared bus
argument-hint: "<message text>"
---

Append a message from this session to the cross-session bus. The session is auto-tagged based on the current working directory.

Run this exact command, with the user's message as a single quoted argument so it survives shell parsing:

```bash
~/.claude/bin/bus.sh send "$ARGUMENTS"
```

Confirm to the user what was sent and which tag was applied.
