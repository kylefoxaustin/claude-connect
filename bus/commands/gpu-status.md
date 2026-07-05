---
description: Check the shared-GPU reservation — who holds it, mode, time left, any pending request
---

Check the current shared-GPU reservation. **Read-only — this does NOT message anyone.** The bus already surfaces the GPU status in your per-prompt context when it's held; this is the on-demand detailed check.

```bash
~/.claude/bin/bus.sh gpu status
```

Report the result to the user. Then:
- **FREE** → if you need the GPU, claim it with `/gpu-reserve`.
- **held by another session** → respect the hold. A `hard` hold is theirs until they finish or the user stops them (wait, or ask the user). A `soft` hold means they'll yield if asked — use `/gpu-request`.
- **held by YOU** → carry on; remember to `/gpu-release` when done (or `/gpu-keep` to extend).
