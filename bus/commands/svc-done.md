---
description: Service Claudes: finish the current job and return the result to the requester
---

Finish the job you are serving and send the result back. The requester is woken automatically
(directed mail) — that is what makes the whole thing fire-and-forget.

```bash
~/.claude/bin/bus.sh svc done $ARGUMENTS
```

Usage: `/svc-done <service> <result — where you put it / what you made>`.
Then run `/svc-next` for the next job, unless it tells you Kyle has claimed the slot.
