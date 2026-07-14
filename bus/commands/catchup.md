---
description: Get current on the bus after an absence — digest ALL unread at once, no page-by-page slog
---

Catch up on everything you missed while you were away, in one shot. Unlike `/msg-check` (which pages a large backlog ~20 messages at a time), this prints a ONE-LINE DIGEST of every unread message addressed to you or broadcast, oldest-first, and advances your read cursor — so you go from "hundreds unread" to current without either burning many turns or silently skipping mail.

```bash
~/.claude/bin/bus.sh catchup
```

If the backlog is very large it digests a bounded page and tells you how many remain — run it again to continue. To pull the full body of any message afterward, use `~/.claude/bin/bus.sh check --all`.

After the digest, tell the user what you missed that needs a reply or action, and ask how they want to proceed.
