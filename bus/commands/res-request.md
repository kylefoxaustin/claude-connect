---
description: Ask the current holder of a shared resource to yield it (flags them)
argument-hint: "<resource>"
---
Signal the current holder of a shared resource that you'd like it. This does not force
anything — it flags the owner, who sees the request in their per-prompt context and can
`/release` it (especially a `soft` hold) or keep it.
```bash
~/.claude/bin/bus.sh res request $ARGUMENTS
```
Tell the user you've flagged the holder. For a **hard** hold, be prepared to wait.
