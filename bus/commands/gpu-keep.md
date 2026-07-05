---
description: Extend (heartbeat) your shared-GPU reservation for a fresh duration
argument-hint: "<duration 30m|1h>"
---

Extend your existing GPU reservation from now, before it expires.

```bash
~/.claude/bin/bus.sh gpu keep $ARGUMENTS
```

Confirm the new expiry to the user. (If you no longer hold the GPU, it reports nothing to extend.)
