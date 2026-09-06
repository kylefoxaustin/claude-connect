---
description: Get current on the bus after an absence — digest ALL unread at once, no page-by-page slog
---

Catch up on everything you missed while you were away, in one shot. Unlike `/msg-check` (which pages a large backlog ~20 messages at a time), this prints a ONE-LINE DIGEST of every unread message addressed to you or broadcast, **newest-first** (so you reach the LIVE state before the history), and advances your read cursor — so you go from "hundreds unread" to current without either burning many turns or silently skipping mail.

```bash
~/.claude/bin/bus.sh catchup
```

Add `--thread-order` for OLDEST-first instead — a causal replay, for when you need to follow how a
conversation developed rather than where it ended up.

If the backlog exceeds the cap it digests a bounded page and DISCLOSES how many remain — run it again
to continue. A digest is TRIAGE, not comprehension: it tells you a thread moved, never enough to act
on. Before acting, read the full thread with `~/.claude/bin/bus.sh check --all` or
`catchup --thread-order`.

⚠️ Prefer this over `/msg-check` on any large backlog. A `check` that emits hundreds of full bodies
can have its tool result truncated by the harness and still advance the cursor — that cost one session
193 messages, marked read and never received. The one-line digest is small enough that it cannot
happen.

After the digest, tell the user what you missed that needs a reply or action, and ask how they want to proceed.
