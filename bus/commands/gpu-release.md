---
description: Release your shared-GPU reservation so other sessions can use it
---

Release the GPU reservation held by this session (do this as soon as your GPU work is done, so others aren't blocked).

```bash
~/.claude/bin/bus.sh gpu release
```

Confirm to the user it's released. If it reports you didn't hold it, no action was needed.
