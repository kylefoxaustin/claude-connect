---
description: Service Claudes: claim the next job in your queue
---

Take the next queued job. Refuses if you are already serving one, or if Kyle has claimed the
next opening.

```bash
~/.claude/bin/bus.sh svc next $ARGUMENTS
```

Usage: `/svc-next <your-service-name>`. Do the work, then `/svc-done` to return the result —
that wakes the requester automatically.
