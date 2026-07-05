---
description: Ask the current GPU holder to yield it (flags them; they see it on their next turn)
---

Signal the current GPU holder that you'd like the GPU. This **does not force anything** — it flags the owner, who sees the request in their per-prompt context and can `/gpu-release` (especially for a `soft` hold) or keep it.

```bash
~/.claude/bin/bus.sh gpu request
```

Tell the user you've flagged the holder. Note: for a **hard** hold, the owner may legitimately keep it until their job finishes — be prepared to wait, or ask the user to intervene if it's urgent.
