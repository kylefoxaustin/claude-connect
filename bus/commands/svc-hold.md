---
description: Claim the NEXT opening on a service Claude — it finishes its current job, then waits for you
---

Claim the next slot on a service. It will finish what it is currently rendering (so no GPU work
is thrown away), then STOP and wait for you instead of pulling the next queued job.

```bash
~/.claude/bin/bus.sh svc hold $ARGUMENTS
```

Usage: `/svc-hold <service> [why]`. Release it again with `/svc-resume <service>`.
